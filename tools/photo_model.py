"""Explicit images/generations: Base64 or narrowly scoped Aliyun OSS result URLs."""
import os,json,base64,binascii,struct,zlib,time,io,warnings,asyncio,socket,ipaddress,re,tempfile
from pathlib import Path
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
# Only documented DashScope result patterns; no arbitrary OSS bucket/suffix.
ALIYUN_RESULT_HOST_PATTERN=re.compile(
    r'dashscope-[a-z0-9](?:[a-z0-9-]{0,52}[a-z0-9])?\.(?:oss-accelerate|oss-cn-[a-z0-9]+(?:-[a-z0-9]+)*)\.aliyuncs\.com'
)
def allowed_aliyun_result_host(host):
    return isinstance(host,str) and len(host)<=253 and all(len(label)<=63 for label in host.split('.')) and ALIYUN_RESULT_HOST_PATTERN.fullmatch(host) is not None

def safe_result_host(value):
    try:
        host=urlparse(value).hostname if isinstance(value,str) else None
        return host if host and re.fullmatch(r'[a-zA-Z0-9.-]{1,253}',host) else 'invalid-host'
    except ValueError:return 'invalid-host'

def receipt_path(store,run_id):
    if not isinstance(run_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',run_id):raise DomainError('RECEIPT_INVALID','结果回执标识无效',422)
    folder=store.path/'photo-receipts'
    if folder.is_symlink():raise DomainError('RECEIPT_INVALID','结果回执目录不得为符号链接',500)
    return folder/(run_id+'.json')

def save_image_receipt(store,run,value,request_id=None):
    if not isinstance(value,str) or not value or len(value)>8192:raise DomainError('IMAGE_OUTPUT_INVALID','返回的结果URL无效；未下载',502)
    safe_id=request_id if isinstance(request_id,str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',request_id) else None
    path=receipt_path(store,run['id']);path.parent.mkdir(mode=0o700,exist_ok=True);os.chmod(path.parent,0o700)
    receipt={'run_id':run['id'],'photo_project_id':run['photo_project_id'],'url':value,'request_id':safe_id,'created_at':now()}
    with store.tx():
        current=store.get('run',run['id'],False)
        if not current:raise DomainError('CANCELLED','原任务已删除，未保存回执')
        fd,temp=tempfile.mkstemp(prefix='receipt-',suffix='.tmp',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as file:
                json.dump(receipt,file,ensure_ascii=False);file.flush();os.fsync(file.fileno())
            os.chmod(temp,0o600);os.replace(temp,path)
        finally:Path(temp).unlink(missing_ok=True)
        metadata={'available':True,'host':safe_result_host(value),'request_id':safe_id}
        current['image_receipt']=metadata;current['steps'].append({'step':'result_receipt_saved','status':'succeeded','at':now(),**metadata});store.put('run',current)
    return receipt

def load_image_receipt(store,run):
    path=receipt_path(store,run['id'])
    if not path.is_file() or path.is_symlink():raise DomainError('RECEIPT_MISSING','原任务没有可用私有回执，不能恢复已丢失的URL',404)
    try:
        if path.stat().st_size>16384:raise ValueError()
        receipt=json.loads(path.read_text(encoding='utf-8'))
        if receipt['run_id']!=run['id'] or receipt['photo_project_id']!=run['photo_project_id'] or not isinstance(receipt['url'],str):raise ValueError()
        return receipt
    except (ValueError,KeyError,TypeError,OSError):raise DomainError('RECEIPT_INVALID','私有结果回执校验失败',409)

async def recover_image_receipt(store,run):
    original=store.get('run',run['recovery_of']);receipt=load_image_receipt(store,original)
    try:return await download_aliyun_result(receipt['url'])
    except DomainError as exc:raise DomainError(exc.code,f"阶段：结果下载；主机：{safe_result_host(receipt['url'])}；{exc.message}",exc.status)
    except httpx.HTTPError:raise DomainError('IMAGE_DOWNLOAD_FAILED',f"阶段：结果下载；主机：{safe_result_host(receipt['url'])}；连接失败，未调用生成接口",502)

def validate_aliyun_endpoint(value):
    validate_base_url(value);parsed=urlparse(value)
    host=parsed.hostname or ''
    try:port=parsed.port
    except ValueError:raise DomainError('ALIYUN_ENDPOINT_REQUIRED','阿里云服务端口无效',422)
    if parsed.scheme!='https' or port not in (None,443) or parsed.path.rstrip('/')!='/compatible-mode/v1' or not (host=='dashscope.aliyuncs.com' or re.fullmatch(r'[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com',host)):
        raise DomainError('ALIYUN_ENDPOINT_REQUIRED','aliyun_url协议仅支持阿里云北京官方兼容接口',422)

async def resolve_aliyun_result(value):
    if not isinstance(value,str) or not value or len(value)>8192 or any(c.isspace() or ord(c)<32 for c in value):raise DomainError('IMAGE_URL_UNSAFE','图片URL格式不安全',502)
    try:
        parsed=urlparse(value);host=parsed.hostname
        if parsed.scheme!='https' or not allowed_aliyun_result_host(host) or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment:raise ValueError()
        results=await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo,host,443,type=socket.SOCK_STREAM),timeout=10)
        addresses=[]
        for result in results:
            address=ipaddress.ip_address(result[4][0]);effective=address.ipv4_mapped if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped else address
            if not effective.is_global or effective.is_private or effective.is_loopback or effective.is_link_local or effective.is_reserved or effective.is_multicast or effective.is_unspecified:raise ValueError()
            addresses.append(str(address))
        if not addresses:raise ValueError()
        address=sorted(set(addresses),key=lambda x:(':' in x,x))[0]
        return httpx.URL(value).copy_with(host=address),host
    except (ValueError,OSError,asyncio.TimeoutError):raise DomainError('IMAGE_URL_UNSAFE','图片URL主机或DNS地址不在安全边界内',502)

async def download_aliyun_result(value):
    pinned,host=await resolve_aliyun_result(value)
    # Connect to the validated IP, use the official Host/TLS SNI; proxies disabled.
    # No Authorization or generation-session cookies go to the storage server.
    async with httpx.AsyncClient(timeout=httpx.Timeout(120,connect=15),follow_redirects=False,trust_env=False) as client:
        async with client.stream('GET',pinned,headers={'Host':host,'Accept':'image/png,image/jpeg,image/webp'},extensions={'sni_hostname':host}) as response:
            if response.status_code!=200:raise DomainError('IMAGE_DOWNLOAD_FAILED','官方结果下载失败或尝试重定向，未继续请求',502)
            mime=response.headers.get('content-type','').split(';',1)[0].strip().lower()
            if mime not in ('image/png','image/jpeg','image/webp') or response.headers.get('content-encoding','identity').lower() not in ('identity',''):raise DomainError('IMAGE_DOWNLOAD_TYPE','结果须为未压缩传输的PNG、JPEG或WebP',502)
            length=response.headers.get('content-length')
            if length:
                try:
                    if not 0<int(length)<=MAX_IMAGE_BYTES:raise ValueError()
                except ValueError:raise DomainError('IMAGE_TOO_LARGE','图片结果大小无效或超过20 MiB',502)
            chunks=[];count=0
            async for chunk in response.aiter_bytes():
                count+=len(chunk)
                if count>MAX_IMAGE_BYTES:raise DomainError('IMAGE_TOO_LARGE','图片结果超过20 MiB',502)
                chunks.append(chunk)
    result=sniff_image(b''.join(chunks))
    if result[1]!=mime:raise DomainError('IMAGE_DOWNLOAD_TYPE','图片声明类型与真实解码格式不一致',502)
    return result

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
    validate_base_url(config['base_url'])
    aliyun=config['response_format']=='aliyun_url'
    if aliyun:validate_aliyun_endpoint(config['base_url'])
    price=config.get('estimated_price_per_image');began=time.monotonic()
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
        if aliyun:body['prompt_extend']=False
        async with httpx.AsyncClient(timeout=httpx.Timeout(600 if aliyun else 120,connect=15),follow_redirects=False,trust_env=False) as client:
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
            if aliyun:
                receipt=save_image_receipt(store,run,items[0].get('url'),response.headers.get('x-request-id') or data.get('request_id'))
                current=store.get('run',run['id'],False)
                if not current or current['status']=='cancelled':raise DomainError('CANCELLED','任务已取消，不下载结果')
                try:result=await download_aliyun_result(receipt['url'])
                except DomainError as exc:raise DomainError(exc.code,f"阶段：结果下载；主机：{safe_result_host(receipt['url'])}；{exc.message}",exc.status)
                except httpx.HTTPError:raise DomainError('IMAGE_DOWNLOAD_FAILED',f"阶段：结果下载；主机：{safe_result_host(receipt['url'])}；连接失败，回执已保存",502)
            else:
                encoded=items[0].get('b64_json')
                if not isinstance(encoded,str):raise DomainError('IMAGE_BASE64_REQUIRED','通用协议仅支持b64_json；阿里云需明确选择aliyun_url',502)
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
                # Receipt/download steps may follow the paid request in the log.
                attempt=next(step for step in reversed(current['steps']) if step['step']=='image_request')
                attempt.update(status='succeeded' if success else 'failed',elapsed_seconds=round(time.monotonic()-began,3))
                inp=usage.get('input_tokens');out=usage.get('output_tokens')
                current['usage']={'input_tokens':inp if type(inp) is int and inp>=0 else None,'output_tokens':out if type(out) is int and out>=0 else None,'cost':price,'cost_status':'estimated' if price is not None else 'unknown','price_date':config.get('price_date'),'basis':'configured per-image estimate, not supplier invoice'};store.put('run',current)
