import { useState } from 'react'
import LabInput from './components/LabInput.jsx'
import ResultsDisplay from './components/ResultsDisplay.jsx'
import PipelineView from './components/PipelineView.jsx'
import PanelInsights from './components/PanelInsights.jsx'
import { analyzeLabs, API_BASE } from './api.js'

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleAnalyze = async (labs) => {
    setLoading(true)
    setError(null)
    try {
      setData(await analyzeLabs(labs))
    } catch (err) {
      setError(err.message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead-inner">
          <div>
            <h1>Clinical Lab Triage Agent</h1>
            <p className="subtitle">
              Deterministic classification over MCP · explanations by Gemini
            </p>
          </div>
          {data?.meta && (
            <div className="meta-chips">
              <span className="tag tag-mcp">{data.meta.mcp_calls} MCP calls</span>
              <span className={`tag ${data.meta.llm_ok ? 'tag-llm' : 'tag-fallback'}`}>
                {data.meta.llm_ok ? data.meta.llm_model : 'LLM unavailable'}
              </span>
            </div>
          )}
        </div>
      </header>

      {/* The assignment's key constraint, as a designed element rather than fine print. */}
      <div className="disclaimer" role="note">
        <span className="disclaimer-icon" aria-hidden="true">⚕</span>
        <div>
          <strong>Decision support, not a diagnosis.</strong>
          <span>
            {' '}Automated triage for clinician review only. It does not replace
            clinical judgement, and no output here is a diagnosis.
          </span>
        </div>
      </div>

      <main className="content">
        <LabInput onAnalyze={handleAnalyze} loading={loading} />

        {loading && (
          <div className="panel state-panel">
            <div className="spinner" aria-hidden="true" />
            <div>
              <h3>Running the agent…</h3>
              <p className="hint">
                Classifying over MCP, then one batched Gemini call for all
                explanations. Usually a few seconds.
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="panel state-panel state-error" role="alert">
            <span className="state-icon" aria-hidden="true">⚠</span>
            <div>
              <h3>Backend unreachable</h3>
              <p>{error}</p>
              <p className="hint">Configured API base: <code>{API_BASE}</code></p>
            </div>
          </div>
        )}

        {data && !loading && (
          <>
            {data.errors?.length > 0 && (
              <div className="panel state-panel state-warn">
                <span className="state-icon" aria-hidden="true">ℹ</span>
                <div>
                  <h3>{data.errors.length} input issue(s) — handled, not rejected</h3>
                  <ul className="issue-list">
                    {data.errors.map((e, i) => (
                      <li key={i}>
                        {e.index !== null && e.index !== undefined ? `Row ${e.index + 1}: ` : ''}
                        {e.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            <PanelInsights insights={data.panel_insights} />
            <ResultsDisplay summary={data.summary} results={data.results} />
            <PipelineView pipeline={data.pipeline} />
          </>
        )}
      </main>

      <footer className="footer">
        <p>
          Classification is deterministic and runs in code, exposed as MCP tools.
          The language model writes explanations only — it never sets a status.
        </p>
        <p className="footer-strong">Decision support, not a diagnosis.</p>
      </footer>
    </div>
  )
}
