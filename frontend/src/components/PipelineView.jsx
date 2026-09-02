const STAGE_META = {
  classify: { title: 'Classify', blurb: 'Deterministic rules via MCP' },
  route: { title: 'Route', blurb: 'Ordering, next steps, panel detection' },
  explain: { title: 'Explain', blurb: 'Gemini writes the prose' },
}

/** Renders the agent's own trace: Classify -> Route -> Explain. */
export default function PipelineView({ pipeline }) {
  if (!pipeline?.length) return null

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Agent pipeline</h2>
        <span className="hint">LangGraph StateGraph · tools called over MCP (stdio)</span>
      </div>

      <ol className="pipeline">
        {pipeline.map((stage, i) => {
          const meta = STAGE_META[stage.stage] || { title: stage.stage, blurb: '' }
          return (
            <li className="stage" key={stage.stage + i}>
              <div className="stage-head">
                <span className="stage-num">{i + 1}</span>
                <div>
                  <h4>{meta.title}</h4>
                  <span className="hint">{meta.blurb}</span>
                </div>
              </div>
              <p className="stage-detail">{stage.detail}</p>
              <div className="stage-tags">
                <span className={`tag ${stage.llm_used ? 'tag-llm' : 'tag-rule'}`}>
                  {stage.llm_used ? 'LLM used' : 'no LLM'}
                </span>
                {stage.mcp_calls > 0 && (
                  <span className="tag tag-mcp">{stage.mcp_calls} MCP calls</span>
                )}
                {(stage.tools_used || []).map((t) => (
                  <span className="tag tag-tool" key={t}>{t}()</span>
                ))}
              </div>
              {i < pipeline.length - 1 && <div className="stage-arrow" aria-hidden="true">↓</div>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
