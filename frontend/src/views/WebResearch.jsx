import { useEffect, useState } from 'react'
import { ArrowUp, Globe, Loader2, Plus, Search, Square, RotateCcw } from 'lucide-react'
import { useResearchStream } from '../hooks/useResearchStream'
import { useApp } from '../context'
import Markdown from '../components/Markdown'
import { Empty, ErrorBox, ExportButtons, SourceList, Steps, elapsed, scrollToSource, autoGrow } from '../components/common'

const EXAMPLES = [
  'What are the latest breakthroughs in solid-state batteries?',
  'How does retrieval-augmented generation reduce LLM hallucinations?',
  'Compare the economic effects of remote work in the US and UK',
]

const DEPTHS = [
  { id: 'quick', label: 'Quick', hint: '1 query · 4 sources' },
  { id: 'standard', label: 'Standard', hint: '2 queries · 6 sources' },
  { id: 'deep', label: 'Deep', hint: '3 queries · 10 sources' },
]

export default function WebResearch({ resetSignal }) {
  const { model } = useApp()
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('')
  const [depth, setDepth] = useState('standard')
  const [highlight, setHighlight] = useState(null)
  const r = useResearchStream()

  const submit = (q = question) => {
    if (q.trim().length < 3 || r.running) return
    setAsked(q.trim())
    r.run('/api/research/web', { question: q.trim(), depth, model })
  }

  const started = r.running || r.answer || r.error || r.steps.length

  const startOver = () => {
    r.reset()
    setQuestion('')
    setAsked('')
    setHighlight(null)
  }
  useEffect(() => {
    if (resetSignal) startOver()
  }, [resetSignal]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="view">
      <header className="view-header">
        <div>
          <h1>Web Research</h1>
          <p className="muted">Searches the web, reads the sources and writes an answer with citations.</p>
        </div>
        {started && (
          <button className="btn btn-ghost" onClick={startOver}>
            <Plus size={16} /> New research
          </button>
        )}
      </header>

      <form
        className="ask-box"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Search size={18} className="muted" />
        <textarea
          rows={1}
          value={question}
          placeholder="Ask a research question…"
          onChange={(e) => setQuestion(e.target.value)}
          onInput={autoGrow}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        {r.running ? (
          <button type="button" className="btn btn-icon btn-danger" onClick={r.stop} title="Stop" disabled={r.stopping}>
            {r.stopping ? <Loader2 size={16} className="spin" /> : <Square size={16} />}
          </button>
        ) : (
          <button className="btn btn-icon btn-primary" disabled={question.trim().length < 3} title="Research">
            <ArrowUp size={18} />
          </button>
        )}
      </form>
      <div className="segmented" role="radiogroup" aria-label="Research depth">
        {DEPTHS.map((d) => (
          <button
            key={d.id}
            type="button"
            className={depth === d.id ? 'active' : ''}
            onClick={() => setDepth(d.id)}
            title={d.hint}
          >
            {d.label}
            <span>{d.hint}</span>
          </button>
        ))}
      </div>

      {!started ? (
        <Empty icon={Globe} title="Start with a question">
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                className="chip"
                onClick={() => {
                  setQuestion(ex)
                  submit(ex)
                }}
              >
                {ex}
              </button>
            ))}
          </div>
        </Empty>
      ) : (
        <div className="result-grid">
          <section className="card answer-card">
            <div className="answer-top">
              <h2>{asked}</h2>
              {!r.running && (r.answer || r.error) && (
                <button className="btn btn-ghost btn-sm" onClick={() => submit(asked)}>
                  <RotateCcw size={14} /> Retry
                </button>
              )}
            </div>
            <Steps steps={r.steps} running={r.running} />
            {r.queries.length > 1 && (
              <div className="queries">
                {r.queries.map((q) => (
                  <span key={q} className="tag">
                    <Search size={11} /> {q}
                  </span>
                ))}
              </div>
            )}
            <ErrorBox message={r.error} />
            {r.answer && (
              <Markdown
                text={r.answer}
                sources={r.sources}
                streaming={r.running}
                onCite={(n) => scrollToSource('web', n, setHighlight)}
              />
            )}
            {r.entryId && (
              <div className="answer-footer">
                <span className="muted small">
                  {r.stopped && '⏹ Stopped · '}Saved to Library · {r.sources.length} sources · {elapsed(r.startedAt, r.finishedAt)}
                </span>
                <ExportButtons entryIds={[r.entryId]} />
              </div>
            )}
          </section>
          <aside className="sources-col">
            <h3 className="col-title">Sources {r.sources.length ? `(${r.sources.length})` : ''}</h3>
            {r.sources.length ? (
              <SourceList sources={r.sources} highlight={highlight} idPrefix="web" />
            ) : (
              <div className="skeleton-list">{r.running && [0, 1, 2].map((i) => <div key={i} className="skeleton" />)}</div>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
