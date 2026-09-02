"""Deterministic clinical lab triage rules.

This module is the single source of truth for classification. It contains NO
LLM calls and no randomness: the same (test_name, value) pair always produces
the same status and the same `basis` string. The LLM (Phase 2) may only write
prose *around* these results — it never decides a status.

`mcp_server.py` exposes the three public functions here as MCP tools. Nothing
else in the application is permitted to import this module: the agent reaches
these rules over the MCP protocol, not by direct function call.

THRESHOLDS ARE ILLUSTRATIVE DEMO VALUES, not an authoritative clinical source.
"""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = (
    REPO_ROOT / "Laboratory_Test_Resutlts_dataset" / "lab_test_results_public.csv"
)

# --------------------------------------------------------------------------
# Canonical markers
# --------------------------------------------------------------------------
# normal_low/high  : inclusive bounds of the normal band
# critical_low/high: breaching these is Critical. `None` means "this marker has
#                    no critical bound in that direction" (e.g. a low creatinine
#                    is not a critical finding), so that direction can never
#                    escalate past Warning.
CANONICAL_MARKERS: dict[str, dict[str, Any]] = {
    "GLUCOSE": {
        "display_name": "Glucose",
        "unit": "mg/dL",
        "normal_low": 70.0,
        "normal_high": 99.0,
        "critical_low": 54.0,
        "critical_high": 250.0,
    },
    "CREATININE": {
        "display_name": "Creatinine",
        "unit": "mg/dL",
        "normal_low": 0.7,
        "normal_high": 1.3,
        "critical_low": None,
        "critical_high": 4.0,
    },
    "POTASSIUM": {
        "display_name": "Potassium",
        "unit": "mmol/L",
        "normal_low": 3.5,
        "normal_high": 5.0,
        "critical_low": 2.5,
        "critical_high": 6.0,
    },
    "SODIUM": {
        "display_name": "Sodium",
        "unit": "mmol/L",
        "normal_low": 135.0,
        "normal_high": 145.0,
        "critical_low": 120.0,
        "critical_high": 160.0,
    },
    "HEMOGLOBIN": {
        "display_name": "Hemoglobin",
        "unit": "g/dL",
        "normal_low": 12.0,
        "normal_high": 17.5,
        "critical_low": 7.0,
        "critical_high": 20.0,
    },
    "WBC": {
        "display_name": "WBC",
        "unit": "x10^9/L",
        "normal_low": 4.0,
        "normal_high": 11.0,
        "critical_low": 2.0,
        "critical_high": 30.0,
    },
}

# Alias -> canonical key. Matching is EXACT on the normalized name, never
# substring: the dataset's "Glikozile Hemoglobin (HbA1c)" contains both
# "glikoz" and "hemoglobin" while being neither analyte, and "Lökosit (Strip)"
# is a qualitative urine dipstick rather than a WBC count. Substring matching
# silently misclassifies both, which would corrupt the triage status.
ALIASES: dict[str, str] = {
    # GLUCOSE
    "glucose": "GLUCOSE",
    "glukoz": "GLUCOSE",
    "blood glucose": "GLUCOSE",
    "serum glucose": "GLUCOSE",
    "fasting glucose": "GLUCOSE",
    "glu": "GLUCOSE",
    "kan sekeri": "GLUCOSE",
    "aclik kan sekeri": "GLUCOSE",
    # CREATININE
    "creatinine": "CREATININE",
    "kreatinin": "CREATININE",
    "serum creatinine": "CREATININE",
    "creat": "CREATININE",
    "cr": "CREATININE",
    # POTASSIUM
    "potassium": "POTASSIUM",
    "potasyum": "POTASSIUM",
    "k": "POTASSIUM",
    "k+": "POTASSIUM",
    "serum potassium": "POTASSIUM",
    # SODIUM
    "sodium": "SODIUM",
    "sodyum": "SODIUM",
    "na": "SODIUM",
    "na+": "SODIUM",
    "serum sodium": "SODIUM",
    # HEMOGLOBIN
    "hemoglobin": "HEMOGLOBIN",
    "haemoglobin": "HEMOGLOBIN",
    "hgb": "HEMOGLOBIN",
    "hb": "HEMOGLOBIN",
    # WBC
    "wbc": "WBC",
    "white blood cell": "WBC",
    "white blood cells": "WBC",
    "white blood cell count": "WBC",
    "leukocyte": "WBC",
    "leukocytes": "WBC",
    "leucocyte": "WBC",
    "lokosit": "WBC",  # Turkish "Lökosit", after diacritic folding
    "beyaz kure": "WBC",
}

# Unit strings we accept as equivalent per marker. WBC is the notable case:
# the dataset reports 10^3/uL, which is numerically identical to x10^9/L
# (6.37 in one is 6.37 in the other), so the 4.0-11.0 band applies unchanged.
EQUIVALENT_UNITS: dict[str, set[str]] = {
    "WBC": {"x10^9/l", "10^9/l", "10*9/l", "10^3/ul", "10*3/ul", "k/ul", "g/l"},
    "GLUCOSE": {"mg/dl"},
    "CREATININE": {"mg/dl"},
    "POTASSIUM": {"mmol/l", "meq/l"},
    "SODIUM": {"mmol/l", "meq/l"},
    "HEMOGLOBIN": {"g/dl"},
}

VALID_STATUSES = ("normal", "warning", "critical", "unknown")


# --------------------------------------------------------------------------
# Name normalization
# --------------------------------------------------------------------------
def normalize_name(text: Any) -> str:
    """Lowercase, fold diacritics, collapse whitespace, drop trailing punctuation.

    Turkish 'Lökosit' folds to 'lokosit' and 'İnsülin' to 'insulin', so a single
    ASCII alias table covers both the English and dataset spellings.
    """
    if text is None:
        return ""
    s = str(text).strip().lower()
    # Turkish dotted/dotless i do not decompose under NFKD; map them first.
    s = s.replace("ı", "i").replace("İ".lower(), "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = " ".join(s.split())
    return s.strip(" .:_-")


def _to_float(value: Any) -> Optional[float]:
    """Parse a lab value to float, or None if it is not numeric.

    Qualitative dipstick results ("Negatif", "1+", "Normal") and blanks all
    return None, which the caller turns into an `unknown` status rather than
    a crash.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f and abs(f) != float("inf") else None
    s = str(value).strip().replace(",", ".")
    if not s:
        return None
    for prefix in ("<", ">", "<=", ">=", "="):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _fmt(x: Optional[float]) -> str:
    """Format a number without trailing zeros (250.0 -> '250', 0.70 -> '0.7')."""
    if x is None:
        return "n/a"
    return f"{x:g}"


# --------------------------------------------------------------------------
# Dataset-derived ranges (fallback tier)
# --------------------------------------------------------------------------
_dataset_cache: Optional[dict[str, dict[str, Any]]] = None


def _load_dataset_ranges() -> dict[str, dict[str, Any]]:
    """Index the source CSV by normalized test name -> numeric normal band.

    Only rows with numeric Min_Reference and Max_Reference are indexed; the
    qualitative dipstick rows ("Negatif") are skipped. A missing or unreadable
    dataset degrades to an empty index rather than raising, so the MCP server
    still starts and still serves the six hardcoded markers.
    """
    global _dataset_cache
    if _dataset_cache is not None:
        return _dataset_cache

    ranges: dict[str, dict[str, Any]] = {}
    try:
        with DATASET_PATH.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("Test_Name") or "").strip()
                lo = _to_float(row.get("Min_Reference"))
                hi = _to_float(row.get("Max_Reference"))
                if not name or lo is None or hi is None or lo > hi:
                    continue
                key = normalize_name(name)
                if key in ALIASES:
                    # A canonical marker always wins; hardcoded ranges carry
                    # the critical bounds the dataset does not have.
                    continue
                ranges[key] = {
                    "display_name": name,
                    "unit": (row.get("Unit") or "").strip(),
                    "normal_low": lo,
                    "normal_high": hi,
                }
    except (OSError, csv.Error, UnicodeDecodeError):
        ranges = {}

    _dataset_cache = ranges
    return ranges


# --------------------------------------------------------------------------
# Tool 1: reference_range_lookup
# --------------------------------------------------------------------------
def reference_range_lookup(test_name: str) -> dict[str, Any]:
    """Resolve a test name to its reference ranges. Never raises.

    Resolution order:
      1. Normalize the name and consult the alias map.
      2. Canonical marker -> hardcoded normal + critical bounds, source="hardcoded".
      3. Dataset row -> Min/Max_Reference as the normal band, source="mcp_lookup",
         critical bounds null (the dataset carries no critical thresholds).
      4. No match -> {"status": "unknown"}.
    """
    key = normalize_name(test_name)

    if not key:
        return {
            "status": "unknown",
            "test_name": test_name,
            "matched": False,
            "source": None,
            "reason": "Empty or missing test name.",
        }

    canonical = ALIASES.get(key)
    if canonical:
        m = CANONICAL_MARKERS[canonical]
        return {
            "status": "ok",
            "test_name": test_name,
            "canonical_name": canonical,
            "display_name": m["display_name"],
            "matched": True,
            "unit": m["unit"],
            "reference": {
                "normal_low": m["normal_low"],
                "normal_high": m["normal_high"],
                "critical_low": m["critical_low"],
                "critical_high": m["critical_high"],
            },
            "source": "hardcoded",
            "notes": "Illustrative demo thresholds, not an authoritative clinical source.",
        }

    ds = _load_dataset_ranges().get(key)
    if ds:
        return {
            "status": "ok",
            "test_name": test_name,
            "canonical_name": None,
            "display_name": ds["display_name"],
            "matched": True,
            "unit": ds["unit"],
            "reference": {
                "normal_low": ds["normal_low"],
                "normal_high": ds["normal_high"],
                "critical_low": None,
                "critical_high": None,
            },
            "source": "mcp_lookup",
            "notes": (
                "Normal band taken from the source dataset. The dataset defines no "
                "critical thresholds, so this marker can only be classified normal "
                "or warning, never critical."
            ),
        }

    return {
        "status": "unknown",
        "test_name": test_name,
        "matched": False,
        "source": None,
        "reason": (
            f"'{test_name}' does not match any of the six triage markers or any "
            f"test in the reference dataset."
        ),
    }


# --------------------------------------------------------------------------
# Tool 2: classify_result  (DETERMINISTIC — no LLM)
# --------------------------------------------------------------------------
def classify_result(test_name: str, value: Any) -> dict[str, Any]:
    """Classify one lab value. Deterministic; identical inputs -> identical output.

    Rules, evaluated in order:
      R0  no reference range, or non-numeric value  -> unknown
      R1  value < critical_low                      -> critical
      R2  value > critical_high                     -> critical
      R3  normal_low <= value <= normal_high        -> normal
      R4  otherwise (outside normal, inside critical) -> warning

    A marker with a `None` critical bound cannot escalate past warning in that
    direction: dataset-sourced markers have no critical bounds at all and are
    therefore only ever normal or warning.
    """
    ref_info = reference_range_lookup(test_name)
    numeric = _to_float(value)

    if ref_info["status"] != "ok":
        return {
            "status": "unknown",
            "basis": (
                f"No reference range is defined for '{test_name}', so no rule could "
                f"be applied. Reported value: {value}."
            ),
            "rule": "R0_no_reference_range",
            "test_name": test_name,
            "value": value,
            "unit": None,
            "reference": {
                "normal_low": None,
                "normal_high": None,
                "critical_low": None,
                "critical_high": None,
            },
            "source": None,
        }

    unit = ref_info["unit"] or ""
    r = ref_info["reference"]
    nl, nh = r["normal_low"], r["normal_high"]
    cl, ch = r["critical_low"], r["critical_high"]

    base = {
        "test_name": test_name,
        "display_name": ref_info["display_name"],
        "unit": unit,
        "reference": r,
        "source": ref_info["source"],
    }

    if numeric is None:
        return {
            **base,
            "status": "unknown",
            "value": value,
            "basis": (
                f"Value '{value}' is not numeric, so the numeric reference band "
                f"{_fmt(nl)}-{_fmt(nh)} {unit} could not be applied."
            ),
            "rule": "R0_non_numeric_value",
        }

    base["value"] = numeric
    u = f" {unit}".rstrip()

    def ratio(a: float, b: Optional[float]) -> Optional[float]:
        if b in (None, 0):
            return None
        return a / b

    def frag(label: str, rat: Optional[float]) -> str:
        return f"{rat:.2f}x {label}" if rat is not None else f"{label} not defined"

    # R1 / R2 — critical
    if cl is not None and numeric < cl:
        return {
            **base,
            "status": "critical",
            "rule": "R1_below_critical_low",
            "basis": (
                f"Value {_fmt(numeric)}{u} falls below critical-low {_fmt(cl)} "
                f"({frag('the critical-low threshold', ratio(numeric, cl))}, "
                f"{frag('the lower normal limit', ratio(numeric, nl))})."
            ),
        }

    if ch is not None and numeric > ch:
        return {
            **base,
            "status": "critical",
            "rule": "R2_above_critical_high",
            "basis": (
                f"Value {_fmt(numeric)}{u} exceeds critical-high {_fmt(ch)} "
                f"({frag('the critical-high threshold', ratio(numeric, ch))}, "
                f"{frag('the upper normal limit', ratio(numeric, nh))})."
            ),
        }

    # R3 — normal
    if nl is not None and nh is not None and nl <= numeric <= nh:
        return {
            **base,
            "status": "normal",
            "rule": "R3_within_normal_band",
            "basis": (
                f"Value {_fmt(numeric)}{u} lies within the normal band "
                f"{_fmt(nl)}-{_fmt(nh)}{u}."
            ),
        }

    # R4 — warning
    if nh is not None and numeric > nh:
        ceiling = (
            f" but stays below critical-high {_fmt(ch)}."
            if ch is not None
            else ". No critical-high threshold is defined for this marker, so it "
            "cannot escalate beyond warning."
        )
        return {
            **base,
            "status": "warning",
            "rule": "R4_above_normal_high",
            "basis": (
                f"Value {_fmt(numeric)}{u} exceeds normal-high {_fmt(nh)} by "
                f"{_fmt(numeric - nh)}{u} "
                f"({frag('the upper normal limit', ratio(numeric, nh))})"
                f"{ceiling}"
            ),
        }

    floor = (
        f" but stays above critical-low {_fmt(cl)}."
        if cl is not None
        else ". No critical-low threshold is defined for this marker, so it cannot "
        "escalate beyond warning."
    )
    return {
        **base,
        "status": "warning",
        "rule": "R4_below_normal_low",
        "basis": (
            f"Value {_fmt(numeric)}{u} falls below normal-low {_fmt(nl)} by "
            f"{_fmt(nl - numeric)}{u} "
            f"({frag('the lower normal limit', ratio(numeric, nl))})"
            f"{floor}"
        ),
    }


# --------------------------------------------------------------------------
# Tool 3: get_next_steps
# --------------------------------------------------------------------------
# (canonical marker, status) -> specific suggested action.
NEXT_STEPS: dict[tuple[str, str], str] = {
    ("GLUCOSE", "critical"): (
        "Immediate review: confirm with a STAT repeat glucose, check ketones and "
        "capillary glucose at the bedside, and escalate to endocrinology."
    ),
    ("GLUCOSE", "warning"): (
        "Order HbA1c and a fasting glucose; arrange dietary review and recheck in "
        "4-6 weeks."
    ),
    ("GLUCOSE", "normal"): "No glucose-specific action; continue routine screening.",
    ("CREATININE", "critical"): (
        "Immediate review: assess urine output and volume status, hold nephrotoxic "
        "drugs, send a renal panel, and request an urgent nephrology consult."
    ),
    ("CREATININE", "warning"): (
        "Order eGFR with a urine albumin-to-creatinine ratio, review nephrotoxic "
        "medication, and repeat in 1-2 weeks."
    ),
    ("CREATININE", "normal"): "No renal-specific action; continue routine monitoring.",
    ("POTASSIUM", "critical"): (
        "Immediate review: repeat STAT to exclude haemolysis, start continuous "
        "cardiac monitoring, and obtain a 12-lead ECG."
    ),
    ("POTASSIUM", "warning"): (
        "Repeat potassium with magnesium and a renal panel; review diuretics, ACE "
        "inhibitors and potassium supplements."
    ),
    ("POTASSIUM", "normal"): "No electrolyte-specific action; continue routine monitoring.",
    ("SODIUM", "critical"): (
        "Immediate review: assess neurological status and volume state, correct at "
        "a controlled rate, and escalate to acute medicine."
    ),
    ("SODIUM", "warning"): (
        "Recheck sodium with serum and urine osmolality; review diuretics and fluid "
        "intake."
    ),
    ("SODIUM", "normal"): "No electrolyte-specific action; continue routine monitoring.",
    ("HEMOGLOBIN", "critical"): (
        "Immediate review: assess for active bleeding and haemodynamic stability, "
        "group and save/crossmatch, and escalate to haematology."
    ),
    ("HEMOGLOBIN", "warning"): (
        "Order iron studies including ferritin, plus B12 and folate; screen for a "
        "bleeding source."
    ),
    ("HEMOGLOBIN", "normal"): "No haematology-specific action; continue routine monitoring.",
    ("WBC", "critical"): (
        "Immediate review: screen for sepsis and neutropenia, send blood cultures "
        "with a differential count, and escalate to haematology."
    ),
    ("WBC", "warning"): (
        "Repeat the full blood count with a differential; look for infection or "
        "inflammation and review recent medication."
    ),
    ("WBC", "normal"): "No haematology-specific action; continue routine monitoring.",
}

GENERIC_STEPS: dict[str, str] = {
    "critical": (
        "Immediate clinician review and a confirmatory repeat test before any "
        "action is taken."
    ),
    "warning": (
        "Repeat the test to confirm and review it against the patient's history "
        "and current medication."
    ),
    "normal": "No action indicated; continue routine monitoring.",
    "unknown": (
        "Not triaged automatically: the test name or value could not be resolved "
        "to a reference range. Route to a clinician for manual review."
    ),
}


def get_next_steps(test_name: str, status: str) -> dict[str, Any]:
    """Map (marker, status) to a specific suggested action. Never raises."""
    normalized_status = normalize_name(status)
    if normalized_status not in VALID_STATUSES:
        return {
            "test_name": test_name,
            "status": "unknown",
            "next_steps": GENERIC_STEPS["unknown"],
            "specificity": "generic",
            "note": (
                f"'{status}' is not a recognised status "
                f"(expected one of {', '.join(VALID_STATUSES)})."
            ),
        }

    ref_info = reference_range_lookup(test_name)
    canonical = ref_info.get("canonical_name") if ref_info["status"] == "ok" else None

    if canonical and normalized_status != "unknown":
        specific = NEXT_STEPS.get((canonical, normalized_status))
        if specific:
            return {
                "test_name": test_name,
                "canonical_name": canonical,
                "status": normalized_status,
                "next_steps": specific,
                "specificity": "marker_specific",
            }

    return {
        "test_name": test_name,
        "canonical_name": canonical,
        "status": normalized_status,
        "next_steps": GENERIC_STEPS[normalized_status],
        "specificity": "generic",
    }
