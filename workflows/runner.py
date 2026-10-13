import asyncio,time
from copy import deepcopy
from backend.store import now,uid,DomainError
from backend.schemas import Story,Beat
from agents import fixture
from tools.compiler import compile_document,check_document
from tools.model import complete

def validate_output(doc,brief):
    if doc.get('story'):doc['story']=Story.model_validate(doc['story']).model_dump()
    doc['beats']=[Beat.model_validate(b).model_dump() for b in doc.get('beats',[])]
    doc=compile_document(doc,brief)
    issues=check_document(doc,brief,bool(doc['beats']))
    structural=[x for x in issues['issues'] if x['code'] in ('TIME_COVERAGE','INVALID_REFERENCE','PROMPT_STALE','STORY_MISSING')]
    if structural:raise DomainError('MODEL_OUTPUT_INVALID',str(structural),422)
    return doc

def normalize_candidate(candidate,kind,doc,brief,req,mode):
    if not isinstance(candidate,dict):raise DomainError('MODEL_OUTPUT_INVALID','模型输出必须为 JSON 对象',422)
    candidate=deepcopy(candidate)
    if kind=='expand':
        candidate['beats']=[];candidate['shots']=[]
        if not isinstance(candidate.get('story'),dict):raise DomainError('MODEL_OUTPUT_INVALID','输出缺少 story 对象',422)
        candidate['story']['confirmed']=False
    if kind in ('timeline','rewrite') and candidate.get('story')!=doc.get('story'):raise DomainError('LOCKED_STORY_CHANGED','时间轴任务不得修改已确认故事',422)
    if kind=='timeline' and len(candidate.get('beats',[]))!=brief['duration_seconds']:raise DomainError('MODEL_OUTPUT_INVALID','时间轴必须完整覆盖目标时长',422)
    if kind=='rewrite':
        new=candidate.get('beats',[]);old=doc['beats'];start=req['start_second'];end=req['end_second']
        if len(new)!=len(old):raise DomainError('RANGE_CHANGED','重写不得改变总时长',422)
        for i in range(len(old)):
            if not start<=i<end and new[i]!=old[i]:raise DomainError('RANGE_CHANGED','修改超出授权范围',422)
            for key in req.get('locked_fields',[]):
                if old[i][key]!=new[i][key]:raise DomainError('LOCKED_FIELD_CHANGED','锁定字段被改变',422)
    candidate=validate_output(candidate,brief);candidate['generation_mode']=mode
    return candidate

async def execute(store,run_id,settings):
    began=time.monotonic()
    try:
        await asyncio.sleep(0.03)
        with store.tx():
            run=store.get('run',run_id)
            if run['status']=='cancelled':return
            run.update(status='running',updated_at=now());run['steps'].append({'step':'load_context','status':'succeeded','at':now()});store.put('run',run)
            p=store.project(run['project_id']);revision=store.get('revision',f"{p['id']}:{run['base_revision']}");doc=deepcopy(revision['document']);brief=revision['brief'];ctx=store.get('context',run['context_id'])
        req=run['request'];kind=run['kind'];mode=settings['mode'];reply=None
        if kind=='check':result=check_document(doc,brief,True);candidate=None
        else:
            if mode=='fixture':
                if kind=='expand':candidate=fixture.expand(brief,req.get('instruction',''))
                elif kind=='timeline':candidate=fixture.timeline(brief,doc)
                elif kind=='rewrite':candidate=fixture.rewrite(brief,doc,req['start_second'],req['end_second'],req.get('instruction',''),req.get('locked_fields',[]))
                else:candidate=None;reply=fixture.chat(req['content'],brief)
            else:
                payload={'task':kind,'brief':brief,'document':doc,'request':req,'context':ctx,'output_schema':'chat: {reply:string}; expand: {story:{title,synopsis,assumptions,characters:[{id,name,description}],scenes:[{id,name,description}],confirmed:false},beats:[]}; timeline/rewrite: {story:unchanged,beats:[{start_second,end_second,visual,action,camera,dialogue,sound,prompt,character_ids,scene_id,continuity}]}','required_seconds':brief['duration_seconds']}
                for repair in range(2):
                    try:
                        generated=await complete(store,run,settings,req.get('approval_id'),payload)
                        if kind=='chat':
                            candidate=None;reply=generated.get('reply') if isinstance(generated,dict) else None
                            if not isinstance(reply,str) or not reply.strip():raise DomainError('MODEL_OUTPUT_INVALID','聊天回复缺少 reply 字符串',502)
                        else:candidate=normalize_candidate(generated,kind,doc,brief,req,mode)
                        break
                    except (DomainError,ValueError,KeyError,TypeError) as exc:
                        retryable_output=not isinstance(exc,DomainError) or exc.code in ('MODEL_OUTPUT_INVALID','LOCKED_STORY_CHANGED','RANGE_CHANGED','LOCKED_FIELD_CHANGED')
                        if repair or not retryable_output:raise
                        payload['repair_instruction']='前一输出结构校验失败，请严格按原 Schema 与边界修复。只输出完整 JSON。'
                        payload['validation_error']=exc.message if isinstance(exc,DomainError) else 'Schema validation failed'
                        with store.tx():
                            r=store.get('run',run_id);r['steps'].append({'step':'repair_structure','status':'running','at':now(),'repair_number':1});store.put('run',r)
            with store.tx():
                current=store.get('run',run_id)
                if current['status']=='cancelled':return
                current['status']='validating';store.put('run',current)
            if candidate is not None:
                candidate=normalize_candidate(candidate,kind,doc,brief,req,mode)
                checks=check_document(candidate,brief,bool(candidate['beats']));result=checks
            else:result={'reply':reply}
        with store.tx():
            current=store.get('run',run_id)
            if current['status']=='cancelled':return
            if not store.get('context',run['context_id'])['valid']:raise DomainError('CONTEXT_INVALIDATED','上下文已失效',409)
            proposal_id=None
            if candidate is not None:
                proposal_id=uid();old=revision['document']
                changed=[b['start_second'] for i,b in enumerate(candidate['beats']) if i>=len(old.get('beats',[])) or b!=old['beats'][i]]
                store.put('proposal',{'id':proposal_id,'project_id':p['id'],'base_revision':run['base_revision'],'kind':kind,'status':'pending','document':candidate,'diff':{'story_changed':candidate.get('story')!=old.get('story'),'changed_seconds':changed},'issues':result['issues'],'created_at':now(),'run_id':run_id})
            if run.get('conversation_id'):
                content=reply or ('已生成修改候选，请查看差异后应用。' if proposal_id else '检查完成。')
                store.put('message',{'id':uid(),'project_id':p['id'],'conversation_id':run['conversation_id'],'role':'assistant','content':content,'references':[],'created_at':now(),'run_id':run_id})
            for step in current['steps']:
                if step['step']=='repair_structure' and step['status']=='running':step['status']='succeeded'
            current.update(status='succeeded',proposal_id=proposal_id,result=result,elapsed_seconds=round(time.monotonic()-began,3),updated_at=now());current['steps'].append({'step':'validate_and_save','status':'succeeded','at':now()});store.put('run',current)
    except asyncio.CancelledError:raise
    except Exception as exc:
        with store.tx():
            run=store.get('run',run_id,False)
            if run and run['status']!='cancelled':
                error=exc if isinstance(exc,DomainError) else DomainError('OUTPUT_VALIDATION_FAILED','输出校验失败，未覆盖正式版本',422)
                for step in run['steps']:
                    if step['step']=='repair_structure' and step['status']=='running':step['status']='failed'
                run.update(status='failed',error={'code':error.code,'message':error.message,'retryable':error.retryable},elapsed_seconds=round(time.monotonic()-began,3),updated_at=now());store.put('run',run)
