import hmac
import json
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from ..auth import get_current_member
from ..config import WORKER_SHARED_SECRET, ZLLAMA_API_KEY
from ..db import count_user_rows, get_app_settings, get_conn, utc_now
from ..models import PROFILE_EDITABLE_FIELDS
from ..services.ai_extractor import build_disambiguation_tag
from ..services import github_backup
from ..services.dedupe import find_duplicate_candidates
from ..services.matrimony_links import apply_matrimony_reference
from ..services.interaction_ai import apply_interaction_ai_result
from ..services.snapshot import SnapshotError, backup_meta, build_snapshot_zip, restore_snapshot_zip

router = APIRouter(prefix="/api/worker", tags=["worker"])


def verify_worker_secret(x_worker_secret: Optional[str] = Header(default=None)) -> None:
    if not WORKER_SHARED_SECRET:
        raise HTTPException(status_code=503, detail="worker secret not configured")
    if not x_worker_secret or not hmac.compare_digest(x_worker_secret.strip(), WORKER_SHARED_SECRET):
        raise HTTPException(status_code=401, detail="Invalid X-Worker-Secret header")


def is_remote_mac_worker_online(max_age_seconds: float = 20.0) -> tuple[bool, Optional[str], Optional[str]]:
    conn = get_conn()
    row = conn.execute("SELECT last_heartbeat_at, worker_hostname FROM worker_state WHERE id = 1").fetchone()
    conn.close()
    if not row or not row["last_heartbeat_at"]:
        return False, None, None
    try:
        hb_dt = datetime.fromisoformat(row["last_heartbeat_at"])
        now_dt = datetime.now(timezone.utc)
        age = (now_dt - hb_dt).total_seconds()
        return (age <= max_age_seconds), row["last_heartbeat_at"], row["worker_hostname"]
    except Exception:
        return False, row["last_heartbeat_at"], row["worker_hostname"]


def enqueue_worker_task(task_type: str, target_id: int, payload: dict[str, Any]) -> int:
    conn = get_conn()
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO worker_tasks (task_type, target_id, status, payload_json, created_at, updated_at)
        VALUES (?, ?, 'pending', ?, ?, ?)
        """,
        (task_type, target_id, json.dumps(payload), now, now),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def wait_for_worker_task(task_id: int, timeout_seconds: float = 18.0) -> Optional[dict]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        conn = get_conn()
        row = conn.execute(
            "SELECT status, result_json FROM worker_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        conn.close()
        if row and row["status"] == "completed" and row["result_json"]:
            try:
                return json.loads(row["result_json"])
            except Exception:
                return None
        if row and row["status"] == "failed":
            return None
        time.sleep(0.45)
    return None


@router.get("/status")
def get_worker_status(member: dict = Depends(get_current_member)):
    remote_online, last_hb, hostname = is_remote_mac_worker_online()
    local_ai = bool(ZLLAMA_API_KEY)
    conn = get_conn()
    pending_rows = conn.execute(
        "SELECT id, task_type, target_id, status, created_at FROM worker_tasks WHERE status IN ('pending', 'processing') ORDER BY id ASC"
    ).fetchall()
    conn.close()

    return {
        "ai_ready": local_ai or remote_online,
        "mode": "local_mac" if local_ai else ("remote_mac_worker_online" if remote_online else "offline_fallback_queue"),
        "local_zllama_configured": local_ai,
        "remote_mac_worker_online": remote_online,
        "last_heartbeat_at": last_hb,
        "worker_hostname": hostname,
        "pending_tasks_count": len(pending_rows),
        "pending_tasks": [dict(r) for r in pending_rows],
        "cloud_backup": github_backup.get_state(),
    }


@router.post("/poll")
def poll_next_worker_task(
    payload: dict[str, Any],
    _auth: None = Depends(verify_worker_secret),
):
    hostname = (payload.get("hostname") or "Zscaler-Mac").strip()
    now = utc_now()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO worker_state (id, last_heartbeat_at, worker_hostname, worker_mode)
        VALUES (1, ?, ?, 'outbound_poller')
        ON CONFLICT(id) DO UPDATE SET
            last_heartbeat_at = excluded.last_heartbeat_at,
            worker_hostname = excluded.worker_hostname
        """,
        (now, hostname),
    )

    stale_cutoff = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    task_row = conn.execute(
        """
        SELECT * FROM worker_tasks
        WHERE status = 'pending' OR (status = 'processing' AND updated_at < ?)
        ORDER BY id ASC
        LIMIT 1
        """,
        (stale_cutoff,),
    ).fetchone()

    if not task_row:
        conn.commit()
        conn.close()
        return {"task": None, "settings": get_app_settings()}

    task = dict(task_row)
    conn.execute(
        "UPDATE worker_tasks SET status = 'processing', updated_at = ? WHERE id = ?",
        (now, task["id"]),
    )
    conn.commit()

    try:
        task_payload = json.loads(task.get("payload_json") or "{}")
    except Exception:
        task_payload = {}

    existing_profiles = [
        dict(r)
        for r in conn.execute(
            "SELECT id, full_name, age, dob, current_city, hometown, company, occupation, education, gotra, father_details, source_name, primary_contact_phone, candidate_phone, status FROM profiles"
        ).fetchall()
    ]
    conn.close()

    return {
        "task": {
            "id": task["id"],
            "task_type": task["task_type"],
            "target_id": task["target_id"],
            "payload": task_payload,
        },
        "settings": get_app_settings(),
        "existing_profiles": existing_profiles,
    }


@router.get("/media/{media_id}")
def worker_download_media(
    media_id: int,
    _auth: None = Depends(verify_worker_secret),
):
    conn = get_conn()
    row = conn.execute("SELECT * FROM media_assets WHERE id = ?", (media_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Media asset not found")
    fp = Path(row["file_path"])
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="Media file missing on disk")
    return FileResponse(str(fp), filename=row["file_name"])


@router.post("/tasks/{task_id}/complete")
def complete_worker_task(
    task_id: int,
    payload: dict[str, Any],
    _auth: None = Depends(verify_worker_secret),
):
    conn = get_conn()
    task_row = conn.execute("SELECT * FROM worker_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Worker task not found")

    task = dict(task_row)
    now = utc_now()
    ai_bundle = payload.get("ai_bundle") or {}
    final_status = "completed"
    task_error = None

    if task["task_type"] == "extract_import_job":
        job_id = task["target_id"]
        job_row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
        if job_row:
            old_ext = json.loads(job_row["extracted_json"] or "{}")
            merged_ext = {**old_ext, **ai_bundle, "pending_mac_ai": False}
            merged_fields = dict(merged_ext.get("extracted_fields") or {})
            for key in ("external_platform", "external_profile_id", "external_profile_url"):
                if not merged_fields.get(key) and (old_ext.get("extracted_fields") or {}).get(key):
                    merged_fields[key] = old_ext["extracted_fields"][key]
            apply_matrimony_reference(merged_fields, job_row["raw_text"])
            merged_ext["extracted_fields"] = merged_fields
            duplicates = find_duplicate_candidates(
                merged_ext.get("extracted_fields") or {},
                candidate_embedding=merged_ext.get("embedding"),
                exclude_profile_id=job_row["target_profile_id"],
            )
            merged_ext["duplicate_matches"] = duplicates
            target_pid = job_row["target_profile_id"]
            if not target_pid and duplicates and duplicates[0]["confidence"] >= 0.72:
                target_pid = duplicates[0]["profile_id"]
                merged_ext["ai_auto_link_reason"] = (
                    f"Mac AI Auto-Linked to Existing Profile #{target_pid} ({duplicates[0]['full_name']})"
                )

            conn.execute(
                "UPDATE import_jobs SET extracted_json = ?, voice_transcript = ?, target_profile_id = ?, status = CASE WHEN status='pending_mac_ai' THEN 'pending_review' ELSE status END WHERE id = ?",
                (
                    json.dumps(merged_ext),
                    merged_ext.get("voice_transcript") or job_row["voice_transcript"] or "",
                    target_pid,
                    job_id,
                ),
            )

            # If the user already applied the profile while offline, enrich or expand bulk profiles in-place!
            if job_row["status"] == "applied":
                bulk_cands = merged_ext.get("bulk_candidates") or []
                if isinstance(bulk_cands, list) and len(bulk_cands) >= 2:
                    if target_pid:
                        p_check = conn.execute("SELECT full_name FROM profiles WHERE id = ?", (target_pid,)).fetchone()
                        if p_check and (
                            "Diary / Register Batch" in (p_check["full_name"] or "")
                            or "Unnamed" in (p_check["full_name"] or "")
                            or "Candidate" in (p_check["full_name"] or "")
                        ):
                            conn.execute("DELETE FROM profiles WHERE id = ?", (target_pid,))
                    _expand_bulk_candidates_in_db(conn, bulk_cands, job_row["created_by_member"] or "Saurabh", now)
                elif target_pid:
                    _enrich_profile_from_ai_bundle(conn, target_pid, merged_ext, now)

    elif task["task_type"] == "transcribe_meeting_recording":
        meeting_id = task["target_id"]
        m_row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if m_row:
            transcript = ai_bundle.get("voice_transcript") or ""
            ai_summary = ai_bundle.get("interaction_summary") or ai_bundle.get("fit_summary") or ""
            conn.execute(
                "UPDATE meetings SET call_transcript = ?, ai_call_summary = ?, updated_at = ? WHERE id = ?",
                (transcript, ai_summary, now, meeting_id),
            )
            _enrich_profile_from_ai_bundle(conn, m_row["profile_id"], ai_bundle, now)

    elif task["task_type"] == "refresh_profile_ai":
        profile_id = task["target_id"]
        _enrich_profile_from_ai_bundle(conn, profile_id, ai_bundle, now)

    elif task["task_type"] == "update_profile_from_interaction":
        i_row = conn.execute("SELECT * FROM interactions WHERE id = ?", (task["target_id"],)).fetchone()
        if i_row and ai_bundle.get("pending_mac_ai"):
            final_status = "failed"
            task_error = "Worker could not run AI (offline fallback result); nothing applied"
        elif i_row:
            m_row = conn.execute(
                "SELECT role FROM members WHERE name = ?", (i_row["created_by_member"],)
            ).fetchone()
            apply_interaction_ai_result(
                conn,
                i_row["profile_id"],
                ai_bundle,
                i_row["created_by_member"],
                m_row["role"] if m_row else "family",
                interaction_id=i_row["id"],
            )

    conn.execute(
        "UPDATE worker_tasks SET status = ?, result_json = ?, error_text = ?, updated_at = ? WHERE id = ?",
        (final_status, json.dumps(ai_bundle), task_error, now, task_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


def _enrich_profile_from_ai_bundle(conn, profile_id: int, ai_bundle: dict, now: str) -> None:
    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not p_row:
        return
    existing = dict(p_row)
    updates = {}
    for k, v in (ai_bundle.get("extracted_fields") or {}).items():
        if k in PROFILE_EDITABLE_FIELDS and v not in (None, "") and not existing.get(k):
            updates[k] = v
    if ai_bundle.get("ai_fit_score") is not None:
        updates["ai_fit_score"] = ai_bundle["ai_fit_score"]
    if ai_bundle.get("fit_summary"):
        updates["fit_summary"] = ai_bundle["fit_summary"]
    if ai_bundle.get("pre_call_brief"):
        updates["pre_call_brief"] = ai_bundle["pre_call_brief"]
    if ai_bundle.get("positives"):
        updates["positives_json"] = json.dumps(ai_bundle["positives"])
    if ai_bundle.get("concerns"):
        updates["concerns_json"] = json.dumps(ai_bundle["concerns"])
    if ai_bundle.get("missing_questions"):
        updates["missing_questions_json"] = json.dumps(ai_bundle["missing_questions"])
    if ai_bundle.get("embedding"):
        updates["embedding_json"] = json.dumps(ai_bundle["embedding"])

    merged = {**existing, **updates}
    updates["disambiguation_tag"] = build_disambiguation_tag(merged)
    updates["updated_at"] = now
    set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
    conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), profile_id))


def _expand_bulk_candidates_in_db(conn, bulk_rows: list[dict], member_name: str, now: str) -> None:
    for r in bulk_rows:
        if not r.get("selected", True):
            continue
        fields = dict(r.get("fields") or {})
        name = (fields.get("full_name") or "").strip()
        if not name:
            continue

        matched_id = r.get("matched_profile_id")
        if matched_id:
            ex_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (matched_id,)).fetchone()
            if ex_row:
                ex = dict(ex_row)
                updates = {
                    k: v
                    for k, v in fields.items()
                    if k in PROFILE_EDITABLE_FIELDS and v not in (None, "") and not ex.get(k)
                }
                merged = {**ex, **updates}
                updates["disambiguation_tag"] = build_disambiguation_tag(merged)
                updates["updated_at"] = now
                set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
                conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), matched_id))
                continue

        insert_data = {
            col: fields.get(col)
            for col in PROFILE_EDITABLE_FIELDS
            if fields.get(col) not in (None, "")
        }
        insert_data["full_name"] = name
        insert_data["gender"] = insert_data.get("gender") or "Male"
        insert_data["status"] = insert_data.get("status") or ("Passed" if r.get("is_crossed_out") else "New")
        insert_data["ball_in_court"] = insert_data.get("ball_in_court") or ("closed" if r.get("is_crossed_out") else "us")
        if r.get("is_crossed_out") and not insert_data.get("pass_reason"):
            insert_data["pass_reason"] = "Crossed out in family diary register"
        insert_data["source_name"] = insert_data.get("source_name") or "Family Diary Register"
        insert_data["source_channel"] = insert_data.get("source_channel") or "Relative"
        insert_data["disambiguation_tag"] = build_disambiguation_tag(insert_data)
        insert_data["fit_summary"] = f"Extracted ({r.get('extraction_confidence', 92)}% OCR confidence): {r.get('raw_row_notes') or insert_data['disambiguation_tag']}"
        insert_data["ai_fit_score"] = 45 if r.get("is_crossed_out") else 78
        insert_data["positives_json"] = json.dumps(
            [x for x in [insert_data.get("occupation"), insert_data.get("current_city"), insert_data.get("siblings_details")] if x]
        )
        insert_data["concerns_json"] = json.dumps(r.get("verification_warnings") or [])
        insert_data["missing_questions_json"] = json.dumps(
            ["Ask for full Biodata PDF & Kundli birth details (DOB/TOB/POB)"]
        )
        insert_data["created_by_member"] = member_name
        insert_data["created_at"] = now
        insert_data["updated_at"] = now

        cols = list(insert_data.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(insert_data[c] for c in cols),
        )



MAX_RESTORE_BYTES = 200 * 1024 * 1024


@router.get("/backup/meta")
def worker_backup_meta(_auth: None = Depends(verify_worker_secret)):
    return backup_meta()


@router.get("/backup/snapshot")
def worker_backup_snapshot(_auth: None = Depends(verify_worker_secret)):
    tmp_dir = tempfile.mkdtemp(prefix="rishta_snap_")
    try:
        zip_path, manifest = build_snapshot_zip(Path(tmp_dir))
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename="rishta_snapshot.zip",
        headers={"X-Data-Epoch": manifest["epoch"], "X-Logical-Sha": manifest["logical_sha"]},
        background=BackgroundTask(shutil.rmtree, tmp_dir, True),
    )


@router.post("/backup/restore")
def worker_backup_restore(
    file: UploadFile = File(...),
    force: bool = Query(default=False),
    _auth: None = Depends(verify_worker_secret),
):
    if count_user_rows() > 0 and not force:
        raise HTTPException(status_code=409, detail="Cloud database already has data; use force=true to overwrite")

    tmp_dir = Path(tempfile.mkdtemp(prefix="rishta_upload_"))
    try:
        zip_path = tmp_dir / "upload.zip"
        size = 0
        with open(zip_path, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESTORE_BYTES:
                    raise HTTPException(status_code=413, detail="Backup too large (max 200MB)")
                out.write(chunk)
        try:
            return restore_snapshot_zip(zip_path, force=force)
        except SnapshotError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
