"""Gemini explanation step — the ONLY place an LLM touches this pipeline.

Statuses arrive here already fixed by the deterministic MCP rules. The model is
given each result's status and `basis` as settled fact and asked only to phrase
them; it is never asked what a status should be, and nothing it returns is
allowed to alter one.

The whole batch goes out as ONE structured call (every result plus every panel
narration) rather than one call per row, to stay inside the Gemini free-tier
rate limit and to keep demo latency predictable. If the call fails after its
retries, callers fall back to the deterministic basis text so /analyze_labs
still returns correct classifications.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

UNAVAILABLE_SUFFIX = "(AI explanation unavailable)"


class ResultExplanation(BaseModel):
    """One explanation, keyed back to its result by list index."""

    index: int = Field(description="The 0-based index of the result being explained.")
    explanation: str = Field(
        description=(
            "A short, clinically sensible, NON-DIAGNOSTIC explanation of this "
            "result. One crisp sentence when the status is normal; two to three "
            "sentences when it is warning or critical."
        )
    )


class PanelNarration(BaseModel):
    """One narration of a deterministically detected multi-marker pattern."""

    index: int = Field(description="The 0-based index of the panel pattern.")
    insight: str = Field(
        description=(
            "Two or three sentences explaining why this combination of markers "
            "matters together, framed as decision support and never as a diagnosis."
        )
    )


class ExplanationBatch(BaseModel):
    results: list[ResultExplanation] = Field(default_factory=list)
    panels: list[PanelNarration] = Field(default_factory=list)


SYSTEM_PROMPT = """\
You are a clinical laboratory decision-support assistant writing for a clinician.

CRITICAL CONSTRAINTS — these are not negotiable:
1. The status of every result (normal / warning / critical / unknown) has ALREADY
   been decided by a deterministic rule engine. Treat each status and its "basis"
   as settled fact. NEVER contradict, re-rank, soften or escalate a status.
2. NEVER state or imply a diagnosis. Write decision support: what the value
   indicates, what could plausibly drive it, and what a clinician should weigh.
   Use hedged language ("may reflect", "is consistent with", "warrants review").
3. Do not invent values, reference ranges or results that were not supplied.
4. No patient-directed advice, no treatment dosing, no prognosis.

STYLE:
- normal: ONE crisp reassuring sentence.
- warning: two to three sentences — what is mildly out of range and what to weigh.
- critical: two to three sentences — convey urgency and the immediate concern.
- unknown: say plainly that the test or value could not be matched to a reference
  range and needs manual clinician review. Do not speculate about the analyte.

Return an explanation for EVERY result index given, and a narration for EVERY
panel index given. Do not skip any.
"""


def _render_results(results: list[dict[str, Any]]) -> str:
    lines = []
    for i, r in enumerate(results):
        unit = f" {r.get('unit')}" if r.get("unit") else ""
        lines.append(
            f"[{i}] test={r.get('test_name')} value={r.get('value')}{unit} "
            f"status={r.get('status')} basis=\"{r.get('basis')}\""
        )
    return "\n".join(lines) if lines else "(none)"


def _render_panels(panels: list[dict[str, Any]]) -> str:
    lines = []
    for i, p in enumerate(panels):
        lines.append(
            f"[{i}] markers={', '.join(p.get('markers', []))} "
            f"pattern={p.get('pattern')} "
            f"detected_because=\"{p.get('basis')}\" "
            f"suggested_routing=\"{p.get('routing')}\""
        )
    return "\n".join(lines) if lines else "(none)"


def build_prompt(results: list[dict[str, Any]], panels: list[dict[str, Any]]) -> str:
    return (
        "Explain the following laboratory results.\n\n"
        f"RESULTS ({len(results)}):\n{_render_results(results)}\n\n"
        f"MULTI-MARKER PATTERNS ({len(panels)}):\n{_render_panels(panels)}\n\n"
        "Return one explanation per result index and one insight per panel index."
    )


def _get_model():
    """Build the Gemini chat model, or return None if no key is configured."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key.strip() in ("", "your_gemini_api_key_here"):
        return None, "GEMINI_API_KEY is not set in .env"

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        return None, f"langchain-google-genai is not installed: {exc}"

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    try:
        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.2,
        )
        return model, None
    except Exception as exc:
        return None, f"could not initialise Gemini model: {exc}"


def _retry_delay(error: str, attempt: int) -> float:
    """Back off harder on a quota error than on a transient failure.

    Gemini's free tier answers 429 RESOURCE_EXHAUSTED with a retryDelay, often
    around a minute. Reusing the ordinary one-second backoff there just burns
    both attempts, so a rate-limit error waits long enough to matter.
    """
    if "RESOURCE_EXHAUSTED" in error or "429" in error:
        match = re.search(r"retry in ([0-9.]+)s", error)
        if match:
            return min(float(match.group(1)) + 1.0, 65.0)
        return 20.0 * attempt
    return 1.0 * attempt


async def explain_batch(
    results: list[dict[str, Any]],
    panels: list[dict[str, Any]],
    attempts: int = 3,
) -> tuple[dict[int, str], dict[int, str], dict[str, Any]]:
    """One batched structured Gemini call for all results and panels.

    Returns (explanations_by_index, panel_insights_by_index, meta). On failure
    both maps come back empty and `meta` carries the reason; the caller then
    substitutes the deterministic basis text. This function never raises.
    """
    meta: dict[str, Any] = {
        "provider": "google-gemini",
        "model": os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "batched": True,
        "attempts": 0,
        "ok": False,
        "error": None,
    }

    if not results and not panels:
        meta["ok"] = True
        meta["error"] = "nothing to explain"
        return {}, {}, meta

    model, err = _get_model()
    if model is None:
        meta["error"] = err
        return {}, {}, meta

    structured = model.with_structured_output(ExplanationBatch)
    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", build_prompt(results, panels)),
    ]

    last_error: Optional[str] = None
    for attempt in range(1, attempts + 1):
        meta["attempts"] = attempt
        try:
            batch = await structured.ainvoke(messages)
            by_result = {
                e.index: e.explanation.strip()
                for e in batch.results
                if 0 <= e.index < len(results) and e.explanation.strip()
            }
            by_panel = {
                p.index: p.insight.strip()
                for p in batch.panels
                if 0 <= p.index < len(panels) and p.insight.strip()
            }
            meta["ok"] = True
            meta["returned_results"] = len(by_result)
            meta["returned_panels"] = len(by_panel)
            return by_result, by_panel, meta
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            meta["rate_limited"] = "RESOURCE_EXHAUSTED" in last_error
            if attempt < attempts:
                await asyncio.sleep(_retry_delay(last_error, attempt))

    meta["error"] = last_error
    return {}, {}, meta


def fallback_explanation(result: dict[str, Any]) -> str:
    """Deterministic stand-in when the LLM is unavailable."""
    return f"{result.get('basis', 'No basis recorded.')} {UNAVAILABLE_SUFFIX}"


def fallback_panel_insight(panel: dict[str, Any]) -> str:
    return f"{panel.get('basis', 'Pattern detected.')} {UNAVAILABLE_SUFFIX}"
