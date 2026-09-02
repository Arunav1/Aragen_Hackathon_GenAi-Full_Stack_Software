"""Proof that the triage tools are reachable over a real MCP connection.

This script deliberately does NOT import `lab_rules` or `mcp_server`. It spawns
backend/mcp_server.py as a subprocess and talks to it with the official MCP
Python SDK client (`mcp.ClientSession`) over stdio transport, exercising the
full protocol: initialize -> tools/list -> tools/call. Every number printed
below crossed a process boundary as JSON-RPC.

Usage:
    .venv/bin/python scripts/verify_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "backend" / "mcp_server.py"

RULE = "=" * 78


def show(label: str, payload: Any) -> None:
    print(f"  -> {label}: {json.dumps(payload, ensure_ascii=False, default=str)}")


def unwrap(result: Any) -> Any:
    """Pull the JSON payload out of an MCP CallToolResult."""
    sc = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if sc:
        # FastMCP wraps non-object returns under "result"; dicts come through as-is.
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(REPO_ROOT),
    )

    print(RULE)
    print("MCP CLIENT VERIFICATION - real stdio transport, no direct imports")
    print(RULE)
    print(f"Client   : mcp.ClientSession (official MCP Python SDK)")
    print(f"Transport: stdio")
    print(f"Server   : {sys.executable} {SERVER_PATH.relative_to(REPO_ROOT)}")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(
                f"\n[handshake] connected to '{init.server_info.name}' "
                f"v{init.server_info.version} "
                f"(protocol {init.protocol_version})"
            )

            listing = await session.list_tools()
            print(f"\n[tools/list] {len(listing.tools)} tools advertised over MCP:")
            for tool in listing.tools:
                schema = getattr(tool, "input_schema", None) or getattr(
                    tool, "inputSchema", {}
                )
                required = schema.get("required", [])
                print(f"  - {tool.name}({', '.join(required)})")

            # ---------------- Tool 1: reference_range_lookup ----------------
            print(f"\n{RULE}\nTOOL 1: reference_range_lookup\n{RULE}")
            for name in ["Glucose", "Lökosit", "Potasyum", "Ferritin", "Unobtanium"]:
                res = await session.call_tool(
                    "reference_range_lookup", {"test_name": name}
                )
                payload = unwrap(res)
                print(f"\ntools/call reference_range_lookup(test_name={name!r})")
                if payload.get("status") == "ok":
                    show("source", payload["source"])
                    show("resolved", payload.get("canonical_name") or payload["display_name"])
                    show("unit", payload["unit"])
                    show("reference", payload["reference"])
                else:
                    show("status", payload["status"])
                    show("reason", payload["reason"])

            # ---------------- Tool 2: classify_result ----------------
            print(f"\n{RULE}\nTOOL 2: classify_result (deterministic, no LLM)\n{RULE}")
            cases = [
                ("Glucose", 260, "critical high"),
                ("Glucose", 88, "normal"),
                ("Glucose", 150, "warning high"),
                ("Potassium", 2.1, "critical low"),
                ("Sodium", 131, "warning low"),
                ("Creatinine", 0.4, "warning low - no critical-low bound exists"),
                ("Lökosit", 6.37, "Turkish alias, dataset units"),
                ("Ferritin", 9.0, "dataset-sourced band, cannot reach critical"),
                ("Glucose", "not-a-number", "non-numeric -> unknown"),
                ("Unobtanium", 5, "unknown marker -> unknown"),
            ]
            for name, value, note in cases:
                res = await session.call_tool(
                    "classify_result", {"test_name": name, "value": value}
                )
                payload = unwrap(res)
                print(f"\ntools/call classify_result(test_name={name!r}, value={value!r})  # {note}")
                show("status", payload["status"])
                show("rule", payload["rule"])
                show("basis", payload["basis"])
                show("source", payload["source"])

            # ---------------- Tool 3: get_next_steps ----------------
            print(f"\n{RULE}\nTOOL 3: get_next_steps\n{RULE}")
            step_cases = [
                ("Potassium", "critical"),
                ("Hemoglobin", "warning"),
                ("Glucose", "normal"),
                ("Ferritin", "warning"),
                ("Unobtanium", "unknown"),
                ("Glucose", "catastrophic"),
            ]
            for name, status in step_cases:
                res = await session.call_tool(
                    "get_next_steps", {"test_name": name, "status": status}
                )
                payload = unwrap(res)
                print(f"\ntools/call get_next_steps(test_name={name!r}, status={status!r})")
                show("specificity", payload["specificity"])
                show("next_steps", payload["next_steps"])

            # ---------------- Determinism check ----------------
            print(f"\n{RULE}\nDETERMINISM: same call 5x over MCP\n{RULE}")
            seen = set()
            for _ in range(5):
                res = await session.call_tool(
                    "classify_result", {"test_name": "Glucose", "value": 260}
                )
                p = unwrap(res)
                seen.add((p["status"], p["basis"]))
            print(f"  5 identical calls produced {len(seen)} distinct result(s) "
                  f"-> {'PASS' if len(seen) == 1 else 'FAIL'}")

    print(f"\n{RULE}")
    print("All three tools were invoked through the MCP protocol over stdio.")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
