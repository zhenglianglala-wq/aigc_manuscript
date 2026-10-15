"""Independent photo workspace; prompt and image actions/approvals are separate."""
import asyncio,os,json
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fastapi.responses import Response,FileResponse
from backend.store import DomainError,uid,now,dumps
from backend.schemas import BaseRevision
from backend.photo_schemas import *
from tools.photo_model import require_approval,model_binding,validate_base_url,validate_aliyun_endpoint,load_image_receipt,receipt_path
from tools.prompt_quality import photo_quality
from workflows.photo import execute_photo,compile_photo_prompt,check_photo_prompt

def register_photo_routes(app,store,tasks,text_settings):
    def photo(id):return store.get('photo_project',id)
    def version_match(p,base):
        if p['current_revision']!=base:raise DomainError('REVISION_CONFLICT','照片版本已改变，请刷新比较',409)
    def image_settings():
        cfg=store.get('settings','photo_image',False) or {'id':'photo_image','mode':os.environ.get('IMAGE_MODE') or 'fixture','base_url':os.environ.get('IMAGE_BASE_URL') or '','model':os.environ.get('IMAGE_MODEL') or '','size':'1024x1024','response_format':'auto','estimated_price_per_image':None,'price_date':None}
        return {**cfg,'key_present':bool(os.environ.get('IMAGE_API_KEY')),'paid_calls_enabled':os.environ.get('PAID_IMAGE_CALLS_ENABLED','').lower() in ('true','1','yes'),'base64_only':cfg['response_format']!='aliyun_url'}
    def revised(p,prompt,source,brief=None,title=None):
        parent=p['current_revision'];p.update(current_revision=parent+1,prompt=prompt,updated_at=now())
        if brief is not None:p['brief']=brief
        if title is not None:p['title']=title
        store.put('photo_project',p);store.put('photo_revision',{'id':f"{p['id']}:{p['current_revision']}",'photo_project_id':p['id'],'version':p['current_revision'],'parent_version':parent,'prompt':p['prompt'],'brief':p['brief'],'title':p['title'],'source':source,'created_at':now()});return p
    def scoped(kind,id):
        item=store.get(kind,id);photo(item['photo_project_id']);return item
    def preflight(run,config,purpose):
        if config['mode']=='fixture':return
        if not config['key_present'] or not config['paid_calls_enabled']:raise DomainError('IMAGE_CALLS_DISABLED' if purpose=='image' else 'CALLS_DISABLED','需配置此用途的后端密钥和开关，并明确批准调用',403)
        if not config['base_url'] or not config['model']:raise DomainError('MODEL_NOT_CONFIGURED','请填写服务地址与模型',422)
        validate_base_url(config['base_url'])
        if purpose=='image' and config['response_format']=='aliyun_url':validate_aliyun_endpoint(config['base_url'])
        require_approval(store,run,config,purpose)
    def launch(p,body,purpose):
        request=body.model_dump();kind='photo_'+purpose;existing=next((r for r in store.list('run') if r.get('photo_project_id')==p['id'] and r['kind']==kind and r['idempotency_key']==body.idempotency_key),None)
        config=image_settings() if purpose=='image' else text_settings()
        if existing:
            snapshot={k:v for k,v in config.items() if k not in ('key_present','paid_calls_enabled')}
            original_request=deepcopy(existing['request']['original_request'])
            if purpose=='prompt':original_request.setdefault('creative_direction','faithful')
            if original_request!=request or existing['request']['settings_snapshot']!=snapshot:raise DomainError('IDEMPOTENCY_CONFLICT','相同幂等键对应不同照片请求',409)
            return existing,None
        version_match(p,body.base_revision)
        prompt_snapshot=deepcopy(p['prompt']);prompt_source='project'
        if purpose=='image':
            if body.direct_prompt is not None:
                if not body.confirm_direct_prompt:raise DomainError('DIRECT_PROMPT_CONFIRM_REQUIRED','请明确确认直接输入的Prompt后生成图片',409)
                prompt_snapshot={'compiled_prompt':body.direct_prompt};prompt_source='direct'
                check=check_photo_prompt(prompt_snapshot,p['brief'])
            else:
                if not p['prompt'] or not p['prompt']['confirmed']:raise DomainError('PHOTO_PROMPT_CONFIRM_REQUIRED','请确认项目Prompt，或直接输入已有Prompt并确认',409)
                check=check_photo_prompt(p['prompt'],p['brief'])
            if not check['valid']:raise DomainError('PHOTO_CONSTRAINT_FAILED','Prompt未满足硬约束，请修改后确认',409)
        run={'id':uid(),'project_id':None,'photo_project_id':p['id'],'kind':kind,'status':'queued','base_revision':p['current_revision'],'mode':config['mode'],'steps':[],'usage':{'input_tokens':0 if config['mode']=='fixture' else None,'output_tokens':0 if config['mode']=='fixture' else None,'cost':0 if config['mode']=='fixture' else None,'cost_status':'fixture' if config['mode']=='fixture' else 'unknown'},'result':None,'error':None,'proposal_id':None,'idempotency_key':body.idempotency_key,'created_at':now(),'updated_at':now(),'request':{**request,'original_request':request,'brief_snapshot':deepcopy(p['brief']),'prompt_snapshot':prompt_snapshot,'prompt_source':prompt_source,'settings_snapshot':{k:v for k,v in config.items() if k not in ('key_present','paid_calls_enabled')}}}
        preflight(run,config,purpose)
        context={'id':uid(),'project_id':None,'photo_project_id':p['id'],'revision':p['current_revision'],'message_ids':[],'memory_ids':[],'reference_ids':[],'summary':{'text':'','source_message_ids':[],'method':'photo-snapshot'},'messages':[],'memories':[],'valid':True,'created_at':now()};run['context_id']=context['id']
        store.put('context',context);store.put('run',run);return run,config
    def dispatch(run,config):
        if config is None:return
        task=asyncio.create_task(execute_photo(store,run['id'],config),name=run['id']);tasks.add(task);task.add_done_callback(tasks.discard)
    @app.get('/api/photo-projects')
    def projects():return list(reversed(store.list('photo_project')))
    @app.post('/api/photo-projects',status_code=201)
    def create(body:PhotoProjectNew):
        with store.tx():
            p={'id':uid(),'owner_id':'local-owner','title':body.title or body.brief.description[:24],'brief':body.brief.model_dump(),'current_revision':1,'prompt':None,'created_at':now(),'updated_at':now()};store.put('photo_project',p);store.put('photo_revision',{'id':p['id']+':1','photo_project_id':p['id'],'version':1,'parent_version':None,'prompt':None,'brief':p['brief'],'title':p['title'],'source':'create','created_at':now()});return p
    @app.get('/api/photo-projects/{project_id}')
    def read(project_id:str):return photo(project_id)
    @app.patch('/api/photo-projects/{project_id}')
    def update(project_id:str,body:PhotoProjectPatch):
        with store.tx():
            p=photo(project_id);version_match(p,body.base_revision);brief=body.brief.model_dump() if body.brief else p['brief'];prompt=None if brief!=p['brief'] else p['prompt'];return revised(p,prompt,'manual_project',brief,body.title)
    @app.delete('/api/photo-projects/{project_id}')
    def delete(project_id:str):
        paths=[]
        with store.tx():
            photo(project_id);ids={r['id'] for r in store.list('run') if r.get('photo_project_id')==project_id}
            for task in list(tasks):
                if task.get_name() in ids:task.cancel()
            paths.extend(receipt_path(store,rid) for rid in ids)
            for kind in ('photo_revision','photo_proposal','photo_asset','photo_feedback','photo_approval','run','context'):
                for item in store.list(kind):
                    if item.get('photo_project_id')==project_id:
                        if kind=='photo_asset':paths.append(asset_path(item))
                        store.delete(kind,item['id'])
            store.delete('photo_project',project_id)
        for path in paths:path.unlink(missing_ok=True)
        return {'deleted':True,'existing_backups_retained':True}
    @app.post('/api/photo-projects/{project_id}/quality')
    def quality(project_id:str,body:PhotoQualityRequest):
        with store.lock:
            p=photo(project_id);version_match(p,body.base_revision)
            report=photo_quality(p['brief'],p['prompt'],body.text)
            return {'project_revision':p['current_revision'],'current':report,'baseline':photo_quality(p['brief'],text=body.baseline) if body.baseline is not None else None,'comparison_notice':'对照仅比较写作线索，不推断哪张图片更好；需要同模型、同参数与人工盲评。'}
    @app.post('/api/photo-assets/{asset_id}/feedback',status_code=201)
    def photo_feedback(asset_id:str,body:PhotoFeedbackNew):
        with store.tx():
            asset=scoped('photo_asset',asset_id)
            record={'id':uid(),'photo_project_id':asset['photo_project_id'],'asset_id':asset_id,'asset_mode':asset['mode'],'prompt_text':asset['prompt_text'],'source_revision':asset.get('source_project_revision',asset.get('prompt_revision')),'model':asset['model'],'settings_snapshot':asset['settings_snapshot'],'evaluation_type':'user-reported',**body.model_dump(),'created_at':now()}
            store.put('photo_feedback',record);return record
    @app.get('/api/photo-projects/{project_id}/feedback')
    def photo_feedback_list(project_id:str):
        photo(project_id);return [r for r in store.list('photo_feedback') if r['photo_project_id']==project_id]
    @app.get('/api/photo-projects/{project_id}/runs')
    def runs(project_id:str):photo(project_id);return [r for r in store.list('run') if r.get('photo_project_id')==project_id]
    @app.post('/api/photo-projects/{project_id}/prompt-runs',status_code=202)
    async def prompt_run(project_id:str,body:PhotoPromptRun):
        with store.tx():r,cfg=launch(photo(project_id),body,'prompt')
        dispatch(r,cfg);return r
    @app.post('/api/photo-projects/{project_id}/image-runs',status_code=202)
    async def image_run(project_id:str,body:PhotoImageRun):
        with store.tx():r,cfg=launch(photo(project_id),body,'image')
        dispatch(r,cfg);return r
    @app.post('/api/photo-projects/{project_id}/runs/{original_run_id}/recover-image',status_code=202)
    async def recover_image(project_id:str,original_run_id:str,body:PhotoRecoveryRun):
        with store.tx():
            photo(project_id);original=store.get('run',original_run_id)
            if original.get('photo_project_id')!=project_id or original['kind']!='photo_image':raise DomainError('INVALID_REFERENCE','原任务不属于此照片项目或不是生成图片任务',422)
            if original['status']=='cancelled':raise DomainError('RECOVERY_CANCELLED','已取消的生成任务不能恢复下载',409)
            recoveries=[r for r in store.list('run') if r.get('recovery_of')==original_run_id]
            existing=next((r for r in recoveries if r['idempotency_key']==body.idempotency_key or r['status'] in ('queued','running','validating','succeeded')),None)
            if existing:return existing
            if original['status'] not in ('failed','interrupted'):raise DomainError('RECOVERY_NOT_AVAILABLE','仅失败或中断的Aliyun下载任务可恢复',409)
            config=deepcopy(original['request']['settings_snapshot'])
            if original['mode']!='openai-compatible' or config.get('response_format')!='aliyun_url':raise DomainError('RECOVERY_NOT_AVAILABLE','仅Aliyun URL结果支持无生成恢复',409)
            load_image_receipt(store,original)
            request=deepcopy(original['request']);request['approval_id']=None
            run={'id':uid(),'project_id':None,'photo_project_id':project_id,'kind':'photo_image_recovery','status':'queued','base_revision':original['base_revision'],'mode':original['mode'],'steps':[],'usage':{'input_tokens':0,'output_tokens':0,'cost':0,'cost_status':'recovery_no_generation'},'result':None,'error':None,'proposal_id':None,'idempotency_key':body.idempotency_key,'created_at':now(),'updated_at':now(),'request':request,'recovery_of':original_run_id,'context_id':original['context_id']}
            store.put('run',run)
        dispatch(run,config);return run
    @app.get('/api/photo-projects/{project_id}/proposals')
    def proposals(project_id:str):photo(project_id);return [c for c in store.list('photo_proposal') if c['photo_project_id']==project_id]
    @app.post('/api/photo-proposals/{proposal_id}/apply')
    def apply(proposal_id:str,body:BaseRevision):
        with store.tx():
            c=scoped('photo_proposal',proposal_id);p=photo(c['photo_project_id']);version_match(p,body.base_revision)
            if c['status']!='pending':raise DomainError('PROPOSAL_NOT_PENDING','照片候选已处理',409)
            if c['base_revision']!=p['current_revision']:raise DomainError('REVISION_CONFLICT','照片候选基于旧版本',409)
            prompt=deepcopy(c['prompt']);prompt['confirmed']=False;p=revised(p,prompt,'apply_prompt');c.update(status='applied',applied_revision=p['current_revision']);store.put('photo_proposal',c);return p
    @app.post('/api/photo-proposals/{proposal_id}/dismiss')
    def dismiss(proposal_id:str):
        with store.tx():
            c=scoped('photo_proposal',proposal_id)
            if c['status']!='pending':raise DomainError('PROPOSAL_NOT_PENDING','照片候选已处理',409)
            c['status']='dismissed';store.put('photo_proposal',c);return c
    @app.patch('/api/photo-projects/{project_id}/prompt')
    def edit_prompt(project_id:str,body:PhotoPromptPatch):
        with store.tx():
            p=photo(project_id);version_match(p,body.base_revision)
            if not p['prompt']:raise DomainError('PHOTO_PROMPT_REQUIRED','请先生成并应用照片Prompt',409)
            prompt=deepcopy(p['prompt']);prompt.update(body.changes.model_dump(exclude_none=True));prompt['confirmed']=False;prompt=compile_photo_prompt(prompt,p['brief']);return revised(p,prompt,'manual_prompt')
    @app.post('/api/photo-projects/{project_id}/prompt/confirm')
    def confirm(project_id:str,body:BaseRevision):
        with store.tx():
            p=photo(project_id);version_match(p,body.base_revision)
            if not p['prompt']:raise DomainError('PHOTO_PROMPT_REQUIRED','请先生成并应用照片Prompt',409)
            check=check_photo_prompt(p['prompt'],p['brief'])
            if not check['valid']:raise DomainError('PHOTO_CONSTRAINT_FAILED','Prompt存在硬约束问题，请编辑修正',409)
            prompt=deepcopy(p['prompt']);prompt['confirmed']=True;return revised(p,prompt,'confirm_prompt')
    @app.get('/api/photo-projects/{project_id}/revisions')
    def revisions(project_id:str):photo(project_id);return [r for r in store.list('photo_revision') if r['photo_project_id']==project_id]
    @app.post('/api/photo-projects/{project_id}/revisions/{version}/restore')
    def restore(project_id:str,version:int,body:BaseRevision):
        with store.tx():
            p=photo(project_id);version_match(p,body.base_revision);r=store.get('photo_revision',f'{project_id}:{version}');prompt=deepcopy(r['prompt'])
            if prompt:prompt['confirmed']=False
            return revised(p,prompt,'restore',r['brief'],r['title'])
    @app.get('/api/photo-projects/{project_id}/exports')
    def export(project_id:str,format:str='json'):
        p=photo(project_id)
        if not p['prompt']:raise DomainError('PHOTO_PROMPT_REQUIRED','尚无照片Prompt',409)
        headers={'Content-Disposition':f'attachment; filename="photo-prompt-{project_id}.{"md" if format=="markdown" else "json"}"'}
        if format=='json':return Response(dumps({'photo_project':p,'checks':check_photo_prompt(p['prompt'],p['brief']),'notice':'结构化照片Prompt；fixture为离线模板，效果未验证'}),media_type='application/json',headers=headers)
        if format=='markdown':
            text=f"# {p['title']}\n\n版本：{p['current_revision']} · 模式：{p['prompt']['generation_mode']} · 已确认：{p['prompt']['confirmed']}\n\n{p['prompt']['compiled_prompt']}\n\n负向约束（元数据，不自动发送）：{'、'.join(p['prompt']['negative_constraints'])}\n"
            return Response(text,media_type='text/markdown',headers=headers)
        raise DomainError('INVALID_FORMAT','照片Prompt导出仅支持json/markdown',422)
    def asset_path(a):
        filename=a['filename']
        if filename not in [a['id']+'.'+ext for ext in ('svg','png','jpg','webp')]:raise DomainError('ASSET_INVALID','图片资产路径无效',500)
        path=store.path/'photo-assets'/filename
        if path.is_symlink():raise DomainError('ASSET_INVALID','图片资产不得为符号链接',500)
        return path
    @app.get('/api/photo-projects/{project_id}/assets')
    def assets(project_id:str):photo(project_id);return [a for a in store.list('photo_asset') if a['photo_project_id']==project_id]
    @app.get('/api/photo-assets/{asset_id}/preview')
    def preview(asset_id:str):
        a=scoped('photo_asset',asset_id);path=asset_path(a)
        if not path.is_file():raise DomainError('ASSET_MISSING','图片文件不存在，请恢复包含图片的完整备份',404)
        return FileResponse(path,media_type=a['mime_type'],headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox; default-src 'none'"})
    @app.get('/api/photo-assets/{asset_id}/download')
    def download(asset_id:str):
        a=scoped('photo_asset',asset_id);path=asset_path(a)
        if not path.is_file():raise DomainError('ASSET_MISSING','图片文件不存在',404)
        return FileResponse(path,media_type=a['mime_type'],filename=a['filename'],headers={'X-Content-Type-Options':'nosniff'})
    @app.get('/api/photo-settings/image')
    def image_config():return image_settings()
    @app.patch('/api/photo-settings/image')
    def image_update(body:PhotoImageSettings):
        with store.tx():
            cfg=image_settings();cfg={k:v for k,v in cfg.items() if k not in ('key_present','paid_calls_enabled','base64_only')};updates=body.model_dump(exclude_unset=True)
            if any(updates.get(k,False) is None for k in ('mode','base_url','model','size','response_format')):raise DomainError('INVALID_INPUT','图片核心配置不能为null',422)
            cfg.update(updates)
            if cfg['base_url']:
                validate_base_url(cfg['base_url'])
                if cfg['response_format']=='aliyun_url':validate_aliyun_endpoint(cfg['base_url'])
            store.put('settings',cfg);return image_settings()
    @app.get('/api/photo-settings/prompt')
    def prompt_config():return {**text_settings(),'approval_scope':'photo_prompt'}
    @app.get('/api/photo-approvals')
    def approvals(photo_project_id:str|None=None):
        if photo_project_id:photo(photo_project_id)
        return [a for a in store.list('photo_approval') if not photo_project_id or a['photo_project_id']==photo_project_id]
    @app.post('/api/photo-approvals',status_code=201)
    def approve(body:PhotoApprovalNew):
        with store.tx():
            photo(body.photo_project_id);cfg=image_settings() if body.purpose=='image' else text_settings();known=cfg['estimated_price_per_image'] is not None if body.purpose=='image' else cfg['input_price_per_million'] is not None and cfg['output_price_per_million'] is not None
            binding=model_binding(cfg,body.purpose)
            if body.expected_model_binding is not None and body.expected_model_binding!=binding:raise DomainError('APPROVAL_CONFIG_CHANGED','确认期间服务、模型或参数已改变，请刷新后重新确认',409)
            if not known and not body.accept_unknown_cost:raise DomainError('UNKNOWN_COST','价格未知，需要明确接受未知费用',422)
            a={'id':uid(),**body.model_dump(exclude={'expected_model_binding'}),'status':'active','calls_used':0,'spent':0,'reserved':0,'model_binding':binding,'created_at':now(),'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=body.expires_in_minutes)).isoformat()};store.put('photo_approval',a);return a
    @app.delete('/api/photo-approvals/{approval_id}')
    def revoke(approval_id:str):
        with store.tx():
            a=scoped('photo_approval',approval_id);a['status']='revoked';store.put('photo_approval',a);return a
