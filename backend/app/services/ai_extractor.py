import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
import httpx
from ..config import ZLLAMA_API_KEY, ZLLAMA_BASE_URL, MODEL_PRESETS
from ..db import get_app_settings
from .dedupe import build_profile_embedding_text
from .offline_extractor import (
    offline_compare_profiles,
    offline_extract_rishta_bundle,
)


def _strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return text[start : end + 1]
    return text


def get_active_preset_config() -> dict:
    settings = get_app_settings()
    preset_key = settings.get("ai_preset", "balanced")
    return MODEL_PRESETS.get(preset_key, MODEL_PRESETS["balanced"])


def _call_zllama_chat(
    model_chain: list[str],
    messages: list[dict[str, Any]],
    expect_json: bool = True,
    timeout: float = 45.0,
) -> tuple[dict | str, str]:
    if not ZLLAMA_API_KEY:
        raise RuntimeError("ZLLAMA_API_KEY is missing in .env")

    last_error = None
    url = f"{ZLLAMA_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ZLLAMA_API_KEY}",
        "Content-Type": "application/json",
    }

    for model in model_chain:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.15,
        }
        if "gemini-3" in model:
            payload["reasoning_effort"] = "low"
        if expect_json and model.startswith("gpt-"):
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError(f"Empty choices returned from {model}")
                content = choices[0].get("message", {}).get("content") or ""
                if expect_json:
                    cleaned = _strip_json_fences(content)
                    return json.loads(cleaned), model
                return content.strip(), model
        except Exception as exc:
            last_error = f"{model}: {exc}"
            continue

    raise RuntimeError(f"All models in chain {model_chain} failed. Last error: {last_error}")


def compute_embedding(text: str) -> tuple[Optional[list[float]], Optional[str]]:
    if not text.strip() or not ZLLAMA_API_KEY:
        return None, None
    preset = get_active_preset_config()
    url = f"{ZLLAMA_BASE_URL.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {ZLLAMA_API_KEY}",
        "Content-Type": "application/json",
    }
    for model in preset["embedding_chain"]:
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(url, headers=headers, json={"model": model, "input": text[:6000]})
                resp.raise_for_status()
                emb = resp.json()["data"][0]["embedding"]
                return emb, model
        except Exception:
            continue
    return None, None


def transcribe_voice_note_hinglish(mp3_b64: str, context_hint: str = "") -> tuple[str, str]:
    preset = get_active_preset_config()
    prompt = (
        "You are an expert bilingual Indian Hinglish (Hindi + English) transcriber for family matrimonial/rishta voice notes and call recaps.\n"
        "1. Transcribe the spoken audio accurately in clean Romanized Hinglish / English.\n"
        "2. Preserve all exact proper nouns, numbers, salaries (LPA/CTC), heights, cities, companies, birth times, Gotra, Manglik details, and family opinions.\n"
        f"Context hint: {context_hint}\n"
        "Return JSON with keys: {\"transcript\": \"...\", \"key_points\": [\"...\"]}"
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {"data": mp3_b64, "format": "mp3"}},
            ],
        }
    ]
    res, model_used = _call_zllama_chat(preset["audio_transcribe_chain"], messages, expect_json=True, timeout=60.0)
    if isinstance(res, dict):
        transcript = res.get("transcript") or ""
        pts = res.get("key_points") or []
        if pts:
            transcript = f"{transcript}\nKey audio takeaways: " + "; ".join(str(p) for p in pts)
        return transcript.strip(), model_used
    return str(res), model_used


def check_gotra_clash(extracted_gotra: Optional[str], excluded_gotras: list[str]) -> Optional[str]:
    if not extracted_gotra or not excluded_gotras:
        return None
    g_norm = extracted_gotra.strip().lower()
    if not g_norm or g_norm in ("unknown", "n/a", "none", "-"):
        return None
    for ex in excluded_gotras:
        ex_norm = ex.strip().lower()
        if ex_norm and (ex_norm in g_norm or g_norm in ex_norm):
            return f"Gotra Clash Warning: Candidate Gotra '{extracted_gotra}' matches excluded Gotra '{ex}'."
    return None


def build_disambiguation_tag(fields: dict) -> str:
    parts = []
    occ = fields.get("occupation")
    comp = fields.get("company")
    if occ and comp:
        parts.append(f"{occ} at {comp}")
    elif comp:
        parts.append(comp)
    elif occ:
        parts.append(occ)
    elif fields.get("education"):
        parts.append(fields["education"])

    if fields.get("current_city"):
        parts.append(fields["current_city"])
    elif fields.get("hometown"):
        parts.append(fields["hometown"])

    if fields.get("height"):
        parts.append(str(fields["height"]))

    if fields.get("source_name"):
        parts.append(f"via {fields['source_name']}")
    return " · ".join(parts[:4]) or "Needs Profile Review"


def extract_rishta_bundle(
    raw_text: str = "",
    pdf_texts: Optional[list[str]] = None,
    image_data_urls: Optional[list[str]] = None,
    audio_mp3_b64_list: Optional[list[str]] = None,
    source_name: Optional[str] = None,
    source_channel: Optional[str] = None,
    existing_profile: Optional[dict] = None,
) -> dict:
    preset = get_active_preset_config()
    settings = get_app_settings()
    prefs = settings.get("partner_preferences", {})
    excluded_gotras = prefs.get("excluded_gotras") or []

    models_used: dict[str, str] = {}
    voice_transcripts: list[str] = []

    for idx, mp3_b64 in enumerate(audio_mp3_b64_list or []):
        if mp3_b64:
            try:
                t_text, audio_model = transcribe_voice_note_hinglish(
                    mp3_b64, context_hint=source_name or (existing_profile or {}).get("full_name", "")
                )
                voice_transcripts.append(t_text)
                models_used["audio_transcription"] = audio_model
            except Exception as exc:
                voice_transcripts.append(f"[Audio transcription error on clip {idx + 1}: {exc}]")

    combined_voice_transcript = "\n\n".join(voice_transcripts).strip()

    existing_snapshot = {}
    if existing_profile:
        existing_snapshot = {
            k: v
            for k, v in existing_profile.items()
            if v not in (None, "", [], "{}") and k not in ("embedding_json", "private_notes")
        }

    vision_prompt = f"""You are an elite Indian Matrimonial (Rishta) Intelligence Extractor.
Extract structured candidate facts from the provided WhatsApp text, biodata PDF text/page images, and Hinglish call/voice transcripts.

STRICT ANTI-HALLUCINATION RULES:
1. NEVER invent or guess values that are not explicitly present in the inputs. Use null if a field is not mentioned.
2. Convert Hinglish/Hindi terms accurately (e.g., 'Maanglik'/'Anshik Manglik', 'Gotra', 'Janam samay' -> time_of_birth, 'Janam sthan' -> place_of_birth, package/CTC in LPA).
3. If updating an existing profile, extract ONLY the newly discovered or updated facts from this interaction while keeping consistency with the existing profile snapshot.

Partner Preferences & Criteria for Evaluation:
{json.dumps(prefs, indent=2)}

Existing Profile Snapshot (if updating):
{json.dumps(existing_snapshot, indent=2) if existing_snapshot else "None (New Candidate)"}

Source Hint: source_name={source_name!r}, source_channel={source_channel!r}

Return a valid JSON object matching this EXACT structure:
{{
  "extracted_fields": {{
    "full_name": "string or null",
    "gender": "Female | Male | null",
    "dob": "YYYY-MM-DD or DD MMM YYYY string or null",
    "age": 27,
    "time_of_birth": "e.g. 04:35 AM or null",
    "place_of_birth": "City, State or null",
    "height": "e.g. 5'4\\" or null",
    "marital_status": "Never Married | Divorced | null",
    "diet": "Vegetarian | Non-Vegetarian | Eggetarian | Vegan | null",
    "smoking_drinking": "Non-smoker / Non-drinker | Social | null",
    "education": "Highest degree e.g. MBA, B.Tech, CA or null",
    "college": "Institutions attended or null",
    "occupation": "Role/Title e.g. Senior Product Manager or null",
    "company": "Current employer or null",
    "annual_ctc": "e.g. 32 LPA or null",
    "work_mode": "Hybrid | Remote | On-site | null",
    "current_city": "Current city of residence or null",
    "hometown": "Native place / hometown or null",
    "relocation_openness": "Open to NCR/Bangalore/Abroad etc. or null",
    "father_details": "Father's name & occupation or null",
    "mother_details": "Mother's name & occupation or null",
    "siblings_details": "Brothers/sisters & marital/work status or null",
    "family_type": "Nuclear | Joint | null",
    "family_location": "Where parents live or null",
    "caste_community": "e.g. Brahmin, Kayastha, Aggarwal, etc. or null",
    "sub_caste": "Sub-caste or null",
    "gotra": "Gotra or null",
    "manglik": "No | Yes | Anshik | Unknown",
    "kundli_status": "Not Checked | At Panditji | Matched | Concern | Not Needed",
    "kundli_gunas": "e.g. 28/36 or null",
    "kundli_notes": "Any kundli/astro notes mentioned or null",
    "source_channel": "Relative | Marriage Bureau | Matrimonial App | Direct / Friend",
    "source_name": "Name of relative/mediator/app or null",
    "source_phone": "Mediator phone if mentioned or null",
    "primary_contact_name": "Parent/guardian contact name or null",
    "primary_contact_relation": "Father | Mother | Brother | Self | Mediator | null",
    "primary_contact_phone": "Phone number of parent/contact or null",
    "candidate_phone": "Candidate's direct phone if mentioned or null",
    "linkedin_or_social": "LinkedIn/Instagram handle or URL if mentioned or null"
  }},
  "field_provenance": {{
    "field_name": "Biodata PDF | WhatsApp Message | Voice Note | Call Note"
  }},
  "interaction_summary": "Concise 2-3 sentence summary of what was received or discussed in this import/note."
}}
"""

    text_blocks = []
    if raw_text and raw_text.strip():
        text_blocks.append(f"=== Pasted WhatsApp / Call Note Text ===\n{raw_text.strip()}")
    if pdf_texts:
        for i, pt in enumerate(pdf_texts):
            if pt.strip():
                text_blocks.append(f"=== Biodata PDF #{i+1} Embedded Text ===\n{pt.strip()}")
    if combined_voice_transcript:
        text_blocks.append(f"=== Voice Note Hinglish Transcript ===\n{combined_voice_transcript}")

    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": vision_prompt + "\n\n" + "\n\n".join(text_blocks)}
    ]
    for data_url in (image_data_urls or [])[:6]:
        user_content.append({"type": "image_url", "image_url": {"url": data_url}})

    try:
        vision_json, vision_model = _call_zllama_chat(
            preset["vision_extract_chain"],
            [{"role": "user", "content": user_content}],
            expect_json=True,
            timeout=55.0,
        )
        models_used["vision_extraction"] = vision_model
    except Exception:
        return offline_extract_rishta_bundle(
            raw_text=raw_text,
            pdf_texts=pdf_texts,
            source_name=source_name,
            source_channel=source_channel,
            existing_profile=existing_profile,
        )

    extracted_fields = (vision_json.get("extracted_fields") if isinstance(vision_json, dict) else {}) or {}
    if source_name and not extracted_fields.get("source_name"):
        extracted_fields["source_name"] = source_name
    if source_channel and not extracted_fields.get("source_channel"):
        extracted_fields["source_channel"] = source_channel

    merged_preview = {**existing_snapshot, **{k: v for k, v in extracted_fields.items() if v is not None}}
    gotra_alert = check_gotra_clash(merged_preview.get("gotra"), excluded_gotras)
    if gotra_alert:
        extracted_fields["gotra_clash_alert"] = gotra_alert

    extracted_fields["disambiguation_tag"] = build_disambiguation_tag(merged_preview)

    # Stage 3: Specialist Cultural & Fit Reasoning Advisor (claude-sonnet-4-6 / opus-4-6)
    advisor_prompt = f"""You are a thoughtful, culturally perceptive Indian family rishta advisor assisting Saurabh, his mother (Mummy), and his sister in finding a suitable groom/match for Saurabh's sister.
Given the candidate profile, latest interaction, and the family's partner preferences for Saurabh's sister, provide a sharp, honest evaluation and practical next steps in JSON.

Partner Preferences (for Saurabh's Sister):
{json.dumps(prefs, indent=2)}

Candidate Profile Facts:
{json.dumps(merged_preview, indent=2)}

Latest Interaction Summary:
{vision_json.get("interaction_summary") if isinstance(vision_json, dict) else ""}

Voice Transcript (if any):
{combined_voice_transcript}

Gotra Clash Alert:
{gotra_alert or "None"}

Return a valid JSON object with these exact keys:
{{
  "ai_fit_score": 0 to 100 integer based on alignment with preferences,
  "fit_summary": "2-3 sentence objective assessment of alignment, strengths, and open questions for Saurabh's sister.",
  "positives": ["3-5 specific positive highlights"],
  "concerns": ["Any dealbreakers, mismatches, or ambiguities to watch out for"],
  "missing_questions": ["3-5 high-value missing questions to ask on the next call or via WhatsApp (e.g., exact time/place of birth for kundli, work location flexibility, career plans)"],
  "pre_call_brief": "Compact 4-bullet cheat sheet for Saurabh or Mummy right before getting on a phone call with this family.",
  "suggested_status": "New | Reviewing | Kundli Pending | Info Needed | Talking | Meetup | Shortlisted | On Hold | Passed",
  "suggested_ball_in_court": "us | them | mediator",
  "suggested_follow_up": {{
    "task": "Specific next action e.g. 'Share sister biodata & ask family for birth time/place for Kundli'",
    "due_days": 2,
    "assigned_to": "Saurabh | Mummy | Sister | Family"
  }},
  "draft_whatsapp_replies": {{
    "first_time_share_sister_bio": "Warm first-time outreach message from Saurabh/Mummy sharing Sister's details and initiating conversation",
    "ask_missing_info": "Polite message asking for missing details (e.g., kundli birth time/place or work location preference)",
    "followup_check_in": "Warm consecutive follow-up asking if they had a chance to review Sister's profile / kundli and suggesting a call",
    "brother_to_prospect_direct": "Friendly, modern message from Saurabh (brother) directly to the prospect to set up a quick intro chat",
    "polite_pass": "Gracious, respectful Indian family decline message wishing them the very best"
  }}
}}
"""
    emb_text = build_profile_embedding_text(merged_preview)

    def _run_advisor():
        return _call_zllama_chat(
            preset["reasoning_advisor_chain"],
            [{"role": "user", "content": advisor_prompt}],
            expect_json=True,
            timeout=35.0,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_adv = pool.submit(_run_advisor)
        fut_emb = pool.submit(compute_embedding, emb_text)
        try:
            advisor_json, advisor_model = fut_adv.result()
            models_used["reasoning_advisor"] = advisor_model
        except Exception:
            advisor_json = {}
        emb_vec, emb_model = fut_emb.result()

    if not isinstance(advisor_json, dict):
        advisor_json = {}
    if emb_model:
        models_used["embedding"] = emb_model

    return {
        "extracted_fields": extracted_fields,
        "field_provenance": (vision_json.get("field_provenance") if isinstance(vision_json, dict) else {}) or {},
        "interaction_summary": (vision_json.get("interaction_summary") if isinstance(vision_json, dict) else "") or "",
        "voice_transcript": combined_voice_transcript,
        "gotra_clash_alert": gotra_alert,
        "ai_fit_score": advisor_json.get("ai_fit_score", 75),
        "fit_summary": advisor_json.get("fit_summary", ""),
        "positives": advisor_json.get("positives") or [],
        "concerns": advisor_json.get("concerns") or ([gotra_alert] if gotra_alert else []),
        "missing_questions": advisor_json.get("missing_questions") or [],
        "pre_call_brief": advisor_json.get("pre_call_brief", ""),
        "suggested_status": advisor_json.get("suggested_status", "Reviewing"),
        "suggested_ball_in_court": advisor_json.get("suggested_ball_in_court", "us"),
        "suggested_follow_up": advisor_json.get("suggested_follow_up")
        or {"task": "Review extracted biodata & decide next step", "due_days": 2, "assigned_to": "Family"},
        "draft_whatsapp_replies": advisor_json.get("draft_whatsapp_replies") or {},
        "embedding": emb_vec,
        "models_used": models_used,
    }


def compare_profiles_ai(profiles: list[dict]) -> dict:
    preset = get_active_preset_config()
    settings = get_app_settings()
    prefs = settings.get("partner_preferences", {})

    compact = [
        {
            "id": p["id"],
            "full_name": p["full_name"],
            "age": p.get("age"),
            "height": p.get("height"),
            "current_city": p.get("current_city"),
            "relocation_openness": p.get("relocation_openness"),
            "education": p.get("education"),
            "occupation": p.get("occupation"),
            "company": p.get("company"),
            "annual_ctc": p.get("annual_ctc"),
            "family": f"Father: {p.get('father_details')}; Mother: {p.get('mother_details')}; Siblings: {p.get('siblings_details')}",
            "gotra": p.get("gotra"),
            "manglik": p.get("manglik"),
            "kundli_status": p.get("kundli_status"),
            "source_name": p.get("source_name"),
            "status": p.get("status"),
            "ai_fit_score": p.get("ai_fit_score"),
            "fit_summary": p.get("fit_summary"),
        }
        for p in profiles
    ]

    prompt = f"""Compare these {len(compact)} shortlisted rishta candidates for Saurabh and his family based on their preferences.
Partner Preferences:
{json.dumps(prefs, indent=2)}

Candidates:
{json.dumps(compact, indent=2)}

Return a valid JSON object:
{{
  "executive_summary": "3-4 sentence high-level comparison for a family discussion.",
  "ranking_recommendation": [
    {{
      "profile_id": 1,
      "full_name": "Name",
      "standout_edge": "Why this profile stands out",
      "key_tradeoff_or_question": "Main open question or tradeoff to clarify"
    }}
  ],
  "dimension_winners": {{
    "career_and_education": "Brief comparison across candidates",
    "location_and_lifestyle": "Brief comparison across candidates",
    "family_and_cultural_alignment": "Brief comparison across candidates",
    "immediate_next_step": "Which family to call/meet first and why"
  }}
}}
"""
    try:
        res, model_used = _call_zllama_chat(
            preset["compare_chain"],
            [{"role": "user", "content": prompt}],
            expect_json=True,
            timeout=50.0,
        )
        if isinstance(res, dict):
            res["model_used"] = model_used
            return res
        return {"executive_summary": str(res), "model_used": model_used}
    except Exception:
        return offline_compare_profiles(profiles)


def split_whatsapp_chat_candidates(chat_text: str) -> tuple[list[dict], str]:
    if not chat_text or len(chat_text.strip()) < 40:
        return [], "none"
    preset = get_active_preset_config()
    prompt = f"""You are analyzing a WhatsApp chat export from an Indian family or marriage mediator thread.
Identify distinct matrimonial candidate profiles discussed in the chat text below.
If the entire chat is about only ONE candidate, return a list with 1 item.
If multiple candidates are shared across the thread, split them cleanly into separate items (up to 10 candidates).

WhatsApp Chat Text:
{chat_text[:24000]}

Return a valid JSON object:
{{
  "candidates": [
    {{
      "candidate_name_hint": "Name or identifier",
      "source_name_hint": "Sender or mediator name",
      "relevant_chat_excerpt": "All messages/bio details belonging to this candidate"
    }}
  ]
}}
"""
    res, model_used = _call_zllama_chat(
        preset["batch_triage_chain"],
        [{"role": "user", "content": prompt}],
        expect_json=True,
        timeout=45.0,
    )
    if isinstance(res, dict):
        return (res.get("candidates") or []), model_used
    return [], model_used


def segregate_and_match_upload_bundle(
    raw_text: str,
    pdf_summaries: list[dict],
    audio_transcripts: list[dict],
    image_names: list[dict],
    existing_profiles: list[dict],
) -> tuple[list[dict], str]:
    """
    Uses the strongest frontier reasoning model (gpt-5.4 -> claude-opus-4-6 -> claude-sonnet-4-6)
    to:
      1. Segregate an upload (text, multiple PDFs, voice note transcripts, or .zip contents) into 1..N distinct candidates.
      2. Accurately identify if each segregated candidate belongs to an EXISTING profile in the database.
    """
    compact_existing = [
        {
            "profile_id": p["id"],
            "full_name": p.get("full_name"),
            "age": p.get("age"),
            "dob": p.get("dob"),
            "current_city": p.get("current_city"),
            "hometown": p.get("hometown"),
            "company": p.get("company"),
            "occupation": p.get("occupation"),
            "education": p.get("education"),
            "gotra": p.get("gotra"),
            "father_details": p.get("father_details"),
            "source_name": p.get("source_name"),
            "primary_contact_phone": p.get("primary_contact_phone"),
            "candidate_phone": p.get("candidate_phone"),
            "status": p.get("status"),
        }
        for p in existing_profiles
    ]

    prompt = f"""You are the Lead Entity Resolution & Upload Segregation Architect for an Indian family Rishta Tracker.
Analyze all uploaded items below (WhatsApp text/chat logs, biodata PDF texts, voice note transcripts, and image filenames) alongside the Existing Profiles Database.

YOUR TWO CRITICAL TASKS:
1. SEGREGATE BY PERSON:
   - Determine how many distinct matrimonial candidates/prospects are present across the uploaded text, PDFs, and voice notes.
   - If the upload contains multiple PDFs for different people, OR if a WhatsApp chat / voice note discusses multiple different candidates, split them into separate items in `segregated_candidates` (1 item per distinct person).
   - If all uploaded files/notes are about the SAME single person, return 1 item combining them.
   - Assign each PDF (`pdf_indices`), image (`image_indices`), and relevant text/audio excerpt to the exact person it belongs to.

2. AUTO-LINK TO EXISTING PROFILES:
   - Compare each segregated candidate against `Existing Profiles Database` using Name (including first name or spelling variations), Father's name, Phone numbers, Company, Occupation, City, DOB/Age, Gotra, or Referring Relative.
   - If a candidate in the upload is clearly providing new/additional information, call notes, voice notes, or files for an EXISTING profile, set `matched_existing_profile_id` to that profile's `profile_id`, set `match_confidence` (0.0 to 1.0), and explain why in `match_reason`.
   - If the candidate is a brand-new person not in `Existing Profiles Database`, set `matched_existing_profile_id` to null.

Existing Profiles Database:
{json.dumps(compact_existing, indent=2) if compact_existing else "[] (No existing profiles yet)"}

Uploaded Text / WhatsApp Chat:
{(raw_text or "")[:20000]}

Uploaded Biodata PDFs:
{json.dumps(pdf_summaries, indent=2)}

Uploaded Voice Note / Call Transcripts:
{json.dumps(audio_transcripts, indent=2)}

Uploaded Image Files:
{json.dumps(image_names, indent=2)}

Return a valid JSON object matching this exact schema:
{{
  "segregated_candidates": [
    {{
      "candidate_name_hint": "Full name or best identifier of this person",
      "matched_existing_profile_id": 123,
      "match_confidence": 0.92,
      "match_reason": "Matched Existing Profile #123 (Name + Company + City / Phone)",
      "source_name_hint": "Mediator or relative name if mentioned, else null",
      "segregated_text": "All text/chat/call notes from the upload that pertain specifically to this candidate",
      "segregated_voice_transcript": "All voice transcript segments that pertain specifically to this candidate",
      "pdf_indices": [0],
      "image_indices": [0],
      "audio_indices": [0]
    }}
  ]
}}
"""
    frontier_chain = ["gpt-5.4", "claude-opus-4-6", "claude-sonnet-4-6"]
    res, model_used = _call_zllama_chat(
        frontier_chain,
        [{"role": "user", "content": prompt}],
        expect_json=True,
        timeout=45.0,
    )
    if isinstance(res, dict) and res.get("segregated_candidates"):
        return res["segregated_candidates"], model_used
    return [], model_used

