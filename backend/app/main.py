import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from .auth import get_current_member, verify_session_token
from .config import FRONTEND_DIST_DIR, MEDIA_DIR
from .db import init_db
from .routers import auth_routes, imports, interactions, meetings, preferences, profiles, worker
from .routers.imports import _create_single_import_job
from .routers.meetings import background_reminder_loop
from .services import github_backup
from .services.matrimony_links import parse_matrimony_reference
from .services.media_proc import save_uploaded_bytes, unpack_whatsapp_zip


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    try:
        await asyncio.to_thread(github_backup.startup_restore)
    except Exception as exc:
        github_backup.state["last_error"] = f"startup restore error: {exc}"
    reminder_task = asyncio.create_task(background_reminder_loop())
    backup_task = asyncio.create_task(github_backup.backup_loop())
    try:
        yield
    finally:
        reminder_task.cancel()
        backup_task.cancel()
        await github_backup.final_push()


app = FastAPI(
    title="Rishta Tracker — Multimodal Family AI Workspace",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|[a-zA-Z0-9-]+\.local)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_routes.router)
app.include_router(imports.router)
app.include_router(profiles.router)
app.include_router(interactions.router)
app.include_router(meetings.router)
app.include_router(preferences.router)
app.include_router(worker.router)


@app.get("/media/{subfolder}/{filename}")
def serve_authenticated_media(
    subfolder: str,
    filename: str,
    member: dict = Depends(get_current_member),
):
    """Serve uploaded photos, biodata PDFs, and voice notes ONLY to authenticated family members."""
    if subfolder not in ("photos", "biodata", "voice", "imports"):
        raise HTTPException(status_code=404, detail="Invalid media folder")
    base_dir = MEDIA_DIR.resolve()
    target = (MEDIA_DIR / subfolder / filename).resolve()
    if not target.is_relative_to(base_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(str(target))


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/share-target")
async def pwa_web_share_target(
    request: Request,
    title: Optional[str] = Form(default=""),
    text: Optional[str] = Form(default=""),
    url: Optional[str] = Form(default=""),
    files: list[UploadFile] = File(default=[]),
):
    """Android Chrome PWA Web Share Target endpoint (requires active authenticated session cookie)."""
    token = request.cookies.get("rishta_session")
    member = verify_session_token(token) if token else None
    if not member:
        return RedirectResponse(url="/?login_required=1", status_code=303)

    member_name = member["name"]
    shared_text = "\n".join(x for x in [title, text, url] if x and x.strip())
    pdf_items = []
    image_items = []
    audio_items = []

    for up in files:
        if not up.filename:
            continue
        content = await up.read()
        if not content:
            continue
        ext = Path(up.filename).suffix.lower()
        ctype = (up.content_type or "").lower()
        if ext == ".zip" or "zip" in ctype:
            zp, _ = save_uploaded_bytes(content, up.filename, "imports")
            unpacked = unpack_whatsapp_zip(zp)
            if unpacked["chat_text"]:
                shared_text = f"{shared_text}\n\n{unpacked['chat_text']}".strip()
            pdf_items.extend(unpacked["pdfs"])
            image_items.extend(unpacked["images"])
            audio_items.extend(unpacked["audios"])
        elif ext == ".pdf" or "pdf" in ctype:
            p, u = save_uploaded_bytes(content, up.filename, "biodata")
            pdf_items.append((p, u, up.filename))
        elif ext in (".jpg", ".jpeg", ".png", ".webp") or ctype.startswith("image/"):
            p, u = save_uploaded_bytes(content, up.filename, "photos")
            image_items.append((p, u, up.filename))
        elif ext in (".opus", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".webm") or ctype.startswith("audio/"):
            p, u = save_uploaded_bytes(content, up.filename, "voice")
            audio_items.append((p, u, up.filename))

    shared_ref = parse_matrimony_reference(shared_text)
    if shared_text or pdf_items or image_items or audio_items:
        job = _create_single_import_job(
            raw_text=shared_text,
            pdf_items=pdf_items,
            image_items=image_items,
            audio_items=audio_items,
            source_name=shared_ref["platform"] if shared_ref else "WhatsApp Share",
            source_channel="Matrimonial App" if shared_ref else "Relative",
            target_profile_id=None,
            member_name=member_name,
            mode_label="single",
        )
        return RedirectResponse(url=f"/?review_job={job['job_id']}", status_code=303)

    return RedirectResponse(url="/?tab=import", status_code=303)


if (FRONTEND_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")), name="assets")


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("media/"):
        return HTMLResponse("Not Found", status_code=404)
    dist_resolved = FRONTEND_DIST_DIR.resolve()
    candidate = (FRONTEND_DIST_DIR / full_path).resolve()
    if full_path and candidate.is_relative_to(dist_resolved) and candidate.is_file():
        return FileResponse(str(candidate))
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse(
        "<h2>Rishta Tracker Backend is running.</h2><p>Frontend build not found in frontend/dist yet.</p>"
    )
