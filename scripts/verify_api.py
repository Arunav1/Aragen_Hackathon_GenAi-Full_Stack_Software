"""End-to-end proof for POST /analyze_labs.

Starts uvicorn as a subprocess, POSTs a payload crafted to trigger all three
severities plus an unknown marker and at least two multi-marker panel patterns,
prints the full JSON response, then asserts the graded properties:

  * every result carries an explanation
  * every status matches the deterministic rule expected for that value
  * the pipeline trace contains classify -> route -> explain in order
  * panel_insights is populated
  * the agent reached its tools over MCP

Usage:
    .venv/bin/python scripts/verify_api.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("VERIFY_PORT", "8077"))
BASE = f"http://127.0.0.1:{PORT}"
RULE = "=" * 78

# (test_name, value, unit, expected_status, why)
PAYLOAD_CASES: list[tuple[str, Any, str, str, str]] = [
    ("Glucose", 260, "mg/dL", "critical", "above critical-high 250"),
    ("Creatinine", 4.8, "mg/dL", "critical", "above critical-high 4.0"),
    ("Potassium", 6.4, "mmol/L", "critical", "above critical-high 6.0"),
    ("Hemoglobin", 9.1, "g/dL", "warning", "below normal-low 12.0, above critical-low 7.0"),
    ("Sodium", 131, "mmol/L", "warning", "below normal-low 135, above critical-low 120"),
    ("Lökosit", 12.5, "10^3/uL", "warning", "Turkish alias; above normal-high 11.0"),
    ("WBC", 7.2, "x10^9/L", "normal", "inside 4.0-11.0"),
    ("Ferritin", 45, "ug/L", "normal", "dataset-sourced band 15-150"),
    ("Unobtanium", 42, "mg/dL", "unknown", "no reference range"),
    ("Glucose", "n/a", "mg/dL", "unknown", "non-numeric value"),
    ("", 5, "mmol/L", "unknown", "empty test name"),
    ("Sodium", None, "mmol/L", "unknown", "missing value"),
]

EXPECTED_PANELS = {
    "renal_impairment_with_hyperkalemia",  # creatinine high + potassium high
    "anemia",                              # hemoglobin low
    "hyperglycemia_with_hyponatremia",     # glucose high + sodium low
    "cytopenia_or_infection_signal",       # WBC abnormal + hemoglobin low
}


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--app-dir", "backend", "--port", str(PORT), "--log-level", "warning",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for _ in range(60):
        if proc.poll() is not None:
            print(proc.stdout.read() if proc.stdout else "")
            raise RuntimeError("uvicorn exited during startup")
        try:
            httpx.get(f"{BASE}/health", timeout=1.0)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("uvicorn did not become ready")


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def check_no_direct_imports() -> bool:
    """Static proof of the integrity rule: the agent never imports the rules.

    If `agent.py` or `mcp_client.py` ever imported `lab_rules` or `mcp_server`,
    classification could silently bypass MCP while still looking correct. This
    fails the build instead.
    """
    import ast

    forbidden = {"lab_rules", "mcp_server"}
    violations: list[str] = []
    for filename in ("agent.py", "mcp_client.py", "llm.py"):
        path = REPO_ROOT / "backend" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        violations.append(f"{filename}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in forbidden:
                    violations.append(f"{filename}:{node.lineno} from {node.module}")

    return check(
        "agent never imports lab_rules/mcp_server directly",
        not violations,
        "; ".join(violations) if violations else "agent.py, mcp_client.py, llm.py clean",
    )


def main() -> int:
    print(RULE)
    print("API VERIFICATION - POST /analyze_labs end to end")
    print(RULE)

    print("\n[integrity] static check of the MCP-only rule")
    integrity_ok = check_no_direct_imports()

    proc = start_server()
    try:
        health = httpx.get(f"{BASE}/health", timeout=10).json()
        print(f"\n[health] {json.dumps(health)}")
        if not health.get("llm_configured"):
            print("\n  !! GEMINI_API_KEY is not configured — explanations will use the")
            print("     deterministic fallback. Classifications are unaffected.")

        tools = httpx.get(f"{BASE}/mcp_tools", timeout=30).json()
        print(f"[mcp_tools] {json.dumps(tools)}")

        payload = {
            "labs": [
                {"test_name": n, "value": v, "unit": u}
                for n, v, u, _, _ in PAYLOAD_CASES
            ]
        }
        print(f"\n[request] POST /analyze_labs with {len(payload['labs'])} labs")

        t0 = time.time()
        resp = httpx.post(f"{BASE}/analyze_labs", json=payload, timeout=180)
        elapsed = time.time() - t0
        print(f"[response] HTTP {resp.status_code} in {elapsed:.1f}s\n")

        data = resp.json()
        print(RULE)
        print("FULL JSON RESPONSE")
        print(RULE)
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # ---------------- assertions ----------------
        print(f"\n{RULE}\nASSERTIONS\n{RULE}")
        passed = integrity_ok

        passed &= check("HTTP 200", resp.status_code == 200)

        results: list[dict[str, Any]] = data.get("results", [])
        passed &= check(
            "all labs returned a result",
            len(results) == len(PAYLOAD_CASES),
            f"{len(results)}/{len(PAYLOAD_CASES)}",
        )

        # statuses — results are ordered critical-first, so match by position in
        # the request rather than by list order.
        expected = {}
        for name, value, _, status, why in PAYLOAD_CASES:
            expected.setdefault((name, str(value)), (status, why))
        wrong = []
        for r in results:
            key = (r["test_name"], str(r["value"]))
            exp = expected.get(key)
            if exp and r["status"] != exp[0]:
                wrong.append(f"{r['test_name']}={r['value']} got {r['status']}, want {exp[0]}")
        passed &= check(
            "every status matches its deterministic rule",
            not wrong,
            "; ".join(wrong) if wrong else f"{len(results)} checked",
        )

        missing_expl = [r["test_name"] for r in results if not r.get("explanation")]
        passed &= check(
            "every result carries an explanation", not missing_expl, str(missing_expl)
        )

        llm_count = sum(1 for r in results if r.get("explanation_source") == "llm")
        print(f"       -> {llm_count}/{len(results)} explanations came from the LLM, "
              f"{len(results) - llm_count} from the deterministic fallback")

        missing_basis = [r["test_name"] for r in results if not r.get("basis")]
        passed &= check("every result carries a basis", not missing_basis, str(missing_basis))

        missing_steps = [r["test_name"] for r in results if not r.get("next_steps")]
        passed &= check("every result carries next_steps", not missing_steps, str(missing_steps))

        stages = [p["stage"] for p in data.get("pipeline", [])]
        passed &= check(
            "pipeline trace is classify -> route -> explain",
            stages == ["classify", "route", "explain"],
            str(stages),
        )

        panels = data.get("panel_insights", [])
        found = {p["pattern"] for p in panels}
        passed &= check("panel_insights is populated", len(panels) > 0, f"{len(panels)} found")
        passed &= check(
            "expected panel patterns fired",
            found and found.issubset(EXPECTED_PANELS),
            ", ".join(sorted(found)) or "none",
        )
        passed &= check(
            "every panel carries an insight and routing",
            all(p.get("insight") and p.get("routing") for p in panels),
        )

        summary = data.get("summary", {})
        actual_counts = {
            s: sum(1 for r in results if r["status"] == s)
            for s in ("critical", "warning", "normal", "unknown")
        }
        passed &= check(
            "summary counts match the results",
            all(summary.get(k) == v for k, v in actual_counts.items()),
            json.dumps(actual_counts),
        )
        passed &= check(
            "all three severities are present",
            all(actual_counts[s] > 0 for s in ("critical", "warning", "normal")),
            json.dumps(actual_counts),
        )

        meta = data.get("meta", {})
        passed &= check(
            "agent reached tools over MCP",
            meta.get("mcp_calls", 0) > 0,
            f"{meta.get('mcp_calls')} tools/call round-trips",
        )
        passed &= check(
            "explain stage is the only LLM stage",
            [p["stage"] for p in data["pipeline"] if p.get("llm_used")] in ([], ["explain"]),
            str([p["stage"] for p in data["pipeline"] if p.get("llm_used")]),
        )
        drift = next(
            (p.get("status_drift") for p in data["pipeline"] if p["stage"] == "explain"),
            [],
        )
        passed &= check("the LLM changed no statuses", not drift, str(drift))

        # ---------------- degenerate input ----------------
        print(f"\n{RULE}\nEDGE CASE: empty labs list\n{RULE}")
        empty = httpx.post(f"{BASE}/analyze_labs", json={"labs": []}, timeout=30)
        passed &= check("empty labs returns 200, not a crash", empty.status_code == 200)
        passed &= check(
            "empty labs keeps the contract shape",
            set(["summary", "pipeline", "results", "panel_insights"]).issubset(
                empty.json().keys()
            ),
        )
        print(f"  response: {json.dumps(empty.json()['summary'])} "
              f"errors={json.dumps(empty.json()['errors'])}")

        print(f"\n{RULE}")
        print("RESULT: " + ("ALL ASSERTIONS PASSED" if passed else "SOME ASSERTIONS FAILED"))
        print(RULE)
        return 0 if passed else 1

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
