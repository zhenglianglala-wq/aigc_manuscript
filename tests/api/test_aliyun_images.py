"""Aliyun signed URL protocol: fully mocked HTTP and DNS, no live connections."""
import json
import socket
import httpx
import pytest
from test_photos import approval, confirmed, done, image_run, image_transport, invalid_pixels_png, png_bytes

API = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
OSS = 'dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com'
URL = f'https://{OSS}/generated/test.png?Signature=MOCK_SIGNATURE'
PUBLIC_IP = '93.184.216.34'

def aliyun_config(client, base_url=API):
    response=client.patch('/api/photo-settings/image',json={'mode':'openai-compatible','base_url':base_url,'model':'simulated-aliyun','response_format':'aliyun_url'})
    assert response.status_code==200,response.text
    return response.json()

def mock_dns(monkeypatch,addresses=(PUBLIC_IP,)):
    def resolve(host,port,*args,**kwargs):
        return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',(ip,443)) for ip in addresses]
    monkeypatch.setattr(socket,'getaddrinfo',resolve)

def generated(client,p,ap):
    response=image_run(client,p,approval_id=ap['id']);assert response.status_code==202,response.text
    return done(client,response.json())

@pytest.mark.parametrize('host',[OSS,'dashscope-result-wlcb-acdr-1.oss-cn-wulanchabu.aliyuncs.com','dashscope-result-wlcb-acdr-1.oss-accelerate.aliyuncs.com'])
def test_official_oss_download_has_no_key_and_pins_validated_public_ip(client,monkeypatch,host):
    p=confirmed(client);calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='POST':return httpx.Response(200,json={'data':[{'url':f'https://{host}/generated/test.png?Signature=MOCK_SIGNATURE'}]})
        return httpx.Response(200,content=png_bytes(),headers={'Content-Type':'image/png'})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch);aliyun_config(client);ap=approval(client,p)
    record=generated(client,p,ap);assert record['status']=='succeeded',record
    assert len(calls)==2 and [r.method for r in calls]==['POST','GET']
    assert calls[0].url.path=='/compatible-mode/v1/images/generations'
    body=json.loads(calls[0].content);assert body['n']==1 and body['prompt']==p['prompt']['compiled_prompt'] and body['prompt_extend'] is False
    get=calls[1];assert get.url.host==PUBLIC_IP and get.headers['host']==host
    assert 'authorization' not in get.headers and 'proxy-authorization' not in get.headers
    assert 'simulated-placeholder-key' not in str(get.url) and 'simulated-placeholder-key' not in str(get.headers)
    assert get.url.path=='/generated/test.png' and get.url.params['Signature']=='MOCK_SIGNATURE'
    sni=get.extensions.get('sni_hostname');assert sni in {host,host.encode()},'TLS identity must remain official OSS hostname'
    asset=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    assert client.get(asset['download_url']).content==png_bytes()

@pytest.mark.parametrize('unsafe',[
    'https://example.com/test.png','https://127.0.0.1/test.png','https://localhost/test.png',
    'http://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/test.png',
    'https://user:password@dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/test.png',
    'https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com.evil.example/test.png',
    'https://random-bucket.oss-cn-shenzhen.aliyuncs.com/test.png',
    'https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com:8443/test.png',
    'file:///private/tmp/test.png'
])
def test_untrusted_download_url_is_rejected_before_get(client,monkeypatch,unsafe):
    p=confirmed(client);calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,json={'data':[{'url':unsafe}]})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch);aliyun_config(client);ap=approval(client,p)
    record=generated(client,p,ap);assert record['status']=='failed',record
    assert len(calls)==1 and calls[0].method=='POST'
    assert client.get(f"/api/photo-projects/{p['id']}/assets").json()==[]

@pytest.mark.parametrize('addresses',[('127.0.0.1',),('10.0.0.1',),(PUBLIC_IP,'169.254.169.254')])
def test_official_name_resolving_to_any_private_address_is_rejected(client,monkeypatch,addresses):
    p=confirmed(client);calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,json={'data':[{'url':URL}]})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch,addresses);aliyun_config(client);ap=approval(client,p)
    assert generated(client,p,ap)['status']=='failed'
    assert len(calls)==1

@pytest.mark.parametrize('kind',['redirect','bad_pixels','declared_oversize','stream_oversize'])
def test_download_redirect_invalid_pixels_and_size_fail_without_asset_or_retry(client,monkeypatch,kind):
    from tools.photo_model import MAX_IMAGE_BYTES
    p=confirmed(client);calls=[]
    class Oversize(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(MAX_IMAGE_BYTES//(1024*1024)+1):yield b'x'*(1024*1024)
    def handler(req):
        calls.append(req)
        if req.method=='POST':return httpx.Response(200,json={'data':[{'url':URL}]})
        if kind=='redirect':return httpx.Response(302,headers={'Location':'https://127.0.0.1/private.png'})
        if kind=='bad_pixels':return httpx.Response(200,content=invalid_pixels_png(),headers={'Content-Type':'image/png'})
        if kind=='declared_oversize':return httpx.Response(200,content=png_bytes(),headers={'Content-Type':'image/png','Content-Length':str(MAX_IMAGE_BYTES+1)})
        return httpx.Response(200,stream=Oversize(),headers={'Content-Type':'image/png'})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch);aliyun_config(client);ap=approval(client,p)
    record=generated(client,p,ap);assert record['status']=='failed',record
    if kind.endswith('oversize'):assert record['error']['code']=='IMAGE_TOO_LARGE',record
    if kind=='bad_pixels':assert record['error']['code']=='IMAGE_INVALID',record
    assert len(calls)==2 and client.get(f"/api/photo-projects/{p['id']}/assets").json()==[]

def test_generic_protocol_still_refuses_official_url_and_format_change_invalidates_approval(client,monkeypatch):
    p=confirmed(client);calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,json={'data':[{'url':URL}]})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch)
    response=client.patch('/api/photo-settings/image',json={'mode':'openai-compatible','base_url':API,'model':'simulated-aliyun','response_format':'auto'});assert response.status_code==200
    ap=approval(client,p);assert generated(client,p,ap)['status']=='failed';assert len(calls)==1
    new_approval=approval(client,p)
    assert client.patch('/api/photo-settings/image',json={'response_format':'aliyun_url'}).status_code==200
    rejected=image_run(client,p,approval_id=new_approval['id']);assert rejected.status_code==403,rejected.text
    assert len(calls)==1

@pytest.mark.parametrize('base_url',['https://example.com/compatible-mode/v1','http://dashscope.aliyuncs.com/compatible-mode/v1','https://dashscope.aliyuncs.com/wrong','https://user:password@dashscope.aliyuncs.com/compatible-mode/v1'])
def test_aliyun_protocol_cannot_be_pointed_to_arbitrary_provider(client,base_url):
    response=client.patch('/api/photo-settings/image',json={'mode':'openai-compatible','base_url':base_url,'model':'test','response_format':'aliyun_url'})
    assert response.status_code==422,response.text

def test_private_receipt_recovers_only_download_without_generation_approval_or_snapshot_changes(client,monkeypatch):
    import stat
    p=confirmed(client);calls=[];get_count=0
    def handler(req):
        nonlocal get_count
        calls.append(req)
        if req.method=='POST':return httpx.Response(200,json={'data':[{'url':URL}]})
        get_count+=1
        if get_count==1:return httpx.Response(503,headers={'Content-Type':'image/png'})
        return httpx.Response(200,content=png_bytes(),headers={'Content-Type':'image/png'})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch);config=aliyun_config(client);ap=approval(client,p)
    original=generated(client,p,ap);assert original['status']=='failed'
    rid=original['id'];receipt=client.app.state.store.path/'photo-receipts'/f'{rid}.json'
    assert receipt.is_file(), 'Generation receipt must survive a later download failure'
    raw=receipt.read_text();assert URL in raw and 'simulated-placeholder-key' not in raw
    assert stat.S_IMODE(receipt.stat().st_mode)==0o600
    assert 'MOCK_SIGNATURE' not in json.dumps(client.get(f'/api/runs/{rid}').json())
    assert 'MOCK_SIGNATURE' not in json.dumps(client.get(f"/api/photo-projects/{p['id']}/runs").json())
    backup=client.post('/api/backups',json={}).json()
    assert b'MOCK_SIGNATURE' not in client.get(f"/api/backups/{backup['id']}/download").content
    # Subsequent edits/configuration and revoked credentials cannot alter the paid generation snapshot.
    edited=client.patch(f"/api/photo-projects/{p['id']}/prompt",json={'base_revision':p['current_revision'],'changes':{'subject':'新版本主体，不应进入旧图片'}})
    assert edited.status_code==200
    assert client.patch('/api/photo-settings/image',json={'model':'new-model','size':'1536x1024'}).status_code==200
    assert client.delete(f"/api/photo-approvals/{ap['id']}").status_code==200
    monkeypatch.setenv('IMAGE_API_KEY','');monkeypatch.setenv('PAID_IMAGE_CALLS_ENABLED','false')
    body={'idempotency_key':'download-recovery-only'}
    response=client.post(f"/api/photo-projects/{p['id']}/runs/{rid}/recover-image",json=body)
    assert response.status_code==202,response.text
    concurrent=client.post(f"/api/photo-projects/{p['id']}/runs/{rid}/recover-image",json={'idempotency_key':'another-download-click'})
    assert concurrent.status_code==202 and concurrent.json()['id']==response.json()['id']
    recovery=done(client,response.json());assert recovery['status']=='succeeded',recovery
    assert recovery['kind']=='photo_image_recovery' and recovery['recovery_of']==rid
    assert recovery['usage']['cost']==0 and recovery['usage']['cost_status']=='recovery_no_generation'
    assert sum(req.method=='POST' for req in calls)==1 and sum(req.method=='GET' for req in calls)==2
    assert all('authorization' not in req.headers for req in calls if req.method=='GET')
    approvals=client.get(f"/api/photo-approvals?photo_project_id={p['id']}").json();assert len(approvals)==1 and approvals[0]['calls_used']==1
    asset=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    assert asset['prompt_revision']==p['current_revision'] and asset['prompt_text']==p['prompt']['compiled_prompt']
    assert asset['model']==config['model'] and asset['size']==config['size']
    assert client.get(asset['download_url']).content==png_bytes()
    repeated=client.post(f"/api/photo-projects/{p['id']}/runs/{rid}/recover-image",json=body)
    assert repeated.status_code==202 and repeated.json()['id']==recovery['id']
    assert len(calls)==3 and len(client.get(f"/api/photo-projects/{p['id']}/assets").json())==1
    assert 'MOCK_SIGNATURE' not in json.dumps(client.get(f"/api/runs/{recovery['id']}").json())

def test_download_recovery_requires_original_receipt_and_matching_project(client):
    from test_photos import new_photo
    p=confirmed(client);other=new_photo(client)
    fixture=generated(client,p,{'id':None})
    assert fixture['status']=='succeeded'
    body={'idempotency_key':'no-receipt'}
    response=client.post(f"/api/photo-projects/{p['id']}/runs/{fixture['id']}/recover-image",json=body)
    assert response.status_code in {404,409} and 'error' in response.json(),response.text
    foreign=client.post(f"/api/photo-projects/{other['id']}/runs/{fixture['id']}/recover-image",json={'idempotency_key':'wrong-project'})
    assert foreign.status_code in {404,422},foreign.text

def test_cancelled_generation_with_receipt_cannot_resume_download(client,monkeypatch):
    import asyncio,threading,time
    p=confirmed(client);calls=[];started=threading.Event();release=threading.Event()
    async def handler(req):
        calls.append(req)
        if req.method=='POST':return httpx.Response(200,json={'data':[{'url':URL}]})
        started.set()
        while not release.is_set():await asyncio.sleep(.01)
        return httpx.Response(200,content=png_bytes(),headers={'Content-Type':'image/png'})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch);aliyun_config(client);ap=approval(client,p)
    response=image_run(client,p,approval_id=ap['id']);assert response.status_code==202
    rid=response.json()['id'];assert started.wait(2)
    assert client.post(f'/api/runs/{rid}/cancel',json={}).status_code==200
    release.set();time.sleep(.08)
    receipt=client.app.state.store.path/'photo-receipts'/f'{rid}.json';assert receipt.is_file()
    refused=client.post(f"/api/photo-projects/{p['id']}/runs/{rid}/recover-image",json={'idempotency_key':'cancelled-recovery'})
    assert refused.status_code==409 and refused.json()['error']['code']=='RECOVERY_CANCELLED'
    assert len(calls)==2 and client.get(f"/api/photo-projects/{p['id']}/assets").json()==[]

def test_deleted_project_erases_receipt_and_cannot_recover(client,monkeypatch):
    p=confirmed(client);calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='POST':return httpx.Response(200,json={'data':[{'url':URL}]})
        return httpx.Response(503,headers={'Content-Type':'image/png'})
    image_transport(monkeypatch,handler);mock_dns(monkeypatch);aliyun_config(client);ap=approval(client,p)
    failed=generated(client,p,ap);assert failed['status']=='failed'
    receipt=client.app.state.store.path/'photo-receipts'/f"{failed['id']}.json";assert receipt.is_file()
    assert client.delete(f"/api/photo-projects/{p['id']}").status_code==200
    assert not receipt.exists()
    refused=client.post(f"/api/photo-projects/{p['id']}/runs/{failed['id']}/recover-image",json={'idempotency_key':'deleted-project'})
    assert refused.status_code==404 and len(calls)==2
