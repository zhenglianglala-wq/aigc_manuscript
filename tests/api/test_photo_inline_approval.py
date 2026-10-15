from test_photos import new_photo


def test_confirmation_binding_change_creates_no_approval(client):
    p = new_photo(client)
    cfg = client.patch('/api/photo-settings/image', json={'estimated_price_per_image': .1}).json()
    fields = ('base_url', 'model', 'size', 'response_format', 'estimated_price_per_image')
    binding = {key: cfg[key] for key in fields}
    client.patch('/api/photo-settings/image', json={'model': 'changed-after-review'})
    body = {'photo_project_id': p['id'], 'purpose': 'image', 'max_calls': 1,
            'budget': .1, 'expected_model_binding': binding}
    response = client.post('/api/photo-approvals', json=body)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'APPROVAL_CONFIG_CHANGED'
    assert client.get('/api/photo-approvals').json() == []
    body['expected_model_binding']['model'] = 'changed-after-review'
    response = client.post('/api/photo-approvals', json=body)
    assert response.status_code == 201
    assert 'expected_model_binding' not in response.json()
