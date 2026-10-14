"""Only OpenAI-compatible chat/completions JSON protocol; no implicit calls."""
import os,json,asyncio,time
from pathlib import Path
import httpx
from datetime import datetime,timezone
from backend.store import DomainError,now

async def complete(store,run,settings,approval_id,payload,approval_kind="approval"):
    key=os.environ.get('LLM_API_KEY','')
    if not key or os.environ.get('PAID_CALLS_ENABLED','').lower() not in ('true','1','yes'):
        raise DomainError('CALLS_DISABLED','需配置后端 Key 并开启调用，再创建明确批准记录',403)
    if not settings.get('model') or not settings.get('base_url'):raise DomainError('MODEL_NOT_CONFIGURED','模型或服务地址未配置',400)
    rules=json.loads((Path(__file__).resolve().parents[1]/'prompts'/'roles.json').read_text())
    system=rules['boundary']+' '+rules['roles'].get(run.get('kind','chat'),rules['roles']['chat'])
    messages=[{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    for attempt in range(3):
        t=time.monotonic()
        with store.tx():
            r=store.get('run',run['id'])
            if r['status']=='cancelled':raise DomainError('CANCELLED','任务已取消')
            ap=store.get(approval_kind,approval_id or '',False)
            if not ap or (approval_kind=='approval' and ap.get('project_id')!=run.get('project_id')) or (approval_kind=='photo_approval' and (ap.get('photo_project_id')!=run.get('photo_project_id') or ap.get('purpose')!='prompt')) or ap['status']!='active' or datetime.fromisoformat(ap['expires_at'])<=datetime.now(timezone.utc):raise DomainError('APPROVAL_REQUIRED','缺少有效的项目调用批准',403)
            if ap.get('model_binding') and ap['model_binding']!={k:settings[k] for k in ('base_url','model','input_price_per_million','output_price_per_million','max_output_tokens')}:raise DomainError('APPROVAL_CONFIG_CHANGED','模型或价格改变，请重新批准',403)
            if ap['calls_used']>=ap['max_calls']:raise DomainError('CALL_LIMIT','批准的调用次数已用完',403)
            pi=settings.get('input_price_per_million');po=settings.get('output_price_per_million')
            known=pi is not None and po is not None
            if not known and not ap['accept_unknown_cost']:raise DomainError('UNKNOWN_COST','需明确接受未知费用',403)
            # UTF-8 byte bound is deliberately conservative for local preflight.
            reserve=(len(json.dumps(messages,ensure_ascii=False).encode())*pi+settings['max_output_tokens']*po)/1e6 if known else None
            if known and ap['budget'] is not None and ap['spent']+ap.get('reserved',0)+reserve>ap['budget']:raise DomainError('BUDGET_EXCEEDED','本地预算预检查未通过',403)
            ap['calls_used']+=1;ap['reserved']=ap.get('reserved',0)+(reserve or 0);store.put(approval_kind,ap)
            r['prompt_version']=rules['version'];r['steps'].append({'step':'model_request','attempt':attempt+1,'status':'running','at':now(),'model':settings['model']});store.put('run',r)
        response=None;usage={};success=False;retry=False;error=None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90),follow_redirects=False) as client:
                response=await client.post(settings['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':settings['model'],'messages':messages,'temperature':settings['temperature'],'max_tokens':settings['max_output_tokens'],'response_format':{'type':'json_object'}})
            if response.status_code in (429,500,502,503,504):
                retry=True;raise DomainError('UPSTREAM_RETRY','上游暂时不可用',502,True)
            if response.status_code in (401,403):raise DomainError('UPSTREAM_AUTH','上游鉴权失败',502)
            if response.status_code>=400:raise DomainError('UPSTREAM_ERROR',f'上游 HTTP {response.status_code}',502)
            data=response.json();usage=data.get('usage') or {};content=data['choices'][0]['message']['content'];result=json.loads(content)
            success=True
        except (httpx.TimeoutException,httpx.NetworkError):retry=True;error=DomainError('UPSTREAM_NETWORK','上游连接失败或超时',502,True)
        except DomainError as exc:error=exc
        except (ValueError,KeyError,TypeError):error=DomainError('MODEL_OUTPUT_INVALID','模型未返回有效 JSON；未保存正式产物',502)
        finally:
            with store.tx():
                ap=store.get(approval_kind,approval_id);ap['reserved']=max(0,ap.get('reserved',0)-(reserve or 0))
                inp=usage.get('prompt_tokens');out=usage.get('completion_tokens');cost=(inp*pi+out*po)/1e6 if known and isinstance(inp,int) and isinstance(out,int) else None
                # If upstream may have billed without reporting usage, hold conservative reserve.
                ap['spent']+=cost if cost is not None else (reserve or 0);store.put(approval_kind,ap)
                r=store.get('run',run['id']);r['steps'][-1].update(status='succeeded' if success else 'failed',elapsed_seconds=round(time.monotonic()-t,3),usage={'input_tokens':inp,'output_tokens':out,'estimated_cost':cost,'cost_status':'estimated' if cost is not None else 'unknown'})
                u=r['usage'];attempts=[s.get('usage',{}) for s in r['steps'] if s['step']=='model_request']
                partial={}
                for total_key,attempt_key in (('input_tokens','input_tokens'),('output_tokens','output_tokens'),('cost','estimated_cost')):
                    values=[a.get(attempt_key) for a in attempts]
                    available=[value for value in values if isinstance(value,(int,float))]
                    partial[total_key]=sum(available) if available else None
                    u[total_key]=sum(available) if len(available)==len(values) else None
                u['partial_known']=partial
                u['cost_status']='estimated' if u['cost'] is not None else 'unknown'
                u['price_date']=settings.get('price_date');store.put('run',r)
        if success:return result
        if not retry or attempt==2:raise error
        await asyncio.sleep(0.15*(2**attempt))
