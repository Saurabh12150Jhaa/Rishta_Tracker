import pytest
from fastapi.testclient import TestClient

import app.db as db
import app.routers.interactions as interactions_router
import app.routers.worker as worker_router
import app.services.ai_extractor as ai_extractor
from app.main import app
from app.services import github_backup

SECRET = "test-secret-123"


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rishta.sqlite")
    monkeypatch.setattr(db, "MEDIA_DIR", media)
    monkeypatch.setattr(worker_router, "WORKER_SHARED_SECRET", SECRET)
    monkeypatch.setattr(ai_extractor, "ZLLAMA_API_KEY", "")
    monkeypatch.setattr(interactions_router, "ZLLAMA_API_KEY", "")
    monkeypatch.setattr(worker_router, "ZLLAMA_API_KEY", "")
    for key in ("BACKUP_GITHUB_REPO", "BACKUP_GITHUB_TOKEN", "BACKUP_GITHUB_BRANCH", "BACKUP_GITHUB_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(github_backup, "_TRANSPORT", None)
    github_backup.state.update(
        configured=False,
        last_push_at=None,
        last_pushed_sha=None,
        last_conflict_sha=None,
        last_error=None,
        restored_at=None,
        restore_failed=False,
        restore_ok=False,
    )
    db.init_db()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"member_name": "Saurabh", "pin": "1234"})
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    client.token = token
    client.member_headers = {"Authorization": f"Bearer {token}"}
    client.worker_headers = {"X-Worker-Secret": SECRET}
    client.media = media
    return client


def insert_profile(name="Test Person", **extra):
    conn = db.get_conn()
    cols = {"full_name": name, "created_at": db.utc_now(), "updated_at": db.utc_now(), **extra}
    conn.execute(
        f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(cols.values()),
    )
    conn.commit()
    conn.close()
