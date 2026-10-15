"""Rule profiles compile the SAME beat facts; no vendor execution claims."""
from copy import deepcopy
from tools.prompt_quality import video_quality
PROFILES={
 'generic_text_to_video':{'label':'通用文生视频','version':'1.0','verified':False,'source':'https://deepmind.google/models/veo/prompt-guide/'},
 'motion_first_image_to_video':{'label':'动作优先图生视频','version':'1.1','verified':False,'source':'https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide'}
}
def compile_document(document,brief):
    doc=deepcopy(document);beats=doc.get('beats',[]);story=doc.get('story') or {}
    characters={c['id']:c for c in story.get('characters',[])}
    scenes={s['id']:s for s in story.get('scenes',[])}
    profile=brief.get('prompt_profile','generic_text_to_video')
    for b in beats:
        if profile=='motion_first_image_to_video':b['prompt']=f"{b['action']}；{b['camera']}。动作平稳连续。"
        else:
            fixed='；'.join(characters[c]['description'] for c in b['character_ids'] if c in characters)
            b['prompt']=f"{brief['style']}，{brief['aspect_ratio']}。{fixed}。{scenes.get(b['scene_id'],{}).get('description','')}。{b['visual']}。{b['action']}；{b['camera']}。{b['continuity']}"
    shots=[]
    groups=[]
    for b in beats:
        key=(b['scene_id'],tuple(b['character_ids']))
        if not groups or len(groups[-1])>=5 or key!=(groups[-1][0]['scene_id'],tuple(groups[-1][0]['character_ids'])):groups.append([])
        groups[-1].append(b)
    for group in groups:
        start=group[0]['start_second']
        if not group:continue
        unique=lambda key:list(dict.fromkeys(b[key] for b in group if b[key]))
        if profile=='motion_first_image_to_video':prompt='；'.join(f"{b['start_second']-start}–{b['end_second']-start}秒：{b['action']}；{b['camera']}" for b in group)+'。运动衔接自然。'
        else:
            fixed='；'.join(characters[c]['description'] for c in group[0]['character_ids'] if c in characters)
            scene=scenes.get(group[0]['scene_id'],{}).get('description','')
            prompt=f"{brief['style']}，{brief['aspect_ratio']}。{fixed}。{scene}。"+'；'.join(unique('visual')+unique('action')+unique('camera'))
        shots.append({'id':f'shot-{start}','start_second':group[0]['start_second'],'end_second':group[-1]['end_second'],'prompt':prompt,'beat_seconds':[b['start_second'] for b in group],'continuity':'保持人物、道具与场景一致','profile':profile,'profile_version':PROFILES[profile]['version'],'capability_verified':False})
    doc['shots']=shots;doc['prompt_profile']=profile;doc['prompt_profile_metadata']=PROFILES[profile]
    doc['negative_constraints']=brief['must_avoid'];doc['negative_constraints_exported_as_prompt']=False
    return doc

def check_document(doc,brief,require_timeline=False):
    issues=[]
    def add(code,msg,second=None,severity='error'):issues.append({'code':code,'message':msg,'second':second,'severity':severity})
    story=doc.get('story');beats=doc.get('beats',[])
    if not story:add('STORY_MISSING','尚未生成故事')
    if require_timeline and not beats:add('TIMELINE_MISSING','尚未生成时间轴')
    if beats:
        if len(beats)!=brief['duration_seconds']:add('TIME_COVERAGE','逐秒条数与时长不符')
        chars={c['id'] for c in (story or {}).get('characters',[])};scenes={s['id'] for s in (story or {}).get('scenes',[])}
        for i,b in enumerate(beats):
            if b['start_second']!=i or b['end_second']!=i+1:add('TIME_COVERAGE','时间缺失或重叠',i)
            if any(c not in chars for c in b['character_ids']) or b['scene_id'] not in scenes:add('INVALID_REFERENCE','人物或场景引用无效',i)
        expected=compile_document(doc,brief)
        if expected.get('shots')!=doc.get('shots') or any(a['prompt']!=b['prompt'] for a,b in zip(expected['beats'],beats)):add('PROMPT_STALE','逐秒与分镜 Prompt 不一致')
    text=(story or {}).get('synopsis','')+' '.join(b['visual']+' '+b['action']+' '+b['dialogue'] for b in beats)
    rendered=text+' '.join(b.get(k,'') for b in beats for k in ('camera','sound','prompt','continuity'))+' '.join(x['description'] for x in (story or {}).get('characters',[])+(story or {}).get('scenes',[]))+' '.join(s['prompt'] for s in doc.get('shots',[]))
    for x in brief['must_include']:
        if x not in text:add('MUST_INCLUDE',f'缺少必须内容：{x}')
    for x in brief['must_avoid']:
        if x in rendered:add('MUST_AVOID',f'出现禁止内容：{x}')
    # Rules check explicit IDs and constraints; visual continuity still requires human review.
    return {'valid':not any(x['severity']=='error' for x in issues),'issues':issues,'human_review_required':['叙事节奏','视觉连续性','外部模型实际执行'],'scope':'mechanical','writing_review':video_quality(doc)}
