import json
import urllib.parse
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from ..auth import get_current_member, require_owner, sanitize_profile_for_member
from ..db import get_app_settings, get_conn, utc_now
from ..models import (
    CompareProfilesRequest,
    CustomWhatsAppRequest,
    PROFILE_EDITABLE_FIELDS,
    ProfileCreateOrUpdate,
)
from ..services.ai_extractor import (
    build_disambiguation_tag,
    check_gotra_clash,
    compare_profiles_ai,
    compute_embedding,
    extract_rishta_bundle,
)
from ..services.dedupe import build_profile_embedding_text, normalize_phone

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _build_clean_whatsapp_summary(p: dict) -> str:
    lines = [f"*Profile Summary: {p.get('full_name') or 'Candidate'}*"]
    if p.get("age") or p.get("dob") or p.get("height"):
        bio_bits = [
            f"Age: {p['age']}" if p.get("age") else None,
            f"DOB: {p['dob']}" if p.get("dob") else None,
            f"Height: {p['height']}" if p.get("height") else None,
        ]
        lines.append("• " + " | ".join(b for b in bio_bits if b))
    if p.get("time_of_birth") or p.get("place_of_birth"):
        lines.append(
            f"• Birth Details: {p.get('time_of_birth') or 'Time N/A'}, {p.get('place_of_birth') or 'Place N/A'}"
        )
    if p.get("education") or p.get("college"):
        lines.append(f"• Education: {' — '.join(x for x in [p.get('education'), p.get('college')] if x)}")
    if p.get("occupation") or p.get("company") or p.get("annual_ctc"):
        work = " at ".join(x for x in [p.get("occupation"), p.get("company")] if x)
        if p.get("annual_ctc"):
            work = f"{work} ({p['annual_ctc']})" if work else p["annual_ctc"]
        lines.append(f"• Career: {work}")
    if p.get("current_city") or p.get("hometown"):
        loc = f"Current: {p.get('current_city') or 'N/A'}"
        if p.get("hometown"):
            loc += f" | Hometown: {p['hometown']}"
        lines.append(f"• Location: {loc}")
    if p.get("gotra") or p.get("caste_community") or p.get("manglik"):
        cult = [
            p.get("caste_community"),
            f"Gotra: {p['gotra']}" if p.get("gotra") else None,
            f"Manglik: {p['manglik']}" if p.get("manglik") else None,
        ]
        lines.append("• Community/Astro: " + " | ".join(c for c in cult if c))
    if p.get("father_details") or p.get("mother_details") or p.get("siblings_details"):
        fam = [
            f"Father: {p['father_details']}" if p.get("father_details") else None,
            f"Mother: {p['mother_details']}" if p.get("mother_details") else None,
            f"Siblings: {p['siblings_details']}" if p.get("siblings_details") else None,
        ]
        lines.append("• Family: " + " ; ".join(f for f in fam if f))
    if p.get("source_name"):
        lines.append(f"• Referred via: {p['source_name']} ({p.get('source_channel') or 'Contact'})")
    return "\n".join(lines)


def _build_wa_me_link(phone: Optional[str], text: str = "") -> Optional[str]:
    digits = normalize_phone(phone)
    if len(digits) < 10:
        return None
    intl = f"91{digits}" if len(digits) == 10 else digits
    encoded = urllib.parse.quote(text) if text else ""
    return f"https://wa.me/{intl}" + (f"?text={encoded}" if encoded else "")


@router.get("/summary-stats")
def get_summary_stats(member: dict = Depends(get_current_member)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, status, ball_in_court, source_name, source_channel, priority, gotra_clash_alert FROM profiles"
    ).fetchall()

    by_status: dict[str, int] = {}
    by_ball: dict[str, int] = {"us": 0, "them": 0, "mediator": 0, "closed": 0}
    by_mediator: dict[str, dict] = {}

    for r in rows:
        st = r["status"] or "New"
        by_status[st] = by_status.get(st, 0) + 1
        bc = r["ball_in_court"] or "us"
        if st not in ("Passed", "Archived"):
            by_ball[bc] = by_ball.get(bc, 0) + 1
        med = (r["source_name"] or "").strip()
        if med:
            if med not in by_mediator:
                by_mediator[med] = {
                    "source_name": med,
                    "source_channel": r["source_channel"] or "Relative",
                    "total": 0,
                    "active": 0,
                    "shortlisted": 0,
                }
            by_mediator[med]["total"] += 1
            if st not in ("Passed", "Archived"):
                by_mediator[med]["active"] += 1
            if st in ("Shortlisted", "Talking", "Meetup"):
                by_mediator[med]["shortlisted"] += 1

    follow_ups = conn.execute(
        """
        SELECT f.*, p.full_name, p.status as profile_status, p.disambiguation_tag
        FROM follow_ups f
        JOIN profiles p ON p.id = f.profile_id
        WHERE f.completed = 0
        ORDER BY COALESCE(f.due_date, '9999-12-31') ASC, f.id DESC
        LIMIT 25
        """
    ).fetchall()

    pending_imports = conn.execute(
        "SELECT COUNT(*) as c FROM import_jobs WHERE status = 'pending_review'"
    ).fetchone()["c"]

    upcoming_meetings = conn.execute(
        """
        SELECT m.*, p.full_name as candidate_name, p.disambiguation_tag
        FROM meetings m
        JOIN profiles p ON p.id = m.profile_id
        WHERE m.stage IN ('proposing', 'scheduled')
        ORDER BY CASE WHEN m.stage='scheduled' THEN 0 ELSE 1 END, COALESCE(m.scheduled_at, m.created_at) ASC
        LIMIT 20
        """
    ).fetchall()
    conn.close()

    return {
        "total_profiles": len(rows),
        "by_status": by_status,
        "by_ball_in_court": by_ball,
        "mediators": sorted(by_mediator.values(), key=lambda x: x["total"], reverse=True),
        "open_follow_ups": [dict(f) for f in follow_ups],
        "upcoming_meetings": [dict(m) for m in upcoming_meetings],
        "pending_imports_count": pending_imports,
    }


@router.get("")
def list_profiles(
    q: Optional[str] = None,
    status: Optional[str] = None,
    ball_in_court: Optional[str] = None,
    source_name: Optional[str] = None,
    member: dict = Depends(get_current_member),
):
    conn = get_conn()
    clauses = []
    params = []

    if status and status != "ALL":
        if status == "ACTIVE":
            clauses.append("status NOT IN ('Passed', 'Archived')")
        else:
            clauses.append("status = ?")
            params.append(status)

    if ball_in_court and ball_in_court != "ALL":
        clauses.append("ball_in_court = ?")
        params.append(ball_in_court)

    if source_name and source_name != "ALL":
        clauses.append("lower(source_name) = lower(?)")
        params.append(source_name)

    if q and q.strip():
        like = f"%{q.strip()}%"
        clauses.append(
            "(full_name LIKE ? OR current_city LIKE ? OR hometown LIKE ? OR company LIKE ? "
            "OR occupation LIKE ? OR education LIKE ? OR gotra LIKE ? OR source_name LIKE ? "
            "OR caste_community LIKE ? OR disambiguation_tag LIKE ?)"
        )
        params.extend([like] * 10)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM profiles {where_sql} ORDER BY CASE WHEN priority='High' THEN 0 ELSE 1 END, updated_at DESC",
        tuple(params),
    ).fetchall()

    vote_rows = conn.execute("SELECT * FROM family_votes").fetchall()
    votes_by_profile: dict[int, list[dict]] = {}
    for vr in vote_rows:
        votes_by_profile.setdefault(vr["profile_id"], []).append(dict(vr))

    fu_rows = conn.execute(
        "SELECT * FROM follow_ups WHERE completed = 0 ORDER BY COALESCE(due_date, '9999-12-31') ASC"
    ).fetchall()
    fu_by_profile: dict[int, list[dict]] = {}
    for fr in fu_rows:
        fu_by_profile.setdefault(fr["profile_id"], []).append(dict(fr))

    out = []
    for r in rows:
        p = sanitize_profile_for_member(dict(r), member)
        p["family_votes"] = votes_by_profile.get(p["id"], [])
        p["open_follow_ups"] = fu_by_profile.get(p["id"], [])
        out.append(p)

    conn.close()
    return {"profiles": out}


@router.post("")
def create_profile(req: ProfileCreateOrUpdate, member: dict = Depends(get_current_member)):
    conn = get_conn()
    settings = get_app_settings()
    excluded_gotras = settings.get("partner_preferences", {}).get("excluded_gotras") or []

    payload = req.model_dump(exclude_none=True)
    if "private_notes" in payload and member["role"] != "owner":
        payload.pop("private_notes", None)

    positives = payload.pop("positives", [])
    concerns = payload.pop("concerns", [])
    missing_q = payload.pop("missing_questions", [])

    if not payload.get("full_name"):
        payload["full_name"] = "New Candidate"
    if not payload.get("status"):
        payload["status"] = "New"
    if not payload.get("ball_in_court"):
        payload["ball_in_court"] = "us"

    gotra_alert = check_gotra_clash(payload.get("gotra"), excluded_gotras)
    if gotra_alert:
        payload["gotra_clash_alert"] = gotra_alert

    payload["disambiguation_tag"] = build_disambiguation_tag(payload)
    payload["positives_json"] = json.dumps(positives)
    payload["concerns_json"] = json.dumps(concerns)
    payload["missing_questions_json"] = json.dumps(missing_q)

    emb_vec, _ = compute_embedding(build_profile_embedding_text(payload))
    if emb_vec:
        payload["embedding_json"] = json.dumps(emb_vec)

    now = utc_now()
    payload["created_by_member"] = member["name"]
    payload["created_at"] = now
    payload["updated_at"] = now

    cols = [c for c in payload.keys() if c in PROFILE_EDITABLE_FIELDS or c.endswith("_json") or c in ("created_by_member", "created_at", "updated_at")]
    cur = conn.execute(
        f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(payload[c] for c in cols),
    )
    new_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return sanitize_profile_for_member(dict(row), member)


@router.get("/mediator-report/{source_name}")
def get_mediator_status_report(source_name: str, member: dict = Depends(get_current_member)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, full_name, age, current_city, company, status, ball_in_court, pass_reason, kundli_status FROM profiles WHERE lower(source_name) = lower(?) ORDER BY updated_at DESC",
        (source_name.strip(),),
    ).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No profiles found for mediator '{source_name}'.")

    lines = [f"Namaste! Sharing a quick status update on the profiles referred by {source_name}:", ""]
    for idx, r in enumerate(rows, 1):
        status = r["status"]
        detail = ""
        if status == "Kundli Pending":
            detail = "Currently checking Kundli / birth details."
        elif status == "Info Needed":
            detail = "Awaiting a few additional details."
        elif status in ("Talking", "Meetup", "Shortlisted"):
            detail = "In active conversation / progressing positively."
        elif status == "On Hold":
            detail = "On hold for now."
        elif status == "Passed":
            detail = f"We decided not to proceed further ({r['pass_reason'] or 'preference mismatch'})."
        else:
            detail = "Reviewing with family."
        loc_comp = " · ".join(x for x in [r["current_city"], r["company"]] if x)
        label = f"{r['full_name']}" + (f" ({loc_comp})" if loc_comp else "")
        lines.append(f"{idx}. *{label}* — {detail}")

    lines.append("\nThank you so much for your continued support and guidance!")
    return {
        "source_name": source_name,
        "count": len(rows),
        "whatsapp_report_text": "\n".join(lines),
    }


@router.post("/compare")
def compare_profiles(req: CompareProfilesRequest, member: dict = Depends(get_current_member)):
    if len(req.profile_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 profiles to compare side by side.")
    conn = get_conn()
    placeholders = ", ".join("?" for _ in req.profile_ids)
    rows = conn.execute(f"SELECT * FROM profiles WHERE id IN ({placeholders})", tuple(req.profile_ids)).fetchall()
    vote_rows = conn.execute(
        f"SELECT * FROM family_votes WHERE profile_id IN ({placeholders})", tuple(req.profile_ids)
    ).fetchall()
    conn.close()

    votes_map: dict[int, list[dict]] = {}
    for vr in vote_rows:
        votes_map.setdefault(vr["profile_id"], []).append(dict(vr))

    profiles = []
    for r in rows:
        p = sanitize_profile_for_member(dict(r), member)
        p["family_votes"] = votes_map.get(p["id"], [])
        profiles.append(p)

    try:
        ai_comparison = compare_profiles_ai(profiles)
    except Exception as exc:
        ai_comparison = {"executive_summary": f"AI comparison unavailable: {exc}", "model_used": "fallback"}

    return {"profiles": profiles, "ai_comparison": ai_comparison}


@router.get("/{profile_id}")
def get_profile_detail(profile_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")

    profile = sanitize_profile_for_member(dict(row), member)
    assets = conn.execute(
        "SELECT * FROM media_assets WHERE profile_id = ? ORDER BY id DESC", (profile_id,)
    ).fetchall()

    if member["role"] == "owner":
        interactions = conn.execute(
            "SELECT * FROM interactions WHERE profile_id = ? ORDER BY occurred_at DESC, id DESC",
            (profile_id,),
        ).fetchall()
    else:
        interactions = conn.execute(
            "SELECT * FROM interactions WHERE profile_id = ? AND visibility = 'shared' ORDER BY occurred_at DESC, id DESC",
            (profile_id,),
        ).fetchall()

    votes = conn.execute(
        "SELECT * FROM family_votes WHERE profile_id = ? ORDER BY updated_at DESC", (profile_id,)
    ).fetchall()
    follow_ups = conn.execute(
        "SELECT * FROM follow_ups WHERE profile_id = ? ORDER BY completed ASC, COALESCE(due_date, '9999-12-31') ASC",
        (profile_id,),
    ).fetchall()
    conn.close()

    clean_summary = _build_clean_whatsapp_summary(profile)
    profile["media_assets"] = [dict(a) for a in assets]
    profile["interactions"] = [dict(i) for i in interactions]
    profile["family_votes"] = [dict(v) for v in votes]
    profile["follow_ups"] = [dict(f) for f in follow_ups]
    profile["clean_whatsapp_summary"] = clean_summary
    profile["wa_links"] = {
        "primary_contact": _build_wa_me_link(profile.get("primary_contact_phone")),
        "candidate": _build_wa_me_link(profile.get("candidate_phone")),
        "mediator": _build_wa_me_link(profile.get("source_phone")),
    }
    return profile


@router.patch("/{profile_id}")
def update_profile(profile_id: int, req: ProfileCreateOrUpdate, member: dict = Depends(get_current_member)):
    conn = get_conn()
    existing_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not existing_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")

    existing = dict(existing_row)
    payload = req.model_dump(exclude_unset=True)
    if "private_notes" in payload and member["role"] != "owner":
        payload.pop("private_notes", None)

    updates = {}
    for k, v in payload.items():
        if k in PROFILE_EDITABLE_FIELDS:
            updates[k] = v

    if "positives" in payload and payload["positives"] is not None:
        updates["positives_json"] = json.dumps(payload["positives"])
    if "concerns" in payload and payload["concerns"] is not None:
        updates["concerns_json"] = json.dumps(payload["concerns"])
    if "missing_questions" in payload and payload["missing_questions"] is not None:
        updates["missing_questions_json"] = json.dumps(payload["missing_questions"])

    merged = {**existing, **updates}
    settings = get_app_settings()
    excluded_gotras = settings.get("partner_preferences", {}).get("excluded_gotras") or []
    updates["gotra_clash_alert"] = check_gotra_clash(merged.get("gotra"), excluded_gotras)
    updates["disambiguation_tag"] = build_disambiguation_tag(merged)
    updates["updated_at"] = utc_now()

    set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
    conn.execute(f"UPDATE profiles SET {set_clause} WHERE id = ?", (*updates.values(), profile_id))
    conn.commit()
    updated_row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()
    return sanitize_profile_for_member(dict(updated_row), member)


@router.post("/{profile_id}/refresh-ai")
def refresh_profile_ai(profile_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")
    existing = dict(row)

    interactions = conn.execute(
        "SELECT title, summary, raw_text, transcript, created_by_member, occurred_at FROM interactions WHERE profile_id = ? AND visibility = 'shared' ORDER BY occurred_at ASC",
        (profile_id,),
    ).fetchall()
    notes_history = "\n\n".join(
        f"[{i['occurred_at'][:10]} by {i['created_by_member']}] {i['title']}: {i['summary'] or ''} {i['raw_text'] or ''} {i['transcript'] or ''}"
        for i in interactions
    )

    ai_bundle = extract_rishta_bundle(
        raw_text=notes_history or existing.get("shared_family_notes") or "",
        existing_profile=existing,
        source_name=existing.get("source_name"),
        source_channel=existing.get("source_channel"),
    )

    if ai_bundle.get("pending_mac_ai"):
        conn.close()
        raise HTTPException(
            status_code=503,
            detail="Mac AI is offline — fit analysis will be available once your Mac worker is online",
        )

    now = utc_now()
    conn.execute(
        """
        UPDATE profiles
        SET ai_fit_score = ?, fit_summary = ?, positives_json = ?, concerns_json = ?,
            missing_questions_json = ?, pre_call_brief = ?, gotra_clash_alert = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            ai_bundle.get("ai_fit_score"),
            ai_bundle.get("fit_summary"),
            json.dumps(ai_bundle.get("positives") or []),
            json.dumps(ai_bundle.get("concerns") or []),
            json.dumps(ai_bundle.get("missing_questions") or []),
            ai_bundle.get("pre_call_brief") or "",
            ai_bundle.get("gotra_clash_alert"),
            now,
            profile_id,
        ),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()
    return {
        "profile": sanitize_profile_for_member(dict(updated), member),
        "draft_whatsapp_replies": ai_bundle.get("draft_whatsapp_replies") or {},
        "models_used": ai_bundle.get("models_used") or {},
    }


@router.post("/{profile_id}/archive")
def toggle_archive_profile(
    profile_id: int,
    archive: bool = True,
    reason: Optional[str] = "Not needed / Archived",
    member: dict = Depends(get_current_member),
):
    require_owner(member)
    conn = get_conn()
    row = conn.execute("SELECT id, status FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")

    new_status = "Archived" if archive else "Reviewing"
    new_ball = "closed" if archive else "us"
    now = utc_now()
    conn.execute(
        "UPDATE profiles SET status = ?, ball_in_court = ?, pass_reason = COALESCE(?, pass_reason), updated_at = ? WHERE id = ?",
        (new_status, new_ball, reason if archive else None, now, profile_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()
    return sanitize_profile_for_member(dict(updated), member)


@router.get("/{profile_id}/whatsapp-templates")
def get_granular_whatsapp_templates(profile_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Profile not found")
    p = sanitize_profile_for_member(dict(row), member)
    relatives = [dict(r) for r in conn.execute("SELECT * FROM relatives ORDER BY name ASC").fetchall()]
    conn.close()

    settings = get_app_settings()
    outbound = settings.get("my_outbound_pack") or {}
    sister_bio = (outbound.get("shareable_whatsapp_bio") or "").strip()
    sister_name = outbound.get("my_full_name") or "my sister"
    cand_name = p.get("full_name") or "your son/family member"
    cand_first = cand_name.split()[0] if cand_name else "there"
    parent_name = p.get("primary_contact_name") or "Uncle ji / Aunty ji"
    source_ref = f" through {p['source_name']}" if p.get("source_name") else ""
    missing_list = p.get("missing_questions") or []
    missing_str = (
        "\n".join(f"• {q}" for q in missing_list[:3])
        if missing_list
        else "• Exact Time & Place of Birth (for Kundli matching)\n• Current work location & future city preference"
    )
    clean_card = _build_clean_whatsapp_summary(p)

    templates = [
        # --- FIRST-TIME OUTREACH TEMPLATES ---
        {
            "id": "first_share_sister_bio",
            "category": "first_time",
            "stage_label": "1st Time · Share Sister's Biodata & Initiate Talks",
            "audience": "Prospect's Family / Mediator",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"We received {cand_name}'s profile{source_ref} and were glad to go through his details.\n\n"
                f"{sister_bio}\n\n"
                f"Please let us know once you have had a chance to review, and we can connect on a quick phone call at your convenience.\n"
                f"Warm regards,\nSaurabh & Family"
            ),
        },
        {
            "id": "first_ack_and_ask_kundli",
            "category": "first_time",
            "stage_label": "1st Time · Acknowledge Profile & Ask for Birth/Kundli Details",
            "audience": "Prospect's Family / Mediator",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"Thank you for sharing {cand_name}'s biodata{source_ref}. Our family went through the details and would love to take this forward.\n\n"
                f"To help us check Kundli / initial alignment, could you please share:\n"
                f"{missing_str}\n\n"
                f"Warm regards,\nSaurabh & Family"
            ),
        },
        {
            "id": "first_forward_to_relative",
            "category": "first_time",
            "stage_label": "1st Time · Forward Candidate Summary to Family / Relative",
            "audience": "Relative / Family Member",
            "text": (
                f"Namaste! Sharing this profile we received{source_ref} for review:\n\n"
                f"{clean_card}\n\n"
                f"Please share your thoughts or if you know the family."
            ),
        },
        {
            "id": "first_brother_to_prospect",
            "category": "first_time",
            "stage_label": "1st Time · Saurabh (Brother) Direct Intro to Prospect",
            "audience": "Prospect Directly",
            "text": (
                f"Hi {cand_first}! Hope you're doing well. I'm Saurabh ({sister_name}'s brother). "
                f"Our families connected regarding your profile{source_ref}, and we'd love to catch up for a quick 10-minute intro chat whenever you're free this week. Let me know what time works best for you!"
            ),
        },
        # --- CONSECUTIVE / FOLLOW-UP TEMPLATES ---
        {
            "id": "followup_1_gentle_nudge",
            "category": "follow_up",
            "stage_label": "Follow-Up #1 · Gentle Check-in (Did you review Sister's profile?)",
            "audience": "Prospect's Family",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"Hope everyone at home is doing well. Just following up on my sister's profile that we shared earlier regarding {cand_name}. "
                f"Please let us know your family's thoughts whenever convenient—no rush at all.\n\nWarm regards,\nSaurabh & Family"
            ),
        },
        {
            "id": "followup_2_kundli_update",
            "category": "follow_up",
            "stage_label": "Follow-Up #2 · Kundli / Horoscope Update (Positive Match -> Next Step)",
            "audience": "Prospect's Family",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"Sharing a quick update regarding {cand_name} — we had the Kundli / horoscope details checked with our Panditji and the alignment looks positive"
                + (f" ({p['kundli_gunas']}). " if p.get("kundli_gunas") else ". ")
                + "We would love to schedule a phone call between our families this week. Please let us know what evening works best for you."
            ),
        },
        {
            "id": "followup_3_schedule_family_call",
            "category": "follow_up",
            "stage_label": "Follow-Up #3 · Propose Time Slots for Family Phone Call",
            "audience": "Prospect's Family",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"Looking forward to speaking with you regarding {cand_name}. Would today or tomorrow evening around 7:30 PM – 8:30 PM work for a quick phone call with my mother and me?"
            ),
        },
        {
            "id": "followup_4_connect_sister_prospect",
            "category": "follow_up",
            "stage_label": "Follow-Up #4 · Connect Sister & Prospect for 1:1 Conversation",
            "audience": "Prospect's Family / Prospect",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"It was really lovely speaking with you. Since both families feel positive, we thought it would be great for {cand_first} and my sister to speak directly and get to know each other. "
                f"Please share {cand_first}'s convenient time / number and we can connect them this weekend."
            ),
        },
        {
            "id": "followup_5_post_call_meetup",
            "category": "follow_up",
            "stage_label": "Follow-Up #5 · Post-Call Warm Follow-Up & Plan In-Person Meetup",
            "audience": "Prospect's Family / Prospect",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"My sister and {cand_first} had a very nice conversation. We'd love to plan an in-person meeting whenever convenient for both sides. Please let us know your upcoming schedule!"
            ),
        },
        {
            "id": "followup_6_mediator_check",
            "category": "follow_up",
            "stage_label": "Follow-Up #6 · Check Status via Referring Relative / Mediator",
            "audience": "Referring Relative / Mediator",
            "text": (
                f"Namaste {p.get('source_name') or 'ji'}! 🙏\n"
                f"Hope you are doing well. Wanted to check if you heard any update from {cand_name}'s family ({p.get('current_city') or ''}) regarding the profile we exchanged? "
                f"Please let us know whenever you speak with them."
            ),
        },
        {
            "id": "followup_7_hold_travelling",
            "category": "follow_up",
            "stage_label": "Follow-Up #7 · Polite Hold (Family Travelling / Will Reconnect Soon)",
            "audience": "Prospect's Family / Mediator",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"Wanted to keep you posted that our family is tied up with some travel/commitments for the next few days. "
                f"We will reconnect with you early next week regarding {cand_name}. Thank you for your patience!"
            ),
        },
        {
            "id": "followup_8_polite_pass",
            "category": "follow_up",
            "stage_label": "Closure · Gracious & Respectful Family Decline",
            "audience": "Prospect's Family / Mediator",
            "text": (
                f"Namaste {parent_name}! 🙏\n"
                f"Thank you so much for your warmth and for sharing {cand_name}'s profile. After discussing at home"
                f"{' and checking Kundli alignment' if p.get('kundli_status') == 'Concern' else ''}, "
                f"we feel a few preferences/parameters may not align fully for us to take this forward right now. "
                f"We truly wish {cand_first} and your family the very best in your search! 🙏"
            ),
        },
    ]

    recipients = []
    if p.get("primary_contact_phone"):
        recipients.append(
            {
                "label": f"Prospect Family ({p.get('primary_contact_name') or 'Parent'}: {p['primary_contact_phone']})",
                "phone": p["primary_contact_phone"],
                "type": "prospect_family",
            }
        )
    if p.get("candidate_phone"):
        recipients.append(
            {
                "label": f"Prospect Direct ({cand_first}: {p['candidate_phone']})",
                "phone": p["candidate_phone"],
                "type": "prospect_direct",
            }
        )
    if p.get("source_phone"):
        recipients.append(
            {
                "label": f"Referring Relative/Mediator ({p.get('source_name') or 'Mediator'}: {p['source_phone']})",
                "phone": p["source_phone"],
                "type": "mediator",
            }
        )
    for rel in relatives:
        if rel.get("phone"):
            recipients.append(
                {
                    "label": f"Relative: {rel['name']} ({rel['relation']} · {rel['phone']})",
                    "phone": rel["phone"],
                    "type": "relative",
                }
            )

    return {
        "profile_id": profile_id,
        "full_name": p.get("full_name"),
        "recipients": recipients,
        "templates": templates,
        "sister_outbound_bio": sister_bio,
        "clean_profile_summary": clean_card,
    }


@router.delete("/{profile_id}")
def delete_profile(profile_id: int, member: dict = Depends(get_current_member)):
    require_owner(member)
    conn = get_conn()
    conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
