import asyncio,time
from pathlib import Path
from backend.store import now,uid,DomainError
from backend.photo_schemas import PhotoPrompt
from agents.photo_fixture import make_prompt,placeholder
from tools.model import complete
from tools.photo_model import generate_image

PROMPT_FIELDS=('subject','environment','composition','lighting','camera','style','color','mood','details')
def compile_photo_prompt(prompt,brief,mode=None):
    p=PhotoPrompt.model_validate(prompt).model_dump()
    if mode:p['generation_mode']=mode
    p['compiled_prompt']='。'.join(p[key] for key in PROMPT_FIELDS if p[key])+'。'
    p['negative_constraints']=list(dict.fromkeys(p['negative_constraints']+brief['must_avoid']))
    return p

def check_photo_prompt(prompt,brief):
    issues=[];text=prompt['compiled_prompt']
    for value in brief['must_include']:
        if value not in text:issues.append({'code':'MUST_INCLUDE','message':'缺少必须内容：'+value})
    for value in brief['must_avoid']:
        if value in text:issues.append({'code':'MUST_AVOID','message':'正向Prompt出现禁止内容：'+value})
    return {'valid':not issues,'issues':issues,'scope':'literal mechanical checks; visual quality unverified'}

async def execute_photo(store,run_id,config):
    began=time.monotonic();path=None
    try:
        await asyncio.sleep(0.03)
        with store.tx():
            run=store.get('run',run_id)
            if run['status']=='cancelled':return
            store.get('photo_project',run['photo_project_id'])
            run.update(status='running',updated_at=now());run['steps'].append({'step':'load_photo_snapshot','status':'succeeded','at':now()});store.put('run',run)
        request=run['request'];brief=request['brief_snapshot'];proposal_id=None;asset=None
        if run['kind']=='photo_prompt':
            if config['mode']=='fixture':prompt=compile_photo_prompt(make_prompt(brief,request.get('instruction','')),brief,'fixture')
            else:
                payload={'task':'photo_prompt','brief':brief,'current_prompt':request.get('prompt_snapshot'),'instruction':request.get('instruction',''),'output_schema':PhotoPrompt.model_json_schema(),'rules':'只生成照片Prompt JSON，不生成图片，confirmed必须false'}
                for repair in range(2):
                    try:
                        output=await complete(store,run,config,request.get('approval_id'),payload,approval_kind='photo_approval')
                        prompt=compile_photo_prompt(output,brief,'openai-compatible');break
                    except (DomainError,ValueError,TypeError,KeyError) as exc:
                        if repair or isinstance(exc,DomainError) and exc.code!='MODEL_OUTPUT_INVALID':raise
                        payload['repair_instruction']='前一结果未满足Schema，严格修复后只输出JSON。'
            prompt['confirmed']=False;checks=check_photo_prompt(prompt,brief)
            with store.tx():
                current=store.get('run',run_id)
                if current['status']=='cancelled':return
                store.get('photo_project',run['photo_project_id'])
                proposal_id=uid();store.put('photo_proposal',{'id':proposal_id,'photo_project_id':run['photo_project_id'],'base_revision':run['base_revision'],'status':'pending','prompt':prompt,'diff':{'prompt_changed':prompt!=request.get('prompt_snapshot')},'issues':checks['issues'],'created_at':now(),'run_id':run_id})
                current.update(status='succeeded',proposal_id=proposal_id,result=checks,elapsed_seconds=round(time.monotonic()-began,3),updated_at=now());current['steps'].append({'step':'save_prompt_candidate','status':'succeeded','at':now()});store.put('run',current)
        else:
            if config['mode']=='fixture':raw,mime,ext,width,height=placeholder(request['prompt_snapshot'],config['size'])
            else:raw,mime,ext,width,height=await generate_image(store,run,config)
            with store.tx():
                current=store.get('run',run_id)
                if current['status']=='cancelled':return
                store.get('photo_project',run['photo_project_id'])
                id=uid();folder=store.path/'photo-assets';folder.mkdir(exist_ok=True);filename=id+'.'+ext;path=folder/filename
                path.write_bytes(raw)
                asset={'id':id,'photo_project_id':run['photo_project_id'],'prompt_revision':None if request.get('prompt_source')=='direct' else run['base_revision'],'prompt_source':request.get('prompt_source','project'),'source_project_revision':run['base_revision'],'prompt_text':request['prompt_snapshot']['compiled_prompt'],'mode':config['mode'],'label':'离线占位图，非 AI 照片' if config['mode']=='fixture' else '外部图片模型生成','size':config['size'],'model':config['model'],'settings_snapshot':{k:v for k,v in config.items() if k not in ('key_present','paid_calls_enabled')},'mime_type':mime,'width':width,'height':height,'created_at':now(),'filename':filename,'preview_url':f'/api/photo-assets/{id}/preview','download_url':f'/api/photo-assets/{id}/download'}
                store.put('photo_asset',asset);current.update(status='succeeded',proposal_id=None,result={'asset_id':id},elapsed_seconds=round(time.monotonic()-began,3),updated_at=now());current['steps'].append({'step':'save_photo_asset','status':'succeeded','at':now()});store.put('run',current)
    except asyncio.CancelledError:
        if path:path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if path:path.unlink(missing_ok=True)
        with store.tx():
            current=store.get('run',run_id,False)
            if current and current['status']!='cancelled':
                error=exc if isinstance(exc,DomainError) else DomainError('PHOTO_OUTPUT_INVALID','照片任务输出校验失败，未覆盖已保存产物',502)
                current.update(status='failed',error={'code':error.code,'message':error.message,'retryable':False},elapsed_seconds=round(time.monotonic()-began,3),updated_at=now());store.put('run',current)
