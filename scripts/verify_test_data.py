"""End-to-end verification of the synthetic fixtures in test_data/.

For each CSV: parse it the same way the frontend does, POST it to
/analyze_labs, print the summary and every result, and assert the severities,
panel insights and explanation quality the fixture was written to produce.

Also checks two things that are easy to let drift:
  * the fixtures use headers the frontend's CSV parser actually accepts
  * the documented edge cases (invalid name, missing value, non-numeric)
    still return a structured response rather than crashing

Usage:
    .venv/bin/python scripts/verify_test_data.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DATA = REPO_ROOT / "test_data"
PORT = int(os.getenv("VERIFY_PORT", "8078"))
BASE = f"http://127.0.0.1:{PORT}"
RULE = "=" * 78

# Header aliases accepted by frontend/src/components/LabInput.jsx. Kept in sync
# deliberately: if the parser and the fixtures drift, the UI upload path breaks
# while this script would still pass.
COLUMN_ALIASES = {
    "test_name": "test_name", "test": "test_name", "name": "test_name",
    "test name": "test_name",
    "value": "value", "result": "value",
    "unit": "unit", "units": "unit",
}

FIXTURES = [
    {
        "file": "all_normal.csv",
        "title": "ALL NORMAL — the all-clear path",
        "expect": {
            "min": {"normal": 7},
            "zero": ["critical", "warning", "unknown"],
            "min_panels": 0,
            "max_panels": 0,
        },
    },
    {
        "file": "mixed.csv",
        "title": "MIXED — a realistic spread including one qualitative row",
        "expect": {
            "min": {"critical": 1, "warning": 2, "normal": 1, "unknown": 1},
            "zero": [],
            "min_panels": 1,
            "max_panels": None,
        },
    },
    {
        "file": "critical_heavy.csv",
        "title": "CRITICAL HEAVY — multiple criticals driving panel insights",
        "expect": {
            "min": {"critical": 2},
            "zero": [],
            "min_panels": 1,
            "max_panels": None,
        },
    },
]

EDGE_CASES = [
    ({"test_name": "Notarealtest", "value": 5, "unit": "mg/dL"}, "invalid test name"),
    ({"test_name": "Glucose", "value": None, "unit": "mg/dL"}, "missing value"),
    ({"test_name": "Glucose", "value": "abc", "unit": "mg/dL"}, "non-numeric value"),
    ({"test_name": "", "value": 5, "unit": "mg/dL"}, "empty test name"),
    ({"test_name": None, "value": None, "unit": None}, "everything missing"),
]


def parse_csv_like_frontend(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Mirror of the frontend parser, so fixture headers are checked, not assumed."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return [], []
    header = [COLUMN_ALIASES.get(h.strip().lower()) for h in rows[0]]
    labs = []
    for cells in rows[1:]:
        if not any(c.strip() for c in cells):
            continue
        lab = {"test_name": "", "value": "", "unit": ""}
        for field, cell in zip(header, cells):
            if field:
                lab[field] = cell.strip()
        labs.append(lab)
    return labs, header


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", "backend",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
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
    print(f"    [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def run_fixture(fixture: dict[str, Any]) -> bool:
    path = TEST_DATA / fixture["file"]
    labs, header = parse_csv_like_frontend(path)

    print(f"\n{RULE}\n{fixture['file']} — {fixture['title']}\n{RULE}")
    print(f"  header parsed as : {header}")
    print(f"  rows             : {len(labs)}")

    passed = check(
        "headers match the frontend CSV parser",
        "test_name" in header and "value" in header,
        f"{header}",
    )

    resp = httpx.post(f"{BASE}/analyze_labs", json={"labs": labs}, timeout=180)
    passed &= check("HTTP 200", resp.status_code == 200)
    data = resp.json()

    summary = data["summary"]
    print(f"\n  SUMMARY  critical={summary['critical']}  warning={summary['warning']}"
          f"  normal={summary['normal']}  unknown={summary['unknown']}"
          f"  total={summary['total']}")

    print("\n  RESULTS")
    for r in data["results"]:
        src = "LLM" if r["explanation_source"] == "llm" else "FALLBACK"
        print(f"    {r['status']:<8} {str(r['test_name'])[:22]:<24} "
              f"{str(r['value']):>8} {r['unit']:<9} [{r['source'] or 'none'}/{src}]")
        print(f"             basis: {r['basis']}")

    if data["panel_insights"]:
        print("\n  PANEL INSIGHTS")
        for p in data["panel_insights"]:
            print(f"    {p['pattern']} ({p['severity']}) — {', '.join(p['markers'])}")
            print(f"      routing: {p['routing']}")
            print(f"      insight: {p['insight'][:150]}…")

    print("\n  ASSERTIONS")
    exp = fixture["expect"]
    for status, minimum in exp["min"].items():
        passed &= check(
            f"at least {minimum} {status}", summary[status] >= minimum,
            f"got {summary[status]}",
        )
    for status in exp["zero"]:
        passed &= check(f"no {status} results", summary[status] == 0,
                        f"got {summary[status]}")

    panels = data["panel_insights"]
    passed &= check(f"at least {exp['min_panels']} panel insight(s)",
                    len(panels) >= exp["min_panels"], f"got {len(panels)}")
    if exp["max_panels"] is not None:
        passed &= check(f"at most {exp['max_panels']} panel insight(s)",
                        len(panels) <= exp["max_panels"], f"got {len(panels)}")

    scored = [r for r in data["results"] if r["status"] != "unknown"]
    passed &= check("every row came back", len(data["results"]) == len(labs),
                    f"{len(data['results'])}/{len(labs)}")
    passed &= check(
        "every scored result has a Gemini explanation (not the fallback)",
        all(r["explanation_source"] == "llm" for r in scored),
        f"{sum(1 for r in scored if r['explanation_source'] == 'llm')}/{len(scored)}",
    )
    passed &= check("no explanation carries the unavailable marker",
                    not any("(AI explanation unavailable)" in r["explanation"]
                            for r in data["results"]))
    passed &= check("every scored result has a basis",
                    all(r["basis"].strip() for r in scored))
    passed &= check("every scored result has next_steps",
                    all(r["next_steps"].strip() for r in scored))
    passed &= check("every panel has an insight and routing",
                    all(p["insight"].strip() and p["routing"].strip() for p in panels))

    # The basis must quote the value it actually scored — the explainability claim.
    mismatched = [
        r["test_name"] for r in scored
        if not re.search(re.escape(f"{float(r['value']):g}"), r["basis"])
    ]
    passed &= check("each basis quotes its own value", not mismatched, str(mismatched))

    passed &= check("the LLM changed no statuses",
                    not next((p.get("status_drift") for p in data["pipeline"]
                              if p["stage"] == "explain"), []))
    return passed


def run_edge_cases() -> bool:
    print(f"\n{RULE}\nEDGE CASES — must degrade, never crash\n{RULE}")
    passed = True
    for lab, label in EDGE_CASES:
        resp = httpx.post(f"{BASE}/analyze_labs", json={"labs": [lab]}, timeout=120)
        ok = resp.status_code == 200
        data = resp.json() if ok else {}
        results = data.get("results", [])
        status = results[0]["status"] if results else "(no result)"
        basis = results[0]["basis"] if results else ""
        print(f"\n  {label}: {json.dumps(lab)}")
        print(f"    -> HTTP {resp.status_code}, status={status}")
        print(f"    -> basis: {basis}")
        passed &= check("200 with a structured body",
                        ok and len(results) == 1 and status == "unknown")
        passed &= check("basis explains why it was not scored", bool(basis.strip()))

    resp = httpx.post(f"{BASE}/analyze_labs", json={"labs": []}, timeout=60)
    print(f"\n  empty labs list -> HTTP {resp.status_code}")
    passed &= check("empty list returns 200 in contract shape",
                    resp.status_code == 200
                    and {"summary", "pipeline", "results", "panel_insights"}
                    .issubset(resp.json().keys()))
    return passed


def main() -> int:
    print(RULE)
    print("TEST-DATA VERIFICATION — three synthetic fixtures, end to end")
    print(RULE)

    proc = start_server()
    try:
        health = httpx.get(f"{BASE}/health", timeout=10).json()
        print(f"\n[health] model={health['llm_model']} "
              f"llm_configured={health['llm_configured']}")
        if not health["llm_configured"]:
            print("  !! GEMINI_API_KEY missing — the explanation assertions will fail.")

        passed = True
        for fixture in FIXTURES:
            passed &= run_fixture(fixture)
        passed &= run_edge_cases()

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
