import SeverityBadge from './SeverityBadge.jsx'
import RangeGauge from './RangeGauge.jsx'

const GROUPS = [
  { status: 'critical', title: 'Critical', icon: '🚨' },
  { status: 'warning', title: 'Warning', icon: '⚠️' },
  { status: 'normal', title: 'Normal', icon: '✓' },
  { status: 'unknown', title: 'Not triaged', icon: '?' },
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
        <div>
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

export default function ResultsDisplay({ summary, results }) {
  if (!results?.length) return null

  const grouped = GROUPS.map((g) => ({
    ...g,
    items: results.filter((r) => r.status === g.status),
  })).filter((g) => g.items.length > 0)

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Results</h2>
        <div className="summary-strip">
          <span className="chip chip-critical">🚨 {summary.critical} critical</span>
          <span className="chip chip-warning">⚠️ {summary.warning} warning</span>
          <span className="chip chip-normal">✓ {summary.normal} normal</span>
          {summary.unknown > 0 && (
            <span className="chip chip-unknown">? {summary.unknown} unknown</span>
          )}
        </div>
      </div>

      {grouped.map((group) => (
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
    </section>
  )
}
