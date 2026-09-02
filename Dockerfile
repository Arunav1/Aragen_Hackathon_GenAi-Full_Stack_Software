# Single-service image: builds the React frontend, then serves it from the same
# FastAPI process that exposes the API.
#
# Why one service: the frontend's API URL is otherwise baked in at build time,
# so a split deployment fails whenever VITE_API_BASE is unset or set after the
# build. Same-origin removes that failure mode and the CORS configuration with it.
#
# This must be a real container, not a serverless function — the agent spawns
# backend/mcp_server.py as a stdio subprocess per request.

# ---------- stage 1: build the frontend ----------
FROM node:20-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# No VITE_API_BASE on purpose: with no build-time value the app falls back to
# its own origin, which is exactly where the API is served from here.
RUN npm run build

# ---------- stage 2: the API, serving that build ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across code changes.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
# lab_rules degrades gracefully without this, but shipping it keeps the
# dataset-derived reference ranges (source="mcp_lookup") working.
COPY Laboratory_Test_Resutlts_dataset/ Laboratory_Test_Resutlts_dataset/

COPY --from=web /web/dist frontend/dist

# Do not run as root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Bind 0.0.0.0 so the platform health check can reach the process, and honour
# $PORT where the host supplies one.
CMD ["sh", "-c", "uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
