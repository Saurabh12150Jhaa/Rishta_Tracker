import json
import math
import re
from difflib import SequenceMatcher
from typing import Optional
from ..db import get_conn


def normalize_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"\b(ms|miss|mr|dr|shri|smt|er|ca)\b\.?", "", name.lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    return " ".join(cleaned.split())


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_profile_embedding_text(fields: dict) -> str:
    parts = [
        f"Name: {fields.get('full_name') or ''}",
        f"DOB: {fields.get('dob') or ''} Age: {fields.get('age') or ''}",
        f"Birthplace: {fields.get('place_of_birth') or ''} Hometown: {fields.get('hometown') or ''}",
        f"City: {fields.get('current_city') or ''}",
        f"Education: {fields.get('education') or ''} {fields.get('college') or ''}",
        f"Work: {fields.get('occupation') or ''} at {fields.get('company') or ''}",
        f"Family: Father {fields.get('father_details') or ''} Mother {fields.get('mother_details') or ''}",
        f"Gotra: {fields.get('gotra') or ''} Community: {fields.get('caste_community') or ''}",
    ]
    return " | ".join(p for p in parts if p.strip())


def find_duplicate_candidates(
    extracted_fields: dict,
    candidate_embedding: Optional[list[float]] = None,
    exclude_profile_id: Optional[int] = None,
) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, full_name, dob, age, current_city, company, occupation,
               gotra, source_name, status, pass_reason, updated_at,
               primary_contact_phone, candidate_phone, embedding_json
        FROM profiles
        """
    ).fetchall()
    conn.close()

    ext_name = normalize_name(extracted_fields.get("full_name"))
    ext_dob = (extracted_fields.get("dob") or "").strip()
    ext_phones = {
        p
        for p in (
            normalize_phone(extracted_fields.get("primary_contact_phone")),
            normalize_phone(extracted_fields.get("candidate_phone")),
        )
        if len(p) >= 10
    }
    ext_company = (extracted_fields.get("company") or "").strip().lower()
    ext_city = (extracted_fields.get("current_city") or "").strip().lower()

    matches = []
    for row in rows:
        if exclude_profile_id and row["id"] == exclude_profile_id:
            continue

        reasons = []
        score = 0.0

        row_phones = {
            p
            for p in (
                normalize_phone(row["primary_contact_phone"]),
                normalize_phone(row["candidate_phone"]),
            )
            if len(p) >= 10
        }
        if ext_phones and row_phones and (ext_phones & row_phones):
            score += 0.65
            reasons.append("Exact phone number match")

        row_name = normalize_name(row["full_name"])
        if ext_name and row_name:
            name_sim = SequenceMatcher(None, ext_name, row_name).ratio()
            if name_sim >= 0.88:
                score += 0.45
                reasons.append(f"Name match ({int(name_sim * 100)}%)")
            elif name_sim >= 0.72:
                score += 0.25
                reasons.append(f"Similar name ({int(name_sim * 100)}%)")

        if ext_dob and row["dob"] and ext_dob == row["dob"].strip():
            score += 0.35
            reasons.append(f"Same DOB ({ext_dob})")

        if ext_company and row["company"] and ext_company in row["company"].lower():
            score += 0.15
            reasons.append(f"Same company ({row['company']})")

        if ext_city and row["current_city"] and ext_city == row["current_city"].lower():
            score += 0.10

        emb_sim = 0.0
        if candidate_embedding and row["embedding_json"]:
            try:
                row_emb = json.loads(row["embedding_json"])
                emb_sim = cosine_similarity(candidate_embedding, row_emb)
                if emb_sim >= 0.82:
                    score = max(score, emb_sim)
                    reasons.append(f"High AI profile similarity ({int(emb_sim * 100)}%)")
            except Exception:
                pass

        if score >= 0.45 or emb_sim >= 0.82:
            previously_passed_warning = None
            if row["status"] == "Passed":
                previously_passed_warning = (
                    f"Previously marked Passed ({row['pass_reason'] or 'No reason recorded'})"
                )
            matches.append(
                {
                    "profile_id": row["id"],
                    "full_name": row["full_name"],
                    "current_city": row["current_city"],
                    "company": row["company"],
                    "occupation": row["occupation"],
                    "source_name": row["source_name"],
                    "status": row["status"],
                    "pass_reason": row["pass_reason"],
                    "previously_passed_warning": previously_passed_warning,
                    "confidence": round(min(score, 0.99), 2),
                    "reasons": reasons,
                }
            )

    matches.sort(key=lambda m: m["confidence"], reverse=True)
    return matches[:5]
