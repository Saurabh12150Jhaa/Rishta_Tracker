import asyncio
import base64
import logging
import os
import shutil
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from ..db import count_user_rows, logical_sha
from .snapshot import SnapshotError, build_snapshot_zip, restore_snapshot_zip

log = logging.getLogger("rishta.github_backup")

API_ROOT = "https://api.github.com"
FINAL_PUSH_TIMEOUT_SECONDS = 20.0

_TRANSPORT: Optional[httpx.BaseTransport] = None

state: dict = {
    "configured": False,
    "last_push_at": None,
    "last_pushed_sha": None,
    "last_conflict_sha": None,
    "last_error": None,
    "restored_at": None,
    "restore_failed": False,
    "restore_ok": False,
}


def get_config() -> Optional[dict]:
    repo = os.getenv("BACKUP_GITHUB_REPO", "").strip()
    token = os.getenv("BACKUP_GITHUB_TOKEN", "").strip()
    if not repo or not token:
        return None
    return {
        "repo": repo,
        "token": token,
        "branch": os.getenv("BACKUP_GITHUB_BRANCH", "").strip() or "main",
        "path": os.getenv("BACKUP_GITHUB_PATH", "").strip() or "snapshot.zip",
    }


def get_state() -> dict:
    state["configured"] = get_config() is not None
    return {k: state[k] for k in ("configured", "last_push_at", "last_pushed_sha", "last_error", "restored_at", "restore_failed")}


def _client(cfg: dict, accept: str = "application/vnd.github+json") -> httpx.Client:
    kwargs: dict = {
        "base_url": API_ROOT,
        "timeout": 120.0,
        "headers": {
            "Authorization": f"Bearer {cfg['token']}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rishta-tracker-backup",
        },
    }
    if _TRANSPORT is not None:
        kwargs["transport"] = _TRANSPORT
    else:
        try:
            import truststore

            kwargs["verify"] = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            pass
    return httpx.Client(**kwargs)


def _fail_restore(message: str) -> None:
    log.error("[GitHubBackup] restore failed: %s", message)
    state["restore_failed"] = True
    state["restore_ok"] = False
    state["last_error"] = message


def startup_restore() -> None:
    cfg = get_config()
    state["configured"] = cfg is not None
    if not cfg:
        return
    tmp_dir = Path(tempfile.mkdtemp(prefix="rishta_ghrestore_"))
    try:
        if count_user_rows() > 0:
            state["restore_failed"] = False
            state["restore_ok"] = True
            return
        with _client(cfg, accept="application/vnd.github.raw") as client:
            resp = client.get(
                f"/repos/{cfg['repo']}/contents/{cfg['path']}", params={"ref": cfg["branch"]}
            )
        if resp.status_code == 404:
            log.info("[GitHubBackup] no backup yet in %s", cfg["repo"])
            state["restore_failed"] = False
            state["restore_ok"] = True
            return
        if resp.status_code != 200:
            _fail_restore(f"GitHub returned HTTP {resp.status_code} while fetching backup")
            return
        zip_path = tmp_dir / "backup.zip"
        zip_path.write_bytes(resp.content)
        result = restore_snapshot_zip(zip_path, force=False)
        state["restored_at"] = datetime.now(timezone.utc).isoformat()
        state["restore_failed"] = False
        state["restore_ok"] = True
        state["last_error"] = None
        state["last_pushed_sha"] = logical_sha()
        log.warning("[GitHubBackup] RESTORED from GitHub: %s", result)
    except SnapshotError as exc:
        _fail_restore(f"restore rejected ({exc.status_code}): {exc.detail}")
    except Exception as exc:
        _fail_restore(f"restore error: {exc}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _push_file(cfg: dict, repo_path: str, zip_path: Path, message: str) -> None:
    content = base64.b64encode(zip_path.read_bytes()).decode("ascii")
    repo = cfg["repo"]
    branch = cfg["branch"]
    with _client(cfg) as client:
        blob = client.post(f"/repos/{repo}/git/blobs", json={"content": content, "encoding": "base64"})
        blob.raise_for_status()
        blob_sha = blob.json()["sha"]
        for attempt in range(2):
            ref = client.get(f"/repos/{repo}/git/ref/heads/{branch}")
            ref.raise_for_status()
            head_sha = ref.json()["object"]["sha"]
            commit = client.get(f"/repos/{repo}/git/commits/{head_sha}")
            commit.raise_for_status()
            base_tree = commit.json()["tree"]["sha"]
            tree = client.post(
                f"/repos/{repo}/git/trees",
                json={
                    "base_tree": base_tree,
                    "tree": [{"path": repo_path, "mode": "100644", "type": "blob", "sha": blob_sha}],
                },
            )
            tree.raise_for_status()
            new_commit = client.post(
                f"/repos/{repo}/git/commits",
                json={"message": message, "tree": tree.json()["sha"], "parents": [head_sha]},
            )
            new_commit.raise_for_status()
            patch = client.patch(
                f"/repos/{repo}/git/refs/heads/{branch}", json={"sha": new_commit.json()["sha"]}
            )
            if patch.status_code == 422 and attempt == 0:
                continue
            patch.raise_for_status()
            return


def _push_snapshot(cfg: dict, conflict: bool) -> dict:
    tmp_dir = Path(tempfile.mkdtemp(prefix="rishta_ghpush_"))
    try:
        zip_path, manifest = build_snapshot_zip(tmp_dir)
        if conflict:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            repo_path = f"conflicts/snapshot_{stamp}.zip"
        else:
            repo_path = cfg["path"]
        message = f"backup: {manifest['user_rows']} rows, sha {manifest['logical_sha'][:8]}"
        _push_file(cfg, repo_path, zip_path, message)
        return manifest
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def backup_tick() -> None:
    cfg = get_config()
    state["configured"] = cfg is not None
    if not cfg:
        return
    try:
        rows = count_user_rows()
        if state["restore_failed"] and rows == 0:
            startup_restore()
            rows = count_user_rows()
        if rows == 0:
            return

        current_sha = logical_sha()
        if state["restore_failed"]:
            if current_sha == state["last_conflict_sha"]:
                return
            manifest = _push_snapshot(cfg, conflict=True)
            state["last_conflict_sha"] = manifest["logical_sha"]
            state["last_push_at"] = datetime.now(timezone.utc).isoformat()
            state["last_error"] = (
                "Restore from GitHub failed but new data exists; saved to conflicts/ "
                "in the backup repo instead of overwriting the main backup. Manual merge needed."
            )
            log.warning("[GitHubBackup] %s", state["last_error"])
            return

        if current_sha == state["last_pushed_sha"]:
            return
        manifest = _push_snapshot(cfg, conflict=False)
        state["last_pushed_sha"] = manifest["logical_sha"]
        state["last_push_at"] = datetime.now(timezone.utc).isoformat()
        state["last_error"] = None
        log.info("[GitHubBackup] pushed backup (%s rows)", manifest["user_rows"])
    except Exception as exc:
        state["last_error"] = f"push failed: {exc}"
        log.error("[GitHubBackup] %s", state["last_error"])


async def backup_loop() -> None:
    interval = float(os.getenv("BACKUP_INTERVAL_SECONDS", "60"))
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(backup_tick)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["last_error"] = f"backup loop error: {exc}"


async def final_push() -> None:
    if get_config() is None:
        return
    try:
        await asyncio.wait_for(asyncio.to_thread(backup_tick), timeout=FINAL_PUSH_TIMEOUT_SECONDS)
    except Exception as exc:
        log.error("[GitHubBackup] final push failed: %s", exc)
