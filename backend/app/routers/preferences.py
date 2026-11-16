from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from ..auth import get_current_member, require_owner
from ..config import MODEL_PRESETS, get_network_info
from ..db import create_sqlite_backup, get_app_settings, get_conn, update_app_settings
from ..services.ai_extractor import check_gotra_clash

router = APIRouter(prefix="/api", tags=["preferences"])


@router.get("/settings")
def read_settings(member: dict = Depends(get_current_member)):
    settings = get_app_settings()
    return {
        "settings": settings,
        "model_presets": MODEL_PRESETS,
        "network": get_network_info(),
    }


@router.put("/settings")
def save_settings(payload: dict[str, Any], member: dict = Depends(get_current_member)):
    updated = update_app_settings(payload)
    excluded_gotras = updated.get("partner_preferences", {}).get("excluded_gotras") or []

    conn = get_conn()
    rows = conn.execute("SELECT id, gotra FROM profiles").fetchall()
    for r in rows:
        alert = check_gotra_clash(r["gotra"], excluded_gotras)
        conn.execute("UPDATE profiles SET gotra_clash_alert = ? WHERE id = ?", (alert, r["id"]))
    conn.commit()
    conn.close()

    return {"settings": updated, "model_presets": MODEL_PRESETS}


@router.get("/backup/export-json")
def export_backup_json(member: dict = Depends(get_current_member)):
    require_owner(member)
    conn = get_conn()
    profiles = [dict(r) for r in conn.execute("SELECT * FROM profiles ORDER BY id ASC").fetchall()]
    for p in profiles:
        p.pop("embedding_json", None)
    interactions = [dict(r) for r in conn.execute("SELECT * FROM interactions ORDER BY id ASC").fetchall()]
    votes = [dict(r) for r in conn.execute("SELECT * FROM family_votes ORDER BY id ASC").fetchall()]
    follow_ups = [dict(r) for r in conn.execute("SELECT * FROM follow_ups ORDER BY id ASC").fetchall()]
    media = [dict(r) for r in conn.execute("SELECT * FROM media_assets ORDER BY id ASC").fetchall()]
    conn.close()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "exported_at": stamp,
        "settings": get_app_settings(),
        "profiles": profiles,
        "interactions": interactions,
        "family_votes": votes,
        "follow_ups": follow_ups,
        "media_assets": media,
    }
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="rishta_tracker_backup_{stamp}.json"'},
    )


@router.get("/backup/export-sqlite")
def export_backup_sqlite(member: dict = Depends(get_current_member)):
    require_owner(member)
    backup_path = create_sqlite_backup()
    return FileResponse(
        str(backup_path),
        media_type="application/x-sqlite3",
        filename=backup_path.name,
    )
