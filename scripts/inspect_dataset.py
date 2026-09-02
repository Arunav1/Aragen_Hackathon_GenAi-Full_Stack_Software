"""Phase 0 dataset inspection.

Prints the schema, sample rows, which of our six triage markers appear in the
source CSV, and whether the dataset carries its own reference ranges.

Usage:
    python scripts/inspect_dataset.py
"""

import csv
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "Laboratory_Test_Resutlts_dataset" / "lab_test_results_public.csv"

# The six markers the triage agent classifies. Values are the aliases we expect
# to see in the wild (dataset spellings are Turkish).
#
# Matching is EXACT on the normalized name, never substring: "Glikozile
# Hemoglobin (HbA1c)" contains both "glikoz" and "hemoglobin" but is neither
# serum glucose nor hemoglobin, and "Lökosit (Strip)" is a qualitative urine
# dipstick, not a WBC count. Substring matching silently misclassifies both.
TARGET_MARKERS = {
    "GLUCOSE": ["glucose", "glukoz", "kan sekeri", "kan şekeri", "aclik kan sekeri"],
    "CREATININE": ["creatinine", "kreatinin"],
    "POTASSIUM": ["potassium", "potasyum", "k+"],
    "SODIUM": ["sodium", "sodyum", "na+"],
    "HEMOGLOBIN": ["hemoglobin", "hgb", "hb"],
    "WBC": ["wbc", "lokosit", "lökosit", "leukocyte", "white blood cell"],
}


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def main() -> int:
    if not DATASET.exists():
        print(f"Dataset not found: {DATASET}")
        return 1

    with DATASET.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    columns = list(rows[0].keys()) if rows else []

    print(f"File     : {DATASET.relative_to(REPO_ROOT)}")
    print(f"Rows     : {len(rows)}")
    print(f"Columns  : {len(columns)}")
    for col in columns:
        print(f"  - {col}")

    print("\n--- 5 sample rows ---")
    for row in rows[:5]:
        print(
            f"  {row['Test_Name']:<32} {row['Result']:>10} {row['Unit']:<10} "
            f"ref={row['Reference_Range']:<12} status={row['Status']}"
        )

    print("\n--- Target marker coverage (exact normalized name match) ---")
    matched_names = set()
    for canonical, aliases in TARGET_MARKERS.items():
        hits = [r for r in rows if normalize(r["Test_Name"]) in aliases]
        for h in hits:
            matched_names.add(h["Test_Name"])
        if hits:
            for h in hits:
                print(
                    f"  FOUND    {canonical:<12} as '{h['Test_Name']}' = "
                    f"{h['Result']} {h['Unit']} (ref {h['Reference_Range']})"
                )
        else:
            print(f"  MISSING  {canonical:<12} (no row in dataset)")

    unmatched = [r["Test_Name"] for r in rows if r["Test_Name"] not in matched_names]
    print(f"\n  Rows that fall through to 'unknown' ({len(unmatched)}):")
    print("    " + ", ".join(unmatched))

    print("\n--- Reference ranges present? ---")
    with_range = sum(1 for r in rows if r["Min_Reference"] and r["Max_Reference"])
    numeric_range = 0
    for r in rows:
        try:
            float(r["Min_Reference"])
            float(r["Max_Reference"])
            numeric_range += 1
        except (TypeError, ValueError):
            pass
    print(f"  Rows with Min/Max_Reference populated : {with_range}/{len(rows)}")
    print(f"  Rows with NUMERIC Min/Max_Reference   : {numeric_range}/{len(rows)}")
    print("  Critical thresholds in dataset        : NO (normal band only)")

    print("\n--- Status distribution ---")
    for status, count in Counter(r["Status"] for r in rows).most_common():
        print(f"  {status:<12} {count}")

    print("\n--- Units seen ---")
    print("  " + ", ".join(sorted({r["Unit"] for r in rows if r["Unit"].strip()})))

    return 0


if __name__ == "__main__":
    sys.exit(main())
