from backend.store import now

def invalidate(store,message_ids=(),memory_ids=()):
    """Invalidate provenance descendants, not only the first cached snapshot.

    Assistant messages derived from deleted/edited preferences are excluded too:
    otherwise an echoed preference could re-enter through later chat history.
    Audit IDs remain, while affected context text is redacted.
    """
    mids=set(message_ids);memids=set(memory_ids);snapshots=store.list('context')
    runs=store.list('run');messages=store.list('message');affected=set()
    grew=True
    while grew:
        grew=False
        for snap in snapshots:
            if mids.intersection(snap['message_ids']) or memids.intersection(snap['memory_ids']):
                if snap['id'] not in affected:affected.add(snap['id']);grew=True
        run_ids={r['id'] for r in runs if r.get('context_id') in affected}
        for m in messages:
            if m['role']=='assistant' and m.get('run_id') in run_ids and m['id'] not in mids:
                mids.add(m['id']);grew=True
                store.put('excluded_source',{'id':m['id'],'reason':'derived_context_invalidated'})
    for snap in snapshots:
        if snap['id'] in affected:
            snap.update(valid=False,messages=[],memories=[],summary={'text':'','source_message_ids':[],'method':'invalidated'},invalidated_at=now())
            store.put('context',snap)
    for run in runs:
        if run.get('context_id') in affected and run['status'] in ('queued','running','validating'):
            run.update(status='cancelled',error={'code':'CONTEXT_INVALIDATED','message':'上下文来源已删除或修改','retryable':False},updated_at=now());store.put('run',run)
    for mem in store.list('memory'):
        if mids.intersection(mem['source_message_ids']) and mem['status']!='deleted':
            mem.update(status='inactive',updated_at=now());store.put('memory',mem)
    return mids

def erase_source_outputs(store,message_ids):
    """Erase raw message-derived copies while preserving operational audit IDs.

    Applied project revisions are explicit, independent user artifacts and are
    retained. Pending/applied proposal copies and chat run payloads are redacted.
    """
    mids=set(message_ids)
    contexts={c['id'] for c in store.list('context') if mids.intersection(c['message_ids'])}
    runs={r['id'] for r in store.list('run') if r.get('context_id') in contexts}
    runs.update(m['run_id'] for m in store.list('message') if m['id'] in mids and m.get('run_id'))
    for r in store.list('run'):
        if r['id'] not in runs:continue
        req=r.get('request',{})
        for field in ('content','instruction','message_body'):
            if field in req:req[field]=None if field=='message_body' else ''
        req['source_redacted']=True
        r.update(request=req,result={'redacted':True},source_redacted=True,updated_at=now())
        # Upstream validation errors could contain pieces of invalid generated text.
        if r.get('error'):r['error']['message']='来源消息已删除，相关输出已移除'
        store.put('run',r)
    for c in store.list('proposal'):
        if c.get('run_id') not in runs:continue
        c.update(status='dismissed',document={'story':None,'beats':[],'shots':[]},diff={'redacted':True},issues=[],source_redacted=True,invalidation_reason='source_deleted')
        store.put('proposal',c)
    for m in store.list('message'):
        if m['id'] in mids and m['role']=='assistant':
            m.update(content='[来源消息已删除，衍生回复已移除]',references=[],source_redacted=True);store.put('message',m)
    for m in store.list('memory'):
        if mids.intersection(m['source_message_ids']) and m['status']!='deleted':
            m.update(content='',status='deleted',version=m['version']+1,updated_at=now(),invalidation_reason='source_deleted');store.put('memory',m)
