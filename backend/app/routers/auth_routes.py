import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from ..auth import create_session_token, get_current_member, require_owner
from ..config import CERTS_DIR, MODEL_PRESETS, get_network_info
from ..db import get_app_settings, get_conn, hash_pin, utc_now
from ..models import (
    CreateMemberRequest,
    LoginRequest,
    RelativeCreateOrUpdate,
    UpdateMemberRequest,
    UpdatePinRequest,
)
from ..services.dedupe import normalize_phone

router = APIRouter(prefix="/api", tags=["auth"])

# Brute-force rate limiter per IP (max 5 failed attempts in 5 minutes)
_failed_login_attempts: dict[str, list[float]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300


@router.get("/auth/members")
def list_members():
    conn = get_conn()
    conn.execute("DELETE FROM members WHERE lower(name) IN ('papa', 'father')")
    conn.commit()
    rows = conn.execute("SELECT id, name, role, avatar_color, created_at FROM members ORDER BY id ASC").fetchall()
    conn.close()
    return {"members": [dict(r) for r in rows]}


@router.post("/auth/login")
def login(req: LoginRequest, request: Request, response: Response):
    client_ip = (request.client.host if request.client else "unknown")
    now_ts = time.time()
    recent_fails = [t for t in _failed_login_attempts.get(client_ip, []) if now_ts - t < LOCKOUT_WINDOW_SECONDS]
    _failed_login_attempts[client_ip] = recent_fails

    if len(recent_fails) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many failed PIN attempts. Please wait 5 minutes before trying again.",
        )

    conn = get_conn()
    row = conn.execute(
        "SELECT id, name, role, avatar_color, pin_hash FROM members WHERE lower(name) = lower(?)",
        (req.member_name.strip(),),
    ).fetchone()
    conn.close()

    if not row or row["pin_hash"] != hash_pin(req.pin):
        recent_fails.append(now_ts)
        _failed_login_attempts[client_ip] = recent_fails
        raise HTTPException(status_code=401, detail="Invalid PIN for selected member.")

    _failed_login_attempts.pop(client_ip, None)

    member = {
        "id": row["id"],
        "name": row["name"],
        "role": row["role"],
        "avatar_color": row["avatar_color"],
    }
    token = create_session_token(member)
    response.set_cookie(
        key="rishta_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
    )
    return {"token": token, "member": member}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("rishta_session")
    return {"ok": True}


@router.get("/auth/me")
def get_me(member: dict = Depends(get_current_member)):
    return {"member": member, "network": get_network_info()}


@router.post("/auth/members")
def add_family_member(req: CreateMemberRequest, member: dict = Depends(get_current_member)):
    require_owner(member)
    role = "owner" if req.role == "owner" else "family"
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO members (name, role, avatar_color, pin_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (req.name.strip(), role, req.avatar_color, hash_pin(req.pin), utc_now()),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Could not create member: {exc}")
    conn.close()
    return {"id": new_id, "name": req.name.strip(), "role": role, "avatar_color": req.avatar_color}


@router.put("/auth/members/{member_id}")
def update_family_member(
    member_id: int, req: UpdateMemberRequest, member: dict = Depends(get_current_member)
):
    require_owner(member)
    conn = get_conn()
    row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Member not found")

    new_name = (req.name or row["name"]).strip()
    new_role = req.role if req.role in ("owner", "family") else row["role"]
    new_color = req.avatar_color or row["avatar_color"]
    new_pin_hash = hash_pin(req.pin) if req.pin and req.pin.strip() else row["pin_hash"]

    conn.execute(
        "UPDATE members SET name = ?, role = ?, avatar_color = ?, pin_hash = ? WHERE id = ?",
        (new_name, new_role, new_color, new_pin_hash, member_id),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT id, name, role, avatar_color, created_at FROM members WHERE id = ?", (member_id,)
    ).fetchone()
    conn.close()
    return dict(updated)


@router.delete("/auth/members/{member_id}")
def delete_family_member(member_id: int, member: dict = Depends(get_current_member)):
    require_owner(member)
    conn = get_conn()
    row = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Member not found")
    if row["name"].lower() == "saurabh":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot delete primary Owner account (Saurabh).")
    conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.put("/auth/pin")
def update_pin(req: UpdatePinRequest, member: dict = Depends(get_current_member)):
    if member["role"] != "owner" and member["name"].lower() != req.member_name.strip().lower():
        raise HTTPException(status_code=403, detail="Only the Owner or the member themselves can update this PIN.")
    conn = get_conn()
    conn.execute(
        "UPDATE members SET pin_hash = ? WHERE lower(name) = lower(?)",
        (hash_pin(req.new_pin), req.member_name.strip()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/relatives")
def list_relatives(member: dict = Depends(get_current_member)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM relatives ORDER BY name ASC").fetchall()
    prof_counts = conn.execute(
        """
        SELECT lower(source_name) as sname,
               COUNT(*) as total_count,
               SUM(CASE WHEN status NOT IN ('Passed', 'Archived') THEN 1 ELSE 0 END) as active_count
        FROM profiles
        WHERE source_name IS NOT NULL AND trim(source_name) != ''
        GROUP BY lower(source_name)
        """
    ).fetchall()
    conn.close()

    counts_map = {r["sname"]: dict(r) for r in prof_counts}
    out = []
    for r in rows:
        d = dict(r)
        c = counts_map.get(d["name"].strip().lower(), {})
        d["total_profiles"] = c.get("total_count", 0)
        d["active_profiles"] = c.get("active_count", 0)
        digits = normalize_phone(d.get("phone"))
        d["wa_link"] = f"https://wa.me/91{digits}" if len(digits) == 10 else None
        out.append(d)
    return {"relatives": out}


@router.post("/relatives")
def create_relative(req: RelativeCreateOrUpdate, member: dict = Depends(get_current_member)):
    conn = get_conn()
    now = utc_now()
    try:
        cur = conn.execute(
            """
            INSERT INTO relatives (name, relation, side, phone, city, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.name.strip(),
                req.relation.strip(),
                req.side.strip(),
                (req.phone or "").strip(),
                (req.city or "").strip(),
                (req.notes or "").strip(),
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Relative with that name already exists or invalid: {exc}")
    row = conn.execute("SELECT * FROM relatives WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return dict(row)


@router.put("/relatives/{relative_id}")
def update_relative(
    relative_id: int, req: RelativeCreateOrUpdate, member: dict = Depends(get_current_member)
):
    conn = get_conn()
    old_row = conn.execute("SELECT * FROM relatives WHERE id = ?", (relative_id,)).fetchone()
    if not old_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Relative not found")

    old_name = old_row["name"]
    now = utc_now()
    conn.execute(
        """
        UPDATE relatives
        SET name = ?, relation = ?, side = ?, phone = ?, city = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            req.name.strip(),
            req.relation.strip(),
            req.side.strip(),
            (req.phone or "").strip(),
            (req.city or "").strip(),
            (req.notes or "").strip(),
            now,
            relative_id,
        ),
    )
    conn.execute(
        """
        UPDATE profiles
        SET source_name = ?, source_phone = CASE WHEN ? != '' THEN ? ELSE source_phone END
        WHERE lower(source_name) = lower(?)
        """,
        (req.name.strip(), (req.phone or "").strip(), (req.phone or "").strip(), old_name),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM relatives WHERE id = ?", (relative_id,)).fetchone()
    conn.close()
    return dict(updated)


@router.delete("/relatives/{relative_id}")
def delete_relative(relative_id: int, member: dict = Depends(get_current_member)):
    conn = get_conn()
    conn.execute("DELETE FROM relatives WHERE id = ?", (relative_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/setup/info")
def setup_info(member: dict = Depends(get_current_member)):
    settings = get_app_settings()
    active_preset = settings.get("ai_preset", "balanced")
    return {
        "network": get_network_info(),
        "active_ai_preset": active_preset,
        "ai_presets": MODEL_PRESETS,
    }


@router.get("/setup/ca.crt")
def download_ca_cert():
    ca_path = CERTS_DIR / "rishta-local-ca.crt"
    if not ca_path.exists():
        raise HTTPException(status_code=404, detail="Local Root CA certificate not generated yet.")
    return FileResponse(
        str(ca_path),
        media_type="application/x-x509-ca-cert",
        filename="rishta-local-ca.crt",
    )
