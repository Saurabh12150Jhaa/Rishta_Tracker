import json

import httpx
import pytest

import app.db as db
from app.services import github_backup, snapshot
from conftest import insert_profile

REPO = "owner/data"


class FakeGithub:
    def __init__(self, contents=(404, b""), patch_statuses=None):
        self.calls = []
        self.bodies = []
        self.contents = contents
        self.patch_statuses = list(patch_statuses or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        body = json.loads(request.content) if request.content and request.method != "GET" else None
        self.bodies.append(body)
        base = f"/repos/{REPO}"
        if request.method == "GET" and path.startswith(f"{base}/contents/"):
            return httpx.Response(self.contents[0], content=self.contents[1])
        if request.method == "POST" and path == f"{base}/git/blobs":
            return httpx.Response(201, json={"sha": "blob1"})
        if request.method == "GET" and path == f"{base}/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "head1"}})
        if request.method == "GET" and path == f"{base}/git/commits/head1":
            return httpx.Response(200, json={"tree": {"sha": "tree0"}})
        if request.method == "POST" and path == f"{base}/git/trees":
            return httpx.Response(201, json={"sha": "tree1"})
        if request.method == "POST" and path == f"{base}/git/commits":
            return httpx.Response(201, json={"sha": "commit1"})
        if request.method == "PATCH" and path == f"{base}/git/refs/heads/main":
            status = self.patch_statuses.pop(0) if self.patch_statuses else 200
            return httpx.Response(status, json={"ok": status == 200})
        return httpx.Response(500, json={"unexpected": path})

    def pushes(self):
        return [c for c in self.calls if c[0] == "PATCH"]


@pytest.fixture()
def gh(iso, monkeypatch):
    monkeypatch.setenv("BACKUP_GITHUB_REPO", REPO)
    monkeypatch.setenv("BACKUP_GITHUB_TOKEN", "tok")

    def install(fake):
        monkeypatch.setattr(github_backup, "_TRANSPORT", httpx.MockTransport(fake))
        return fake

    return install


def _snapshot_bytes(tmp_path, n=2):
    for i in range(n):
        insert_profile(f"Person {i}")
    zip_path, manifest = snapshot.build_snapshot_zip(tmp_path / "snap")
    return zip_path.read_bytes(), manifest


def _wipe():
    conn = db.get_conn()
    conn.execute("DELETE FROM profiles")
    conn.execute("UPDATE instance_meta SET value='wiped' WHERE key='data_epoch'")
    conn.commit()
    conn.close()


def test_disabled_without_config(iso):
    github_backup.startup_restore()
    github_backup.backup_tick()
    assert github_backup.get_state()["configured"] is False


def test_startup_restore_when_empty(iso, gh, tmp_path):
    data, manifest = _snapshot_bytes(tmp_path)
    _wipe()
    fake = gh(FakeGithub(contents=(200, data)))
    github_backup.startup_restore()
    assert db.count_user_rows() == 2
    assert db.get_data_epoch() == manifest["epoch"]
    st = github_backup.get_state()
    assert st["restored_at"] and not st["restore_failed"]
    assert fake.calls[0][0] == "GET"


def test_startup_restore_skipped_when_data_present(iso, gh):
    insert_profile("Existing")
    fake = gh(FakeGithub())
    github_backup.startup_restore()
    assert fake.calls == []
    assert not github_backup.state["restore_failed"]


def test_startup_restore_404_means_no_backup(iso, gh):
    gh(FakeGithub(contents=(404, b"")))
    github_backup.startup_restore()
    assert github_backup.state["restore_ok"] and not github_backup.state["restore_failed"]
    assert github_backup.state["last_error"] is None


@pytest.mark.parametrize("contents", [(500, b"boom"), (200, b"not a zip")])
def test_startup_restore_failure_sets_flag(iso, gh, contents):
    gh(FakeGithub(contents=contents))
    github_backup.startup_restore()
    st = github_backup.get_state()
    assert st["restore_failed"] and st["last_error"]


def test_push_on_sha_change_only(iso, gh):
    fake = gh(FakeGithub())
    insert_profile("A")
    github_backup.backup_tick()
    assert len(fake.pushes()) == 1
    assert [c[0] + " " + c[1].split(f"/repos/{REPO}")[1] for c in fake.calls] == [
        "POST /git/blobs",
        "GET /git/ref/heads/main",
        "GET /git/commits/head1",
        "POST /git/trees",
        "POST /git/commits",
        "PATCH /git/refs/heads/main",
    ]
    tree_body = fake.bodies[3]
    assert tree_body["base_tree"] == "tree0"
    assert tree_body["tree"][0]["path"] == "snapshot.zip" and tree_body["tree"][0]["sha"] == "blob1"
    commit_body = fake.bodies[4]
    assert commit_body["parents"] == ["head1"] and commit_body["message"].startswith("backup: ")

    github_backup.backup_tick()
    assert len(fake.pushes()) == 1

    insert_profile("B")
    github_backup.backup_tick()
    assert len(fake.pushes()) == 2
    assert github_backup.get_state()["last_push_at"]


def test_heartbeat_does_not_trigger_push(iso, gh):
    fake = gh(FakeGithub())
    insert_profile("A")
    github_backup.backup_tick()
    iso.post("/api/worker/poll", headers=iso.worker_headers, json={"hostname": "h"})
    github_backup.backup_tick()
    assert len(fake.pushes()) == 1


def test_no_push_when_empty(iso, gh):
    fake = gh(FakeGithub())
    github_backup.backup_tick()
    assert fake.calls == []


def test_conflict_copy_when_restore_failed(iso, gh):
    fake = gh(FakeGithub(contents=(500, b"")))
    github_backup.startup_restore()
    assert github_backup.state["restore_failed"]
    insert_profile("New data after wipe")
    fake.contents = (500, b"")
    github_backup.backup_tick()
    assert len(fake.pushes()) == 1
    paths = [b["tree"][0]["path"] for b in fake.bodies if b and "tree" in b and isinstance(b["tree"], list)]
    assert paths and paths[0].startswith("conflicts/snapshot_") and paths[0].endswith(".zip")
    assert github_backup.state["last_error"] and "merge" in github_backup.state["last_error"]
    github_backup.backup_tick()
    assert len(fake.pushes()) == 1


def test_fast_forward_race_retries_once(iso, gh):
    fake = gh(FakeGithub(patch_statuses=[422, 200]))
    insert_profile("A")
    github_backup.backup_tick()
    assert len(fake.pushes()) == 2
    assert len([c for c in fake.calls if c[1].endswith("/git/ref/heads/main")]) == 2
    assert github_backup.state["last_error"] is None


def test_status_endpoint_exposes_cloud_backup(iso):
    r = iso.get("/api/worker/status", headers=iso.member_headers)
    assert r.status_code == 200
    assert r.json()["cloud_backup"]["configured"] is False
