from backend.store import now,uid

def assemble(store,project,conversation_id=None,references=None):
    messages=[m for m in store.list('message',project['id']) if m.get('conversation_id')==conversation_id] if conversation_id else []
    excluded={x['id'] for x in store.list('excluded_source')}
    messages=[m for m in messages if m['id'] not in excluded]
    memories=[m for m in store.list('memory') if m['status']=='confirmed' and (m['scope']=='user' or m['project_id']==project['id'])]
    # Source-aware deterministic context budget. No model-generated summaries.
    recent=[];budget=12000
    for m in reversed(messages[-12:]):
        content=m['content'][:min(4000,budget)]
        if not content:break
        recent.append({'id':m['id'],'role':m['role'],'content':content});budget-=len(content)
    recent.reverse();ids={m['id'] for m in recent};older=[m for m in messages if m['id'] not in ids][-20:]
    parts=[];summary_ids=[];summary_budget=2400
    for m in older:
        part=(f"{m['role']}: {m['content'][:120]}")[:summary_budget]
        if not part:break
        parts.append(part);summary_ids.append(m['id']);summary_budget-=len(part)+1
    summary={'text':'\n'.join(parts),'source_message_ids':summary_ids,'method':'extractive'}
    selected=[];mem_budget=6000
    for m in memories:
        if len(m['content'])>mem_budget:continue
        selected.append({'id':m['id'],'content':m['content'],'version':m['version']});mem_budget-=len(m['content'])
    return {'id':uid(),'project_id':project['id'],'revision':project['current_revision'],'message_ids':[m['id'] for m in recent]+summary['source_message_ids'],'memory_ids':[m['id'] for m in selected],'reference_ids':references or [],'summary':summary,'messages':recent,'memories':selected,'valid':True,'created_at':now(),'budget_method':'characters','character_limit':20400}
