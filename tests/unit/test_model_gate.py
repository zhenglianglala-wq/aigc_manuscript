"""Simulated HTTP only; the transport never opens a socket."""
import asyncio
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from backend.store import DomainError, Store
from tools import model

def prepared(tmp_path, monkeypatch, handler, max_calls=3, known=False):
    monkeypatch.setenv("LLM_API_KEY", "test-placeholder-never-a-real-secret")
    monkeypatch.setenv("PAID_CALLS_ENABLED", "true")
    original = httpx.AsyncClient
    monkeypatch.setattr(model.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    store = Store(tmp_path)
    r = {"id": "run", "project_id": "p", "kind": "chat", "status": "running", "steps": [], "usage": {"input_tokens": None, "output_tokens": None, "cost": None, "cost_status": "unknown"}}
    a = {"id": "approval", "project_id": "p", "status": "active", "expires_at": (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(), "calls_used": 0, "max_calls": max_calls, "accept_unknown_cost": True, "budget": None, "spent": 0}
    with store.tx(): store.put("run", r); store.put("approval", a)
    settings = {"model": "simulated", "base_url": "https://invalid.example", "max_output_tokens": 1000, "temperature": .7, "input_price_per_million": 1 if known else None, "output_price_per_million": 2 if known else None, "price_date": "2026-10-12"}
    return store, r, settings

def test_disabled_and_revoked_do_not_send_http(tmp_path, monkeypatch):
    calls = []
    store, r, settings = prepared(tmp_path, monkeypatch, lambda req: calls.append(req))
    monkeypatch.setenv("PAID_CALLS_ENABLED", "false")
    with pytest.raises(DomainError) as err: asyncio.run(model.complete(store, r, settings, "approval", {}))
    assert err.value.code == "CALLS_DISABLED" and not calls
    monkeypatch.setenv("PAID_CALLS_ENABLED", "true")
    with store.tx():
        a = store.get("approval", "approval"); a["status"] = "revoked"; store.put("approval", a)
    with pytest.raises(DomainError) as err: asyncio.run(model.complete(store, r, settings, "approval", {}))
    assert err.value.code == "APPROVAL_REQUIRED" and not calls
    store.conn.close()

def test_retry_consumes_approval_limit(tmp_path, monkeypatch):
    calls = []
    def handler(req): calls.append(req); return httpx.Response(503, json={})
    store, r, settings = prepared(tmp_path, monkeypatch, handler, max_calls=1)
    with pytest.raises(DomainError) as err: asyncio.run(model.complete(store, r, settings, "approval", {}))
    assert err.value.code == "CALL_LIMIT"
    assert len(calls) == 1 and store.get("approval", "approval")["calls_used"] == 1
    assert store.get("run", "run")["usage"]["cost"] is None
    store.conn.close()

def test_reported_usage_and_cost(tmp_path, monkeypatch):
    def handler(req): return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"hello"}'}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
    store, r, settings = prepared(tmp_path, monkeypatch, handler, known=True)
    assert asyncio.run(model.complete(store, r, settings, "approval", {})) == {"reply": "hello"}
    usage = store.get("run", "run")["usage"]
    assert usage["input_tokens"] == 100 and usage["output_tokens"] == 50
    assert usage["cost"] == pytest.approx(.0002)
    assert store.get("approval", "approval")["spent"] == pytest.approx(.0002)
    store.conn.close()

def test_missing_usage_is_unknown(tmp_path, monkeypatch):
    def handler(req): return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"hello"}'}}]})
    store, r, settings = prepared(tmp_path, monkeypatch, handler, known=True)
    asyncio.run(model.complete(store, r, settings, "approval", {}))
    usage = store.get("run", "run")["usage"]
    assert usage["input_tokens"] is usage["output_tokens"] is usage["cost"] is None
    assert usage["cost_status"] == "unknown"
    store.conn.close()

def test_retry_with_missing_usage_cannot_be_fully_reported(tmp_path, monkeypatch):
    calls = []
    def handler(req):
        calls.append(req)
        if len(calls) == 1: return httpx.Response(503, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"hello"}'}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
    store, r, settings = prepared(tmp_path, monkeypatch, handler, known=True)
    asyncio.run(model.complete(store, r, settings, "approval", {}))
    usage = store.get("run", "run")["usage"]
    assert usage["cost_status"] in {"unknown", "partial"}, "One attempt lacks usage: aggregate cost cannot be called fully reported"
    assert usage["input_tokens"] is usage["output_tokens"] is usage["cost"] is None, "Aggregate usage is unknown when any attempt is missing usage"
    assert usage["partial_known"]["input_tokens"] == 100
    assert usage["partial_known"]["output_tokens"] == 50
    assert usage["partial_known"]["cost"] == pytest.approx(.0002)
    store.conn.close()
