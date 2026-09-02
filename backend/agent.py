"""LangGraph triage agent: classify -> route -> explain.

The agent is an MCP *client*. Every reference lookup, classification and
next-step suggestion is a `tools/call` over stdio to backend/mcp_server.py;
this module imports neither `lab_rules` nor `mcp_server`. The MCP client is
handed to the nodes through the LangGraph config rather than the state, since
an open session is not serialisable.

Node responsibilities:
  classify  deterministic only — two MCP calls per lab, no LLM
  route     ordering, in-code multi-marker pattern detection, one MCP call
            per result for next steps, no LLM
  explain   the single LLM step — one batched Gemini call for everything
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

import llm
from mcp_client import TriageToolClient

STATUS_ORDER = {"critical": 0, "warning": 1, "unknown": 2, "normal": 3}


class TriageState(TypedDict, total=False):
    """State threaded through the graph."""

    labs: list[dict[str, Any]]
    classified: list[dict[str, Any]]
    routed: dict[str, list[dict[str, Any]]]
    panel_insights: list[dict[str, Any]]
    pipeline: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    llm_meta: dict[str, Any]


def _tools(config: RunnableConfig) -> TriageToolClient:
    client = (config or {}).get("configurable", {}).get("mcp_client")
    if client is None:
        raise RuntimeError("No MCP client supplied in config.configurable.mcp_client")
    return client


def _direction(rule: Optional[str]) -> str:
    """Derive the breach direction from the deterministic rule id."""
    r = rule or ""
    if "below" in r:
        return "low"
    if "above" in r:
        return "high"
    return "none"


# --------------------------------------------------------------------------
# Node 1: classify  (deterministic — no LLM)
# --------------------------------------------------------------------------
async def classify_node(state: TriageState, config: RunnableConfig) -> dict[str, Any]:
    tools = _tools(config)
    labs = state.get("labs") or []

    classified: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    calls_before = len(tools.call_log)

    for i, lab in enumerate(labs):
        raw_name = lab.get("test_name")
        raw_value = lab.get("value")
        supplied_unit = lab.get("unit")

        if raw_name is None or not str(raw_name).strip():
            errors.append(
                {"index": i, "field": "test_name", "detail": "Missing or empty test name."}
            )
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            errors.append(
                {"index": i, "field": "value", "detail": "Missing or empty value."}
            )

        # BOTH tools reached over MCP — never imported.
        ref = await tools.reference_range_lookup(raw_name)
        verdict = await tools.classify_result(raw_name, raw_value)

        if verdict.get("_transport_error"):
            errors.append(
                {"index": i, "field": "mcp", "detail": verdict.get("basis", "MCP error")}
            )

        reference = verdict.get("reference") or ref.get("reference") or {
            "normal_low": None,
            "normal_high": None,
            "critical_low": None,
            "critical_high": None,
        }
        status = verdict.get("status", "unknown")
        if status not in STATUS_ORDER:
            status = "unknown"

        classified.append(
            {
                "index": i,
                "test_name": raw_name if raw_name is not None else "",
                "display_name": verdict.get("display_name") or ref.get("display_name"),
                "canonical_name": ref.get("canonical_name"),
                "value": verdict.get("value", raw_value),
                "unit": supplied_unit or verdict.get("unit") or ref.get("unit") or "",
                "status": status,
                "reference": reference,
                "basis": verdict.get("basis", "No basis recorded."),
                "rule": verdict.get("rule"),
                "direction": _direction(verdict.get("rule")),
                "source": verdict.get("source") or ref.get("source"),
            }
        )

    counts = {s: sum(1 for c in classified if c["status"] == s) for s in STATUS_ORDER}
    mcp_calls = len(tools.call_log) - calls_before

    pipeline_entry = {
        "stage": "classify",
        "detail": (
            f"Classified {len(classified)} result(s) deterministically over MCP "
            f"({mcp_calls} tools/call round-trips to reference_range_lookup and "
            f"classify_result). No LLM involved. "
            f"critical={counts['critical']}, warning={counts['warning']}, "
            f"normal={counts['normal']}, unknown={counts['unknown']}."
        ),
        "tools_used": ["reference_range_lookup", "classify_result"],
        "mcp_calls": mcp_calls,
        "llm_used": False,
        "counts": counts,
    }

    return {
        "classified": classified,
        "errors": (state.get("errors") or []) + errors,
        "pipeline": (state.get("pipeline") or []) + [pipeline_entry],
    }


# --------------------------------------------------------------------------
# Panel detection — deterministic, in code
# --------------------------------------------------------------------------
def detect_panels(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect multi-marker patterns from already-fixed statuses.

    Pure code, no LLM: the pattern either fires or it does not, and each
    carries a deterministic `basis`. The LLM only narrates the `insight`.
    """
    by_marker: dict[str, dict[str, Any]] = {}
    for c in classified:
        key = c.get("canonical_name")
        if key and key not in by_marker:
            by_marker[key] = c

    def abnormal(marker: str, direction: str) -> Optional[dict[str, Any]]:
        c = by_marker.get(marker)
        if not c:
            return None
        if c["status"] in ("warning", "critical") and c["direction"] == direction:
            return c
        return None

    panels: list[dict[str, Any]] = []

    # 1. Renal: creatinine and potassium both elevated.
    creat, pot = abnormal("CREATININE", "high"), abnormal("POTASSIUM", "high")
    if creat and pot:
        panels.append(
            {
                "pattern": "renal_impairment_with_hyperkalemia",
                "markers": [creat["display_name"] or "Creatinine", pot["display_name"] or "Potassium"],
                "basis": (
                    f"Creatinine {creat['value']} {creat['unit']} is {creat['status']}-high "
                    f"and potassium {pot['value']} {pot['unit']} is {pot['status']}-high; "
                    f"reduced renal clearance impairs potassium excretion, so the two "
                    f"together carry more weight than either alone."
                ),
                "routing": "Nephrology consult",
                "severity": "critical"
                if "critical" in (creat["status"], pot["status"])
                else "warning",
            }
        )

    # 2. Anemia: low hemoglobin.
    hgb = abnormal("HEMOGLOBIN", "low")
    if hgb:
        panels.append(
            {
                "pattern": "anemia",
                "markers": [hgb["display_name"] or "Hemoglobin"],
                "basis": (
                    f"Hemoglobin {hgb['value']} {hgb['unit']} is {hgb['status']}-low "
                    f"against a normal floor of {hgb['reference'].get('normal_low')}, "
                    f"which meets the threshold for an anemia workup."
                ),
                "routing": "Anemia workup — iron studies, B12/folate, haematology review",
                "severity": hgb["status"],
            }
        )

    # 3. Hyperglycemia with low sodium — measured sodium falls as glucose rises.
    glu, sod = abnormal("GLUCOSE", "high"), abnormal("SODIUM", "low")
    if glu and sod:
        panels.append(
            {
                "pattern": "hyperglycemia_with_hyponatremia",
                "markers": [glu["display_name"] or "Glucose", sod["display_name"] or "Sodium"],
                "basis": (
                    f"Glucose {glu['value']} {glu['unit']} is {glu['status']}-high while "
                    f"sodium {sod['value']} {sod['unit']} is {sod['status']}-low; measured "
                    f"sodium falls as glucose rises, so the sodium figure should be "
                    f"interpreted alongside the glucose rather than in isolation."
                ),
                "routing": "Endocrinology review — correct sodium for glucose before acting",
                "severity": "critical"
                if "critical" in (glu["status"], sod["status"])
                else "warning",
            }
        )

    # 4. Infection/marrow signal: abnormal WBC alongside low hemoglobin.
    wbc = by_marker.get("WBC")
    if wbc and wbc["status"] in ("warning", "critical") and hgb:
        panels.append(
            {
                "pattern": "cytopenia_or_infection_signal",
                "markers": [wbc["display_name"] or "WBC", hgb["display_name"] or "Hemoglobin"],
                "basis": (
                    f"WBC {wbc['value']} {wbc['unit']} is {wbc['status']}-{wbc['direction']} "
                    f"alongside a {hgb['status']}-low hemoglobin of {hgb['value']} "
                    f"{hgb['unit']}; two abnormal cell lines together raise the "
                    f"possibility of a marrow or systemic process rather than an "
                    f"isolated finding."
                ),
                "routing": "Haematology review — full blood count with differential",
                "severity": "critical"
                if "critical" in (wbc["status"], hgb["status"])
                else "warning",
            }
        )

    return panels


# --------------------------------------------------------------------------
# Node 2: route  (deterministic — no LLM)
# --------------------------------------------------------------------------
async def route_node(state: TriageState, config: RunnableConfig) -> dict[str, Any]:
    tools = _tools(config)
    classified = state.get("classified") or []
    calls_before = len(tools.call_log)

    ordered = sorted(
        classified, key=lambda c: (STATUS_ORDER.get(c["status"], 9), c["index"])
    )

    # get_next_steps reached over MCP, one call per result.
    for c in ordered:
        steps = await tools.get_next_steps(c["test_name"], c["status"])
        c["next_steps"] = steps.get("next_steps", "Route to a clinician for review.")
        c["next_steps_specificity"] = steps.get("specificity", "generic")

    routed = {
        "critical": [c for c in ordered if c["status"] == "critical"],
        "warning": [c for c in ordered if c["status"] == "warning"],
        "normal": [c for c in ordered if c["status"] == "normal"],
        "unknown": [c for c in ordered if c["status"] == "unknown"],
    }

    panels = detect_panels(classified)
    mcp_calls = len(tools.call_log) - calls_before

    pipeline_entry = {
        "stage": "route",
        "detail": (
            f"Ordered results critical-first "
            f"({len(routed['critical'])} critical, {len(routed['warning'])} warning, "
            f"{len(routed['normal'])} normal, {len(routed['unknown'])} unknown) and "
            f"fetched next steps over MCP ({mcp_calls} tools/call round-trips to "
            f"get_next_steps). Detected {len(panels)} multi-marker pattern(s) in "
            f"code: {', '.join(p['pattern'] for p in panels) or 'none'}. No LLM involved."
        ),
        "tools_used": ["get_next_steps"],
        "mcp_calls": mcp_calls,
        "llm_used": False,
        "panels_detected": [p["pattern"] for p in panels],
    }

    return {
        "classified": ordered,
        "routed": routed,
        "panel_insights": panels,
        "pipeline": (state.get("pipeline") or []) + [pipeline_entry],
    }


# --------------------------------------------------------------------------
# Node 3: explain  (the only LLM step)
# --------------------------------------------------------------------------
async def explain_node(state: TriageState, config: RunnableConfig) -> dict[str, Any]:
    results = state.get("classified") or []
    panels = state.get("panel_insights") or []

    statuses_before = [r["status"] for r in results]

    by_result, by_panel, meta = await llm.explain_batch(results, panels)

    filled_llm = 0
    for i, r in enumerate(results):
        text = by_result.get(i)
        if text:
            r["explanation"] = text
            r["explanation_source"] = "llm"
            filled_llm += 1
        else:
            r["explanation"] = llm.fallback_explanation(r)
            r["explanation_source"] = "deterministic_fallback"

    for i, p in enumerate(panels):
        text = by_panel.get(i)
        if text:
            p["insight"] = text
            p["insight_source"] = "llm"
        else:
            p["insight"] = llm.fallback_panel_insight(p)
            p["insight_source"] = "deterministic_fallback"

    # Integrity guard: the LLM writes prose only. If any status moved, that is
    # a bug, not a judgement call — restore and record it.
    drift = [
        r["test_name"]
        for r, before in zip(results, statuses_before)
        if r["status"] != before
    ]
    for r, before in zip(results, statuses_before):
        r["status"] = before

    if meta.get("ok"):
        detail = (
            f"Generated {filled_llm}/{len(results)} explanation(s) and "
            f"{len(by_panel)}/{len(panels)} panel narration(s) in ONE batched "
            f"{meta['model']} call (attempt {meta['attempts']}). Statuses were "
            f"supplied to the model as fixed and were not re-evaluated."
        )
    else:
        detail = (
            f"LLM unavailable ({meta.get('error')}); fell back to the deterministic "
            f"basis text for all {len(results)} result(s) and {len(panels)} panel(s). "
            f"Classifications are unaffected."
        )

    pipeline_entry = {
        "stage": "explain",
        "detail": detail,
        "tools_used": [],
        "mcp_calls": 0,
        "llm_used": bool(meta.get("ok")),
        "llm_model": meta.get("model"),
        "llm_ok": bool(meta.get("ok")),
        "status_drift": drift,
    }

    return {
        "classified": results,
        "panel_insights": panels,
        "llm_meta": meta,
        "pipeline": (state.get("pipeline") or []) + [pipeline_entry],
    }


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------
def build_graph():
    """classify -> route -> explain -> END."""
    graph = StateGraph(TriageState)
    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)
    graph.add_node("explain", explain_node)
    graph.set_entry_point("classify")
    graph.add_edge("classify", "route")
    graph.add_edge("route", "explain")
    graph.add_edge("explain", END)
    return graph.compile()


TRIAGE_GRAPH = build_graph()


async def run_triage(labs: list[dict[str, Any]]) -> TriageState:
    """Open one MCP session and run the graph over it."""
    from mcp_client import open_triage_tools

    async with open_triage_tools() as tools:
        initial: TriageState = {
            "labs": labs,
            "classified": [],
            "routed": {},
            "panel_insights": [],
            "pipeline": [],
            "errors": [],
        }
        final = await TRIAGE_GRAPH.ainvoke(
            initial, config={"configurable": {"mcp_client": tools}}
        )
        final["mcp_call_log"] = tools.call_log
        return final
