import pytest
from backend.store import Store

def test_restart_marks_unfinished_runs_interrupted(tmp_path):
    store = Store(tmp_path)
    with store.tx():
        for status in ["queued", "running", "validating", "succeeded", "cancelled"]:
            store.put("run", {"id": status, "status": status, "project_id": "p"})
    store.conn.close()
    reopened = Store(tmp_path)
    for status in ["queued", "running", "validating"]:
        assert reopened.get("run", status)["status"] == "interrupted"
    assert reopened.get("run", "succeeded")["status"] == "succeeded"
    assert reopened.get("run", "cancelled")["status"] == "cancelled"
    reopened.conn.close()

def test_transaction_failure_does_not_partially_write(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(RuntimeError):
        with store.tx():
            store.put("project", {"id": "p", "title": "must rollback"})
            raise RuntimeError("injected failure")
    assert store.get("project", "p", required=False) is None
    store.conn.close()
