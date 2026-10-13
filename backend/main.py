"""Local single-user API. All references are project-bound; keys stay server-side."""
import os,asyncio,sqlite3,json,csv,io
from pathlib import Path
from datetime import datetime,timezone,timedelta
from copy import deepcopy
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,Response,FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from backend.store import Store,DomainError,now,uid,dumps
from backend.schemas import *
from context.assembly import assemble
from memory.lifecycle import invalidate,erase_source_outputs
from tools.compiler import compile_document,check_document,PROFILES
from workflows.runner import execute

load_dotenv(Path(__file__).resolve().parents[1]/'.env',override=False)

def create_app(data_dir=None):
    store=Store(data_dir or os.environ.get('DATA_DIR') or Path(__file__).resolve().parents[1]/'data')
    tasks=set()
    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in list(tasks):task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        with store.lock:
            store.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)');store.conn.close()
    app=FastAPI(title='AIGC Script Studio',version='0.1.0',lifespan=lifespan)
    app.state.store=store;app.state.tasks=tasks
    app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173','http://localhost:8173','http://127.0.0.1:8173'],allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Content-Type'])
    @app.exception_handler(DomainError)
    async def domain_error(request,exc):return JSONResponse(status_code=exc.status,content={'error':{'code':exc.code,'message':exc.message,'retryable':exc.retryable}})
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):return JSONResponse(status_code=422,content={'error':{'code':'INVALID_INPUT','message':'; '.join(f"{'.'.join(map(str,e['loc']))}: {e['msg']}" for e in exc.errors()),'retryable':False}})
    def settings():
        default={'id':'model','mode':os.environ.get('LLM_MODE') or 'fixture','base_url':os.environ.get('LLM_BASE_URL') or '','model':os.environ.get('LLM_MODEL') or '','max_output_tokens':12000,'temperature':0.7,'input_price_per_million':None,'output_price_per_million':None,'price_date':None}
        config=store.get('settings','model',False) or default
        return {**config,'key_present':bool(os.environ.get('LLM_API_KEY')),'paid_calls_enabled':os.environ.get('PAID_CALLS_ENABLED','').lower() in ('true','1','yes')}
    def check_url(value,model=False):
        p=urlparse(value)
        if p.username or p.password or not p.hostname:raise DomainError('INVALID_URL','URL 不得含凭证，必须包含有效主机',422)
        if model:
            if p.query or p.fragment or not (p.scheme=='https' or p.scheme=='http' and p.hostname in ('localhost','127.0.0.1','::1')):raise DomainError('INVALID_URL','服务地址需 HTTPS 或本机 HTTP，不含查询参数',422)
        elif p.scheme not in ('https','http'):raise DomainError('INVALID_URL','仅支持 HTTP(S) 链接',422)
        return value
    def reference_check(p,refs):
        for ref in refs:
            type=ref['type'];id=ref['id']
            if type=='beat':
                if not id.isdigit() or not any(b['start_second']==int(id) for b in p['document']['beats']):raise DomainError('INVALID_REFERENCE','秒引用不属于当前项目',422)
            elif type=='shot':
                if not any(s['id']==id for s in p['document']['shots']):raise DomainError('INVALID_REFERENCE','分镜引用不属于当前项目',422)
            elif type=='revision':
                if not id.isdigit() or not store.get('revision',f"{p['id']}:{id}",False):raise DomainError('INVALID_REFERENCE','版本引用无效',422)
            else:
                m=store.get('message',id,False)
                if not m or m['project_id']!=p['id']:raise DomainError('INVALID_REFERENCE','消息引用不属于当前项目',422)
    def range_check(p,req):
        if not p['document']['beats']:raise DomainError('TIMELINE_REQUIRED','请先生成并应用时间轴',409)
        start=req.get('start_second');end=req.get('end_second')
        if start is None or end is None or not 0<=start<end<=p['brief']['duration_seconds']:raise DomainError('INVALID_RANGE','重写范围必须在完整时间轴内',422)
    def preflight(p,req,config):
        if config['mode']=='fixture' or req.get('kind')=='check':return
        if not config['key_present'] or not config['paid_calls_enabled']:raise DomainError('CALLS_DISABLED','真实调用需后端密钥、开关和明确批准',403)
        if not config['model'] or not config['base_url']:raise DomainError('MODEL_NOT_CONFIGURED','请先设置模型与服务地址',422)
        check_url(config['base_url'],True)
        ap=store.get('approval',req.get('approval_id') or '',False)
        if not ap or ap['project_id']!=p['id'] or ap['status']!='active' or datetime.fromisoformat(ap['expires_at'])<=datetime.now(timezone.utc):raise DomainError('APPROVAL_REQUIRED','请先批准此项目的调用范围和次数',403)
        if ap.get('model_binding') and ap['model_binding']!={k:config[k] for k in ('base_url','model','input_price_per_million','output_price_per_million','max_output_tokens')}:raise DomainError('APPROVAL_CONFIG_CHANGED','模型或价格已改变，请重新批准',403)
        if ap['calls_used']>=ap['max_calls']:raise DomainError('CALL_LIMIT','批准次数已用完',403)
        if (config['input_price_per_million'] is None or config['output_price_per_million'] is None) and not ap['accept_unknown_cost']:raise DomainError('UNKNOWN_COST','需明确接受未知费用',403)
    def launch(p,req,conversation_id=None):
        runkey=req['idempotency_key'];existing=next((r for r in store.list('run',p['id']) if r['idempotency_key']==runkey and r.get('conversation_id')==conversation_id),None)
        if existing:
            if existing['request']!=req:raise DomainError('IDEMPOTENCY_CONFLICT','相同幂等键不能用于不同请求',409)
            return existing,None
        store.match_version(p,req['base_revision'])
        if req['kind']=='timeline' and not (p['document'].get('story') or {}).get('confirmed'):raise DomainError('STORY_CONFIRM_REQUIRED','先应用并确认故事',409)
        if req['kind']=='rewrite':range_check(p,req)
        config=settings();preflight(p,req,config)
        ctx=assemble(store,p,conversation_id,req.get('references'))
        run={'id':uid(),'project_id':p['id'],'kind':req['kind'],'status':'queued','base_revision':req['base_revision'],'steps':[],'proposal_id':None,'result':None,'error':None,'usage':{'input_tokens':0 if config['mode']=='fixture' else None,'output_tokens':0 if config['mode']=='fixture' else None,'cost':0 if config['mode']=='fixture' else None,'cost_status':'fixture' if config['mode']=='fixture' else 'unknown'},'mode':config['mode'],'created_at':now(),'updated_at':now(),'request':req,'idempotency_key':runkey,'conversation_id':conversation_id,'context_id':ctx['id']}
        store.put('context',ctx);store.put('run',run)
        return run,config
    def dispatch(run,config):
        if config is None:return
        task=asyncio.create_task(execute(store,run['id'],config),name=run['id']);tasks.add(task);task.add_done_callback(tasks.discard)
    @app.get('/health')
    def health():return {'status':'ok','mode':settings()['mode'],'version':'0.1.0','owner_model':'local-single-user'}
    @app.get('/api/prompt-profiles')
    def profiles():return [{'id':k,**v} for k,v in PROFILES.items()]
    @app.get('/api/profile')
    def profile():return store.get('profile','owner')
    @app.patch('/api/profile')
    def profile_update(body:ProfilePatch):
        with store.tx():
            p=store.get('profile','owner');p.update(body.model_dump(exclude_none=True));store.put('profile',p);return p
    @app.get('/api/projects')
    def projects():return list(reversed(store.list('project')))
    @app.post('/api/projects',status_code=201)
    def project_create(body:NewProject):
        with store.tx():
            brief=body.brief.model_dump();p={'id':uid(),'owner_id':'local-owner','title':body.title or brief['description'][:24],'brief':brief,'current_revision':1,'document':{'story':None,'beats':[],'shots':[]},'created_at':now(),'updated_at':now()}
            store.put('project',p);store.put('revision',{'id':p['id']+':1','project_id':p['id'],'version':1,'parent_version':None,'source':'create','document':p['document'],'brief':brief,'title':p['title'],'created_at':now()});return p
    @app.get('/api/projects/{project_id}')
    def project_read(project_id:str):return store.project(project_id)
    @app.patch('/api/projects/{project_id}')
    def project_update(project_id:str,body:ProjectPatch):
        with store.tx():
            p=store.project(project_id);store.match_version(p,body.base_revision);doc=deepcopy(p['document']);brief=body.brief.model_dump() if body.brief else p['brief']
            if body.brief and {k:v for k,v in brief.items() if k!='prompt_profile'}!={k:v for k,v in p['brief'].items() if k!='prompt_profile'}:doc={'story':None,'beats':[],'shots':[]}
            elif body.brief:doc=compile_document(doc,brief)
            return store.write_revision(p,doc,'manual_project',brief,body.title)
    @app.delete('/api/projects/{project_id}')
    def project_delete(project_id:str):
        with store.tx():
            p=store.project(project_id)
            ids={r['id'] for r in store.list('run',project_id)}
            for task in list(tasks):
                if task.get_name() in ids:task.cancel()
            message_ids=[m['id'] for m in store.list('message',project_id)]
            invalidate(store,message_ids=message_ids)
            for kind in ('run','proposal','message','conversation','context','memory','revision','reference','feedback','approval'):
                for entity in store.list(kind,project_id):
                    if kind=='message':store.put('excluded_source',{'id':entity['id'],'reason':'project_deleted'})
                    store.delete(kind,entity['id'])
            store.delete('project',project_id)
        return {'deleted':True}
    @app.patch('/api/projects/{project_id}/story')
    def story_update(project_id:str,body:dict):
        if set(body)-{'base_revision','changes'}:raise DomainError('INVALID_INPUT','未知字段',422)
        changes=body.get('changes',{})
        if not isinstance(changes,dict) or set(changes)-{'title','synopsis','characters','scenes','assumptions'}:raise DomainError('INVALID_INPUT','故事字段无效',422)
        with store.tx():
            p=store.project(project_id);store.match_version(p,body.get('base_revision'));doc=deepcopy(p['document'])
            if not doc['story']:raise DomainError('STORY_REQUIRED','请先生成故事',409)
            doc['story'].update(changes);doc['story']['confirmed']=False
            try:doc['story']=Story.model_validate(doc['story']).model_dump()
            except ValidationError:raise DomainError('INVALID_INPUT','故事字段校验失败',422)
            if changes:doc['beats']=[];doc['shots']=[]
            return store.write_revision(p,doc,'manual_story')
    @app.post('/api/projects/{project_id}/story/confirm')
    def story_confirm(project_id:str,body:BaseRevision):
        with store.tx():
            p=store.project(project_id);store.match_version(p,body.base_revision);doc=deepcopy(p['document'])
            if not doc['story']:raise DomainError('STORY_REQUIRED','请先应用故事候选',409)
            doc['story']['confirmed']=True;return store.write_revision(p,doc,'confirm_story')
    @app.patch('/api/projects/{project_id}/beats/{second}')
    def beat_edit(project_id:str,second:int,body:BeatPatch):
        with store.tx():
            p=store.project(project_id);store.match_version(p,body.base_revision);doc=deepcopy(p['document'])
            if not 0<=second<len(doc['beats']):raise DomainError('INVALID_REFERENCE','秒不属于当前时间轴',422)
            doc['beats'][second].update(body.changes.model_dump(exclude_none=True));doc=compile_document(doc,p['brief'])
            return store.write_revision(p,doc,'manual_beat')
    @app.get('/api/projects/{project_id}/revisions')
    def revisions(project_id:str):store.project(project_id);return store.list('revision',project_id)
    @app.post('/api/projects/{project_id}/revisions/{version}/restore')
    def restore(project_id:str,version:int,body:BaseRevision):
        with store.tx():
            p=store.project(project_id);store.match_version(p,body.base_revision);r=store.get('revision',f'{project_id}:{version}');return store.write_revision(p,r['document'],'restore',r['brief'],r['title'])
    @app.post('/api/projects/{project_id}/runs',status_code=202)
    async def run_create(project_id:str,body:RunRequest):
        with store.tx():run,config=launch(store.project(project_id),body.model_dump())
        dispatch(run,config);return run
    @app.get('/api/projects/{project_id}/runs')
    def project_runs(project_id:str):store.project(project_id);return store.list('run',project_id)
    @app.get('/api/runs/{run_id}')
    def run_read(run_id:str):return store.get('run',run_id)
    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id:str):
        with store.tx():
            r=store.get('run',run_id)
            if r['status'] in ('queued','running','validating'):r.update(status='cancelled',updated_at=now());store.put('run',r)
            return r
    @app.get('/api/runs/{run_id}/context')
    def run_context(run_id:str):return store.get('context',store.get('run',run_id)['context_id'])
    @app.get('/api/projects/{project_id}/proposals')
    def proposals(project_id:str):store.project(project_id);return store.list('proposal',project_id)
    @app.post('/api/proposals/{proposal_id}/apply')
    def apply(proposal_id:str,body:BaseRevision):
        with store.tx():
            c=store.get('proposal',proposal_id);p=store.project(c['project_id']);store.match_version(p,body.base_revision)
            if c['status']!='pending':raise DomainError('PROPOSAL_NOT_PENDING','候选已应用或放弃',409)
            if c['base_revision']!=p['current_revision']:raise DomainError('REVISION_CONFLICT','候选基于旧版本，请重新生成',409)
            p=store.write_revision(p,c['document'],'apply_'+c['kind']);c.update(status='applied',applied_revision=p['current_revision']);store.put('proposal',c);return p
    @app.post('/api/proposals/{proposal_id}/dismiss')
    def dismiss(proposal_id:str):
        with store.tx():
            c=store.get('proposal',proposal_id)
            if c['status']!='pending':raise DomainError('PROPOSAL_NOT_PENDING','候选已处理',409)
            c['status']='dismissed';store.put('proposal',c);return c
    @app.get('/api/projects/{project_id}/checks')
    def checks(project_id:str):p=store.project(project_id);return check_document(p['document'],p['brief'],True)
    @app.get('/api/projects/{project_id}/exports')
    def exports(project_id:str,format:str='json'):
        p=store.project(project_id);check=check_document(p['document'],p['brief'],True)
        if not check['valid']:raise DomainError('EXPORT_BLOCKED','请修复结构或硬约束问题后导出',409)
        headers={'Content-Disposition':f'attachment; filename="script-{project_id}.{"md" if format=="markdown" else format}"'}
        if format=='json':return Response(dumps({'project':p,'checks':check,'notice':'时间要求需外部生成后验证；fixture为离线示例'}),media_type='application/json',headers=headers)
        if format=='markdown':
            text=f"# {p['title']}\n\n{p['document']['story']['synopsis']}\n\n版本：{p['current_revision']} · 模式：{p['document'].get('generation_mode','manual')}\n\n"
            for s in p['document']['shots']:text+=f"## {s['start_second']}–{s['end_second']} 秒\n\n{s['prompt']}\n\n"
            text+='## 逐秒剧本\n\n'+ '\n'.join(f"- {b['start_second']}–{b['end_second']}：{b['visual']} | {b['action']} | {b['camera']} | {b['dialogue']} | {b['sound']}\n  Prompt：{b['prompt']}" for b in p['document']['beats'])
            return Response(text,media_type='text/markdown',headers=headers)
        if format=='csv':
            output=io.StringIO();writer=csv.writer(output);writer.writerow(['start_second','end_second','visual','action','camera','dialogue','sound','prompt','shot_prompt'])
            def safe(v):return "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v
            for b in p['document']['beats']:
                shot=next(s for s in p['document']['shots'] if b['start_second'] in s['beat_seconds']);writer.writerow([safe(b[k]) for k in ('start_second','end_second','visual','action','camera','dialogue','sound','prompt')]+[safe(shot['prompt'])])
            return Response('\ufeff'+output.getvalue(),media_type='text/csv',headers=headers)
        raise DomainError('INVALID_FORMAT','仅支持 json/markdown/csv',422)
    @app.get('/api/projects/{project_id}/conversations')
    def conversations(project_id:str):store.project(project_id);return store.list('conversation',project_id)
    @app.post('/api/projects/{project_id}/conversations',status_code=201)
    def conversation_create(project_id:str,body:ConversationNew):
        with store.tx():
            store.project(project_id);c={'id':uid(),'project_id':project_id,'title':body.title,'created_at':now()};store.put('conversation',c);return c
    @app.get('/api/conversations/{conversation_id}/messages')
    def messages(conversation_id:str):
        c=store.get('conversation',conversation_id);return [m for m in store.list('message',c['project_id']) if m['conversation_id']==conversation_id]
    @app.post('/api/conversations/{conversation_id}/messages',status_code=202)
    async def message_send(conversation_id:str,body:MessageNew):
        with store.tx():
            c=store.get('conversation',conversation_id);p=store.project(c['project_id']);refs=[x.model_dump() for x in body.references];reference_check(p,refs)
            existing=next((r for r in store.list('run',p['id']) if r.get('conversation_id')==conversation_id and r['idempotency_key']==body.idempotency_key),None)
            if existing:
                if existing['request'].get('message_body')!=body.model_dump():raise DomainError('IDEMPOTENCY_CONFLICT','相同幂等键对应不同消息',409)
                return existing
            req={'kind':'rewrite' if body.intent=='rewrite' else 'chat','base_revision':p['current_revision'],'idempotency_key':body.idempotency_key,'content':body.content,'instruction':body.content,'references':refs,'approval_id':body.approval_id,'start_second':body.start_second,'end_second':body.end_second,'locked_fields':[],'message_body':body.model_dump()}
            if body.intent=='rewrite':range_check(p,req)
            preflight(p,req,settings())
            message={'id':uid(),'project_id':p['id'],'conversation_id':conversation_id,'role':'user','content':body.content,'references':refs,'created_at':now(),'run_id':None};store.put('message',message)
            run,config=launch(p,req,conversation_id);message['run_id']=run['id'];store.put('message',message)
        dispatch(run,config);return run
    def delete_message(m):
        store.put('excluded_source',{'id':m['id'],'reason':'source_deleted'});affected=invalidate(store,message_ids=[m['id']]);erase_source_outputs(store,affected);store.delete('message',m['id'])
    @app.delete('/api/messages/{message_id}')
    def message_delete(message_id:str):
        with store.tx():delete_message(store.get('message',message_id))
        return {'deleted':True,'derived_outputs_redacted':True,'retained_independent_artifacts':['applied_project_revisions','existing_backups']}
    @app.delete('/api/conversations/{conversation_id}')
    def conversation_delete(conversation_id:str):
        with store.tx():
            c=store.get('conversation',conversation_id)
            for m in store.list('message',c['project_id']):
                if m['conversation_id']==conversation_id:delete_message(m)
            store.delete('conversation',conversation_id)
        return {'deleted':True,'derived_outputs_redacted':True,'retained_independent_artifacts':['applied_project_revisions','existing_backups']}
    @app.get('/api/memories')
    def memories(project_id:str|None=None):
        if project_id:store.project(project_id)
        return [m for m in store.list('memory') if m['status']!='deleted' and (m['scope']=='user' or m['project_id']==project_id and project_id is not None)]
    @app.post('/api/memories',status_code=201)
    def memory_create(body:MemoryNew):
        with store.tx():
            if body.scope=='project' and not body.project_id:raise DomainError('PROJECT_REQUIRED','项目记忆必须指定项目',422)
            if body.project_id:store.project(body.project_id)
            if body.scope=='user' and body.project_id:raise DomainError('INVALID_SCOPE','用户级记忆不附属项目',422)
            source_project=None
            for id in body.source_message_ids:
                if store.get('excluded_source',id,False):raise DomainError('SOURCE_EXCLUDED','该来源已被排除，不得重新提取记忆',409)
                m=store.get('message',id);source_project=source_project or m['project_id']
                if m['project_id']!=source_project or body.scope=='project' and m['project_id']!=body.project_id:raise DomainError('INVALID_REFERENCE','记忆来源不能串项目',422)
            if body.source_revision:
                if not body.project_id:raise DomainError('PROJECT_REQUIRED','版本来源需指定项目范围',422)
                store.get('revision',f'{body.project_id}:{body.source_revision}')
            mem={'id':uid(),'owner_id':'local-owner',**body.model_dump(),'status':'candidate','version':1,'created_at':now(),'updated_at':now()};store.put('memory',mem);return mem
    @app.patch('/api/memories/{memory_id}')
    def memory_edit(memory_id:str,body:MemoryPatch):
        with store.tx():
            m=store.get('memory',memory_id)
            if m['status']=='deleted':raise DomainError('NOT_FOUND','记忆已删除',404)
            if m['version']!=body.expected_version:raise DomainError('MEMORY_CONFLICT','记忆版本已改变',409)
            for id in m['source_message_ids']:store.put('excluded_source',{'id':id,'reason':'memory_edited'})
            invalidate(store,memory_ids=[memory_id],message_ids=m['source_message_ids'])
            m.update(version=m['version']+1,updated_at=now(),status=body.status or 'candidate')
            if body.content:m['content']=body.content
            store.put('memory',m);return m
    @app.post('/api/memories/{memory_id}/confirm')
    def memory_confirm(memory_id:str,body:MemoryConfirm):
        with store.tx():
            m=store.get('memory',memory_id)
            if m['status']=='deleted':raise DomainError('NOT_FOUND','记忆已删除',404)
            if m['version']!=body.expected_version:raise DomainError('MEMORY_CONFLICT','记忆版本已改变',409)
            for id in m['source_message_ids']:
                if not store.get('message',id,False) or (store.get('excluded_source',id,False) or {}).get('reason') in ('memory_deleted','source_deleted','project_deleted','derived_context_invalidated'):raise DomainError('SOURCE_EXCLUDED','来源已失效，不能确认',409)
            m.update(status='confirmed',version=m['version']+1,updated_at=now());store.put('memory',m);return m
    @app.delete('/api/memories/{memory_id}')
    def memory_delete(memory_id:str):
        with store.tx():
            m=store.get('memory',memory_id)
            linked=list(m['source_message_ids'])
            for message in store.list('message'):
                if m['content'] and m['content'] in message['content'] and (m['scope']=='user' or message['project_id']==m['project_id']):linked.append(message['id'])
            for id in set(linked):store.put('excluded_source',{'id':id,'reason':'memory_deleted'})
            invalidate(store,message_ids=linked,memory_ids=[memory_id]);m.update(content='',status='deleted',version=m['version']+1,updated_at=now());store.put('memory',m)
        return {'deleted':True,'historical_messages_retained':True,'source_excluded_from_future_context':True}
    @app.get('/api/settings/model')
    def model_settings():return settings()
    @app.patch('/api/settings/model')
    def model_update(body:ModelPatch):
        with store.tx():
            cfg=settings();cfg.pop('key_present');cfg.pop('paid_calls_enabled');updates=body.model_dump(exclude_unset=True)
            if any(updates.get(k,False) is None for k in ('mode','base_url','model','max_output_tokens','temperature')):raise DomainError('INVALID_INPUT','模型核心配置不能为 null',422)
            cfg.update(updates)
            if cfg['base_url']:check_url(cfg['base_url'],True)
            store.put('settings',cfg);return settings()
    @app.get('/api/approvals')
    def approvals():return store.list('approval')
    @app.post('/api/approvals',status_code=201)
    def approval_create(body:ApprovalNew):
        with store.tx():
            store.project(body.project_id);cfg=settings()
            if (cfg['input_price_per_million'] is None or cfg['output_price_per_million'] is None) and not body.accept_unknown_cost:raise DomainError('UNKNOWN_COST','价格未知，必须明确接受未知费用',422)
            a={'id':uid(),**body.model_dump(),'calls_used':0,'spent':0,'reserved':0,'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=body.expires_in_minutes)).isoformat(),'status':'active','created_at':now(),'model_binding':{k:cfg[k] for k in ('base_url','model','input_price_per_million','output_price_per_million','max_output_tokens')}};store.put('approval',a);return a
    @app.delete('/api/approvals/{approval_id}')
    def approval_revoke(approval_id:str):
        with store.tx():a=store.get('approval',approval_id);a['status']='revoked';store.put('approval',a)
        return a
    @app.get('/api/projects/{project_id}/references')
    def references(project_id:str):store.project(project_id);return store.list('reference',project_id)
    @app.post('/api/projects/{project_id}/references',status_code=201)
    def reference_create(project_id:str,body:ReferenceNew):
        with store.tx():
            store.project(project_id);check_url(body.url);r={'id':uid(),'project_id':project_id,**body.model_dump(),'created_at':now(),'source_type':'user-provided','observed_by_system':False};store.put('reference',r);return r
    @app.get('/api/projects/{project_id}/feedback')
    def feedback(project_id:str):store.project(project_id);return store.list('feedback',project_id)
    @app.post('/api/projects/{project_id}/feedback',status_code=201)
    def feedback_create(project_id:str,body:FeedbackNew):
        with store.tx():
            store.project(project_id);store.get('revision',f'{project_id}:{body.revision}');check_url(body.url);r={'id':uid(),'project_id':project_id,**body.model_dump(),'created_at':now(),'evaluation_type':'user-reported'};store.put('feedback',r);return r
    @app.post('/api/backups',status_code=201)
    def backup_create():
        id=uid();folder=store.path/'backups';folder.mkdir(exist_ok=True);path=folder/(id+'.sqlite3')
        with store.lock:
            target=sqlite3.connect(path)
            try:store.conn.backup(target)
            finally:target.close()
        with store.tx():meta={'id':id,'filename':path.name,'created_at':now()};store.put('backup',meta)
        return meta
    @app.get('/api/backups/{backup_id}/download')
    def backup_download(backup_id:str):
        b=store.get('backup',backup_id);return FileResponse(store.path/'backups'/b['filename'],media_type='application/vnd.sqlite3',filename=b['filename'])
    return app

app=create_app()
