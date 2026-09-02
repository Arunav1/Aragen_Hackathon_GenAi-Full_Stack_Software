"""Clinical lab triage MCP server (FastMCP, stdio transport).

Exposes exactly three tools. The LangGraph agent in Phase 2 is a real MCP
*client* that reaches these over stdio — it never imports `lab_rules` directly.
That boundary is the point: classification runs deterministically on this side
of the protocol, and the LLM on the other side only ever writes prose about a
status it was handed.

Run standalone:
    .venv/bin/python backend/mcp_server.py

Verify over a real MCP client:
    .venv/bin/python scripts/verify_mcp.py
"""

from __future__ import annotations

from typing import Any, Union

from fastmcp import FastMCP

import lab_rules

mcp = FastMCP(
    name="clinical-lab-triage",
    instructions=(
        "Deterministic clinical lab triage tools. Call reference_range_lookup to "
        "resolve a test name to its reference band, classify_result to obtain a "
        "status and the exact rule that produced it, and get_next_steps for the "
        "suggested follow-up action. You MUST NOT decide a status yourself: "
        "classify_result is the only authority on normal/warning/critical. "
        "Output is decision support, not a diagnosis."
    ),
)


@mcp.tool(
    name="reference_range_lookup",
    description=(
        "Resolve a lab test name to its reference ranges. Handles English, "
        "Turkish and dataset spellings via an alias map. Returns hardcoded "
        "normal + critical bounds for the six triage markers, dataset-derived "
        "normal bounds otherwise, or status 'unknown' if the name is "
        "unrecognised. Never raises."
    ),
)
def reference_range_lookup(test_name: str) -> dict[str, Any]:
    """Look up the reference range for a lab test by name."""
    return lab_rules.reference_range_lookup(test_name)


@mcp.tool(
    name="classify_result",
    description=(
        "Deterministically classify a lab value as normal, warning, critical or "
        "unknown, and return the exact rule that fired together with a 'basis' "
        "string quantifying how far outside range the value sits. This is the "
        "sole authority on status — an LLM must never override it. Non-numeric "
        "values and unknown test names return 'unknown' rather than raising."
    ),
)
def classify_result(
    test_name: str, value: Union[float, int, str, None]
) -> dict[str, Any]:
    """Classify a single lab result deterministically."""
    return lab_rules.classify_result(test_name, value)


@mcp.tool(
    name="get_next_steps",
    description=(
        "Return a suggested follow-up action for a (test_name, status) pair, "
        "e.g. critical potassium -> repeat STAT plus cardiac monitoring. Falls "
        "back to a generic action for unrecognised markers or statuses. "
        "Suggestions are decision support, not a diagnosis."
    ),
)
def get_next_steps(test_name: str, status: str) -> dict[str, Any]:
    """Suggest the next clinical step for a classified result."""
    return lab_rules.get_next_steps(test_name, status)


if __name__ == "__main__":
    # stdio is the default transport; the client spawns this file as a subprocess.
    # The banner is suppressed so it cannot interleave with the JSON-RPC stream.
    mcp.run(show_banner=False)
