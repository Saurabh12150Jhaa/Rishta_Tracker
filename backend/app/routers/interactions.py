import mimetypes
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from ..auth import get_current_member
from ..config import ZLLAMA_API_KEY
from ..db import get_conn, utc_now
from ..models import FamilyVoteRequest, FollowUpCreate
from ..services.ai_extractor import extract_rishta_bundle
from ..services.interaction_ai import apply_interaction_ai_result
from ..services.media_proc import save_uploaded_bytes, transcode_audio_to_mp3_b64
from .worker import enqueue_worker_task, is_remote_mac_worker_online, wait_for_worker_task

router = APIRouter(prefix="/api", tags=["interactions"])

VOICE_PENDING_SUMMARY = "Voice note — transcription pending (Mac AI)"
INLINE_WAIT_SECONDS = 45


def _audio_mime_type(upload: UploadFile) -> str:
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    guessed, _ = mimetypes.guess_type(upload.filename or "")
    return guessed or "application/octet-stream"


def _local_extract(raw_text: str, audio_path, existing: dict) -> dict:
    audio_b64 = []
    if audio_path:
        mp3_b64 = transcode_audio_to_mp3_b64(audio_path)
        if mp3_b64:
            audio_b64.append(mp3_b64)
    return extract_rishta_bundle(
        raw_text=raw_text,
        audio_mp3_b64_list=audio_b64,
        existing_profile=existing,
        source_name=existing.get("source_name"),
        source_channel=existing.get("source_channel"),
    )


@router.post("/profiles/{profile_id}/interactions")
async def add_interaction(
    profile_id: int,
    interaction_type: str = Form(default="phone_call"),
    title: str = Form(default="Call / Meeting Update"),
    raw_text: str = Form(default=""),
    visibility: str = Form(default="shared"),
    run_ai_update: bool = Form(default=True),
    audio_file: Optional[UploadFile] = File(default=None),
    member: dict = Depends(get_current_member),
):
    conn = get_conn()
    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not p_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")
    existing = dict(p_row)

    if visibility == "owner_only" and member["role"] != "owner":
        visibility = "shared"

    now = utc_now()
    aud_path = None
    voice_asset_id: Optional[int] = None
    if audio_file and audio_file.filename:
        audio_bytes = await audio_file.read()
        if audio_bytes:
            aud_path, url_path = save_uploaded_bytes(audio_bytes, audio_file.filename, "voice")
            cur_m = conn.execute(
                """
                INSERT INTO media_assets (
                    profile_id, asset_type, file_name, file_path, url_path,
                    mime_type, uploaded_by, created_at
                ) VALUES (?, 'voice_note', ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    audio_file.filename,
                    str(aud_path),
                    url_path,
                    _audio_mime_type(audio_file),
                    member["name"],
                    now,
                ),
            )
            voice_asset_id = cur_m.lastrowid

    has_input = bool(raw_text.strip() or voice_asset_id)
    summary = raw_text[:280] if raw_text.strip() else (VOICE_PENDING_SUMMARY if voice_asset_id else title)

    cur = conn.execute(
        """
        INSERT INTO interactions (
            profile_id, interaction_type, title, summary, raw_text, transcript,
            visibility, created_by_member, occurred_at, created_at, has_voice
        ) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            interaction_type,
            title,
            summary,
            raw_text,
            visibility,
            member["name"],
            now,
            now,
            1 if voice_asset_id else 0,
        ),
    )
    interaction_id = cur.lastrowid
    conn.commit()

    ai_result = None
    ai_pending = False
    task_id: Optional[int] = None
    worker_online = False

    if run_ai_update and has_input:
        if ZLLAMA_API_KEY:
            conn.close()
            conn = None
            try:
                ai_result = await run_in_threadpool(_local_extract, raw_text, aud_path, existing)
            except Exception as exc:
                ai_result = None
                note = f"{summary} (AI extraction skipped: {exc})"
                conn = get_conn()
                conn.execute("UPDATE interactions SET summary = ? WHERE id = ?", (note, interaction_id))
                conn.commit()
                conn.close()
                conn = None
                summary = note
            if ai_result is not None and ai_result.get("pending_mac_ai"):
                ai_result = None
                ai_pending = True
            if conn is None:
                conn = get_conn()
        else:
            ai_pending = True

        if ai_result is not None:
            apply_interaction_ai_result(
                conn, profile_id, ai_result, member["name"], member["role"], interaction_id=interaction_id
            )
            conn.commit()
        elif ai_pending:
            conn.close()
            conn = None
            task_id = enqueue_worker_task(
                "update_profile_from_interaction",
                interaction_id,
                {
                    "interaction_id": interaction_id,
                    "target_profile_id": profile_id,
                    "raw_text": raw_text,
                    "media_asset_ids": [voice_asset_id] if voice_asset_id else [],
                    "source_name": existing.get("source_name"),
                    "source_channel": existing.get("source_channel"),
                },
            )
            worker_online, _, _ = is_remote_mac_worker_online()
            if worker_online:
                live_res = await run_in_threadpool(wait_for_worker_task, task_id, INLINE_WAIT_SECONDS)
                if live_res:
                    conn = get_conn()
                    apply_interaction_ai_result(
                        conn, profile_id, live_res, member["name"], member["role"], interaction_id=interaction_id
                    )
                    conn.commit()
                    conn.close()
                    conn = None
                    ai_pending = False
            conn = get_conn()

    row = conn.execute(
        "SELECT summary, transcript, ai_applied_at FROM interactions WHERE id = ?", (interaction_id,)
    ).fetchone()
    conn.close()
    if row and row["ai_applied_at"]:
        ai_pending = False
    return {
        "ok": True,
        "interaction_id": interaction_id,
        "summary": row["summary"] if row else summary,
        "transcript": row["transcript"] if row else "",
        "ai_result": ai_result,
        "ai_pending": ai_pending,
        "task_id": task_id,
        "worker_online": worker_online,
    }


@router.post("/profiles/{profile_id}/votes")
def cast_family_vote(profile_id: int, req: FamilyVoteRequest, member: dict = Depends(get_current_member)):
    conn = get_conn()
    now = utc_now()
    conn.execute(
        """
        INSERT INTO family_votes (profile_id, member_name, member_role, vote, comment, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(profile_id, member_name) DO UPDATE SET
            vote = excluded.vote,
            comment = excluded.comment,
            updated_at = excluded.updated_at
        """,
        (profile_id, member["name"], member["role"], req.vote, req.comment, now),
    )
    conn.execute("UPDATE profiles SET updated_at = ? WHERE id = ?", (now, profile_id))
    conn.commit()
    rows = conn.execute("SELECT * FROM family_votes WHERE profile_id = ? ORDER BY updated_at DESC", (profile_id,)).fetchall()
    conn.close()
    return {"votes": [dict(r) for r in rows]}


@router.post("/profiles/{profile_id}/follow-ups")
def create_follow_up(profile_id: int, req: FollowUpCreate, member: dict = Depends(get_current_member)):
    conn = get_conn()
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO follow_ups (
            profile_id, task, due_date, assigned_to, ball_in_court,
            completed, created_by_member, created_at
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            profile_id,
            req.task.strip(),
            req.due_date,
            req.assigned_to or member["name"],
            req.ball_in_court or "us",
            member["name"],
            now,
        ),
    )
    fid = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM follow_ups WHERE id = ?", (fid,)).fetchone()
    conn.close()
    return dict(row)


@router.patch("/follow-ups/{follow_up_id}")
def toggle_follow_up(follow_up_id: int, completed: bool = True, member: dict = Depends(get_current_member)):
    conn = get_conn()
    conn.execute("UPDATE follow_ups SET completed = ? WHERE id = ?", (1 if completed else 0, follow_up_id))
    conn.commit()
    conn.close()
    return {"ok": True, "id": follow_up_id, "completed": completed}
