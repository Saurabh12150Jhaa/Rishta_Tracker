import asyncio
import json
import subprocess
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from ..auth import get_current_member
from ..config import MODEL_PRESETS
from ..db import get_app_settings, get_conn, utc_now
from ..models import PROFILE_EDITABLE_FIELDS
from ..services.ai_extractor import (
    _call_zllama_chat,
    build_disambiguation_tag,
    extract_rishta_bundle,
    get_active_preset_config,
)
from ..services.dedupe import normalize_phone
from ..services.media_proc import save_uploaded_bytes, transcode_audio_to_mp3_b64
from ..services.offline_extractor import offline_quick_parse_meeting
from .worker import enqueue_worker_task, is_remote_mac_worker_online, wait_for_worker_task

router = APIRouter(prefix="/api", tags=["meetings"])


def _send_ntfy_alert(topic: str, title: str, message: str, click_url: str = "") -> bool:
    if not topic or not topic.strip():
        return False
    headers = {
        "Title": title[:100],
        "Priority": "high",
        "Tags": "calendar,telephone_receiver",
    }
    if click_url:
        headers["Click"] = click_url
    try:
        with httpx.Client(timeout=6.0) as client:
            resp = client.post(
                f"https://ntfy.sh/{topic.strip()}",
                content=message.encode("utf-8"),
                headers=headers,
            )
            return resp.status_code < 300
    except Exception:
        return False


def _send_macos_notification(title: str, message: str) -> None:
    try:
        safe_t = title.replace('"', "'")
        safe_m = message.replace('"', "'")
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_m}" with title "{safe_t}" sound name "Glass"'],
            capture_output=True,
            timeout=3,
        )
    except Exception:
        pass


def dispatch_two_phone_reminder(meeting: dict, profile: dict, is_test: bool = False) -> dict:
    settings = get_app_settings()
    devices = settings.get("alert_devices") or {}

    cand_name = profile.get("full_name") or "Candidate"
    when_str = (meeting.get("scheduled_at") or "Upcoming").replace("T", " at ")
    mtype = meeting.get("meeting_type") or "Call / Meeting"
    agenda = meeting.get("pre_meeting_notes") or profile.get("pre_call_brief") or "Review dossier before call"

    title = f"{'[TEST] ' if is_test else ''}Rishta Reminder: {mtype} with {cand_name}"
    body = (
        f"Scheduled: {when_str}\n"
        f"Participants: {meeting.get('participants') or 'Family'}\n"
        f"Location/Mode: {meeting.get('location_or_link') or mtype}\n"
        f"Pre-Call Points: {agenda[:240]}"
    )

    sent_channels = []
    if meeting.get("notify_phone_1", 1) and devices.get("phone_1_ntfy_topic"):
        ok1 = _send_ntfy_alert(devices["phone_1_ntfy_topic"], title, body)
        if ok1:
            sent_channels.append(f"Phone 1 Push ({devices.get('phone_1_name', 'Phone 1')})")

    if meeting.get("notify_phone_2", 1) and devices.get("phone_2_ntfy_topic"):
        ok2 = _send_ntfy_alert(devices["phone_2_ntfy_topic"], title, body)
        if ok2:
            sent_channels.append(f"Phone 2 Push ({devices.get('phone_2_name', 'Phone 2')})")

    _send_macos_notification(title, f"{when_str} — {cand_name}")
    sent_channels.append("Mac Desktop Notification")

    wa_text = (
        f"🔔 *Meeting / Call Reminder*\n"
        f"• *Candidate:* {cand_name} ({profile.get('disambiguation_tag') or ''})\n"
        f"• *Type:* {mtype}\n"
        f"• *When:* {when_str}\n"
        f"• *Participants:* {meeting.get('participants') or 'Family'}\n"
        f"• *Pre-Call Talking Points:* {agenda}"
    )

    p1_digits = normalize_phone(devices.get("phone_1_whatsapp"))
    p2_digits = normalize_phone(devices.get("phone_2_whatsapp"))

    return {
        "sent_channels": sent_channels,
        "whatsapp_reminder_text": wa_text,
        "phone_1_wa_url": f"https://wa.me/91{p1_digits}?text={urllib.parse.quote(wa_text)}"
        if len(p1_digits) == 10
        else f"https://wa.me/?text={urllib.parse.quote(wa_text)}",
        "phone_2_wa_url": f"https://wa.me/91{p2_digits}?text={urllib.parse.quote(wa_text)}"
        if len(p2_digits) == 10
        else f"https://wa.me/?text={urllib.parse.quote(wa_text)}",
    }


def _enrich_meeting(m: dict, p: dict) -> dict:
    settings = get_app_settings()
    devices = settings.get("alert_devices") or {}
    cand_name = p.get("full_name") or "Candidate"
    out = dict(m)
    out["candidate_name"] = cand_name
    out["disambiguation_tag"] = p.get("disambiguation_tag")

    # Stage 1 (Before Schedule): WhatsApp Slot Proposal Text
    slots = m.get("proposed_slots_text") or "this weekend (Saturday or Sunday evening)"
    parent_name = p.get("primary_contact_name") or "ji"
    out["whatsapp_slot_proposal_text"] = (
        f"Namaste {parent_name}! 🙏\n"
        f"We would love to schedule a {m.get('meeting_type') or 'phone call'} regarding {cand_name}. "
        f"Would {slots} work for your family? Please let us know what time suits you best."
    )

    # Stage 2 (After Schedule): Google Calendar 2-Phone Invite Link & WhatsApp Confirmation
    sched = m.get("scheduled_at")
    if sched:
        try:
            dt_start = datetime.fromisoformat(sched)
        except Exception:
            dt_start = datetime.now() + timedelta(days=1)
        dt_end = dt_start + timedelta(minutes=45)
        gcal_dates = f"{dt_start.strftime('%Y%m%dT%H%M00')}/{dt_end.strftime('%Y%m%dT%H%M00')}"
        guests = ",".join(
            e.strip()
            for e in [devices.get("phone_1_email") or "", devices.get("phone_2_email") or ""]
            if e and "@" in e
        )
        details = (
            f"Candidate: {cand_name} ({p.get('disambiguation_tag') or ''})\n"
            f"Participants: {m.get('participants') or ''}\n"
            f"Pre-Call Talking Points: {m.get('pre_meeting_notes') or p.get('pre_call_brief') or ''}"
        )
        gcal_params = {
            "action": "TEMPLATE",
            "text": f"Rishta {m.get('meeting_type')}: {cand_name}",
            "dates": gcal_dates,
            "details": details,
            "location": m.get("location_or_link") or "Phone / Video Call",
        }
        if guests:
            gcal_params["add"] = guests
        out["google_calendar_url"] = f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(gcal_params)}"
    else:
        out["google_calendar_url"] = None

    out["ics_download_url"] = f"/api/meetings/{m['id']}/calendar.ics"
    return out


async def background_reminder_loop():
    """Polls every 45 seconds for upcoming scheduled meetings and alerts Phone 1 & Phone 2."""
    while True:
        try:
            conn = get_conn()
            rows = conn.execute(
                "SELECT * FROM meetings WHERE stage = 'scheduled' AND reminder_sent = 0 AND scheduled_at IS NOT NULL"
            ).fetchall()
            now_local = datetime.now()
            for r in rows:
                m = dict(r)
                try:
                    sched_dt = datetime.fromisoformat(m["scheduled_at"])
                    if sched_dt.tzinfo is not None:
                        sched_dt = sched_dt.astimezone().replace(tzinfo=None)
                    lead_mins = int(m.get("reminder_minutes") or 30)
                    trigger_dt = sched_dt - timedelta(minutes=lead_mins)
                    if trigger_dt <= now_local <= sched_dt + timedelta(minutes=30):
                        p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (m["profile_id"],)).fetchone()
                        if p_row:
                            dispatch_two_phone_reminder(m, dict(p_row), is_test=False)
                        conn.execute("UPDATE meetings SET reminder_sent = 1 WHERE id = ?", (m["id"],))
                        conn.commit()
                except Exception:
                    continue
            conn.close()
        except Exception:
            pass
        await asyncio.sleep(45)


@router.post("/meetings/quick-parse")
def quick_parse_meeting_text(payload: dict, member: dict = Depends(get_current_member)):
    raw_text = (payload.get("text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Provide meeting description text.")

    preset = get_active_preset_config()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    prompt = f"""Current local time on Mac: {now_str}.
Parse the user's natural-language meeting/call note into structured fields for a family rishta tracker.
User input: {raw_text!r}

Return JSON with exact keys:
{{
  "stage": "proposing | scheduled",
  "meeting_type": "Family Phone Call | 1:1 Prospect Call | Video Call | In-Person Meetup",
  "title": "Short descriptive title",
  "proposed_slots_text": "Human-readable proposed slots if not yet fixed, or empty string",
  "scheduled_at": "YYYY-MM-DDTHH:MM if a specific date/time was stated, else null",
  "location_or_link": "Phone / Zoom / Cafe name if mentioned, else empty string",
  "participants": "Who will join (e.g. Saurabh, Mummy & Prospect's Father)",
  "pre_meeting_notes": "Topics/questions to cover on the call"
}}
"""
    try:
        res, model_used = _call_zllama_chat(
            preset["batch_triage_chain"],
            [{"role": "user", "content": prompt}],
            expect_json=True,
            timeout=25.0,
        )
        if isinstance(res, dict):
            res["model_used"] = model_used
            return res
    except Exception:
        return offline_quick_parse_meeting(raw_text)
    return offline_quick_parse_meeting(raw_text)


@router.get("/meetings")
def list_all_meetings(profile_id: Optional[int] = None, member: dict = Depends(get_current_member)):
    conn = get_conn()
    if profile_id:
        rows = conn.execute(
            "SELECT * FROM meetings WHERE profile_id = ? ORDER BY COALESCE(scheduled_at, created_at) DESC",
            (profile_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM meetings ORDER BY CASE WHEN stage='scheduled' THEN 0 WHEN stage='proposing' THEN 1 ELSE 2 END, COALESCE(scheduled_at, created_at) ASC"
        ).fetchall()

    prof_rows = conn.execute("SELECT * FROM profiles").fetchall()
    prof_map = {r["id"]: dict(r) for r in prof_rows}
    conn.close()

    out = []
    for r in rows:
        p = prof_map.get(r["profile_id"], {})
        out.append(_enrich_meeting(dict(r), p))
    return {"meetings": out}


@router.post("/profiles/{profile_id}/meetings")
def create_meeting(profile_id: int, payload: dict, member: dict = Depends(get_current_member)):
    conn = get_conn()
    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not p_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = dict(p_row)

    settings = get_app_settings()
    default_rem = settings.get("alert_devices", {}).get("default_reminder_minutes_before", 30)

    stage = payload.get("stage") or ("scheduled" if payload.get("scheduled_at") else "proposing")
    meeting_type = payload.get("meeting_type") or "Family Phone Call"
    title = payload.get("title") or f"{meeting_type} — {profile.get('full_name')}"
    proposed_slots_text = payload.get("proposed_slots_text") or ""
    scheduled_at = payload.get("scheduled_at") or None
    location_or_link = payload.get("location_or_link") or ""
    participants = payload.get("participants") or "Saurabh, Mummy & Prospect Family"
    pre_meeting_notes = payload.get("pre_meeting_notes") or ""
    reminder_minutes = int(payload.get("reminder_minutes") or default_rem)
    notify_phone_1 = 1 if payload.get("notify_phone_1", True) else 0
    notify_phone_2 = 1 if payload.get("notify_phone_2", True) else 0

    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO meetings (
            profile_id, stage, meeting_type, title, proposed_slots_text,
            scheduled_at, location_or_link, participants, pre_meeting_notes,
            reminder_minutes, notify_phone_1, notify_phone_2, reminder_sent,
            created_by_member, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            profile_id,
            stage,
            meeting_type,
            title,
            proposed_slots_text,
            scheduled_at,
            location_or_link,
            participants,
            pre_meeting_notes,
            reminder_minutes,
            notify_phone_1,
            notify_phone_2,
            member["name"],
            now,
            now,
        ),
    )
    mid = cur.lastrowid

    if stage == "scheduled":
        next_status = "Meetup" if "Meetup" in meeting_type else "Talking"
        conn.execute(
            "UPDATE profiles SET status = CASE WHEN status IN ('New', 'Reviewing', 'Info Needed') THEN ? ELSE status END, updated_at = ? WHERE id = ?",
            (next_status, now, profile_id),
        )

    conn.commit()
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (mid,)).fetchone()
    conn.close()

    enriched = _enrich_meeting(dict(row), profile)
    if stage == "scheduled" and payload.get("send_immediate_alert", True):
        enriched["alert_dispatch"] = dispatch_two_phone_reminder(dict(row), profile, is_test=False)
    return enriched


@router.patch("/meetings/{meeting_id}")
def update_meeting(meeting_id: int, payload: dict, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Meeting not found")
    existing = dict(row)

    allowed = [
        "stage",
        "meeting_type",
        "title",
        "proposed_slots_text",
        "scheduled_at",
        "location_or_link",
        "participants",
        "pre_meeting_notes",
        "reminder_minutes",
        "notify_phone_1",
        "notify_phone_2",
        "post_meeting_notes",
    ]
    updates = {k: payload[k] for k in allowed if k in payload}
    if "scheduled_at" in updates and updates["scheduled_at"] != existing.get("scheduled_at"):
        updates["reminder_sent"] = 0
        if "stage" not in updates and updates["scheduled_at"]:
            updates["stage"] = "scheduled"

    updates["updated_at"] = utc_now()
    set_sql = ", ".join(f"{k} = ?" for k in updates.keys())
    conn.execute(f"UPDATE meetings SET {set_sql} WHERE id = ?", (*updates.values(), meeting_id))
    conn.commit()

    updated = dict(conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone())
    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (updated["profile_id"],)).fetchone()
    conn.close()
    return _enrich_meeting(updated, dict(p_row) if p_row else {})


@router.post("/meetings/{meeting_id}/send-reminder")
def trigger_meeting_reminder_now(meeting_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Meeting not found")
    m = dict(row)
    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (m["profile_id"],)).fetchone()
    conn.close()
    res = dispatch_two_phone_reminder(m, dict(p_row) if p_row else {}, is_test=False)
    return {"ok": True, **res}


@router.post("/meetings/test-phone-alerts")
def test_two_phone_alerts(member: dict = Depends(get_current_member)):
    dummy_meeting = {
        "meeting_type": "Family Phone Call",
        "scheduled_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "participants": "Saurabh & Mummy",
        "location_or_link": "Phone Call",
        "pre_meeting_notes": "Test alert from Rishta Dossier! Both phones are configured for meeting reminders.",
        "notify_phone_1": 1,
        "notify_phone_2": 1,
    }
    dummy_profile = {"full_name": "Sample Groom Family", "disambiguation_tag": "Test Verification"}
    res = dispatch_two_phone_reminder(dummy_meeting, dummy_profile, is_test=True)
    return {"ok": True, **res}


@router.get("/meetings/{meeting_id}/calendar.ics")
def download_meeting_ics(meeting_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Meeting not found")
    m = dict(row)
    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (m["profile_id"],)).fetchone()
    conn.close()
    p = dict(p_row) if p_row else {}

    sched = m.get("scheduled_at")
    try:
        dt_start = datetime.fromisoformat(sched) if sched else (datetime.now() + timedelta(days=1))
    except Exception:
        dt_start = datetime.now() + timedelta(days=1)
    dt_end = dt_start + timedelta(minutes=45)

    fmt = "%Y%m%dT%H%M00"
    summary = f"Rishta {m.get('meeting_type')}: {p.get('full_name') or 'Candidate'}"
    desc = (
        f"Participants: {m.get('participants') or ''}\\n"
        f"Pre-Call Brief: {(m.get('pre_meeting_notes') or p.get('pre_call_brief') or '').replace(chr(10), '\\n')}"
    )
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Rishta Dossier//Mac AI Server//EN",
            "BEGIN:VEVENT",
            f"UID:rishta-meeting-{m['id']}@rishta.local",
            f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{dt_start.strftime(fmt)}",
            f"DTEND:{dt_end.strftime(fmt)}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            f"LOCATION:{m.get('location_or_link') or 'Phone Call'}",
            "BEGIN:VALARM",
            "TRIGGER:-PT60M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:Reminder (1 hr): {summary}",
            "END:VALARM",
            "BEGIN:VALARM",
            "TRIGGER:-PT15M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:Reminder (15 min): {summary}",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="rishta_meeting_{m["id"]}.ics"'},
    )


@router.post("/meetings/{meeting_id}/complete-with-recording")
async def complete_meeting_with_call_recording(
    meeting_id: int,
    post_meeting_notes: str = Form(default=""),
    recording_file: Optional[UploadFile] = File(default=None),
    member: dict = Depends(get_current_member),
):
    conn = get_conn()
    m_row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not m_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = dict(m_row)
    profile_id = meeting["profile_id"]

    p_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not p_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")
    existing = dict(p_row)

    now = utc_now()
    recording_url = meeting.get("call_recording_url")
    audio_mp3_b64_list: list[str] = []
    rec_media_id: Optional[int] = None

    if recording_file and recording_file.filename:
        raw_bytes = await recording_file.read()
        if raw_bytes:
            aud_path, url_path = save_uploaded_bytes(raw_bytes, recording_file.filename, "voice")
            recording_url = url_path
            mp3_b64 = transcode_audio_to_mp3_b64(aud_path)
            if mp3_b64:
                audio_mp3_b64_list.append(mp3_b64)
            cur_m = conn.execute(
                """
                INSERT INTO media_assets (
                    profile_id, asset_type, file_name, file_path, url_path,
                    mime_type, uploaded_by, created_at
                ) VALUES (?, 'voice_note', ?, ?, ?, 'audio/mpeg', ?, ?)
                """,
                (
                    profile_id,
                    f"Call_Recording_{recording_file.filename}",
                    str(aud_path),
                    url_path,
                    member["name"],
                    now,
                ),
            )
            rec_media_id = cur_m.lastrowid

    combined_notes = "\n".join(
        x
        for x in [
            f"Meeting Type: {meeting.get('meeting_type')} ({meeting.get('title')})",
            f"Pre-Meeting Agenda: {meeting.get('pre_meeting_notes') or ''}",
            f"Post-Meeting Notes: {post_meeting_notes}",
        ]
        if x.strip()
    )

    ai_bundle = extract_rishta_bundle(
        raw_text=combined_notes,
        audio_mp3_b64_list=audio_mp3_b64_list,
        existing_profile=existing,
        source_name=existing.get("source_name"),
        source_channel=existing.get("source_channel"),
    )

    call_transcript = ai_bundle.get("voice_transcript") or ""
    ai_summary = ai_bundle.get("interaction_summary") or ai_bundle.get("fit_summary") or post_meeting_notes

    # Update meeting as completed
    conn.execute(
        """
        UPDATE meetings
        SET stage = 'completed', post_meeting_notes = ?, call_recording_url = ?,
            call_transcript = ?, ai_call_summary = ?, updated_at = ?
        WHERE id = ?
        """,
        (post_meeting_notes, recording_url, call_transcript, ai_summary, now, meeting_id),
    )

    # Apply extracted profile updates from the call recording & notes
    updates = {}
    for k, v in (ai_bundle.get("extracted_fields") or {}).items():
        if k in PROFILE_EDITABLE_FIELDS and v not in (None, ""):
            if k == "private_notes" and member["role"] != "owner":
                continue
            updates[k] = v

    if ai_bundle.get("suggested_status"):
        updates["status"] = ai_bundle["suggested_status"]
    if ai_bundle.get("suggested_ball_in_court"):
        updates["ball_in_court"] = ai_bundle["suggested_ball_in_court"]
    if ai_bundle.get("fit_summary"):
        updates["fit_summary"] = ai_bundle["fit_summary"]
    if ai_bundle.get("ai_fit_score") is not None:
        updates["ai_fit_score"] = ai_bundle["ai_fit_score"]
    if ai_bundle.get("pre_call_brief"):
        updates["pre_call_brief"] = ai_bundle["pre_call_brief"]
    if ai_bundle.get("positives"):
        updates["positives_json"] = json.dumps(ai_bundle["positives"])
    if ai_bundle.get("concerns"):
        updates["concerns_json"] = json.dumps(ai_bundle["concerns"])
    if ai_bundle.get("missing_questions"):
        updates["missing_questions_json"] = json.dumps(ai_bundle["missing_questions"])

    merged = {**existing, **updates}
    updates["disambiguation_tag"] = build_disambiguation_tag(merged)
    updates["updated_at"] = now

    set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
    conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), profile_id))

    # Add timeline interaction
    conn.execute(
        """
        INSERT INTO interactions (
            profile_id, interaction_type, title, summary, raw_text, transcript,
            visibility, created_by_member, occurred_at, created_at
        ) VALUES (?, 'phone_call', ?, ?, ?, ?, 'shared', ?, ?, ?)
        """,
        (
            profile_id,
            f"Completed: {meeting.get('title')}",
            ai_summary,
            post_meeting_notes,
            call_transcript,
            member["name"],
            now,
            now,
        ),
    )

    # Create next follow-up task suggested by AI
    sugg_fu = ai_bundle.get("suggested_follow_up")
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
                ai_bundle.get("suggested_ball_in_court") or "us",
                member["name"],
                now,
            ),
        )

    conn.commit()
    updated_m = dict(conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone())
    conn.close()

    if ai_bundle.get("pending_mac_ai"):
        task_id = enqueue_worker_task(
            "transcribe_meeting_recording",
            meeting_id,
            {
                "meeting_id": meeting_id,
                "profile_id": profile_id,
                "raw_text": combined_notes,
                "media_asset_ids": [rec_media_id] if rec_media_id else [],
            },
        )
        remote_online, _, _ = is_remote_mac_worker_online()
        if remote_online:
            live_res = wait_for_worker_task(task_id, timeout_seconds=18.0)
            if live_res:
                call_transcript = live_res.get("voice_transcript") or call_transcript
                ai_summary = live_res.get("interaction_summary") or ai_summary

    return {
        "ok": True,
        "meeting": _enrich_meeting(updated_m, merged),
        "call_transcript": call_transcript,
        "ai_call_summary": ai_summary,
        "draft_whatsapp_replies": ai_bundle.get("draft_whatsapp_replies") or {},
        "models_used": ai_bundle.get("models_used") or {},
        "pending_mac_ai": bool(ai_bundle.get("pending_mac_ai")),
    }


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
