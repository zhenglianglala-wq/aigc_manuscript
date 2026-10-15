from test_photos import new_photo,done,confirmed,image_run


def test_local_diagnosis_comparison_does_not_change_project_or_call_models(client,monkeypatch):
    p=new_photo(client)
    async def forbidden(*args,**kwargs):raise AssertionError('Diagnostic must not call a model')
    monkeypatch.setattr('workflows.photo.complete',forbidden)
    monkeypatch.setattr('workflows.photo.generate_image',forbidden)
    body={'base_revision':p['current_revision'],'text':'高级感大片，俯拍又仰拍','baseline':'白色陶瓷杯放在画面左侧，右侧窗边暖光'}
    r=client.post(f"/api/photo-projects/{p['id']}/quality",json=body)
    assert r.status_code==200 and r.json()['baseline'] is not None
    assert any(i['code']=='POSSIBLE_CONFLICT' for i in r.json()['current']['issues'])
    assert client.get(f"/api/photo-projects/{p['id']}").json()==p
    assert client.get(f"/api/photo-projects/{p['id']}/runs").json()==[]
    body['base_revision']=999
    assert client.post(f"/api/photo-projects/{p['id']}/quality",json=body).status_code==409


def test_direction_candidates_preserve_subject_and_need_user_application(client):
    p=new_photo(client,'一只橘猫坐在木桌上')
    prompts=[]
    for direction in ('faithful','cinematic','commercial'):
        response=client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json={'base_revision':1,'idempotency_key':direction,'creative_direction':direction})
        run=done(client,response.json());assert run['status']=='succeeded',run
        proposals=client.get(f"/api/photo-projects/{p['id']}/proposals").json()
        candidate=next(x for x in proposals if x['id']==run['proposal_id'])
        assert candidate['creative_direction']==direction
        assert candidate['prompt']['creative_direction']==direction
        assert candidate['prompt']['subject']==p['brief']['description']
        assert candidate['prompt']['assumptions'] and not candidate['prompt']['confirmed']
        prompts.append(candidate['prompt']['compiled_prompt'])
    assert len(set(prompts))==3
    assert client.get(f"/api/photo-projects/{p['id']}").json()==p
    assert client.get(f"/api/photo-projects/{p['id']}/assets").json()==[]
    assert client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json={'base_revision':1,'idempotency_key':'bad','creative_direction':'random'}).status_code==422


def test_feedback_freezes_actual_asset_source_and_deletes_with_project(client):
    p=confirmed(client);r=done(client,image_run(client,p).json());assert r['status']=='succeeded'
    a=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    body={'adherence':4,'composition':3,'lighting':5,'notes':'下一次只调整主体位置'}
    response=client.post(f"/api/photo-assets/{a['id']}/feedback",json=body)
    assert response.status_code==201
    record=response.json();assert record['prompt_text']==a['prompt_text'] and record['model']==a['model']
    assert record['evaluation_type']=='user-reported' and record['asset_mode']=='fixture'
    assert client.get(f"/api/photo-projects/{p['id']}/feedback").json()==[record]
    assert client.post(f"/api/photo-assets/{a['id']}/feedback",json={**body,'adherence':True}).status_code==422
    client.delete(f"/api/photo-projects/{p['id']}")
    assert client.app.state.store.list('photo_feedback')==[]


def test_legacy_prompt_run_without_direction_remains_idempotent(client):
    p=new_photo(client)
    body={'base_revision':1,'idempotency_key':'legacy-direction'}
    run=done(client,client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json=body).json())
    store=client.app.state.store
    with store.tx():
        old=store.get('run',run['id']);old['request']['original_request'].pop('creative_direction');store.put('run',old)
    repeat=client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json=body)
    assert repeat.status_code==202 and repeat.json()['id']==run['id']
    assert client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json={**body,'creative_direction':'cinematic'}).status_code==409
