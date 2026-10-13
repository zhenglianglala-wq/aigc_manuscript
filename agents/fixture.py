"""Deterministic brief-driven sample generator, NOT AI inference."""
from copy import deepcopy
import re
from tools.compiler import compile_document

def creative_topic(text,forbidden):
    # Separate explicit prohibition clauses from visual content. This is a literal
    # fixture rule, not semantic understanding or a quality claim.
    clauses=re.split(r'[，,。；;！!？?\n]+',text)
    eligible=[c.strip() for c in clauses if c.strip() and not re.search(r'(禁止|避免|不要|不得|不能出现|不出现|不包含)',c) and not any(x in c for x in forbidden)]
    return '，'.join(eligible) or '一个未指定主题的角色完成一次选择'

def expand(brief,instruction=''):
    text=creative_topic(brief['description'],brief['must_avoid']);instruction=creative_topic(instruction,brief['must_avoid']) if instruction else '';must='、'.join(brief['must_include'])
    return {'story':{'title':text[:24], 'synopsis':f'开场：{text}。发展：主人公围绕这个目标行动，遇到一次意外。转折：主人公重新观察线索，调整选择。结尾：以具体行动回应开场。'+(f'必须呈现：{must}。' if must else '')+(f'创作要求：{instruction}' if instruction else ''),'assumptions':['离线可重复样例；主人公、场景和情节连接为创作补充，需用户修改确认','仅按字面分隔禁止子句；缺少创作主题时使用未指定主题样例，不代表语义理解'],'characters':[{'id':'character-1','name':'主人公','description':f'围绕“{text[:60]}”展开行动的主人公；服装和外观在镜头间保持一致'}],'scenes':[{'id':'scene-1','name':'主场景','description':f'{text[:120]}的主要环境，光线与空间方位保持一致'}],'confirmed':False},'beats':[],'shots':[],'generation_mode':'fixture'}
def timeline(brief,document,instruction=''):
    doc=deepcopy(document);n=brief['duration_seconds'];topic=creative_topic(brief['description'],brief['must_avoid'])[:120]
    phases=[('开场','观察环境，确认目标','固定广角，缓慢推进'),('发展','向目标靠近，留意线索','平稳中景跟随'),('转折','停下并重新观察，作出选择','缓慢推进至近景'),('收束','完成一个明确动作，留下余韵','镜头缓慢拉远')]
    doc['beats']=[]
    for i in range(n):
        phase,action,camera=phases[min(3,i*4//n)]
        visual=f'{phase}：{topic}。主人公处于连续行动中，第 {i+1} 秒。'
        if i==0 and brief['must_include']:visual+='画面中呈现：'+'、'.join(brief['must_include'])+'。'
        doc['beats'].append({'start_second':i,'end_second':i+1,'visual':visual,'action':action,'camera':camera,'dialogue':'','sound':'连续环境声','prompt':'','character_ids':[doc['story']['characters'][0]['id']],'scene_id':doc['story']['scenes'][0]['id'],'continuity':'承接上一秒动作与空间方向'})
    doc['generation_mode']='fixture'
    return compile_document(doc,brief)
def rewrite(brief,document,start,end,instruction,locked):
    doc=deepcopy(document);instruction=creative_topic(instruction,brief['must_avoid'])
    for b in doc['beats'][start:end]:
        if 'visual' not in locked:b['visual']=f"{b['visual']} 修改要求：{instruction}"
        elif 'action' not in locked:b['action']=f"{b['action']}；{instruction}"
    return compile_document(doc,brief)
def chat(content,brief):
    return f'【离线示例回复】已记录你的想法：“{content}”。当前项目主题为“{brief["description"][:80]}”。可以先明确角色目标，再调整转折和结尾；如需改剧本，请选择“生成修改候选”，应用前不会改变正式版本。'
