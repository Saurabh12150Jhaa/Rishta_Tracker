import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from ..auth import get_current_member
from ..db import get_conn, utc_now
from ..models import FamilyVoteRequest, FollowUpCreate, PROFILE_EDITABLE_FIELDS
from ..services.ai_extractor import build_disambiguation_tag, extract_rishta_bundle
from ..services.media_proc import save_uploaded_bytes, transcode_audio_to_mp3_b64

router = APIRouter(prefix="/api", tags=["interactions"])


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
    audio_mp3_b64_list: list[str] = []
    if audio_file and audio_file.filename:
        audio_bytes = await audio_file.read()
        if audio_bytes:
            aud_path, url_path = save_uploaded_bytes(audio_bytes, audio_file.filename, "voice")
            mp3_b64 = transcode_audio_to_mp3_b64(aud_path)
            if mp3_b64:
                audio_mp3_b64_list.append(mp3_b64)
            conn.execute(
                """
                INSERT INTO media_assets (
                    profile_id, asset_type, file_name, file_path, url_path,
                    mime_type, uploaded_by, created_at
                ) VALUES (?, 'voice_note', ?, ?, ?, 'audio/mpeg', ?, ?)
                """,
                (profile_id, audio_file.filename, str(aud_path), url_path, member["name"], now),
            )

    ai_result = None
    transcript = ""
    summary = raw_text[:280] if raw_text else title

    if run_ai_update and (raw_text.strip() or audio_mp3_b64_list):
        try:
            ai_result = extract_rishta_bundle(
                raw_text=raw_text,
                audio_mp3_b64_list=audio_mp3_b64_list,
                existing_profile=existing,
                source_name=existing.get("source_name"),
                source_channel=existing.get("source_channel"),
            )
            transcript = ai_result.get("voice_transcript") or ""
            summary = ai_result.get("interaction_summary") or summary

            updates = {}
            for k, v in (ai_result.get("extracted_fields") or {}).items():
                if k in PROFILE_EDITABLE_FIELDS and v not in (None, ""):
                    if k == "private_notes" and member["role"] != "owner":
                        continue
                    updates[k] = v

            if ai_result.get("suggested_status"):
                updates["status"] = ai_result["suggested_status"]
            if ai_result.get("suggested_ball_in_court"):
                updates["ball_in_court"] = ai_result["suggested_ball_in_court"]
            if ai_result.get("fit_summary"):
                updates["fit_summary"] = ai_result["fit_summary"]
            if ai_result.get("ai_fit_score") is not None:
                updates["ai_fit_score"] = ai_result["ai_fit_score"]
            if ai_result.get("pre_call_brief"):
                updates["pre_call_brief"] = ai_result["pre_call_brief"]
            if ai_result.get("positives"):
                updates["positives_json"] = json.dumps(ai_result["positives"])
            if ai_result.get("concerns"):
                updates["concerns_json"] = json.dumps(ai_result["concerns"])
            if ai_result.get("missing_questions"):
                updates["missing_questions_json"] = json.dumps(ai_result["missing_questions"])

            merged = {**existing, **updates}
            updates["disambiguation_tag"] = build_disambiguation_tag(merged)
            updates["updated_at"] = now

            set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
            conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), profile_id))

            sugg_fu = ai_result.get("suggested_follow_up")
            if sugg_fu and sugg_fu.get("task"):
                due_days = int(sugg_fu.get("due_days") or 2)
                due_date = (datetime.now(timezone.utc) + timedelta(days=due_days)).strftime("%Y-%m-%d")
                conn.execute(
                    """
                    INSERT INTO follow_ups (
                        profile_id, task, due_date, assigned_to, ball_in_court,
                        completed, created_by_member, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        profile_id,
                        sugg_fu["task"],
                        due_date,
                        sugg_fu.get("assigned_to") or member["name"],
                        ai_result.get("suggested_ball_in_court") or "us",
                        member["name"],
                        now,
                    ),
                )
        except Exception as exc:
            summary = f"{summary} (AI extraction skipped: {exc})"

    cur = conn.execute(
        """
        INSERT INTO interactions (
            profile_id, interaction_type, title, summary, raw_text, transcript,
            visibility, created_by_member, occurred_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            interaction_type,
            title,
            summary,
            raw_text,
            transcript,
            visibility,
            member["name"],
            now,
            now,
        ),
    )
    interaction_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "ok": True,
        "interaction_id": interaction_id,
        "summary": summary,
        "transcript": transcript,
        "ai_result": ai_result,
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
