"""Photo workflow and separate authorization, real local DB with fixture/mocked HTTP."""
import base64
import asyncio
import json
import sqlite3
import struct
import time
import threading
import zlib
from uuid import uuid4
import httpx
import pytest

def new_photo(client, description="雨后窗边的白色陶瓷杯"):
    response = client.post("/api/photo-projects", json={"brief": {"description": description, "style": "写实摄影", "aspect_ratio": "1:1"}})
    assert response.status_code == 201, response.text
    return response.json()

def done(client, record):
    deadline = time.monotonic() + 5
    while record["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        assert time.monotonic() < deadline, record
        time.sleep(.01); record = client.get(f"/api/runs/{record['id']}").json()
    return record

def generated_prompt(client, photo):
    response = client.post(f"/api/photo-projects/{photo['id']}/prompt-runs", json={"base_revision": photo["current_revision"], "idempotency_key": str(uuid4())})
    assert response.status_code == 202, response.text
    record = done(client, response.json()); assert record["status"] == "succeeded", record
    response = client.post(f"/api/photo-proposals/{record['proposal_id']}/apply", json={"base_revision": photo["current_revision"]})
    assert response.status_code == 200, response.text
    return response.json()

def confirmed(client):
    p = generated_prompt(client, new_photo(client))
    response = client.post(f"/api/photo-projects/{p['id']}/prompt/confirm", json={"base_revision": p["current_revision"]})
    assert response.status_code == 200, response.text
    return response.json()

def image_run(client, p, **kwargs):
    return client.post(f"/api/photo-projects/{p['id']}/image-runs", json={"base_revision": p["current_revision"], "idempotency_key": str(uuid4()), **kwargs})

def png_bytes():
    # Independently known 1x1 RGB PNG, full CRC-checked chunk structure.
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB",1,1,8,2,0,0,0)) + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) + chunk(b"IEND", b"")

def invalid_pixels_png():
    # Correct PNG container/CRC but invalid pixel compression; preview cannot decode it.
    good=png_bytes();start=good.index(b'IDAT')-4;length=struct.unpack('>I',good[start:start+4])[0]
    payload=b'not-zlib';kind=b'IDAT'
    chunk=struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
    return good[:start]+chunk+good[start+12+length:]

def image_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("IMAGE_API_KEY", "simulated-placeholder-key")
    monkeypatch.setenv("PAID_IMAGE_CALLS_ENABLED", "true")

def image_config(client):
    response = client.patch("/api/photo-settings/image", json={"mode": "openai-compatible", "base_url": "https://invalid.example/v1", "model": "simulated-image", "response_format": "b64_json"})
    assert response.status_code == 200, response.text
    return response.json()

def approval(client, p, purpose="image"):
    response = client.post("/api/photo-approvals", json={"photo_project_id": p["id"], "purpose": purpose, "max_calls": 1, "accept_unknown_cost": True})
    assert response.status_code == 201, response.text
    return response.json()

def test_photo_prompt_does_not_call_image_provider_and_candidate_requires_apply(client, monkeypatch):
    calls = []
    image_transport(monkeypatch, lambda req: calls.append(req))
    image_config(client)
    p = new_photo(client)
    response = client.post(f"/api/photo-projects/{p['id']}/prompt-runs", json={"base_revision": 1, "idempotency_key": "prompt-only"})
    assert response.status_code == 202
    record = done(client, response.json()); assert record["status"] == "succeeded", record
    assert not calls and not client.get(f"/api/photo-projects/{p['id']}/assets").json()
    assert client.get(f"/api/photo-projects/{p['id']}").json()["prompt"] is None
    proposals = client.get(f"/api/photo-projects/{p['id']}/proposals").json()
    assert proposals[0]["status"] == "pending"

def test_photo_text_protocol_uses_prompt_approval_and_never_image_endpoint(client,monkeypatch):
    p=generated_prompt(client,new_photo(client));calls=[];original=httpx.AsyncClient
    def handler(req):
        calls.append(req)
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(p['prompt'])}}],"usage":{"prompt_tokens":20,"completion_tokens":30}})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setenv('LLM_API_KEY','mock-text-only-key');monkeypatch.setenv('PAID_CALLS_ENABLED','true')
    assert client.patch('/api/settings/model',json={'mode':'openai-compatible','base_url':'https://invalid.example/v1','model':'mock-text'}).status_code==200
    video=client.post('/api/projects',json={'brief':{'description':'视频','duration_seconds':5}}).json()
    wrong=client.post('/api/approvals',json={'project_id':video['id'],'max_calls':1,'accept_unknown_cost':True}).json()
    body={'base_revision':p['current_revision'],'idempotency_key':'text-only','approval_id':wrong['id']}
    response=client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json=body)
    assert response.status_code==403 and not calls
    ap=approval(client,p,purpose='prompt');body.update(approval_id=ap['id'],idempotency_key='correct-scope')
    response=client.post(f"/api/photo-projects/{p['id']}/prompt-runs",json=body);assert response.status_code==202,response.text
    record=done(client,response.json());assert record['status']=='succeeded',record
    assert len(calls)==1 and calls[0].url.path=='/v1/chat/completions'
    assert client.get(f"/api/photo-projects/{p['id']}/assets").json()==[]

def test_fixture_image_confirm_revision_history_download_and_edit_invalidation(client, tmp_path):
    p = generated_prompt(client, new_photo(client))
    assert image_run(client, p).status_code == 409
    p = client.post(f"/api/photo-projects/{p['id']}/prompt/confirm", json={"base_revision": p["current_revision"]}).json()
    response = image_run(client, p); assert response.status_code == 202, response.text
    record = done(client, response.json()); assert record["status"] == "succeeded", record
    asset = client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    assert asset["mode"] == "fixture" and "占位" in asset["label"]
    download = client.get(asset["download_url"]); assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert "svg" in download.headers["content-type"]
    file = tmp_path / "fixture.svg"; file.write_bytes(download.content)
    from xml.etree import ElementTree
    svg = ElementTree.parse(file).getroot(); assert svg.tag.endswith("svg")
    assert "非 AI" in download.text or "非AI" in download.text
    assert client.get(asset["preview_url"]).status_code == 200
    edited = client.patch(f"/api/photo-projects/{p['id']}/prompt", json={"base_revision": p["current_revision"], "changes": {"lighting": "低角度暖光"}})
    assert edited.status_code == 200, edited.text
    assert not edited.json()["prompt"]["confirmed"]
    assert image_run(client, edited.json()).status_code == 409
    after = client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    assert after["prompt_revision"] == p["current_revision"] and after["prompt_text"] == asset["prompt_text"]
    assert len(client.get(f"/api/photo-projects/{p['id']}/revisions").json()) >= 4

def test_image_requires_separate_key_switch_and_purpose_approval(client, monkeypatch):
    calls = []
    p = confirmed(client); image_config(client)
    image_transport(monkeypatch, lambda req: calls.append(req))
    monkeypatch.setenv("PAID_IMAGE_CALLS_ENABLED", "false")
    assert image_run(client, p).status_code == 403
    monkeypatch.setenv("PAID_IMAGE_CALLS_ENABLED", "true"); monkeypatch.setenv("IMAGE_API_KEY", "")
    assert image_run(client, p).status_code == 403
    monkeypatch.setenv("IMAGE_API_KEY", "simulated-placeholder-key")
    assert image_run(client, p).status_code == 403
    wrong = approval(client, p, purpose="prompt")
    assert image_run(client, p, approval_id=wrong["id"]).status_code == 403
    video = client.post("/api/projects", json={"brief": {"description": "视频", "duration_seconds": 5}}).json()
    video_approval = client.post("/api/approvals", json={"project_id": video["id"], "max_calls": 1, "accept_unknown_cost": True}).json()
    assert image_run(client, p, approval_id=video_approval["id"]).status_code == 403
    assert not calls

def test_base64_png_protocol_stores_validated_local_image_and_unknown_cost(client, monkeypatch, tmp_path):
    p = confirmed(client); calls = []; data = png_bytes()
    def handler(req): calls.append(req); return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(data).decode()}]})
    image_transport(monkeypatch, handler); image_config(client); ap = approval(client, p)
    response = image_run(client, p, approval_id=ap["id"]); assert response.status_code == 202, response.text
    record = done(client, response.json()); assert record["status"] == "succeeded", record
    assert len(calls) == 1 and calls[0].url.path == "/v1/images/generations"
    body = json.loads(calls[0].content); assert body["n"] == 1 and body["prompt"] == p["prompt"]["compiled_prompt"]
    assert body["response_format"] == "b64_json"
    asset = client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    assert (asset["width"],asset["height"],asset["mime_type"]) == (1,1,"image/png")
    download = client.get(asset["download_url"]); path = tmp_path / "real-protocol.png"; path.write_bytes(download.content)
    assert path.read_bytes() == data and client.get(asset["preview_url"]).content == data
    assert record["usage"]["cost"] is None and record["usage"]["cost_status"] == "unknown"
    assert client.get("/api/photo-settings/image").json()["key_present"] is True
    assert "simulated-placeholder-key" not in json.dumps(asset)

@pytest.mark.parametrize("payload", [{"data":[{"url":"https://invalid.example/image.png"}]},{"data":[{"b64_json":"%%%"}]},{"data":[{"b64_json":base64.b64encode(b"<svg onload='bad'>").decode()}]},{"data":[{"b64_json":base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()}]},{"data":[{"b64_json":base64.b64encode(invalid_pixels_png()).decode()}]}])
def test_unsafe_or_unsupported_image_output_is_not_saved_or_retried(client, monkeypatch, payload):
    p = confirmed(client); calls = []
    def handler(req): calls.append(req); return httpx.Response(200, json=payload)
    image_transport(monkeypatch,handler); image_config(client); ap = approval(client,p)
    response = image_run(client,p,approval_id=ap["id"]); assert response.status_code == 202
    record = done(client,response.json()); assert record["status"] == "failed", record
    assert len(calls) == 1 and client.get(f"/api/photo-projects/{p['id']}/assets").json() == []

def test_image_task_duplicate_cancel_and_project_delete(client):
    p = confirmed(client)
    body = {"base_revision":p["current_revision"],"idempotency_key":"one-image"}
    a = client.post(f"/api/photo-projects/{p['id']}/image-runs",json=body)
    b = client.post(f"/api/photo-projects/{p['id']}/image-runs",json=body)
    assert a.status_code == b.status_code == 202 and a.json()["id"] == b.json()["id"]
    assert client.post(f"/api/runs/{a.json()['id']}/cancel",json={}).status_code == 200
    time.sleep(.08)
    assert client.get(f"/api/runs/{a.json()['id']}").json()["status"] == "cancelled"
    assert client.get(f"/api/photo-projects/{p['id']}/assets").json() == []
    response = image_run(client,p); record = done(client,response.json()); assert record["status"] == "succeeded"
    asset = client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    other = new_photo(client,"其他照片项目")
    assert client.get(f"/api/photo-projects/{other['id']}/assets").json() == []
    assert client.delete(f"/api/photo-projects/{p['id']}").status_code == 200
    assert client.get(asset["download_url"]).status_code == 404
    assert client.get(f"/api/runs/{record['id']}").status_code == 404

@pytest.mark.parametrize("cancel", [False, True])
def test_inflight_image_uses_frozen_prompt_or_discards_cancelled_late_output(client, monkeypatch, cancel):
    p = confirmed(client); started, release = threading.Event(), threading.Event()
    async def handler(req):
        started.set()
        while not release.is_set(): await asyncio.sleep(.01)
        return httpx.Response(200,json={"data":[{"b64_json":base64.b64encode(png_bytes()).decode()}]})
    image_transport(monkeypatch,handler);image_config(client);ap=approval(client,p)
    response=image_run(client,p,approval_id=ap["id"]);assert response.status_code==202
    rid=response.json()["id"]
    assert started.wait(2),"Mock image request did not start"
    if cancel:
        assert client.post(f"/api/runs/{rid}/cancel",json={}).status_code==200
    else:
        edited=client.patch(f"/api/photo-projects/{p['id']}/prompt",json={"base_revision":p["current_revision"],"changes":{"subject":"修改后的黑色茶杯"}})
        assert edited.status_code==200 and not edited.json()["prompt"]["confirmed"]
    release.set();record=done(client,client.get(f"/api/runs/{rid}").json());time.sleep(.08)
    assets=client.get(f"/api/photo-projects/{p['id']}/assets").json()
    if cancel: assert record["status"]=="cancelled" and assets==[]
    else:
        assert record["status"]=="succeeded",record
        assert assets[0]["prompt_revision"]==p["current_revision"] and assets[0]["prompt_text"]==p["prompt"]["compiled_prompt"]

def test_image_settings_change_invalidates_image_approval(client, monkeypatch):
    p=confirmed(client);calls=[]
    image_transport(monkeypatch,lambda req:calls.append(req));image_config(client);ap=approval(client,p)
    assert client.patch("/api/photo-settings/image",json={"model":"different-model"}).status_code==200
    response=image_run(client,p,approval_id=ap["id"])
    assert response.status_code==403 and not calls

def test_fixture_svg_escapes_user_text(client):
    p=generated_prompt(client,new_photo(client,"</text><script>alert(1)</script>窗边花瓶"))
    p=client.post(f"/api/photo-projects/{p['id']}/prompt/confirm",json={"base_revision":p["current_revision"]}).json()
    response=image_run(client,p);record=done(client,response.json());assert record["status"]=="succeeded"
    asset=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    image=client.get(asset["preview_url"])
    from xml.etree import ElementTree
    tree=ElementTree.fromstring(image.content)
    assert not any(node.tag.split('}')[-1].lower()=="script" for node in tree.iter())
    assert b"<script" not in image.content

def test_photo_backup_contains_database_and_actual_asset_bytes(client,tmp_path):
    import io,zipfile
    p=confirmed(client);response=image_run(client,p);assert done(client,response.json())["status"]=="succeeded"
    asset=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    content=client.get(asset["download_url"]).content
    backup=client.post("/api/backups",json={});assert backup.status_code==201,backup.text
    download=client.get(f"/api/backups/{backup.json()['id']}/download");assert download.status_code==200
    archive=zipfile.ZipFile(io.BytesIO(download.content));names=archive.namelist()
    database=next(name for name in names if name.endswith("studio.sqlite3"))
    restored=tmp_path/'restore.sqlite3';restored.write_bytes(archive.read(database))
    with sqlite3.connect(restored) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        row=db.execute("SELECT value FROM entities WHERE kind='photo_asset' AND id=?",(asset['id'],)).fetchone()
        assert json.loads(row[0])["photo_project_id"]==p["id"]
    assert any(archive.read(name)==content for name in names if 'photo-assets/' in name and not name.endswith('/'))

def test_direct_prompt_image_needs_explicit_confirmation_but_no_llm_or_project_prompt(client,monkeypatch):
    p=new_photo(client);calls=[];direct="  A ceramic cup on a wooden table.\nSoft natural light.  "
    def handler(req):
        calls.append(req);return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png_bytes()).decode()}]})
    image_transport(monkeypatch,handler);image_config(client);ap=approval(client,p)
    body={'base_revision':1,'idempotency_key':'direct-unconfirmed','approval_id':ap['id'],'direct_prompt':direct}
    response=client.post(f"/api/photo-projects/{p['id']}/image-runs",json=body)
    assert response.status_code in {409,422} and not calls
    body.update(idempotency_key='direct-confirmed',confirm_direct_prompt=True)
    response=client.post(f"/api/photo-projects/{p['id']}/image-runs",json=body);assert response.status_code==202,response.text
    record=done(client,response.json());assert record['status']=='succeeded',record
    assert len(calls)==1 and calls[0].url.path=='/v1/images/generations'
    assert json.loads(calls[0].content)['prompt']==direct
    current=client.get(f"/api/photo-projects/{p['id']}").json();assert current['prompt'] is None and current['current_revision']==1
    asset=client.get(f"/api/photo-projects/{p['id']}/assets").json()[0]
    assert asset['prompt_revision'] is None and asset['prompt_source']=='direct' and asset['source_project_revision']==1 and asset['prompt_text']==direct
