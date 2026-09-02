import { useRef, useState } from 'react'

/** Demo safety net: hits all three severities, two panel patterns, and an
 *  unknown marker. Nothing needs typing during a pitch. */
const EXAMPLE_LABS = [
  { test_name: 'Glucose', value: '260', unit: 'mg/dL' },
  { test_name: 'Creatinine', value: '4.8', unit: 'mg/dL' },
  { test_name: 'Potassium', value: '6.4', unit: 'mmol/L' },
  { test_name: 'Hemoglobin', value: '9.1', unit: 'g/dL' },
  { test_name: 'Sodium', value: '131', unit: 'mmol/L' },
  { test_name: 'Lökosit', value: '12.5', unit: '10^3/uL' },
  { test_name: 'Ferritin', value: '45', unit: 'ug/L' },
  { test_name: 'Unobtanium', value: '42', unit: 'mg/dL' },
]

const BLANK = { test_name: '', value: '', unit: '' }

// Accept our own header names and the source dataset's.
const COLUMN_ALIASES = {
  test_name: 'test_name', test: 'test_name', name: 'test_name', 'test name': 'test_name',
  value: 'value', result: 'value',
  unit: 'unit', units: 'unit',
}

function splitCsvLine(line) {
  const out = []
  let cur = ''
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i += 1 }
      else if (ch === '"') quoted = false
      else cur += ch
    } else if (ch === '"') quoted = true
    else if (ch === ',') { out.push(cur); cur = '' }
    else cur += ch
  }
  out.push(cur)
  return out.map((s) => s.trim())
}

export function parseCsv(text) {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim())
  if (!lines.length) return { rows: [], error: 'The file is empty.' }

  const header = splitCsvLine(lines[0]).map((h) => COLUMN_ALIASES[h.toLowerCase()] || null)
  if (!header.includes('test_name') || !header.includes('value')) {
    return {
      rows: [],
      error: 'CSV needs a header row with at least test_name and value columns.',
    }
  }

  const rows = lines.slice(1).map((line) => {
    const cells = splitCsvLine(line)
    const row = { ...BLANK }
    header.forEach((field, i) => {
      if (field) row[field] = cells[i] ?? ''
    })
    return row
  })
  return { rows, error: null }
}

export default function LabInput({ onAnalyze, loading }) {
  const [mode, setMode] = useState('manual')
  const [rows, setRows] = useState([{ ...BLANK }, { ...BLANK }, { ...BLANK }])
  const [csvError, setCsvError] = useState(null)
  const [csvName, setCsvName] = useState(null)
  const fileRef = useRef(null)

  const update = (i, field, v) =>
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, [field]: v } : r)))
  const addRow = () => setRows((prev) => [...prev, { ...BLANK }])
  const removeRow = (i) => setRows((prev) => prev.filter((_, j) => j !== i))

  const loadExample = () => {
    setMode('manual')
    setCsvError(null)
    setCsvName(null)
    setRows(EXAMPLE_LABS.map((r) => ({ ...r })))
  }

  const clearAll = () => {
    setRows([{ ...BLANK }, { ...BLANK }, { ...BLANK }])
    setCsvError(null)
    setCsvName(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const handleFile = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setCsvName(file.name)
    const { rows: parsed, error } = parseCsv(await file.text())
    setCsvError(error)
    if (!error) {
      setRows(parsed.length ? parsed : [{ ...BLANK }])
      setMode('manual')
    }
  }

  const populated = rows.filter((r) => r.test_name.trim() || String(r.value).trim())

  const submit = (event) => {
    event.preventDefault()
    // Send rows as typed. Blank names and non-numeric values are deliberately
    // passed through — the backend triages them as `unknown` rather than
    // rejecting them, and that path is worth showing.
    onAnalyze(
      populated.map((r) => ({
        test_name: r.test_name.trim(),
        value: String(r.value).trim(),
        unit: r.unit.trim(),
      }))
    )
  }

  return (
    <form className="panel" onSubmit={submit}>
      <div className="panel-head">
        <h2>Lab values</h2>
        <div className="mode-switch">
          <button
            type="button"
            className={mode === 'manual' ? 'tab tab-on' : 'tab'}
            onClick={() => setMode('manual')}
          >
            Manual entry
          </button>
          <button
            type="button"
            className={mode === 'csv' ? 'tab tab-on' : 'tab'}
            onClick={() => setMode('csv')}
          >
            CSV upload
          </button>
        </div>
      </div>

      {mode === 'csv' && (
        <div className="csv-drop">
          <label className="btn btn-ghost" htmlFor="csv-file">Choose a CSV file</label>
          <input
            id="csv-file"
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            onChange={handleFile}
            hidden
          />
          <p className="hint">
            Header row required: <code>test_name,value,unit</code>
            {' '}(the dataset's <code>Test_Name,Result,Unit</code> also works).
          </p>
          {csvName && !csvError && (
            <p className="hint ok">Loaded {csvName} — {rows.length} row(s), now editable below.</p>
          )}
          {csvError && <p className="hint err">{csvError}</p>}
        </div>
      )}

      <div className="rows">
        <div className="row row-head">
          <span>Test name</span>
          <span>Value</span>
          <span>Unit</span>
          <span />
        </div>
        {rows.map((row, i) => (
          <div className="row" key={i}>
            <input
              value={row.test_name}
              onChange={(e) => update(i, 'test_name', e.target.value)}
              placeholder="e.g. Potassium"
              aria-label={`Test name row ${i + 1}`}
            />
            <input
              value={row.value}
              onChange={(e) => update(i, 'value', e.target.value)}
              placeholder="e.g. 6.4"
              aria-label={`Value row ${i + 1}`}
            />
            <input
              value={row.unit}
              onChange={(e) => update(i, 'unit', e.target.value)}
              placeholder="mmol/L"
              aria-label={`Unit row ${i + 1}`}
            />
            <button
              type="button"
              className="btn-icon"
              onClick={() => removeRow(i)}
              disabled={rows.length === 1}
              aria-label={`Remove row ${i + 1}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="actions">
        <button type="button" className="btn btn-ghost" onClick={addRow}>
          + Add row
        </button>
        <button type="button" className="btn btn-ghost" onClick={loadExample}>
          Load example
        </button>
        <button type="button" className="btn btn-ghost" onClick={clearAll}>
          Clear
        </button>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={loading || populated.length === 0}
        >
          {loading ? 'Analyzing…' : `Analyze ${populated.length || ''} lab${populated.length === 1 ? '' : 's'}`}
        </button>
      </div>
    </form>
  )
}
