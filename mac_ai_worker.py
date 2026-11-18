#!/usr/bin/env python3
"""
Outbound-Only Mac AI Worker for Sister's Rishta Dossier.
- Runs on your Zscaler-connected Mac with ZERO listening ports and ZERO reverse tunnels.
- Polls your permanent Cloud Web App over standard outbound HTTPS:
    POST https://<your-cloud-app>/api/worker/poll
- Calls https://zllama.corp.zscaler.com/v1 locally on your Mac using ZLLAMA_API_KEY.
- Pushes the extracted JSON, Hinglish voice transcript, and bulk diary rows back over outbound HTTPS.
"""
import argparse
import json
import os
import socket
import sqlite3
import ssl
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

try:
    import truststore
    truststore.inject_into_ssl()
    SSL_CTX: ssl.SSLContext | bool = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    SSL_CTX = False

from dotenv import load_dotenv
import httpx

load_dotenv(ROOT_DIR / ".env")

from app.config import WORKER_SHARED_SECRET, ZLLAMA_API_KEY
from app.services.ai_extractor import extract_rishta_bundle
from app.services.media_proc import (
    image_bytes_to_data_url,
    process_pdf_biodata,
    transcode_audio_to_mp3_b64,
)


BACKUPS_DIR = ROOT_DIR / "data" / "cloud_backups"
STATE_FILE = BACKUPS_DIR / "state.json"
LOCAL_MEDIA_DIR = ROOT_DIR / "data" / "media"
BACKUP_INTERVAL_SECONDS = float(os.getenv("BACKUP_INTERVAL_SECONDS", "300"))
MAX_SNAPSHOTS = 50


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_backup_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_backup_state(state: dict) -> None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def decide_sync_action(state: dict, meta: dict, has_backup: bool) -> str:
    """Pure decision: one of empty | download | noop | restore | adopt | conflict."""
    rows = int(meta.get("user_rows") or 0)
    state_epoch = state.get("epoch")
    if not state_epoch:
        return "download" if rows > 0 else "empty"
    if meta.get("epoch") == state_epoch:
        if rows > 0 and meta.get("logical_sha") != state.get("logical_sha"):
            return "download"
        return "noop"
    if rows == 0:
        return "restore" if has_backup else "adopt"
    return "conflict"


def _latest_backup(state: dict) -> Path | None:
    name = state.get("last_backup_file")
    if name and (BACKUPS_DIR / name).is_file():
        return BACKUPS_DIR / name
    candidates = [p for pat in ("snapshot_*.zip", "seed_*.zip") for p in BACKUPS_DIR.glob(pat)]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _download_snapshot(cloud_url: str, secret: str, prefix: str) -> tuple[Path, dict]:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS_DIR / f"{prefix}_{_stamp()}.zip"
    tmp = dest.with_suffix(".part")
    with httpx.Client(timeout=300.0, verify=SSL_CTX) as client:
        with client.stream(
            "GET", f"{cloud_url}/api/worker/backup/snapshot", headers={"X-Worker-Secret": secret}
        ) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    tmp.replace(dest)
    with zipfile.ZipFile(dest) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    return dest, manifest


def _prune_snapshots() -> None:
    snaps = sorted(BACKUPS_DIR.glob("snapshot_*.zip"), key=lambda p: p.name, reverse=True)
    for old in snaps[MAX_SNAPSHOTS:]:
        old.unlink(missing_ok=True)


def _post_restore(cloud_url: str, secret: str, zip_path: Path, force: bool = False) -> dict:
    with httpx.Client(timeout=600.0, verify=SSL_CTX) as client:
        with open(zip_path, "rb") as f:
            r = client.post(
                f"{cloud_url}/api/worker/backup/restore",
                params={"force": "true" if force else "false"},
                headers={"X-Worker-Secret": secret},
                files={"file": (zip_path.name, f, "application/zip")},
            )
    r.raise_for_status()
    return r.json()


def _get_meta(cloud_url: str, secret: str) -> dict:
    with httpx.Client(timeout=60.0, verify=SSL_CTX) as client:
        r = client.get(f"{cloud_url}/api/worker/backup/meta", headers={"X-Worker-Secret": secret})
        r.raise_for_status()
        return r.json()


def sync_cloud_backup(cloud_url: str, secret: str) -> None:
    try:
        cloud_url = cloud_url.rstrip("/")
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        state = load_backup_state()
        meta = _get_meta(cloud_url, secret)
        latest = _latest_backup(state)
        action = decide_sync_action(state, meta, latest is not None)

        if action == "empty":
            print("[Backup] cloud empty, no local backup yet", flush=True)
        elif action == "noop":
            pass
        elif action == "download":
            dest, manifest = _download_snapshot(cloud_url, secret, "snapshot")
            save_backup_state(
                {
                    "epoch": manifest.get("epoch") or meta["epoch"],
                    "logical_sha": manifest.get("logical_sha"),
                    "last_backup_file": dest.name,
                }
            )
            _prune_snapshots()
            print(f"[Backup] saved {dest.name} ({manifest.get('user_rows')} rows)", flush=True)
        elif action == "adopt":
            state.update({"epoch": meta["epoch"], "logical_sha": meta["logical_sha"]})
            save_backup_state(state)
            print("[Backup] cloud epoch changed but cloud empty and no backup to restore; adopted new epoch", flush=True)
        elif action == "restore":
            result = _post_restore(cloud_url, secret, latest, force=False)
            new_meta = _get_meta(cloud_url, secret)
            save_backup_state(
                {"epoch": new_meta["epoch"], "logical_sha": new_meta["logical_sha"], "last_backup_file": latest.name}
            )
            print(
                f"[Backup] !!! AUTO-RESTORED cloud from {latest.name} "
                f"(profiles={result.get('profiles')}, media={result.get('media_files')}) !!!",
                flush=True,
            )
        elif action == "conflict":
            dest, manifest = _download_snapshot(cloud_url, secret, "conflict")
            print(
                f"[Backup] WARNING: cloud was reset AND new data was added before the Mac reconnected. "
                f"NOT restoring. Previous backup: {latest.name if latest else 'none'}; "
                f"current cloud data saved as {dest.name}. Manual merge needed.",
                flush=True,
            )
            save_backup_state(
                {
                    "epoch": manifest.get("epoch") or meta["epoch"],
                    "logical_sha": manifest.get("logical_sha"),
                    "last_backup_file": dest.name,
                }
            )
    except Exception as exc:
        print(f"[Backup] sync error (will retry): {exc}", flush=True)


def build_seed_zip(src: Path) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS_DIR / f"seed_{_stamp()}.zip"
    with tempfile.TemporaryDirectory() as td:
        db_copy = Path(td) / "rishta.sqlite"
        s_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        d_conn = sqlite3.connect(str(db_copy))
        try:
            s_conn.backup(d_conn)
            row = d_conn.execute("SELECT value FROM instance_meta WHERE key='data_epoch'").fetchone() if d_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='instance_meta'"
            ).fetchone() else None
        finally:
            d_conn.close()
            s_conn.close()
        manifest = {"epoch": row[0] if row else "", "created_at": datetime.now(timezone.utc).isoformat()}
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "rishta.sqlite")
            backups_root = (LOCAL_MEDIA_DIR / "backups").resolve()
            if LOCAL_MEDIA_DIR.is_dir():
                for path in sorted(LOCAL_MEDIA_DIR.rglob("*")):
                    if not path.is_file():
                        continue
                    resolved = path.resolve()
                    if backups_root in resolved.parents:
                        continue
                    zf.write(path, f"media/{path.relative_to(LOCAL_MEDIA_DIR).as_posix()}")
            zf.writestr("manifest.json", json.dumps(manifest))
    return dest


def restore_from_path(cloud_url: str, secret: str, path: Path, force: bool) -> None:
    cloud_url = cloud_url.rstrip("/")
    if not path.is_file():
        sys.exit(f"--restore-from path not found: {path}")
    zip_path = build_seed_zip(path) if path.suffix.lower() in (".sqlite", ".db") else path
    result = _post_restore(cloud_url, secret, zip_path, force=force)
    print(f"[Restore] {result}", flush=True)
    save_backup_state({"epoch": result.get("epoch"), "logical_sha": "", "last_backup_file": zip_path.name})
    sync_cloud_backup(cloud_url, secret)


def process_queued_task(cloud_url: str, headers: dict, task: dict, existing_profiles: list[dict]) -> dict:
    payload = task.get("payload") or {}
    raw_text = payload.get("raw_text") or ""
    pdf_texts = list(payload.get("pdf_texts") or [])
    image_data_urls: list[str] = []
    audio_mp3_b64_list: list[str] = []
    media_ids = payload.get("media_asset_ids") or []

    target_profile_id = payload.get("target_profile_id") or payload.get("profile_id")
    existing_profile = next((p for p in existing_profiles if p["id"] == target_profile_id), None)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for mid in media_ids:
            if not mid:
                continue
            try:
                with httpx.Client(timeout=40.0, verify=SSL_CTX) as client:
                    r = client.get(f"{cloud_url}/api/worker/media/{mid}", headers=headers)
                    r.raise_for_status()
                    disp = r.headers.get("content-disposition", "")
                    ctype = (r.headers.get("content-type") or "").lower()
                    fname = f"asset_{mid}.bin"
                    if "filename=" in disp:
                        fname = disp.split("filename=")[-1].strip("\"' ;")
                    fpath = tmp_path / fname
                    fpath.write_bytes(r.content)

                    ext = fpath.suffix.lower()
                    if ext == ".pdf" or "pdf" in ctype:
                        pdf_res = process_pdf_biodata(fpath)
                        if pdf_res["text"] and pdf_res["text"] not in pdf_texts:
                            pdf_texts.append(pdf_res["text"])
                        image_data_urls.extend(pdf_res["page_images"])
                    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic") or "image" in ctype:
                        image_data_urls.append(image_bytes_to_data_url(r.content))
                    elif ext in (".opus", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".webm", ".amr") or "audio" in ctype:
                        mp3_b64 = transcode_audio_to_mp3_b64(fpath)
                        if mp3_b64:
                            audio_mp3_b64_list.append(mp3_b64)
            except Exception as exc:
                print(f"[Worker] Warning downloading media #{mid}: {exc}", flush=True)

    ai_bundle = extract_rishta_bundle(
        raw_text=raw_text,
        pdf_texts=pdf_texts,
        image_data_urls=image_data_urls,
        audio_mp3_b64_list=audio_mp3_b64_list,
        source_name=payload.get("source_name"),
        source_channel=payload.get("source_channel"),
        existing_profile=existing_profile,
        existing_profiles_catalog=existing_profiles,
    )
    return ai_bundle


def run_worker_loop(cloud_url: str) -> None:
    cloud_url = cloud_url.rstrip("/")
    hostname = socket.gethostname()
    headers = {
        "X-Worker-Secret": WORKER_SHARED_SECRET,
        "Content-Type": "application/json",
    }
    last_backup_at = 0.0

    print("============================================================", flush=True)
    print("  Rishta Dossier — Outbound-Only Zscaler Mac AI Worker", flush=True)
    print("  Listening Ports on Mac : ZERO (100% Outbound HTTPS Only)", flush=True)
    print(f"  Target Cloud Dashboard : {cloud_url}", flush=True)
    print(f"  Mac Hostname           : {hostname}", flush=True)
    print(f"  zllama Key Configured  : {'YES' if ZLLAMA_API_KEY else 'NO'}", flush=True)
    print("============================================================", flush=True)

    while True:
        if time.time() - last_backup_at >= BACKUP_INTERVAL_SECONDS:
            sync_cloud_backup(cloud_url, WORKER_SHARED_SECRET)
            last_backup_at = time.time()
        try:
            with httpx.Client(timeout=15.0, verify=SSL_CTX) as client:
                resp = client.post(
                    f"{cloud_url}/api/worker/poll",
                    headers=headers,
                    json={"hostname": hostname},
                )
                resp.raise_for_status()
                data = resp.json()

            task = data.get("task")
            if task:
                tid = task["id"]
                ttype = task["task_type"]
                print(f"[Worker] Picked up task #{tid} ({ttype}) — processing via zllama...", flush=True)
                ai_bundle = process_queued_task(
                    cloud_url, headers, task, data.get("existing_profiles") or []
                )
                with httpx.Client(timeout=30.0, verify=SSL_CTX) as client:
                    c_resp = client.post(
                        f"{cloud_url}/api/worker/tasks/{tid}/complete",
                        headers=headers,
                        json={"ai_bundle": ai_bundle},
                    )
                    c_resp.raise_for_status()
                print(
                    f"[Worker] Completed task #{tid} ({ai_bundle.get('models_used')}) "
                    f"[Multi-Candidate={ai_bundle.get('is_multi_candidate_list', False)}, "
                    f"Rows={len(ai_bundle.get('bulk_candidates') or [])}] ✓",
                    flush=True,
                )
                sync_cloud_backup(cloud_url, WORKER_SHARED_SECRET)
                last_backup_at = time.time()
                continue
        except KeyboardInterrupt:
            print("\n[Worker] Stopped by user.", flush=True)
            break
        except Exception as exc:
            print(f"[Worker] Poll check note: {exc}", flush=True)

        time.sleep(3.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbound-only Mac AI worker")
    parser.add_argument("cloud_url", nargs="?", default=None)
    parser.add_argument("--restore-from", metavar="PATH", help="restore cloud from a .sqlite or backup .zip, then exit")
    parser.add_argument("--force", action="store_true", help="overwrite cloud data on --restore-from")
    args = parser.parse_args()
    target_url = args.cloud_url or os.getenv("CLOUD_SERVER_URL") or "https://sister-rishta-dossier.onrender.com"
    if not WORKER_SHARED_SECRET:
        sys.exit("WORKER_SHARED_SECRET is not set in .env")
    if args.restore_from:
        restore_from_path(target_url, WORKER_SHARED_SECRET, Path(args.restore_from).expanduser().resolve(), args.force)
        return
    run_worker_loop(target_url)


if __name__ == "__main__":
    main()
