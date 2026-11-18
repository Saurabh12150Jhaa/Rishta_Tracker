import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db as db
import app.routers.worker as worker_router
from app.main import app

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
import mac_ai_worker  # noqa: E402

SECRET = "test-secret-123"
AUTH = {"X-Worker-Secret": SECRET}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rishta.sqlite")
    monkeypatch.setattr(db, "MEDIA_DIR", media)
    monkeypatch.setattr(worker_router, "MEDIA_DIR", media)
    monkeypatch.setattr(worker_router, "WORKER_SHARED_SECRET", SECRET)
    db.init_db()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"member_name": "Saurabh", "pin": "1234"})
    assert login.status_code == 200, login.text
    client.member_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    client.media = media
    return client


def _add_profile(client, name):
    r = client.post("/api/profiles", json={"full_name": name}, headers=client.member_headers)
    assert r.status_code == 200, r.text


def _profile_count(client):
    return db_count("profiles")


def db_count(table):
    conn = db.get_conn()
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _restore(client, data: bytes, force=False):
    return client.post(
        f"/api/worker/backup/restore?force={'true' if force else 'false'}",
        headers=AUTH,
        files={"file": ("b.zip", data, "application/zip")},
    )


def _valid_db_bytes(tmp_path) -> bytes:
    p = tmp_path / "valid.sqlite"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL)")
    conn.commit()
    conn.close()
    return p.read_bytes()


def test_wrong_secret_401(env):
    assert env.get("/api/worker/backup/meta", headers={"X-Worker-Secret": "nope"}).status_code == 401
    assert env.get("/api/worker/backup/meta").status_code == 401


def test_empty_secret_503(env, monkeypatch):
    monkeypatch.setattr(worker_router, "WORKER_SHARED_SECRET", "")
    r = env.get("/api/worker/backup/meta", headers={"X-Worker-Secret": ""})
    assert r.status_code == 503


def test_meta_and_logical_sha(env):
    m1 = env.get("/api/worker/backup/meta", headers=AUTH).json()
    assert m1["epoch"] and m1["user_rows"] == 0 and m1["logical_sha"]
    env.post("/api/worker/poll", headers=AUTH, json={"hostname": "h"})
    m2 = env.get("/api/worker/backup/meta", headers=AUTH).json()
    assert m2["logical_sha"] == m1["logical_sha"]
    _add_profile(env, "Alice")
    m3 = env.get("/api/worker/backup/meta", headers=AUTH).json()
    assert m3["logical_sha"] != m1["logical_sha"]
    assert m3["user_rows"] == 1 and m3["epoch"] == m1["epoch"]


def test_snapshot_contents(env):
    _add_profile(env, "Alice")
    (env.media / "photos").mkdir()
    (env.media / "photos" / "a.jpg").write_bytes(b"jpg")
    (env.media / "backups").mkdir()
    (env.media / "backups" / "old.sqlite").write_bytes(b"x")
    r = env.get("/api/worker/backup/snapshot", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["x-data-epoch"] and r.headers["x-logical-sha"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "rishta.sqlite" in names and "manifest.json" in names
        assert "media/photos/a.jpg" in names
        assert not any(n.startswith("media/backups") for n in names)
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["epoch"] == r.headers["x-data-epoch"]


def test_restore_conflict_without_force(env):
    _add_profile(env, "Alice")
    snap = env.get("/api/worker/backup/snapshot", headers=AUTH).content
    assert _restore(env, snap).status_code == 409


def test_restore_round_trip(env):
    for n in ("A", "B", "C"):
        _add_profile(env, n)
    (env.media / "photos").mkdir()
    (env.media / "photos" / "a.jpg").write_bytes(b"jpg")
    snap = env.get("/api/worker/backup/snapshot", headers=AUTH)
    epoch = snap.headers["x-data-epoch"]

    conn = db.get_conn()
    conn.execute("DELETE FROM profiles")
    conn.execute("UPDATE instance_meta SET value='wiped' WHERE key='data_epoch'")
    conn.commit()
    conn.close()
    (env.media / "photos" / "a.jpg").unlink()

    r = _restore(env, snap.content)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["restored"] and body["profiles"] == 3 and body["epoch"] == epoch
    assert body["media_files"] == 1
    assert (env.media / "photos" / "a.jpg").read_bytes() == b"jpg"
    listed = env.get("/api/profiles", headers=env.member_headers).json()
    items = listed["profiles"] if isinstance(listed, dict) else listed
    assert len(items) == 3
    assert db.get_data_epoch() == epoch


def test_restore_path_traversal_rejected(env, tmp_path):
    data = _make_zip(
        {"rishta.sqlite": _valid_db_bytes(tmp_path), "media/ok.txt": "ok", "media/../../evil.txt": "bad"}
    )
    r = _restore(env, data)
    assert r.status_code == 400
    assert not (env.media / "ok.txt").exists()
    assert not (env.media.parent.parent / "evil.txt").exists()
    assert db_count("members") == 3


def test_restore_corrupt_sqlite_rejected(env):
    r = _restore(env, _make_zip({"rishta.sqlite": b"this is not sqlite" * 50}))
    assert r.status_code == 400


def test_restore_missing_db_rejected(env):
    assert _restore(env, _make_zip({"manifest.json": "{}"})).status_code == 400


@pytest.mark.parametrize(
    "state,meta,has_backup,expected",
    [
        ({}, {"epoch": "e1", "user_rows": 0}, False, "empty"),
        ({}, {"epoch": "e1", "user_rows": 5}, False, "download"),
        ({"epoch": "e1", "logical_sha": "a"}, {"epoch": "e1", "user_rows": 5, "logical_sha": "a"}, True, "noop"),
        ({"epoch": "e1", "logical_sha": "a"}, {"epoch": "e1", "user_rows": 5, "logical_sha": "b"}, True, "download"),
        ({"epoch": "e1", "logical_sha": "a"}, {"epoch": "e2", "user_rows": 0, "logical_sha": "z"}, True, "restore"),
        ({"epoch": "e1", "logical_sha": "a"}, {"epoch": "e2", "user_rows": 0, "logical_sha": "z"}, False, "adopt"),
        ({"epoch": "e1", "logical_sha": "a"}, {"epoch": "e2", "user_rows": 2, "logical_sha": "z"}, True, "conflict"),
    ],
)
def test_decide_sync_action(state, meta, has_backup, expected):
    assert mac_ai_worker.decide_sync_action(state, meta, has_backup) == expected
