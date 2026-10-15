"""Evidence-based writing checks, not an aesthetic score or model benchmark."""
import re

VERSION = '1.0'
DIRECTIONS = {
    'faithful': {'label': '忠实还原', 'instruction': '优先还原用户的主体、数量、身份、动作、地点与已有光线。缺失信息采用最少补充，不新增人物、品牌、文字或情节。'},
    'cinematic': {'label': '电影叙事', 'instruction': '在主体事实不变的前提下，用一个明确的视觉焦点、空间层次、具体主光方向和统一色调表达情绪；不要把电影感当作形容词堆砌，不强加夜景、雨景或新情节。'},
    'commercial': {'label': '商业画面', 'instruction': '保持主体及用途不变，明确主体占比、视觉层级、背景干扰控制、真实材质与轮廓光；用户未要求时不要擅加Logo、文案、售价或广告道具。'},
}
VAGUE = ('高级感', '大片感', '高质量', '极致细节', '与主题相关', '由主题呈现', '空间位置清晰', '主体突出', '自然色彩')
CUES = {
    'subject': ('主体', r'人物|女孩|男孩|女人|男人|猫|狗|杯|车|花|山|湖|建筑|产品|瓶|手表|咖啡|portrait|person|cat|dog|cup|car|product'),
    'composition': ('构图', r'左|右|中央|中心|前景|背景|三分|对称|留白|近景|中景|全景|特写|占画面|foreground|background|close.up|center'),
    'lighting': ('光线', r'侧光|逆光|顶光|窗|柔光|硬光|清晨|午后|傍晚|阴天|光从|光源|阴影|backlit|light from|side.light|window'),
    'color': ('色彩', r'暖|冷|绿色|橘|蓝|红|棕|灰|黑白|低饱和|高饱和|色调|warm|cool|green|orange|blue|palette'),
}

def photo_quality(brief, prompt=None, text=None):
    text = text if text is not None else (prompt or {}).get('compiled_prompt', brief['description'])
    issues = []
    def add(code, message, evidence, suggestion, severity='suggestion'):
        issues.append({'code': code, 'severity': severity, 'message': message, 'evidence': evidence[:160], 'suggestion': suggestion})
    for term in brief.get('must_include', []):
        if term not in text: add('REQUIRED_MISSING', '必须内容未出现在正向Prompt', term, '用可见主体或动作明确写入，或修改原要求。', 'warning')
    for term in brief.get('must_avoid', []):
        if term in text: add('FORBIDDEN_PRESENT', '正向Prompt包含禁止内容', term, '先解决正向描述与禁止要求的冲突。', 'warning')
    checks = []
    for field, (label, pattern) in CUES.items():
        value = (prompt or {}).get(field, '') if text == (prompt or {}).get('compiled_prompt') else ''
        evidence = value or next((m.group(0) for m in re.finditer(pattern, text, re.I)), '')
        specific = bool(evidence) and not any(v in evidence for v in VAGUE)
        question = {'subject': '主体是谁，外观与动作是什么？', 'composition': '主体位于哪里，占比多少，前后景如何安排？', 'lighting': '主光从哪里来，是柔光还是硬光？', 'color': '主色与辅色是什么，是否协调？'}[field]
        checks.append({'field': field, 'label': label, 'status': 'specified' if specific else 'needs_detail', 'evidence': evidence[:160], 'question': question})
    vague=[term for term in VAGUE if term in text]
    if vague: add('VAGUE_DESCRIPTION', '抽象修饰不能直接决定画面', '、'.join(vague), '替换为具体的位置、光源、材质或可见动作；没有必要的信息可删去。')
    for a, b in (('俯拍', '仰拍'), ('黑白', '高饱和'), ('浅景深', '所有物体清晰')):
        if a in text and b in text: add('POSSIBLE_CONFLICT', '可能存在冲突，请结合意图判断', a+' / '+b, '为这张照片选择一致的镜头或色彩方案；若是刻意效果，请保留并人工核查。', 'warning')
    if len(text) > 1800: add('PROMPT_DENSITY', '描述较长，可能削弱重点', str(len(text))+'字符', '先保留主体、构图与光线，再按一次一个变量的方式添加细节。')
    return {'rule_version': VERSION, 'character_count': len(text), 'checks': checks, 'issues': issues,
            'scope': '本地启发式写作检查；不判断图像美感，不代表模型评分或生成成功率。'}


def video_quality(document):
    issues=[]
    beats=document.get('beats',[])
    for beat in beats:
        action=beat.get('action','');camera=beat.get('camera','')
        if len(re.findall('然后|接着|同时|随后|并且',action))>=2:
            issues.append({'second':beat['start_second'],'message':'一秒内可能安排了过多动作','evidence':action[:160],'suggestion':'保留一个主要动作，将其余动作分配到相邻秒或分镜。'})
        if '静止' in camera and ('环绕' in camera or '旋转' in camera):
            issues.append({'second':beat['start_second'],'message':'镜头描述可能冲突','evidence':camera[:160],'suggestion':'确认是固定机位还是运动镜头。'})
    if len(beats)>=4 and len({b.get('action','') for b in beats})==1:
        issues.append({'second':None,'message':'多秒动作完全重复','evidence':beats[0].get('action','')[:160],'suggestion':'确认是否刻意停留；需要推进时，写出动作起点、变化与结束。'})
    return {'rule_version':VERSION,'issues':issues,'scope':'写作建议，不改变结构检查结果；叙事与视觉效果仍需人工评估。'}
