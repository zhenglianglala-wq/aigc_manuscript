from tools.prompt_quality import photo_quality,video_quality
from tools.compiler import compile_document


def test_diagnosis_shows_evidence_not_a_quality_winner():
    brief={'description':'橘猫','must_include':['橘猫'],'must_avoid':['Logo']}
    weak=photo_quality(brief,text='高级感大片感，自然色彩，主体突出，俯拍同时仰拍，Logo')
    codes={i['code'] for i in weak['issues']}
    assert {'REQUIRED_MISSING','FORBIDDEN_PRESENT','POSSIBLE_CONFLICT','VAGUE_DESCRIPTION'}<=codes
    assert all(i['evidence'] and i['suggestion'] for i in weak['issues'])
    concrete=photo_quality(brief,text='橘猫位于画面左侧三分线，窗边柔光从右侧照入，暖棕与绿色背景')
    assert all(c['status']=='specified' for c in concrete['checks'])
    assert 'score' not in concrete and 'winner' not in concrete


def test_motion_profile_keeps_later_actions_and_camera_changes():
    beats=[{'start_second':i,'end_second':i+1,'scene_id':'room','character_ids':[],
            'action':a,'camera':camera,'visual':'橘猫在窗边','continuity':'同一场景'}
           for i,(a,camera) in enumerate([('橘猫抬头','固定镜头'),('橘猫转身','缓慢跟拍'),('橘猫跳下窗台','镜头下摇')])]
    doc=compile_document({'beats':beats,'story':{}},{'prompt_profile':'motion_first_image_to_video','must_avoid':[]})
    prompt=doc['shots'][0]['prompt']
    assert prompt.index('抬头')<prompt.index('转身')<prompt.index('跳下窗台')
    assert '镜头下摇' in prompt and '2–3秒' in prompt
    assert doc['shots'][0]['profile_version']=='1.1'


def test_video_overload_is_advisory_with_original_evidence():
    action='站起然后跑开同时挥手随后跳跃'
    r=video_quality({'beats':[{'start_second':0,'action':action,'camera':'静止机位快速环绕'}]})
    assert len(r['issues'])==2 and r['issues'][0]['evidence']==action
