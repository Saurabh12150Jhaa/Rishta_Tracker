import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..db import utc_now
from ..models import PROFILE_EDITABLE_FIELDS
from .ai_extractor import build_disambiguation_tag


def apply_interaction_ai_result(
    conn,
    profile_id: int,
    ai_result: dict,
    member_name: str,
    member_role: str,
    interaction_id: Optional[int] = None,
) -> bool:
    """Apply an AI extraction (call/voice-note update) onto a profile; overwrites fields the call mentioned.

    Returns False without changes when the result is an offline placeholder or was already applied.
    """
    if not ai_result or ai_result.get("pending_mac_ai"):
        return False

    now = utc_now()
    if interaction_id is not None:
        claimed = conn.execute(
            "UPDATE interactions SET ai_applied_at = ? WHERE id = ? AND ai_applied_at IS NULL",
            (now, interaction_id),
        )
        if claimed.rowcount == 0:
            return False

    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if p_row:
        existing = dict(p_row)
        updates = {}
        for k, v in (ai_result.get("extracted_fields") or {}).items():
            if k in PROFILE_EDITABLE_FIELDS and v not in (None, ""):
                if k == "private_notes" and member_role != "owner":
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
                    sugg_fu.get("assigned_to") or member_name,
                    ai_result.get("suggested_ball_in_court") or "us",
                    member_name,
                    now,
                ),
            )

    if interaction_id is not None:
        transcript = ai_result.get("voice_transcript") or ""
        summary = ai_result.get("interaction_summary") or ""
        if transcript:
            conn.execute("UPDATE interactions SET transcript = ? WHERE id = ?", (transcript, interaction_id))
        if summary:
            conn.execute("UPDATE interactions SET summary = ? WHERE id = ?", (summary, interaction_id))
    return True
