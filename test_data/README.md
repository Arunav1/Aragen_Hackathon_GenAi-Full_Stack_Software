# Synthetic test fixtures

**These are hand-authored synthetic test fixtures. They are not patient data, and
they are not copies of or extracts from the Kaggle dataset in
`Laboratory_Test_Resutlts_dataset/`.** Every value was chosen to fall clearly inside
its intended band so that classification is unambiguous during a demo.

All three files use the header `test_name,value,unit`, which is exactly what the
frontend's CSV upload accepts and what `POST /analyze_labs` consumes. Verified end to
end by `scripts/verify_test_data.py`.

| File | Rows | Purpose |
|---|---|---|
| `all_normal.csv` | 7 | The all-clear path — every marker inside its normal band. |
| `mixed.csv` | 7 | A realistic spread: normal, warning, critical, and one qualitative row. |
| `critical_heavy.csv` | 7 | The demo file — multiple criticals that trigger every panel insight. |

## Expected outcomes

### `all_normal.csv`
All seven results normal, no panel insights, nothing routed to manual review. Six
canonical markers score against hardcoded ranges; Ferritin scores against the
dataset-derived band, so this file also exercises the `mcp_lookup` range source.

### `mixed.csv`
- **Critical** — Hemoglobin 6.4 g/dL (below critical-low 7.0)
- **Warning** — Glucose 118 mg/dL, Creatinine 1.9 mg/dL
- **Normal** — Potassium, Sodium, WBC
- **Unknown** — `Protein (Strip)` reported as `Negatif`, a qualitative dipstick result
  with no numeric band. It is not rejected: it is classified `unknown` and routed to
  the collapsed "Requires manual review" section, which exercises that path.

### `critical_heavy.csv`
Five critical results plus two warnings, chosen so that all four multi-marker
patterns fire at once:

| Pattern | Fires because |
|---|---|
| `renal_impairment_with_hyperkalemia` | Creatinine 5.6 high **and** Potassium 6.8 high |
| `anemia` | Hemoglobin 6.2 below critical-low |
| `hyperglycemia_with_hyponatremia` | Glucose 310 high **and** Sodium 128 low |
| `cytopenia_or_infection_signal` | WBC 1.6 critical-low **and** Hemoglobin low |

Sodium 128 is deliberately a *warning*, not a critical: it sits between critical-low
120 and normal-low 135. It still contributes to a panel, which shows that panel
detection weighs combinations rather than only critical values.

Ferritin 8 ug/L is a warning against the dataset-derived band. Because the dataset
carries no critical thresholds, that marker cannot escalate past warning — the
`basis` string says so explicitly.
