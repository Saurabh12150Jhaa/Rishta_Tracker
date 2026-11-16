import os
import re
import socket
import subprocess
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "rishta.sqlite"
CERTS_DIR = ROOT_DIR / "certs"
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"

for sub in ("photos", "biodata", "voice", "imports", "backups"):
    (MEDIA_DIR / sub).mkdir(parents=True, exist_ok=True)

ZLLAMA_API_KEY = os.getenv("ZLLAMA_API_KEY", "").strip()
ZLLAMA_BASE_URL = os.getenv("ZLLAMA_BASE_URL", "https://zllama.corp.zscaler.com/v1").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "rishta-tracker-default-secret")
WORKER_SHARED_SECRET = os.getenv("WORKER_SHARED_SECRET", "rishta-mac-worker-secret-9d4e2a7b1c8f").strip()
CLOUD_SERVER_URL = os.getenv("CLOUD_SERVER_URL", "").strip()
HTTP_PORT = int(os.getenv("HTTP_PORT", "8080"))
HTTPS_PORT = int(os.getenv("HTTPS_PORT", "8443"))
OWNER_DEFAULT_PIN = os.getenv("OWNER_DEFAULT_PIN", "1234")
FAMILY_DEFAULT_PIN = os.getenv("FAMILY_DEFAULT_PIN", "0000")
DEFAULT_AI_PRESET = os.getenv("AI_PRESET", "balanced")

MODEL_PRESETS = {
    "balanced": {
        "label": "Balanced Specialist Router (Recommended)",
        "vision_extract_chain": ["gpt-5.4", "claude-sonnet-4-6", "gemini-3-flash"],
        "audio_transcribe_chain": ["gemini-3-flash", "gemini-3.1-pro"],
        "reasoning_advisor_chain": ["claude-sonnet-4-6", "gpt-5.4", "claude-opus-4-6"],
        "compare_chain": ["claude-opus-4-6", "claude-sonnet-4-6", "gpt-5.4"],
        "batch_triage_chain": ["gpt-5.4-mini", "gemini-3-flash", "gpt-5.4"],
        "embedding_chain": ["text-embedding-3-large", "text-embedding-3-small"],
    },
    "deep": {
        "label": "Max Depth Router (Opus 4.6 + GPT-5.4 + Gemini 3.1 Pro)",
        "vision_extract_chain": ["gpt-5.4", "claude-opus-4-6", "claude-sonnet-4-6"],
        "audio_transcribe_chain": ["gemini-3.1-pro", "gemini-3-flash"],
        "reasoning_advisor_chain": ["claude-opus-4-6", "claude-sonnet-4-6", "gpt-5.4"],
        "compare_chain": ["claude-opus-4-6", "gpt-5.4"],
        "batch_triage_chain": ["gpt-5.4", "gpt-5.4-mini"],
        "embedding_chain": ["text-embedding-3-large", "text-embedding-3-small"],
    },
}


def get_network_info() -> dict:
    lan_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    local_hostname = "localhost"
    try:
        lhn = subprocess.check_output(["scutil", "--get", "LocalHostName"], text=True).strip()
        if lhn:
            local_hostname = f"{lhn}.local"
    except Exception:
        pass

    return {
        "lan_ip": lan_ip,
        "mdns_host": local_hostname,
        "http_port": HTTP_PORT,
        "https_port": HTTPS_PORT,
        "http_lan_url": f"http://{lan_ip}:{HTTP_PORT}",
        "http_mdns_url": f"http://{local_hostname}:{HTTP_PORT}",
        "https_lan_url": f"https://{lan_ip}:{HTTPS_PORT}",
        "https_mdns_url": f"https://{local_hostname}:{HTTPS_PORT}",
        "ca_cert_available": (CERTS_DIR / "rishta-local-ca.crt").exists(),
    }
