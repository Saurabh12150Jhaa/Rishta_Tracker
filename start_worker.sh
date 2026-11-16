#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

CLOUD_URL="${1:-${CLOUD_SERVER_URL:-}}"
if [[ -z "$CLOUD_URL" ]]; then
  echo "Usage: ./start_worker.sh https://your-permanent-app-url.onrender.com"
  echo "(Or set CLOUD_SERVER_URL=https://... in .env)"
  exit 1
fi

# Run outbound-only AI worker under caffeinate (zero listening ports on Mac!)
caffeinate -dimsu /opt/homebrew/bin/uv run --directory "$ROOT_DIR/backend" \
  python "$ROOT_DIR/mac_ai_worker.py" "$CLOUD_URL"
