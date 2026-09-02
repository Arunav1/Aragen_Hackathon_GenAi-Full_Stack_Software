"""MCP client wrapper — the agent's ONLY route to the triage tools.

This module deliberately does not import `lab_rules` or `mcp_server`. It spawns
backend/mcp_server.py as a subprocess and speaks MCP to it over stdio using the
official SDK's `ClientSession`, exactly as scripts/verify_mcp.py proved. Every
classification the agent reports crossed that process boundary as JSON-RPC.

A session is opened per request (spawn -> initialize -> calls -> close) rather
than held open for the application lifetime: a long-lived stdio session has a
fragile anyio cancel-scope lifecycle, and the Gemini call dominates latency
anyway.
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "backend" / "mcp_server.py"


def _unwrap(result: Any) -> Any:
    """Extract the JSON payload from an MCP CallToolResult."""
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured:
        if isinstance(structured, dict):
            return structured.get("result", structured)
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    return {}


class TriageToolClient:
    """Typed facade over MCP `tools/call`, with a per-session call log.

    The call log is what the API surfaces in its pipeline trace, so the number
    of MCP round-trips behind a response is visible rather than asserted.
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self.call_log: list[dict[str, Any]] = []

    async def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            raw = await self._session.call_tool(tool, args)
            payload = _unwrap(raw)
            self.call_log.append({"tool": tool, "args": args, "ok": True})
            return payload if isinstance(payload, dict) else {"result": payload}
        except Exception as exc:  # transport/protocol failure, not a rule outcome
            self.call_log.append(
                {"tool": tool, "args": args, "ok": False, "error": str(exc)}
            )
            return {
                "status": "unknown",
                "basis": f"MCP tool '{tool}' could not be reached: {exc}",
                "rule": "R0_mcp_unavailable",
                "source": None,
                "reference": {
                    "normal_low": None,
                    "normal_high": None,
                    "critical_low": None,
                    "critical_high": None,
                },
                "_transport_error": True,
            }

    async def reference_range_lookup(self, test_name: Any) -> dict[str, Any]:
        return await self._call("reference_range_lookup", {"test_name": test_name})

    async def classify_result(self, test_name: Any, value: Any) -> dict[str, Any]:
        return await self._call(
            "classify_result", {"test_name": test_name, "value": value}
        )

    async def get_next_steps(self, test_name: Any, status: str) -> dict[str, Any]:
        return await self._call(
            "get_next_steps", {"test_name": test_name, "status": status}
        )

    async def list_tools(self) -> list[str]:
        listing = await self._session.list_tools()
        return [t.name for t in listing.tools]


@asynccontextmanager
async def open_triage_tools() -> AsyncIterator[TriageToolClient]:
    """Spawn the MCP server over stdio and yield a client bound to it."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield TriageToolClient(session)
