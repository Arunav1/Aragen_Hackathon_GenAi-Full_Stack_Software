import { useEffect, useState } from 'react'
import ThemeToggle from './components/ThemeToggle.jsx'
import LabInput from './components/LabInput.jsx'
import ResultsDisplay from './components/ResultsDisplay.jsx'
import PipelineView from './components/PipelineView.jsx'
import PanelInsights from './components/PanelInsights.jsx'
import { analyzeLabs, API_BASE } from './api.js'

/** Placeholder cards shaped like the real ones, so the ~1s Gemini wait reads
 *  as the result loading in rather than as an empty pause. */
function ResultsSkeleton() {
  return (
    <section className="panel" aria-busy="true" aria-label="Analyzing lab results">
      <div className="panel-head">
        <h2>Analyzing…</h2>
        <span className="hint">
          Classifying over MCP, then one batched Gemini call for every explanation.
        </span>
      </div>
      <div className="card-grid">
        {[0, 1, 2].map((i) => (
          <div className="card card-skeleton" key={i}>
            <div className="sk sk-title" />
            <div className="sk sk-value" />
            <div className="sk sk-gauge" />
            <div className="sk sk-block" />
            <div className="sk sk-line" />
            <div className="sk sk-line sk-short" />
          </div>
        ))}
      </div>
    </section>
  )
}

/** Remembered choice wins; otherwise follow the OS setting. Storage can throw
 *  in a private window, so every access is guarded. */
function initialTheme() {
  try {
    const saved = localStorage.getItem('theme')
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    /* storage unavailable — fall through to the OS preference */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [theme, setTheme] = useState(initialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', theme)
    // Keeps native scrollbars and form controls in step with the page.
    root.style.colorScheme = theme
    try {
      localStorage.setItem('theme', theme)
    } catch {
      /* not persisting is fine; the toggle still works for this session */
    }
  }, [theme])

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
          <div className="masthead-right">
            {data?.meta && (
              <div className="meta-chips">
                <span className="tag tag-mcp">{data.meta.mcp_calls} MCP calls</span>
                <span className={`tag ${data.meta.llm_ok ? 'tag-llm' : 'tag-fallback'}`}>
                  {data.meta.llm_ok ? data.meta.llm_model : 'LLM unavailable'}
                </span>
              </div>
            )}
            <ThemeToggle
              theme={theme}
              onToggle={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
            />
          </div>
        </div>
      </header>

      {/* The assignment's key constraint: a designed, sticky element rather
          than fine print, so it stays visible while scrolling results. */}
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

        {loading && <ResultsSkeleton />}

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
        <div className="footer-row">
          <p>
            Classification is deterministic and runs in code, exposed as MCP tools.
            The language model writes explanations only — it never sets a status.
          </p>
          <p className="footer-strong">Decision support, not a diagnosis.</p>
        </div>
        <p className="footer-credit">Developed By: Arunabha Dutta</p>
      </footer>
    </div>
  )
}
