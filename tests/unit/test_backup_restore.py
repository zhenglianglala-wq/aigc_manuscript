import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
from backend.store import Store
from scripts.backup import validate

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup.py"

def test_restore_reopens_valid_data_and_retains_prior_copy(tmp_path):
    source = Store(tmp_path / "source")
    with source.tx(): source.put("project", {"id": "p", "brief": {"description": "backup story"}, "current_revision": 1})
    source.conn.close()
    backup = tmp_path / "backup.sqlite3"
    result = subprocess.run([sys.executable, str(SCRIPT), "backup", str(backup), "--data-dir", str(tmp_path / "source")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    target = Store(tmp_path / "target")
    with target.tx(): target.put("project", {"id": "old", "title": "preserve"})
    target.conn.close()
    result = subprocess.run([sys.executable, str(SCRIPT), "restore", str(backup), "--data-dir", str(tmp_path / "target"), "--confirm"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    restored = Store(tmp_path / "target")
    assert restored.get("project", "p")["brief"]["description"] == "backup story"
    assert restored.get("project", "old", False) is None
    restored.conn.close()
    with sqlite3.connect(tmp_path / "target" / "studio.pre-restore.sqlite3") as old:
        assert old.execute("SELECT id FROM entities WHERE kind='project'").fetchone()[0] == "old"

def test_corrupt_restore_does_not_overwrite_existing(tmp_path):
    target = Store(tmp_path / "target"); target.conn.close()
    db = tmp_path / "target" / "studio.sqlite3"
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    corrupt = tmp_path / "broken.sqlite3"; corrupt.write_bytes(b"not a database")
    result = subprocess.run([sys.executable, str(SCRIPT), "restore", str(corrupt), "--data-dir", str(tmp_path / "target"), "--confirm"], capture_output=True)
    assert result.returncode != 0
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before

def test_backup_rejects_orphan_message(tmp_path):
    store = Store(tmp_path)
    with store.tx():
        store.put("project", {"id": "p"})
        store.put("message", {"id": "m", "project_id": "p", "conversation_id": "missing"})
    store.conn.close()
    with pytest.raises(ValueError, match="conversation"): validate(tmp_path / "studio.sqlite3")
