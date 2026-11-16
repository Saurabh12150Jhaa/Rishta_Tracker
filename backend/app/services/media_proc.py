import base64
import io
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Optional
import pymupdf as fitz  # PyMuPDF
from PIL import Image
from ..config import MEDIA_DIR


FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg"


def save_uploaded_bytes(content: bytes, original_name: str, subfolder: str) -> tuple[Path, str]:
    ext = Path(original_name or "file.bin").suffix.lower() or ".bin"
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(original_name or "file").stem)[:40]
    unique_name = f"{safe_stem}_{uuid.uuid4().hex[:8]}{ext}"
    folder = MEDIA_DIR / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / unique_name
    dest.write_bytes(content)
    url_path = f"/media/{subfolder}/{unique_name}"
    return dest, url_path


def image_bytes_to_data_url(content: bytes, max_side: int = 1500) -> str:
    try:
        img = Image.open(io.BytesIO(content))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        b64 = base64.b64encode(content).decode("ascii")
        return f"data:image/png;base64,{b64}"


def process_pdf_biodata(pdf_path: Path, max_pages: int = 4) -> dict:
    doc = fitz.open(str(pdf_path))
    extracted_text_parts: list[str] = []
    page_data_urls: list[str] = []
    extracted_portrait_url: Optional[str] = None
    best_portrait_area = 0

    for page_idx in range(min(len(doc), max_pages)):
        page = doc[page_idx]
        txt = page.get_text("text").strip()
        if txt:
            extracted_text_parts.append(f"--- Page {page_idx + 1} ---\n{txt}")

        pix = page.get_pixmap(dpi=150, alpha=False)
        png_bytes = pix.tobytes("png")
        page_data_urls.append(image_bytes_to_data_url(png_bytes, max_side=1500))

        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                base_img = doc.extract_image(xref)
                img_bytes = base_img["image"]
                pil_img = Image.open(io.BytesIO(img_bytes))
                w, h = pil_img.size
                aspect = w / float(h) if h else 0
                area = w * h
                # Heuristic: candidate portrait embedded inside biodata PDF (not tiny icon, not full-page background)
                if 110 <= w <= 2200 and 110 <= h <= 2600 and 0.42 <= aspect <= 1.35:
                    page_rect = page.rect
                    page_area = page_rect.width * page_rect.height * 4
                    if area > best_portrait_area and area < page_area * 0.85:
                        if pil_img.mode not in ("RGB",):
                            pil_img = pil_img.convert("RGB")
                        out_buf = io.BytesIO()
                        pil_img.save(out_buf, format="JPEG", quality=88)
                        _, url_path = save_uploaded_bytes(
                            out_buf.getvalue(),
                            f"portrait_{pdf_path.stem}.jpg",
                            "photos",
                        )
                        best_portrait_area = area
                        extracted_portrait_url = url_path
            except Exception:
                continue

    doc.close()
    return {
        "text": "\n\n".join(extracted_text_parts),
        "page_images": page_data_urls,
        "portrait_url": extracted_portrait_url,
    }


def transcode_audio_to_mp3_b64(audio_path: Path) -> Optional[str]:
    out_mp3 = audio_path.with_suffix(".transcoded.mp3")
    try:
        subprocess.run(
            [
                FFMPEG_BIN,
                "-y",
                "-i",
                str(audio_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                str(out_mp3),
            ],
            check=True,
            capture_output=True,
            timeout=45,
        )
        mp3_bytes = out_mp3.read_bytes()
        return base64.b64encode(mp3_bytes).decode("ascii")
    except Exception:
        if audio_path.suffix.lower() == ".mp3" and audio_path.exists():
            return base64.b64encode(audio_path.read_bytes()).decode("ascii")
        return None
    finally:
        if out_mp3.exists():
            try:
                out_mp3.unlink()
            except Exception:
                pass


def unpack_whatsapp_zip(zip_path: Path) -> dict:
    extract_dir = MEDIA_DIR / "imports" / f"zip_{uuid.uuid4().hex[:8]}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    chat_texts: list[str] = []
    pdfs: list[tuple[Path, str, str]] = []
    images: list[tuple[Path, str, str]] = []
    audios: list[tuple[Path, str, str]] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir() or info.filename.startswith("__MACOSX") or Path(info.filename).name.startswith("."):
                    continue
                fname = Path(info.filename).name
                ext = Path(fname).suffix.lower()
                raw = zf.read(info.filename)

                if ext == ".txt":
                    try:
                        chat_texts.append(raw.decode("utf-8", errors="replace"))
                    except Exception:
                        pass
                elif ext == ".pdf":
                    p, u = save_uploaded_bytes(raw, fname, "biodata")
                    pdfs.append((p, u, fname))
                elif ext in (".jpg", ".jpeg", ".png", ".webp"):
                    p, u = save_uploaded_bytes(raw, fname, "photos")
                    images.append((p, u, fname))
                elif ext in (".opus", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".webm"):
                    p, u = save_uploaded_bytes(raw, fname, "voice")
                    audios.append((p, u, fname))
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return {
        "chat_text": "\n\n".join(chat_texts),
        "pdfs": pdfs,
        "images": images,
        "audios": audios,
    }
