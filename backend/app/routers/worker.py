import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from ..auth import get_current_member
from ..config import WORKER_SHARED_SECRET, ZLLAMA_API_KEY
from ..db import get_app_settings, get_conn, utc_now
from ..models import PROFILE_EDITABLE_FIELDS
from ..services.ai_extractor import build_disambiguation_tag
from ..services.dedupe import find_duplicate_candidates

router = APIRouter(prefix="/api/worker", tags=["worker"])


def verify_worker_secret(x_worker_secret: Optional[str] = Header(default=None)) -> None:
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

    task_row = conn.execute(
        """
        SELECT * FROM worker_tasks
        WHERE status = 'pending'
        ORDER BY id ASC
        LIMIT 1
        """
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

    if task["task_type"] == "extract_import_job":
        job_id = task["target_id"]
        job_row = conn.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
        if job_row:
            old_ext = json.loads(job_row["extracted_json"] or "{}")
            merged_ext = {**old_ext, **ai_bundle, "pending_mac_ai": False}
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

            # If the user already applied the profile while offline, enrich the profile in-place too!
            if job_row["status"] == "applied" and target_pid:
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

    conn.execute(
        "UPDATE worker_tasks SET status = 'completed', result_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(ai_bundle), now, task_id),
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
