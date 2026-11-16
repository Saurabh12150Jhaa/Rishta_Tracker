import base64
import hashlib
import hmac
import json
import time
from typing import Optional
from fastapi import Header, HTTPException, Request
from .config import SESSION_SECRET
from .db import get_conn


def create_session_token(member: dict) -> str:
    payload = {
        "id": member["id"],
        "name": member["name"],
        "role": member["role"],
        "avatar_color": member.get("avatar_color", "terracotta"),
        "exp": int(time.time()) + 86400 * 30,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_session_token(token: str) -> Optional[dict]:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def get_current_member(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.cookies.get("rishta_session")

    member = verify_session_token(token) if token else None
    if not member:
        raise HTTPException(status_code=401, detail="Authentication required. Please select your member profile & PIN.")

    conn = get_conn()
    row = conn.execute("SELECT id, name, role, avatar_color FROM members WHERE id = ?", (member["id"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Member session no longer valid.")
    return dict(row)


def require_owner(member: dict) -> None:
    if member.get("role") != "owner":
        raise HTTPException(status_code=403, detail="This action is restricted to the Owner account.")


def sanitize_profile_for_member(profile: dict, member: dict) -> dict:
    out = dict(profile)
    out.pop("embedding_json", None)
    for json_col, out_key in (
        ("positives_json", "positives"),
        ("concerns_json", "concerns"),
        ("missing_questions_json", "missing_questions"),
    ):
        raw = out.pop(json_col, "[]")
        try:
            out[out_key] = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            out[out_key] = []

    if member.get("role") != "owner":
        out["private_notes"] = None
    return out
