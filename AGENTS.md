# Rishta Tracker — Project Guide (`AGENTS.md`)

## Architecture & Runtime Notes
- **Backend (`backend/`)**: Python 3.13+ FastAPI managed with `/opt/homebrew/bin/uv`. Uses SQLite WAL (`data/rishta.sqlite`), PyMuPDF (`import pymupdf as fitz`), Pillow, and `/opt/homebrew/bin/ffmpeg`.
- **Frontend (`frontend/`)**: React 18 + TypeScript + Vite PWA built via `/Users/saurabhjha/.bun/bin/bun` (using `bun --bun` in `package.json` scripts because `/opt/homebrew/bin/node` has a Homebrew dylib crash on this Mac).
- **Multi-Model Specialist Router (`backend/app/services/ai_extractor.py`)**:
  - Vision & Biodata JSON Extraction: `gpt-5.4` → `claude-sonnet-4-6` → `gemini-3-flash`
  - Hinglish Audio (`.opus`/`.m4a`) Transcription: `gemini-3-flash` (`reasoning_effort="low"`) → `gemini-3.1-pro`
  - Cultural & Fit Advisor / WhatsApp Replies: `claude-sonnet-4-6` → `gpt-5.4` → `claude-opus-4-6`
  - Side-by-Side Shortlist Compare: `claude-opus-4-6` → `claude-sonnet-4-6`
  - Bulk WhatsApp `.zip` Triage: `gpt-5.4-mini` → `gemini-3-flash`
  - Semantic Deduplication (3072-dim): `text-embedding-3-large` → `text-embedding-3-small`

## Common Commands
- **Start Dual HTTP (`:8080`) + HTTPS (`:8443`) Server (with `caffeinate`)**:
  ```bash
  ./start.sh
  ```
- **Rebuild Frontend PWA**:
  ```bash
  /Users/saurabhjha/.bun/bin/bun run --cwd frontend build
  ```
- **Run End-to-End Backend & Live AI Tests**:
  ```bash
  /opt/homebrew/bin/uv run --directory backend pytest -v
  ```
