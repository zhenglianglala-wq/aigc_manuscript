import csv
import io
import json
import sqlite3
import time
from uuid import uuid4

def project(client, description="雨夜邮差归来", duration=5):
    res = client.post("/api/projects", json={"brief": {"description": description, "duration_seconds": duration}})
    assert res.status_code == 201, res.text
    return res.json()

def terminal(client, run):
    deadline = time.monotonic() + 5
    while run["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        assert time.monotonic() < deadline, run
        time.sleep(.01)
        run = client.get(f"/api/runs/{run['id']}").json()
    return run

def run(client, p, kind="expand", **fields):
    body = {"kind": kind, "base_revision": p["current_revision"], "idempotency_key": str(uuid4()), **fields}
    res = client.post(f"/api/projects/{p['id']}/runs", json=body)
    assert res.status_code == 202, res.text
    return terminal(client, res.json())

def apply(client, p, r):
    assert r["status"] == "succeeded", r
    res = client.post(f"/api/proposals/{r['proposal_id']}/apply", json={"base_revision": p["current_revision"]})
    assert res.status_code == 200, res.text
    return res.json()

def timeline(client):
    p = project(client); p = apply(client, p, run(client, p))
    res = client.post(f"/api/projects/{p['id']}/story/confirm", json={"base_revision": p["current_revision"]})
    assert res.status_code == 200, res.text
    p = res.json()
    return apply(client, p, run(client, p, "timeline"))

def conversation(client, p):
    res = client.post(f"/api/projects/{p['id']}/conversations", json={"title": "测试讨论"})
    assert res.status_code == 201, res.text
    return res.json()

def chat(client, c, content="保留蓝色外套", **kwargs):
    res = client.post(f"/api/conversations/{c['id']}/messages", json={"content": content, "idempotency_key": str(uuid4()), **kwargs})
    assert res.status_code == 202, res.text
    r = terminal(client, res.json()); assert r["status"] == "succeeded", r
    return r

def test_input_boundary(client):
    for description, duration in [(" ", 5), ("a" * 6001, 5), ("正常", 4), ("正常", 121)]:
        res = client.post("/api/projects", json={"brief": {"description": description, "duration_seconds": duration}})
        assert res.status_code == 422
    assert client.get("/api/projects").json() == []

def test_candidate_version_export_and_restore(client):
    from evals.runner import validate_document
    p = project(client)
    r = run(client, p)
    unchanged = client.get(f"/api/projects/{p['id']}").json()
    assert unchanged["document"]["story"] is None and unchanged["current_revision"] == 1
    p = apply(client, p, r)
    stale = client.post(f"/api/proposals/{r['proposal_id']}/apply", json={"base_revision": 1})
    assert stale.status_code == 409
    p = client.post(f"/api/projects/{p['id']}/story/confirm", json={"base_revision": p["current_revision"]}).json()
    p = apply(client, p, run(client, p, "timeline"))
    assert not validate_document(p["document"], 5)
    old_version = p["current_revision"]
    edited = client.patch(f"/api/projects/{p['id']}/beats/2", json={"base_revision": old_version, "changes": {"visual": "雨后的红色信箱"}})
    assert edited.status_code == 200, edited.text
    p = edited.json()
    assert p["document"]["beats"][2]["visual"] == "雨后的红色信箱"
    assert client.get(f"/api/projects/{p['id']}").json() == p
    assert client.patch(f"/api/projects/{p['id']}/beats/2", json={"base_revision": old_version, "changes": {"visual": "过期改动"}}).status_code == 409
    for fmt in ["json", "markdown", "csv"]:
        res = client.get(f"/api/projects/{p['id']}/exports?format={fmt}")
        assert res.status_code == 200, res.text
        assert "attachment" in res.headers.get("content-disposition", "")
        assert "雨后的红色信箱" in res.text
        if fmt == "json": assert json.loads(res.text)
        if fmt == "csv": assert len(list(csv.DictReader(io.StringIO(res.text)))) == 5
    restored = client.post(f"/api/projects/{p['id']}/revisions/{old_version}/restore", json={"base_revision": p["current_revision"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["current_revision"] > p["current_revision"]
    assert restored.json()["document"]["beats"][2]["visual"] != "雨后的红色信箱"

def test_generation_idempotency_and_scope(client):
    p = timeline(client)
    body = {"kind": "rewrite", "base_revision": p["current_revision"], "idempotency_key": "same", "start_second": 2, "end_second": 3, "instruction": "改为晴天", "locked_fields": ["visual"]}
    a = client.post(f"/api/projects/{p['id']}/runs", json=body)
    b = client.post(f"/api/projects/{p['id']}/runs", json=body)
    assert a.status_code == b.status_code == 202
    assert a.json()["id"] == b.json()["id"]
    after = apply(client, p, terminal(client, a.json()))
    assert after["document"]["story"] == p["document"]["story"]
    for i, beat in enumerate(p["document"]["beats"]):
        if i != 2: assert beat == after["document"]["beats"][i]
    assert after["document"]["beats"][2]["visual"] == p["document"]["beats"][2]["visual"]

def test_chat_memory_isolation_confirmation_deletion(client):
    a, b = project(client, "甲的故事"), project(client, "乙的故事")
    ca, cb = conversation(client, a), conversation(client, b)
    first = chat(client, ca)
    message = next(m for m in client.get(f"/api/conversations/{ca['id']}/messages").json() if m["role"] == "user")
    before = client.get(f"/api/projects/{a['id']}").json()
    res = client.post("/api/memories", json={"scope": "project", "project_id": a["id"], "content": "唯一蓝衣偏好", "source_message_ids": [message["id"]]})
    assert res.status_code == 201, res.text
    memory = res.json()
    pending = chat(client, ca)
    assert memory["id"] not in client.get(f"/api/runs/{pending['id']}/context").json()["memory_ids"]
    confirmed = client.post(f"/api/memories/{memory['id']}/confirm", json={"expected_version": memory["version"]})
    assert confirmed.status_code == 200, confirmed.text
    active = chat(client, ca)
    context = client.get(f"/api/runs/{active['id']}/context").json()
    assert memory["id"] in context["memory_ids"]
    assert message["id"] in context["message_ids"] or message["id"] in context["summary"]["source_message_ids"]
    other = chat(client, cb)
    assert memory["id"] not in client.get(f"/api/runs/{other['id']}/context").json()["memory_ids"]
    assert memory["id"] not in {m["id"] for m in client.get(f"/api/memories?project_id={b['id']}").json()}
    assert client.get(f"/api/projects/{a['id']}").json()["document"] == before["document"]
    foreign = client.post("/api/memories", json={"scope": "project", "project_id": b["id"], "content": "串项目", "source_message_ids": [message["id"]]})
    assert foreign.status_code in {400, 403, 404, 422}, foreign.text
    assert client.delete(f"/api/memories/{memory['id']}").status_code == 200
    new = chat(client, ca)
    new_context = client.get(f"/api/runs/{new['id']}/context").json()
    assert memory["id"] not in new_context["memory_ids"]
    assert "唯一蓝衣偏好" not in json.dumps(new_context, ensure_ascii=False)
    old_context = client.get(f"/api/runs/{active['id']}/context").json()
    assert "唯一蓝衣偏好" not in json.dumps(old_context, ensure_ascii=False)
    assert client.delete(f"/api/messages/{message['id']}").status_code == 200
    redacted = client.get(f"/api/runs/{active['id']}/context").json()
    assert "保留蓝色外套" not in json.dumps(redacted, ensure_ascii=False)

def test_memory_version_and_edit_requires_reconfirmation(client):
    p = project(client); c = conversation(client, p)
    memory = client.post("/api/memories", json={"scope": "project", "project_id": p["id"], "content": "蓝衣"}).json()
    confirmed = client.post(f"/api/memories/{memory['id']}/confirm", json={"expected_version": memory["version"]}).json()
    edit = client.patch(f"/api/memories/{memory['id']}", json={"expected_version": confirmed["version"], "content": "红衣"})
    assert edit.status_code == 200, edit.text
    assert edit.json()["status"] == "candidate"
    assert client.patch(f"/api/memories/{memory['id']}", json={"expected_version": confirmed["version"], "content": "过期"}).status_code == 409
    reply = chat(client, c)
    assert memory["id"] not in client.get(f"/api/runs/{reply['id']}/context").json()["memory_ids"]

def test_cross_project_message_reference_rejected(client):
    a, b = project(client), project(client)
    ca, cb = conversation(client, a), conversation(client, b)
    chat(client, ca)
    message = client.get(f"/api/conversations/{ca['id']}/messages").json()[0]
    res = client.post(f"/api/conversations/{cb['id']}/messages", json={"content": "引用", "idempotency_key": "foreign", "references": [{"type": "message", "id": message["id"]}]})
    assert res.status_code in {400, 403, 404, 422}, res.text
    assert client.get(f"/api/conversations/{cb['id']}/messages").json() == []

def test_paid_mode_blocked_without_environment_or_approval(client):
    settings = client.patch("/api/settings/model", json={"mode": "openai-compatible", "base_url": "http://127.0.0.1:9", "model": "test"})
    assert settings.status_code == 200, settings.text
    assert not settings.json()["key_present"] and not settings.json()["paid_calls_enabled"]
    p = project(client)
    response = client.post(f"/api/projects/{p['id']}/runs", json={"kind": "expand", "base_revision": 1, "idempotency_key": "blocked"})
    if response.status_code == 202:
        blocked = terminal(client, response.json()); assert blocked["status"] == "failed", blocked
    else: assert response.status_code in {400, 403, 409, 422}
    rejected = client.post("/api/approvals", json={"project_id": p["id"], "max_calls": 1, "accept_unknown_cost": False})
    assert rejected.status_code in {400, 422}
    accepted = client.post("/api/approvals", json={"project_id": p["id"], "max_calls": 1, "accept_unknown_cost": True})
    assert accepted.status_code == 201, accepted.text
    assert client.delete(f"/api/approvals/{accepted.json()['id']}").status_code == 200
    assert client.get("/api/settings/model").json()["key_present"] is False

def test_backup_download_is_consistent_sqlite(client, tmp_path):
    p = timeline(client)
    backup = client.post("/api/backups", json={})
    assert backup.status_code == 201, backup.text
    download = client.get(f"/api/backups/{backup.json()['id']}/download")
    assert download.status_code == 200, download.text
    path = tmp_path / "restored.sqlite3"; path.write_bytes(download.content)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        row = db.execute("SELECT value FROM entities WHERE kind='project' AND id=?", (p["id"],)).fetchone()
        assert json.loads(row[0])["document"] == p["document"]
        assert "LLM_API_KEY" not in path.read_bytes().decode("utf-8", errors="ignore")

def test_cancel_prevents_late_candidate_and_version_write(client):
    p = project(client)
    started = client.post(f"/api/projects/{p['id']}/runs", json={"kind": "expand", "base_revision": 1, "idempotency_key": "cancel-immediately"})
    assert started.status_code == 202
    rid = started.json()["id"]
    cancelled = client.post(f"/api/runs/{rid}/cancel", json={})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    time.sleep(.08)  # Worker contract delays .03s; ensure late completion cannot submit.
    assert client.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    assert client.get(f"/api/projects/{p['id']}/proposals").json() == []
    unchanged = client.get(f"/api/projects/{p['id']}").json()
    assert unchanged["current_revision"] == 1 and unchanged["document"]["story"] is None

def test_chat_duplicate_is_one_user_message_and_stale_candidate_rejected(client):
    p = timeline(client); c = conversation(client, p)
    body = {"content": "修改第一秒", "intent": "rewrite", "start_second": 0, "end_second": 1, "idempotency_key": "duplicate-message"}
    first = client.post(f"/api/conversations/{c['id']}/messages", json=body)
    second = client.post(f"/api/conversations/{c['id']}/messages", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    ready = terminal(client, first.json()); assert ready["proposal_id"]
    messages = client.get(f"/api/conversations/{c['id']}/messages").json()
    assert sum(m["role"] == "user" for m in messages) == 1
    unchanged = client.get(f"/api/projects/{p['id']}").json()
    assert unchanged["current_revision"] == p["current_revision"]
    edit = client.patch(f"/api/projects/{p['id']}/beats/0", json={"base_revision": p["current_revision"], "changes": {"visual": "用户更新后不可覆盖"}})
    assert edit.status_code == 200
    reject = client.post(f"/api/proposals/{ready['proposal_id']}/apply", json={"base_revision": edit.json()["current_revision"]})
    assert reject.status_code == 409
    assert client.get(f"/api/projects/{p['id']}").json()["document"]["beats"][0]["visual"] == "用户更新后不可覆盖"

def test_approval_bound_to_model_configuration(client, monkeypatch):
    # Explicitly simulated enablement. A transport trap makes accidental calls fail locally.
    import tools.model as model
    import httpx
    original = httpx.AsyncClient
    def reject_http(req): raise AssertionError("Config-change preflight must not send HTTP")
    monkeypatch.setattr(model.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reject_http), **kw))
    monkeypatch.setenv("LLM_API_KEY", "test-placeholder-not-a-secret")
    monkeypatch.setenv("PAID_CALLS_ENABLED", "true")
    p = project(client)
    assert client.patch("/api/settings/model", json={"mode": "openai-compatible", "base_url": "https://invalid.example", "model": "before"}).status_code == 200
    approval = client.post("/api/approvals", json={"project_id": p["id"], "max_calls": 1, "accept_unknown_cost": True})
    assert approval.status_code == 201
    assert client.patch("/api/settings/model", json={"model": "after"}).status_code == 200
    response = client.post(f"/api/projects/{p['id']}/runs", json={"kind": "expand", "base_revision": 1, "idempotency_key": "changed-model", "approval_id": approval.json()["id"]})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "APPROVAL_CONFIG_CHANGED"
    assert client.get(f"/api/projects/{p['id']}/runs").json() == []

def test_sourced_memory_can_edit_reconfirm_and_excludes_old_source(client):
    p = project(client); c = conversation(client, p); chat(client, c, "旧蓝衣偏好")
    source = next(m for m in client.get(f"/api/conversations/{c['id']}/messages").json() if m["role"] == "user")
    memory = client.post("/api/memories", json={"scope": "project", "project_id": p["id"], "content": "蓝衣", "source_message_ids": [source["id"]]}).json()
    memory = client.post(f"/api/memories/{memory['id']}/confirm", json={"expected_version": memory["version"]}).json()
    edited = client.patch(f"/api/memories/{memory['id']}", json={"expected_version": memory["version"], "content": "红衣"}).json()
    response = client.post(f"/api/memories/{memory['id']}/confirm", json={"expected_version": edited["version"]})
    assert response.status_code == 200, response.text
    reply = chat(client, c, "当前偏好是什么")
    snapshot = client.get(f"/api/runs/{reply['id']}/context").json()
    assert memory["id"] in snapshot["memory_ids"]
    assert source["id"] not in snapshot["message_ids"]
    assert "旧蓝衣偏好" not in json.dumps(snapshot, ensure_ascii=False)

def test_structure_repair_is_limited_and_consumes_same_approval(client, monkeypatch):
    import httpx
    import tools.model as model
    from agents.fixture import expand
    original = httpx.AsyncClient
    calls = []
    p = project(client)
    valid = expand(p["brief"])
    def handler(req):
        calls.append(req)
        content = '{}' if len(calls) == 1 else json.dumps(valid, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 20, "completion_tokens": 20}})
    monkeypatch.setattr(model.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("LLM_API_KEY", "test-placeholder-not-a-secret"); monkeypatch.setenv("PAID_CALLS_ENABLED", "true")
    assert client.patch("/api/settings/model", json={"mode": "openai-compatible", "base_url": "https://invalid.example", "model": "simulated"}).status_code == 200
    approval = client.post("/api/approvals", json={"project_id": p["id"], "max_calls": 2, "accept_unknown_cost": True}).json()
    ready = run(client, p, approval_id=approval["id"])
    assert ready["status"] == "succeeded", ready
    assert len(calls) == 2
    assert next(a for a in client.get("/api/approvals").json() if a["id"] == approval["id"])["calls_used"] == 2
    assert client.get(f"/api/projects/{p['id']}").json()["document"]["story"] is None

def test_blind_comparison_cli_parses_real_export_wrapper(client, tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    first, second = timeline(client), timeline(client)
    changed = client.patch(f"/api/projects/{second['id']}/beats/0", json={"base_revision": second["current_revision"], "changes": {"visual": "另一份对比候选画面"}})
    assert changed.status_code == 200
    first_file, second_file = tmp_path / "baseline.json", tmp_path / "workflow.json"
    for p, destination in [(first, first_file), (changed.json(), second_file)]:
        response = client.get(f"/api/projects/{p['id']}/exports?format=json")
        assert response.status_code == 200
        destination.write_bytes(response.content)
    output = tmp_path / "blind"
    command = [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "compare_prompts.py"), str(first_file), str(second_file), "--out", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with (output / "blind-review.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(first["document"]["shots"])
    assert set(rows[0]) == {"case", "start", "end", "A", "B", "preferred", "notes"}
    assert rows[0]["A"] != rows[0]["B"] and rows[0]["preferred"] == ""
    key = json.loads((output / "answer-key.json").read_text())
    assert key["key"][0]["A"] in {"baseline", "workflow"}
    expected = changed.json()["document"]["shots"][0]["prompt"] if key["key"][0]["A"] == "workflow" else first["document"]["shots"][0]["prompt"]
    assert rows[0]["A"] == expected

def test_deleted_message_redacts_run_and_disables_unapplied_proposal(client):
    p = timeline(client); c = conversation(client, p)
    marker = "删除消息专用独有文本-37"
    ready = chat(client, c, marker, intent="rewrite", start_second=0, end_second=1)
    assert ready["proposal_id"]
    source = next(m for m in client.get(f"/api/conversations/{c['id']}/messages").json() if m["role"] == "user")
    assert client.delete(f"/api/messages/{source['id']}").status_code == 200
    run_record = client.get(f"/api/runs/{ready['id']}").json()
    assert marker not in json.dumps(run_record, ensure_ascii=False)
    assert run_record["id"] == ready["id"] and "usage" in run_record
    proposals = client.get(f"/api/projects/{p['id']}/proposals").json()
    proposal = next(pr for pr in proposals if pr["id"] == ready["proposal_id"])
    assert marker not in json.dumps(proposal, ensure_ascii=False)
    apply_response = client.post(f"/api/proposals/{proposal['id']}/apply", json={"base_revision": p["current_revision"]})
    assert apply_response.status_code == 409
    assert client.get(f"/api/projects/{p['id']}").json()["current_revision"] == p["current_revision"]
