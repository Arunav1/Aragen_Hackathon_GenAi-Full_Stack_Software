# Portable backend image — works on Railway, Fly.io, Cloud Run, or anywhere
# that runs a container. Render uses render.yaml instead and does not need this.
#
# The agent spawns backend/mcp_server.py as a stdio subprocess per request, so
# this must be a real container rather than a serverless function.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across code changes.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
# lab_rules falls back gracefully if this is absent, but shipping it keeps the
# dataset-derived reference ranges (source="mcp_lookup") working.
COPY Laboratory_Test_Resutlts_dataset/ Laboratory_Test_Resutlts_dataset/

# Do not run as root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Bind 0.0.0.0 so the platform can reach the process; honour $PORT if set.
CMD ["sh", "-c", "uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
