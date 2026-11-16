#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export PATH="/Users/saurabhjha/.bun/bin:/opt/homebrew/bin:$PATH"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

echo "============================================================"
echo "  Rishta Dossier — Strictly Local Mac + Home Wi-Fi Server"
echo "  (Zero Public Internet Tunnels — Zscaler Policy Compliant)"
echo "============================================================"

# 1. Generate / verify local LAN TLS certificates for current IP
python3 "$ROOT_DIR/certs/generate_certs.py" --force

# 2. Build frontend if dist/ is missing or --build passed
if [[ ! -d "$ROOT_DIR/frontend/dist" ]] || [[ "${1:-}" == "--build" ]]; then
  echo "[1/2] Building Mobile-First React PWA via Bun..."
  (cd "$ROOT_DIR/frontend" && bun run build)
fi

HTTP_PORT="${HTTP_PORT:-8080}"
HTTPS_PORT="${HTTPS_PORT:-8443}"
LAN_IP="$(python3 -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8",80)); print(s.getsockname()[0]); s.close()' 2>/dev/null || echo "127.0.0.1")"
MDNS_HOST="$(scutil --get LocalHostName 2>/dev/null || hostname)"

cleanup() {
  if [[ -n "${HTTPS_PID:-}" ]]; then
    kill "$HTTPS_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Start local HTTPS listener in background on :8443
caffeinate -dimsu /opt/homebrew/bin/uv run --directory "$ROOT_DIR/backend" \
  uvicorn app.main:app --host 0.0.0.0 --port "$HTTPS_PORT" \
  --ssl-keyfile "$ROOT_DIR/certs/server.key" \
  --ssl-certfile "$ROOT_DIR/certs/server.crt" &
HTTPS_PID=$!

echo ""
echo "  Mac Local URL                : http://localhost:${HTTP_PORT}"
echo "  Home Wi-Fi Constant mDNS URL : http://${MDNS_HOST}.local:${HTTP_PORT}"
echo "  Home Wi-Fi Constant HTTPS    : https://${MDNS_HOST}.local:${HTTPS_PORT}"
echo "  Current LAN IP URL           : http://${LAN_IP}:${HTTP_PORT}"
echo "  Public Internet Exposure     : NONE (Strictly Local / LAN Only)"
echo "  Logins                       : Saurabh (PIN 1234) | Mummy (PIN 0000) | Sister (PIN 0000)"
echo "============================================================"

# Start local HTTP listener in foreground on :8080
caffeinate -dimsu /opt/homebrew/bin/uv run --directory "$ROOT_DIR/backend" \
  uvicorn app.main:app --host 0.0.0.0 --port "$HTTP_PORT"
