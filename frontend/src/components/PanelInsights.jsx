/** Multi-marker findings: combinations detected in code, narrated by the LLM. */
export default function PanelInsights({ insights }) {
  if (!insights?.length) return null

  return (
    <section className="panel panel-insights">
      <div className="panel-head">
        <h2>Multi-marker insights</h2>
        <span className="hint">
          Combinations detected deterministically in code · narrated by Gemini
        </span>
      </div>

      <div className="insight-grid">
        {insights.map((p, i) => (
          <article className={`insight insight-${p.severity || 'warning'}`} key={p.pattern + i}>
            <header className="insight-head">
              <div className="marker-chips">
                {(p.markers || []).map((m) => (
                  <span className="marker-chip" key={m}>{m}</span>
                ))}
              </div>
              <span className={`tag tag-sev-${p.severity || 'warning'}`}>{p.severity}</span>
            </header>

            <p className="insight-text">{p.insight}</p>

            <div className="insight-basis">
              <h5>Detected because <span className="tag tag-rule">deterministic</span></h5>
              <p>{p.basis}</p>
            </div>

            <footer className="insight-foot">
              <span className="routing">→ {p.routing}</span>
            </footer>
          </article>
        ))}
      </div>
    </section>
  )
}
