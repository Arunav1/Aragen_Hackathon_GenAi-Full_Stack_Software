import { useState } from 'react'
import SeverityBadge from './SeverityBadge.jsx'
import RangeGauge from './RangeGauge.jsx'

/** Statuses that were actually scored against a reference range. */
const SCORED = [
  { status: 'critical', title: 'Critical', icon: '🚨' },
  { status: 'warning', title: 'Warning', icon: '⚠️' },
  { status: 'normal', title: 'Normal', icon: '✓' },
]

const SOURCE_LABEL = {
  hardcoded: 'range: hardcoded',
  mcp_lookup: 'range: mcp_lookup',
}

function ResultCard({ result }) {
  const fromLlm = result.explanation_source === 'llm'
  return (
    <article className={`card card-${result.status}`}>
      <header className="card-head">
        <div className="card-ident">
          <h4>{result.display_name || result.test_name || '(unnamed test)'}</h4>
          <p className="card-value">
            {result.value === null || result.value === '' ? '—' : String(result.value)}
            {result.unit ? <span className="unit"> {result.unit}</span> : null}
          </p>
        </div>
        <SeverityBadge status={result.status} />
      </header>

      <RangeGauge value={result.value} unit={result.unit} reference={result.reference} />

      <section className="field field-basis">
        <h5>Why flagged <span className="tag tag-rule">deterministic rule</span></h5>
        <p>{result.basis}</p>
        {result.rule && <code className="rule-id">{result.rule}</code>}
      </section>

      <section className="field">
        <h5>
          Clinical explanation{' '}
          <span className={`tag ${fromLlm ? 'tag-llm' : 'tag-fallback'}`}>
            {fromLlm ? 'AI-generated' : 'AI unavailable — showing rule text'}
          </span>
        </h5>
        <p>{result.explanation}</p>
      </section>

      <section className="field">
        <h5>Suggested next steps</h5>
        <p>{result.next_steps}</p>
      </section>

      <footer className="card-foot">
        <span className="tag tag-source">
          {SOURCE_LABEL[result.source] || 'range: none'}
        </span>
      </footer>
    </article>
  )
}

function FilterChip({ kind, count, label, icon, active, onClick }) {
  return (
    <button
      type="button"
      className={`chip chip-${kind}${active ? ' chip-active' : ''}`}
      onClick={onClick}
      aria-pressed={active}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      {count !== undefined ? `${count} ${label}` : label}
    </button>
  )
}

export default function ResultsDisplay({ summary, results }) {
  const [filter, setFilter] = useState('all')
  const [manualOpen, setManualOpen] = useState(false)

  if (!results?.length) return null

  // Unscored rows are routed out of the main grid, not discarded: every row
  // still went through the agent, and the backend's unknown handling is
  // untouched. This is purely a decision about what to surface first.
  const scored = results.filter((r) => r.status !== 'unknown')
  const manual = results.filter((r) => r.status === 'unknown')

  const visible = filter === 'all' ? scored : scored.filter((r) => r.status === filter)
  const grouped = SCORED.map((g) => ({
    ...g,
    items: visible.filter((r) => r.status === g.status),
  })).filter((g) => g.items.length > 0)

  const showManual = manualOpen || filter === 'unknown'

  const pick = (next) => {
    setFilter((cur) => (cur === next ? 'all' : next))
    if (next === 'unknown') setManualOpen(true)
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Results</h2>
        <div className="summary-strip" role="group" aria-label="Filter results by severity">
          <FilterChip
            kind="all"
            label="All"
            active={filter === 'all'}
            onClick={() => setFilter('all')}
          />
          <FilterChip
            kind="critical" icon="🚨" count={summary.critical} label="critical"
            active={filter === 'critical'} onClick={() => pick('critical')}
          />
          <FilterChip
            kind="warning" icon="⚠️" count={summary.warning} label="warning"
            active={filter === 'warning'} onClick={() => pick('warning')}
          />
          <FilterChip
            kind="normal" icon="✓" count={summary.normal} label="normal"
            active={filter === 'normal'} onClick={() => pick('normal')}
          />
          {manual.length > 0 && (
            <FilterChip
              kind="unknown" icon="?" count={manual.length} label="manual"
              active={filter === 'unknown'} onClick={() => pick('unknown')}
            />
          )}
        </div>
      </div>

      {grouped.length === 0 && filter !== 'unknown' && (
        <p className="hint empty-note">No results in this severity.</p>
      )}

      {filter !== 'unknown' &&
        grouped.map((group) => (
          <div className="group" key={group.status}>
            <h3 className={`group-title group-${group.status}`}>
              <span aria-hidden="true">{group.icon}</span> {group.title}
              <span className="group-count">{group.items.length}</span>
            </h3>
            <div className="card-grid">
              {group.items.map((r, i) => (
                <ResultCard key={`${r.test_name}-${i}`} result={r} />
              ))}
            </div>
          </div>
        ))}

      {manual.length > 0 && (
        <div className={`manual${showManual ? ' manual-open' : ''}`}>
          <button
            type="button"
            className="manual-toggle"
            onClick={() => setManualOpen((v) => !v)}
            aria-expanded={showManual}
          >
            <span className="chevron" aria-hidden="true">›</span>
            <span className="manual-title">Requires manual review ({manual.length})</span>
            <span className="manual-sub">
              {manual.length} result{manual.length === 1 ? '' : 's'} couldn&rsquo;t be
              scored against a reference range and {manual.length === 1 ? 'is' : 'are'}{' '}
              routed for manual clinician review.
            </span>
          </button>

          {/* Collapsed with a 0fr/1fr grid row rather than `hidden`, so the
              section can animate open instead of snapping. */}
          <div className="manual-body" aria-hidden={!showManual}>
            <div className="manual-body-inner">
              <div className="card-grid">
                {manual.map((r, i) => (
                  <ResultCard key={`manual-${r.test_name}-${i}`} result={r} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
