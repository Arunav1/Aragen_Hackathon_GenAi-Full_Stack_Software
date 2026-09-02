"""FastAPI surface for the clinical lab triage agent.

POST /analyze_labs runs the LangGraph agent, which reaches its tools only
through the MCP server over stdio. Request validation is deliberately lenient:
a non-numeric value or a nonsense test name is a triage outcome ("unknown"),
not a 422, so the caller always receives a structured response.

Run:
    .venv/bin/python -m uvicorn main:app --app-dir backend --reload --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
# In production the key comes from the host's environment, so a missing .env
# is normal rather than an error.
load_dotenv(REPO_ROOT / ".env", override=False)

import agent  # noqa: E402  (must follow load_dotenv so the LLM sees the key)

DISCLAIMER = (
    "Decision support, not a diagnosis. Automated triage output for clinician "
    "review only; it does not replace clinical judgement."
)

app = FastAPI(
    title="Clinical Lab Triage Agent",
    version="0.2.0",
    description=(
        "Deterministic lab triage over MCP with LLM-written explanations. "
        + DISCLAIMER
    ),
)

# CORS. The dev origins are always allowed; deployed frontends are added via
# the CORS_ORIGINS env var (comma-separated). Without this the hosted frontend
# would be blocked by the browser even though the API itself works.
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
EXTRA_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]

# Preview deployments get a fresh subdomain per commit, so allow them by
# pattern rather than needing a redeploy for every new preview URL.
ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://.*\.(vercel\.app|netlify\.app|onrender\.com)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS + EXTRA_ORIGINS,
    allow_origin_regex=ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class LabInput(BaseModel):
    """One lab row. Every field is optional so bad input triages, not 422s."""

    test_name: Optional[str] = None
    value: Any = None
    unit: Optional[str] = None


class AnalyzeLabsRequest(BaseModel):
    labs: list[LabInput] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Response assembly
# --------------------------------------------------------------------------
def _to_response(state: dict[str, Any]) -> dict[str, Any]:
    classified = state.get("classified") or []
    panels = state.get("panel_insights") or []

    summary = {
        "critical": sum(1 for c in classified if c["status"] == "critical"),
        "warning": sum(1 for c in classified if c["status"] == "warning"),
        "normal": sum(1 for c in classified if c["status"] == "normal"),
        "unknown": sum(1 for c in classified if c["status"] == "unknown"),
        "total": len(classified),
    }

    results = [
        {
            "test_name": c["test_name"],
            "display_name": c.get("display_name"),
            "value": c["value"],
            "unit": c["unit"],
            "status": c["status"],
            "reference": c["reference"],
            "basis": c["basis"],
            "rule": c.get("rule"),
            "explanation": c.get("explanation", ""),
            "explanation_source": c.get("explanation_source", "deterministic_fallback"),
            "next_steps": c.get("next_steps", ""),
            "source": c.get("source"),
        }
        for c in classified
    ]

    panel_insights = [
        {
            "markers": p["markers"],
            "insight": p.get("insight", p.get("basis", "")),
            "routing": p["routing"],
            "pattern": p["pattern"],
            "basis": p["basis"],
            "severity": p.get("severity", "warning"),
            "insight_source": p.get("insight_source", "deterministic_fallback"),
        }
        for p in panels
    ]

    llm_meta = state.get("llm_meta") or {}

    return {
        "summary": summary,
        "pipeline": state.get("pipeline") or [],
        "results": results,
        "panel_insights": panel_insights,
        "errors": state.get("errors") or [],
        "meta": {
            "disclaimer": DISCLAIMER,
            "classification": "deterministic rules via MCP; the LLM never sets a status",
            "tool_transport": "MCP (stdio) — agent is an MCP client",
            "mcp_calls": len(state.get("mcp_call_log") or []),
            "llm_provider": llm_meta.get("provider"),
            "llm_model": llm_meta.get("model"),
            "llm_ok": bool(llm_meta.get("ok")),
            "llm_error": llm_meta.get("error"),
        },
    }


def _empty_response(reason: str) -> dict[str, Any]:
    return {
        "summary": {"critical": 0, "warning": 0, "normal": 0, "unknown": 0, "total": 0},
        "pipeline": [
            {
                "stage": "classify",
                "detail": f"Nothing to classify: {reason}",
                "tools_used": [],
                "mcp_calls": 0,
                "llm_used": False,
            },
            {
                "stage": "route",
                "detail": "No results to route.",
                "tools_used": [],
                "mcp_calls": 0,
                "llm_used": False,
            },
            {
                "stage": "explain",
                "detail": "No results to explain; the LLM was not called.",
                "tools_used": [],
                "mcp_calls": 0,
                "llm_used": False,
            },
        ],
        "results": [],
        "panel_insights": [],
        "errors": [{"index": None, "field": "labs", "detail": reason}],
        "meta": {
            "disclaimer": DISCLAIMER,
            "classification": "deterministic rules via MCP; the LLM never sets a status",
            "tool_transport": "MCP (stdio) — agent is an MCP client",
            "mcp_calls": 0,
            "llm_provider": None,
            "llm_model": None,
            "llm_ok": False,
            "llm_error": None,
        },
    }


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY", "")
    return {
        "status": "ok",
        "llm_configured": bool(key and key != "your_gemini_api_key_here"),
        "llm_model": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "disclaimer": DISCLAIMER,
    }


@app.get("/mcp_tools")
async def mcp_tools() -> dict[str, Any]:
    """Live proof that the tools are served over MCP, not imported."""
    from mcp_client import open_triage_tools

    try:
        async with open_triage_tools() as tools:
            return {"transport": "stdio", "tools": await tools.list_tools()}
    except Exception as exc:
        return {"transport": "stdio", "tools": [], "error": str(exc)}


@app.post("/analyze_labs")
async def analyze_labs(request: AnalyzeLabsRequest) -> JSONResponse:
    labs = [lab.model_dump() for lab in request.labs]

    if not labs:
        return JSONResponse(content=_empty_response("The labs list was empty."))

    try:
        state = await agent.run_triage(labs)
        return JSONResponse(content=_to_response(dict(state)))
    except Exception as exc:
        # Last-resort guard: a transport failure still returns the contract shape.
        payload = _empty_response(
            f"The triage agent could not complete: {type(exc).__name__}: {exc}"
        )
        return JSONResponse(status_code=200, content=payload)


# --------------------------------------------------------------------------
# Static frontend (single-service deployment)
# --------------------------------------------------------------------------
# If a built frontend is present, serve it from this same app. That makes the
# API same-origin with the page, so the deployed frontend needs no baked-in
# backend URL and no CORS configuration — the two things most likely to be
# misconfigured across a two-service deploy.
#
# Mounted LAST so it cannot shadow /analyze_labs, /health or /mcp_tools:
# Starlette matches routes in registration order. Absent in local dev, where
# Vite serves the frontend on :5173 instead.
FRONTEND_DIST = Path(
    os.getenv("FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist"))
)

if (FRONTEND_DIST / "index.html").is_file():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIST), html=True),
        name="frontend",
    )
