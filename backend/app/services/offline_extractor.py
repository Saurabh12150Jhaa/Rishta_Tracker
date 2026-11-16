import re
from datetime import datetime, timedelta
from typing import Optional
from ..db import get_app_settings


def _find_pattern(text: str, patterns: list[str]) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip(" :-\t\r\n,.;")
            if val:
                return val[:160]
    return None


def offline_extract_rishta_bundle(
    raw_text: str = "",
    pdf_texts: Optional[list[str]] = None,
    source_name: Optional[str] = None,
    source_channel: Optional[str] = None,
    existing_profile: Optional[dict] = None,
) -> dict:
    """
    Deterministic Indian Biodata & WhatsApp Forward Extractor that runs in <50ms
    when the Zscaler Mac AI Worker is offline/asleep, ensuring 100% app usability 24/7.
    """
    combined = "\n".join([raw_text or "", *(pdf_texts or [])]).strip()
    settings = get_app_settings()
    prefs = settings.get("partner_preferences") or {}
    excluded_gotras = prefs.get("excluded_gotras") or []

    fields: dict = {}

    # 1. Full Name
    name = _find_pattern(
        combined,
        [
            r"(?:full\s*name|candidate\s*name|boy'?s?\s*name|groom'?s?\s*name|name)\s*[:\-–]\s*([A-Z][a-zA-Z\s\.]{2,45})",
            r"(?:profile\s+of|biodata\s+of|for)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
        ],
    )
    if name:
        fields["full_name"] = name
    elif existing_profile and existing_profile.get("full_name"):
        fields["full_name"] = existing_profile["full_name"]

    fields["gender"] = "Male"

    # 2. Age & DOB
    age_str = _find_pattern(combined, [r"\bage\s*[:\-–]?\s*(\d{2})\b", r"\b(\d{2})\s*(?:yrs|years\s*old)\b"])
    if age_str and age_str.isdigit():
        fields["age"] = int(age_str)

    dob = _find_pattern(
        combined,
        [
            r"(?:date\s*of\s*birth|d\.?o\.?b\.?|janam\s*tithi|born\s*on)\s*[:\-–]\s*([^\n\r\|]{4,28})",
            r"\b(\d{1,2}[\s/\-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s/\-]\d{2,4})\b",
        ],
    )
    if dob:
        fields["dob"] = dob

    # 3. Time & Place of Birth (Kundli)
    tob = _find_pattern(
        combined,
        [
            r"(?:time\s*of\s*birth|t\.?o\.?b\.?|birth\s*time|janam\s*samay)\s*[:\-–]\s*([^\n\r\|]{3,25})",
            r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b",
        ],
    )
    if tob:
        fields["time_of_birth"] = tob

    pob = _find_pattern(
        combined,
        [
            r"(?:place\s*of\s*birth|p\.?o\.?b\.?|birth\s*place|janam\s*sthan)\s*[:\-–]\s*([^\n\r\|]{2,40})",
        ],
    )
    if pob:
        fields["place_of_birth"] = pob

    # 4. Height, Gotra, Manglik, Diet
    height = _find_pattern(
        combined,
        [
            r"(?:height|ht)\s*[:\-–]\s*([^\n\r\|]{2,18})",
            r"\b(5\s*'\s*\d{1,2}\s*\"?|6\s*'\s*\d{1,2}\s*\"?|5\s*ft\s*\d{1,2}\s*in)\b",
        ],
    )
    if height:
        fields["height"] = height

    gotra = _find_pattern(combined, [r"(?:gotra|gothra)\s*[:\-–]\s*([a-zA-Z\s]{2,30})"])
    if gotra:
        fields["gotra"] = gotra

    manglik = _find_pattern(combined, [r"(?:manglik|maanglik|kuja\s*dosha)\s*[:\-–]\s*([^\n\r\|]{2,25})"])
    if manglik:
        if "non" in manglik.lower() or "no" in manglik.lower():
            fields["manglik"] = "No"
        elif "anshik" in manglik.lower() or "partial" in manglik.lower():
            fields["manglik"] = "Anshik"
        elif "yes" in manglik.lower():
            fields["manglik"] = "Yes"
        else:
            fields["manglik"] = manglik

    diet = _find_pattern(combined, [r"(?:diet|food\s*habits|eating)\s*[:\-–]\s*([^\n\r\|]{3,30})"])
    if not diet:
        if re.search(r"\bnon[\s\-]?veg", combined, re.I):
            diet = "Non-Vegetarian"
        elif re.search(r"\beggetarian\b", combined, re.I):
            diet = "Eggetarian"
        elif re.search(r"\bvegetarian\b|\bpure\s*veg\b", combined, re.I):
            diet = "Vegetarian"
    if diet:
        fields["diet"] = diet

    # 5. Education, Occupation, Company, CTC/Package, City
    edu = _find_pattern(
        combined,
        [
            r"(?:education|qualification|degree|academics)\s*[:\-–]\s*([^\n\r]{3,75})",
        ],
    )
    if edu:
        fields["education"] = edu

    occ = _find_pattern(
        combined,
        [
            r"(?:occupation|profession|designation|role|working\s*as)\s*[:\-–]\s*([^\n\r]{3,75})",
        ],
    )
    if occ:
        fields["occupation"] = occ

    comp = _find_pattern(
        combined,
        [
            r"(?:company|organization|employer|working\s*(?:at|with|in))\s*[:\-–]?\s*([A-Z][a-zA-Z0-9\s&\.,\-]{2,50})",
        ],
    )
    if comp:
        fields["company"] = comp

    ctc = _find_pattern(
        combined,
        [
            r"(?:annual\s*package|package|income|ctc|salary|earning)\s*[:\-–]\s*([^\n\r\|]{2,35})",
            r"\b(\d{1,3}(?:\.\d+)?\s*(?:LPA|Lakhs?\s*per\s*annum|Cr|Crore))\b",
        ],
    )
    if ctc:
        fields["annual_ctc"] = ctc

    city = _find_pattern(
        combined,
        [
            r"(?:current\s*location|current\s*city|present\s*location|residing\s*in|location|city)\s*[:\-–]\s*([^\n\r\|]{2,45})",
        ],
    )
    if not city:
        for known_city in ("Gurgaon", "Gurugram", "Noida", "Delhi", "Bangalore", "Bengaluru", "Mumbai", "Hyderabad", "Pune", "Lucknow", "Chennai"):
            if re.search(rf"\b{known_city}\b", combined, re.I):
                city = known_city
                break
    if city:
        fields["current_city"] = city

    # 6. Family & Contacts
    father = _find_pattern(combined, [r"(?:father(?:'s)?\s*(?:name|occupation|details)?|father)\s*[:\-–]\s*([^\n\r]{3,85})"])
    if father:
        fields["father_details"] = father

    mother = _find_pattern(combined, [r"(?:mother(?:'s)?\s*(?:name|occupation|details)?|mother)\s*[:\-–]\s*([^\n\r]{3,85})"])
    if mother:
        fields["mother_details"] = mother

    siblings = _find_pattern(combined, [r"(?:siblings?|brothers?|sisters?)\s*[:\-–]\s*([^\n\r]{2,85})"])
    if siblings:
        fields["siblings_details"] = siblings

    phones = re.findall(r"(?:\+91[\s\-]?)?([6-9]\d{9})\b", combined)
    if phones:
        fields["primary_contact_phone"] = phones[0]
        if len(phones) > 1:
            fields["candidate_phone"] = phones[1]

    if source_name:
        fields["source_name"] = source_name
    if source_channel:
        fields["source_channel"] = source_channel

    # Gotra clash check
    gotra_alert = None
    if fields.get("gotra") and excluded_gotras:
        g_low = fields["gotra"].lower()
        for ex in excluded_gotras:
            if ex.strip().lower() in g_low:
                gotra_alert = f"Gotra Clash Warning: Candidate Gotra '{fields['gotra']}' matches excluded Gotra '{ex}'."
                fields["gotra_clash_alert"] = gotra_alert
                break

    # Disambiguation tag
    tag_bits = [
        fields.get("occupation") or fields.get("education"),
        fields.get("company"),
        fields.get("current_city"),
        fields.get("height"),
        f"via {fields['source_name']}" if fields.get("source_name") else None,
    ]
    fields["disambiguation_tag"] = " · ".join(str(x) for x in tag_bits if x)[:90] or "Queued for Mac AI Deep Review"

    missing_q = []
    if not fields.get("time_of_birth") or not fields.get("place_of_birth"):
        missing_q.append("Exact Time of Birth and Place of Birth for Kundli matching")
    if not fields.get("relocation_openness"):
        missing_q.append("Preferred future city & work-location flexibility")
    if not fields.get("gotra"):
        missing_q.append("Family Gotra and community details")

    cand_name = fields.get("full_name") or (existing_profile or {}).get("full_name") or "Candidate"
    outbound = settings.get("my_outbound_pack") or {}
    sister_bio = outbound.get("shareable_whatsapp_bio") or "Namaste! Sharing my sister's profile details."

    return {
        "extracted_fields": fields,
        "field_provenance": {k: "Offline Smart Parser (Queued for Mac AI)" for k in fields.keys()},
        "interaction_summary": (
            f"Captured details for {cand_name} while Mac AI Worker was offline. "
            "Basic fields extracted immediately; queued for deep Mac AI Vision/Audio enrichment when Mac connects."
        ),
        "voice_transcript": "",
        "gotra_clash_alert": gotra_alert,
        "ai_fit_score": 76 if not gotra_alert else 45,
        "fit_summary": (
            f"Initial offline extraction for {cand_name} ({fields['disambiguation_tag']}). "
            "Deep AI fit scoring will auto-update as soon as your Mac AI Worker comes online."
        ),
        "positives": [x for x in [fields.get("education"), fields.get("company"), fields.get("current_city")] if x],
        "concerns": [gotra_alert] if gotra_alert else [],
        "missing_questions": missing_q,
        "pre_call_brief": (
            f"• Candidate: {cand_name} ({fields['disambiguation_tag']})\n"
            f"• Package: {fields.get('annual_ctc') or 'Ask on call'}\n"
            f"• Ask next: {'; '.join(missing_q)}"
        ),
        "suggested_status": "Reviewing",
        "suggested_ball_in_court": "us",
        "suggested_follow_up": {
            "task": f"Review {cand_name}'s details & share Sister's biodata / ask for Kundli",
            "due_days": 2,
            "assigned_to": "Family",
        },
        "draft_whatsapp_replies": {
            "first_time_share_sister_bio": f"Namaste! 🙏 We received {cand_name}'s profile and would love to take this forward.\n\n{sister_bio}",
            "ask_missing_info": f"Namaste! 🙏 Thank you for sharing {cand_name}'s biodata. Could you please share his exact Time & Place of Birth for Kundli matching?",
            "followup_check_in": f"Namaste! 🙏 Just following up to check if your family had a chance to review my sister's profile regarding {cand_name}.",
            "polite_pass": f"Namaste! 🙏 Thank you for sharing {cand_name}'s profile. After discussing at home, we feel a few parameters may not align right now. Wishing your family the very best!",
        },
        "embedding": None,
        "pending_mac_ai": True,
        "models_used": {"offline_parser": "Instant Deterministic Parser (Queued for Mac AI)"},
    }


def offline_compare_profiles(profiles: list[dict]) -> dict:
    ranked = sorted(profiles, key=lambda p: (p.get("ai_fit_score") or 0), reverse=True)
    names = ", ".join(p.get("full_name") or "Candidate" for p in ranked)
    top = ranked[0] if ranked else {}
    return {
        "executive_summary": (
            f"Side-by-side comparison across {len(profiles)} shortlisted profiles ({names}). "
            f"Currently {top.get('full_name', 'the top candidate')} leads with a {top.get('ai_fit_score') or 75}% fit score "
            f"({top.get('occupation') or ''} at {top.get('company') or 'N/A'}, {top.get('current_city') or 'N/A'})."
        ),
        "ranking_recommendation": [
            {
                "profile_id": p["id"],
                "full_name": p.get("full_name"),
                "standout_edge": f"{p.get('occupation') or ''} {p.get('company') or ''} ({p.get('annual_ctc') or 'CTC N/A'}) in {p.get('current_city') or 'N/A'}",
                "key_tradeoff_or_question": (p.get("missing_questions") or ["Verify Kundli & relocation openness"])[0],
            }
            for p in ranked
        ],
        "dimension_winners": {
            "career_and_education": " | ".join(f"{p.get('full_name')}: {p.get('education') or '—'} / {p.get('company') or '—'} ({p.get('annual_ctc') or '—'})" for p in ranked),
            "location_and_lifestyle": " | ".join(f"{p.get('full_name')}: {p.get('current_city') or '—'} ({p.get('diet') or '—'})" for p in ranked),
            "family_and_cultural_alignment": " | ".join(f"{p.get('full_name')}: Gotra {p.get('gotra') or '—'}, Kundli {p.get('kundli_status') or 'Not Checked'}" for p in ranked),
            "immediate_next_step": f"Prioritize family call / Kundli check with {top.get('full_name', 'top shortlisted candidate')}.",
        },
        "model_used": "Instant Offline Comparator (Mac AI Offline)",
    }


def offline_quick_parse_meeting(text: str) -> dict:
    low = text.lower()
    mtype = "Family Phone Call"
    if "video" in low or "zoom" in low or "meet" in low:
        mtype = "Video Call"
    elif "cafe" in low or "coffee" in low or "person" in low or "hotel" in low:
        mtype = "In-Person Meetup"
    elif "1:1" in low or "sister" in low:
        mtype = "1:1 Prospect Call"

    dt = datetime.now() + timedelta(days=1)
    hour, minute = 19, 30
    hm = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
    if hm:
        h = int(hm.group(1))
        m = int(hm.group(2) or 0)
        ampm = hm.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        hour, minute = h, m

    sched = dt.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    return {
        "stage": "scheduled",
        "meeting_type": mtype,
        "title": text[:60],
        "proposed_slots_text": "",
        "scheduled_at": sched,
        "location_or_link": "Phone / WhatsApp Call",
        "participants": "Saurabh, Mummy & Prospect Family",
        "pre_meeting_notes": text,
        "model_used": "Instant Offline Parser",
    }
