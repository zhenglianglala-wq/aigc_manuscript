"""One explicit images/generations request, Base64 only, no automatic retries."""
import os,json,base64,binascii,struct,zlib,time,io,warnings
from PIL import Image,UnidentifiedImageError
from urllib.parse import urlparse
from datetime import datetime,timezone
import httpx
from backend.store import DomainError,now

MAX_IMAGE_BYTES=20*1024*1024
IMAGE_BINDING=('base_url','model','size','response_format','estimated_price_per_image')
PROMPT_BINDING=('base_url','model','input_price_per_million','output_price_per_million','max_output_tokens')
def validate_base_url(value):
    p=urlparse(value)
    if not p.hostname or p.username or p.password or p.query or p.fragment or not (p.scheme=='https' or p.scheme=='http' and p.hostname in ('localhost','127.0.0.1','::1')):
        raise DomainError('INVALID_URL','服务地址需 HTTPS 或本机 HTTP，不含凭证或查询参数',422)
def model_binding(config,purpose):return {k:config[k] for k in (IMAGE_BINDING if purpose=='image' else PROMPT_BINDING)}
def require_approval(store,run,config,purpose):
    approval_id=run['request'].get('approval_id');ap=store.get('photo_approval',approval_id or '',False)
    if not ap or ap['photo_project_id']!=run['photo_project_id'] or ap['purpose']!=purpose or ap['status']!='active' or datetime.fromisoformat(ap['expires_at'])<=datetime.now(timezone.utc):raise DomainError('PHOTO_APPROVAL_REQUIRED','缺少有效照片调用批准，视频批准不可使用',403)
    if ap['model_binding']!=model_binding(config,purpose):raise DomainError('APPROVAL_CONFIG_CHANGED','服务、模型或参数已改变，请重新批准',403)
    if ap['calls_used']>=ap['max_calls']:raise DomainError('CALL_LIMIT','批准次数已用完',403)
    known=(config.get('estimated_price_per_image') is not None) if purpose=='image' else config.get('input_price_per_million') is not None and config.get('output_price_per_million') is not None
    if not known and not ap['accept_unknown_cost']:raise DomainError('UNKNOWN_COST','需明确接受未知费用',403)
    return ap

def sniff_image(raw):
    if not raw or len(raw)>MAX_IMAGE_BYTES:raise DomainError('IMAGE_INVALID','图片为空或超过20 MiB',502)
    width=height=None;mime=ext=None
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        try:
            if raw[12:16]!=b'IHDR' or len(raw)<45:raise ValueError()
            width,height=struct.unpack('>II',raw[16:24]);offset=8;seen_data=False;seen_end=False
            while offset<len(raw):
                length=struct.unpack('>I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8];end=offset+12+length
                if end>len(raw) or length>MAX_IMAGE_BYTES:raise ValueError()
                if zlib.crc32(raw[offset+4:offset+8+length])&0xffffffff!=struct.unpack('>I',raw[offset+8+length:end])[0]:raise ValueError()
                if kind==b'IDAT':seen_data=True
                if kind==b'IEND':seen_end=True;break
                offset=end
            if not seen_data or not seen_end:raise ValueError()
            mime,ext='image/png','png'
        except (ValueError,struct.error):raise DomainError('IMAGE_INVALID','PNG 数据结构或校验失败',502)
    elif raw.startswith(b'\xff\xd8'):
        try:
            offset=2
            while offset+4<=len(raw):
                if raw[offset]!=255:raise ValueError()
                marker=raw[offset+1];offset+=2
                while marker==255:marker=raw[offset];offset+=1
                if marker in (0xd8,0xd9):continue
                length=int.from_bytes(raw[offset:offset+2],'big')
                if length<2 or offset+length>len(raw):raise ValueError()
                if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                    height,width=struct.unpack('>HH',raw[offset+3:offset+7]);break
                offset+=length
            if not width or not raw.endswith(b'\xff\xd9'):raise ValueError()
            mime,ext='image/jpeg','jpg'
        except (ValueError,struct.error,IndexError):raise DomainError('IMAGE_INVALID','JPEG 数据结构无效',502)
    elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP':
        try:
            if struct.unpack('<I',raw[4:8])[0]+8!=len(raw):raise ValueError()
            kind=raw[12:16]
            if kind==b'VP8X':width=1+int.from_bytes(raw[24:27],'little');height=1+int.from_bytes(raw[27:30],'little')
            elif kind==b'VP8 ' and raw[23:26]==b'\x9d\x01\x2a':width,height=struct.unpack('<HH',raw[26:30]);width&=0x3fff;height&=0x3fff
            elif kind==b'VP8L' and raw[20]==0x2f:
                bits=int.from_bytes(raw[21:25],'little');width=(bits&0x3fff)+1;height=((bits>>14)&0x3fff)+1
            else:raise ValueError()
            mime,ext='image/webp','webp'
        except (ValueError,struct.error,IndexError):raise DomainError('IMAGE_INVALID','WebP 数据结构无效',502)
    if mime is None:raise DomainError('IMAGE_TYPE_UNSUPPORTED','仅接受有效 PNG、JPEG 或 WebP Base64 图片',502)
    if not width or not height or max(width,height)>8192 or width*height>20_000_000:raise DomainError('IMAGE_INVALID','图片尺寸无效或过大',502)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG','JPEG','WEBP') or image.size!=(width,height):raise ValueError('Decoded header mismatch')
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                if image.size!=(width,height):raise ValueError('Decoded dimensions changed')
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombWarning,Image.DecompressionBombError):raise DomainError('IMAGE_INVALID','图片像素解码失败，未保存图片',502)
    return raw,mime,ext,width,height

async def generate_image(store,run,config):
    key=os.environ.get('IMAGE_API_KEY','')
    if not key or os.environ.get('PAID_IMAGE_CALLS_ENABLED','').lower() not in ('true','1','yes'):raise DomainError('IMAGE_CALLS_DISABLED','图片调用需要独立 IMAGE_API_KEY、开关及照片批准',403)
    if not config.get('model') or not config.get('base_url'):raise DomainError('IMAGE_MODEL_NOT_CONFIGURED','请配置图片模型与服务地址',422)
    validate_base_url(config['base_url']);price=config.get('estimated_price_per_image');began=time.monotonic()
    with store.tx():
        current=store.get('run',run['id'])
        if current['status']=='cancelled':raise DomainError('CANCELLED','任务已取消')
        ap=require_approval(store,run,config,'image')
        if price is not None and ap['budget'] is not None and ap['spent']+ap.get('reserved',0)+price>ap['budget']:raise DomainError('BUDGET_EXCEEDED','图片调用预算预检查未通过',403)
        ap['calls_used']+=1;ap['reserved']=ap.get('reserved',0)+(price or 0);store.put('photo_approval',ap)
        current['steps'].append({'step':'image_request','attempt':1,'status':'running','model':config['model'],'at':now()});store.put('run',current)
    success=False;usage={}
    try:
        body={'model':config['model'],'prompt':run['request']['prompt_snapshot']['compiled_prompt'],'size':config['size'],'n':1}
        if config['response_format']=='b64_json':body['response_format']='b64_json'
        async with httpx.AsyncClient(timeout=httpx.Timeout(120),follow_redirects=False) as client:
            async with client.stream('POST',config['base_url'].rstrip('/')+'/images/generations',headers={'Authorization':'Bearer '+key},json=body) as response:
                if response.status_code>=400:raise DomainError('IMAGE_UPSTREAM_ERROR',f'图片服务 HTTP {response.status_code}；未自动重试',502)
                chunks=[];total=0
                async for chunk in response.aiter_bytes():
                    total+=len(chunk)
                    if total>MAX_IMAGE_BYTES*4//3+1024*1024:raise DomainError('IMAGE_TOO_LARGE','图片响应超过大小上限',502)
                    chunks.append(chunk)
        try:
            data=json.loads(b''.join(chunks))
            if not isinstance(data,dict):raise DomainError('IMAGE_OUTPUT_INVALID','图片响应必须为JSON对象',502)
            usage=data.get('usage') if isinstance(data.get('usage'),dict) else {};items=data.get('data')
            if not isinstance(items,list) or len(items)!=1 or not isinstance(items[0],dict):raise DomainError('IMAGE_OUTPUT_INVALID','服务须返回恰好一张图片',502)
            encoded=items[0].get('b64_json')
            if not isinstance(encoded,str):raise DomainError('IMAGE_BASE64_REQUIRED','当前仅支持 b64_json 返回；不下载 URL 图片',502)
            if len(encoded)>MAX_IMAGE_BYTES*4//3+4:raise DomainError('IMAGE_TOO_LARGE','Base64 图片超过20 MiB',502)
            result=sniff_image(base64.b64decode(encoded,validate=True))
        except (ValueError,TypeError,KeyError,binascii.Error):raise DomainError('IMAGE_OUTPUT_INVALID','服务未返回有效 Base64 图片',502)
        success=True;return result
    finally:
        with store.tx():
            ap=store.get('photo_approval',run['request']['approval_id'],False);current=store.get('run',run['id'],False)
            if ap:
                ap['reserved']=max(0,ap.get('reserved',0)-(price or 0));ap['spent']+=price or 0;store.put('photo_approval',ap)
            if current:
                current['steps'][-1].update(status='succeeded' if success else 'failed',elapsed_seconds=round(time.monotonic()-began,3))
                inp=usage.get('input_tokens');out=usage.get('output_tokens')
                current['usage']={'input_tokens':inp if type(inp) is int and inp>=0 else None,'output_tokens':out if type(out) is int and out>=0 else None,'cost':price,'cost_status':'estimated' if price is not None else 'unknown','price_date':config.get('price_date'),'basis':'configured per-image estimate, not supplier invoice'};store.put('run',current)
