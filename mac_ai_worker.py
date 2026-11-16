#!/usr/bin/env python3
"""
Outbound-Only Mac AI Worker for Sister's Rishta Dossier.
- Runs on your Zscaler-connected Mac with ZERO listening ports and ZERO reverse tunnels.
- Polls your permanent Cloud Web App over standard outbound HTTPS:
    GET/POST https://<your-cloud-app>/api/worker/poll
- Calls https://zllama.corp.zscaler.com/v1 locally on your Mac using ZLLAMA_API_KEY.
- Pushes the extracted JSON, Hinglish voice transcript, and embeddings back over outbound HTTPS.
"""
import os
import socket
import ssl
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

try:
    import truststore
    truststore.inject_into_ssl()
    SSL_CTX: ssl.SSLContext | bool = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    SSL_CTX = False

from dotenv import load_dotenv
import httpx

load_dotenv(ROOT_DIR / ".env")

from app.config import WORKER_SHARED_SECRET, ZLLAMA_API_KEY
from app.services.ai_extractor import extract_rishta_bundle
from app.services.media_proc import (
    image_bytes_to_data_url,
    process_pdf_biodata,
    transcode_audio_to_mp3_b64,
)


def process_queued_task(cloud_url: str, headers: dict, task: dict, existing_profiles: list[dict]) -> dict:
    payload = task.get("payload") or {}
    raw_text = payload.get("raw_text") or ""
    pdf_texts = list(payload.get("pdf_texts") or [])
    image_data_urls: list[str] = []
    audio_mp3_b64_list: list[str] = []
    media_ids = payload.get("media_asset_ids") or []

    target_profile_id = payload.get("target_profile_id") or payload.get("profile_id")
    existing_profile = next((p for p in existing_profiles if p["id"] == target_profile_id), None)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for mid in media_ids:
            if not mid:
                continue
            try:
                with httpx.Client(timeout=30.0, verify=SSL_CTX) as client:
                    r = client.get(f"{cloud_url}/api/worker/media/{mid}", headers=headers)
                    r.raise_for_status()
                    disp = r.headers.get("content-disposition", "")
                    fname = f"asset_{mid}.bin"
                    if "filename=" in disp:
                        fname = disp.split("filename=")[-1].strip("\"' ")
                    fpath = tmp_path / fname
                    fpath.write_bytes(r.content)

                    ext = fpath.suffix.lower()
                    if ext == ".pdf":
                        pdf_res = process_pdf_biodata(fpath)
                        if pdf_res["text"] and pdf_res["text"] not in pdf_texts:
                            pdf_texts.append(pdf_res["text"])
                        image_data_urls.extend(pdf_res["page_images"])
                    elif ext in (".jpg", ".jpeg", ".png", ".webp"):
                        image_data_urls.append(image_bytes_to_data_url(r.content))
                    elif ext in (".opus", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".webm", ".amr"):
                        mp3_b64 = transcode_audio_to_mp3_b64(fpath)
                        if mp3_b64:
                            audio_mp3_b64_list.append(mp3_b64)
            except Exception as exc:
                print(f"[Worker] Warning downloading media #{mid}: {exc}")

    ai_bundle = extract_rishta_bundle(
        raw_text=raw_text,
        pdf_texts=pdf_texts,
        image_data_urls=image_data_urls,
        audio_mp3_b64_list=audio_mp3_b64_list,
        source_name=payload.get("source_name"),
        source_channel=payload.get("source_channel"),
        existing_profile=existing_profile,
    )
    return ai_bundle


def run_worker_loop(cloud_url: str) -> None:
    cloud_url = cloud_url.rstrip("/")
    hostname = socket.gethostname()
    headers = {
        "X-Worker-Secret": WORKER_SHARED_SECRET,
        "Content-Type": "application/json",
    }

    print("============================================================")
    print("  Rishta Dossier — Outbound-Only Zscaler Mac AI Worker")
    print("  Listening Ports on Mac : ZERO (100% Outbound HTTPS Only)")
    print(f"  Target Cloud Dashboard : {cloud_url}")
    print(f"  Mac Hostname           : {hostname}")
    print(f"  zllama Key Configured  : {'YES' if ZLLAMA_API_KEY else 'NO'}")
    print("============================================================")

    while True:
        try:
            with httpx.Client(timeout=15.0, verify=SSL_CTX) as client:
                resp = client.post(
                    f"{cloud_url}/api/worker/poll",
                    headers=headers,
                    json={"hostname": hostname},
                )
                resp.raise_for_status()
                data = resp.json()

            task = data.get("task")
            if task:
                tid = task["id"]
                ttype = task["task_type"]
                print(f"[Worker] Picked up task #{tid} ({ttype}) — processing via zllama...")
                ai_bundle = process_queued_task(
                    cloud_url, headers, task, data.get("existing_profiles") or []
                )
                with httpx.Client(timeout=20.0, verify=SSL_CTX) as client:
                    c_resp = client.post(
                        f"{cloud_url}/api/worker/tasks/{tid}/complete",
                        headers=headers,
                        json={"ai_bundle": ai_bundle},
                    )
                    c_resp.raise_for_status()
                print(f"[Worker] Completed task #{tid} ({ai_bundle.get('models_used')}) ✓")
                continue
        except KeyboardInterrupt:
            print("\n[Worker] Stopped by user.")
            break
        except Exception as exc:
            print(f"[Worker] Poll check note: {exc}")

        time.sleep(3.5)


if __name__ == "__main__":
    target_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.getenv("CLOUD_SERVER_URL", "http://127.0.0.1:8080")
    )
    run_worker_loop(target_url)
