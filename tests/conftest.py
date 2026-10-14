import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest.fixture
def client(tmp_path, monkeypatch):
    # Only this project's isolated fixture app; never load another project's .env.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("LLM_MODE", "fixture")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("PAID_CALLS_ENABLED", "false")
    monkeypatch.setenv("IMAGE_MODE", "fixture")
    monkeypatch.setenv("IMAGE_API_KEY", "")
    monkeypatch.setenv("PAID_IMAGE_CALLS_ENABLED", "false")
    from backend.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(data_dir=tmp_path / "db")) as test_client:
        yield test_client
