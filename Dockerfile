# Cloud Web App + Database Dockerfile (No AI API Key stored in cloud!)
FROM oven/bun:1 as frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/bun.lock* ./
RUN bun install
COPY frontend/ ./
RUN bun --bun ./node_modules/typescript/bin/tsc -b && bun --bun ./node_modules/vite/bin/vite.js build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml ./backend/
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart python-dotenv openai httpx pymupdf pillow pydantic
COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
RUN mkdir -p /app/data/media/photos /app/data/media/biodata /app/data/media/voice /app/data/media/imports /app/data/media/backups

ENV PORT=8080
EXPOSE 8080
WORKDIR /app/backend
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
