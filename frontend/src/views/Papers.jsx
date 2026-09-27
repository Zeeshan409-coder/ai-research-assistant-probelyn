import { useEffect, useState } from 'react'
import {
  BookOpen, ChevronDown, ChevronUp, ExternalLink, FileDown, GraduationCap, Library,
  Loader2, Plus, Quote, Search, Sparkles, Square,
} from 'lucide-react'
import { api, streamSSE } from '../api'
import { useApp } from '../context'
import { useResearchStream } from '../hooks/useResearchStream'
import Markdown from '../components/Markdown'
import { Empty, ErrorBox, ExportButtons, Steps, scrollToSource } from '../components/common'

const EXAMPLES = ['graph neural networks for drug discovery', 'vision transformers efficiency', 'LLM hallucination detection']

function PaperCard({ paper, highlight }) {
  const { model, toast } = useApp()
  const [open, setOpen] = useState(false)
  const [summary, setSummary] = useState('')
  const [summarizing, setSummarizing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState(false)

  const summarize = async () => {
    setSummarizing(true)
    setSummary('')
    try {
      await streamSSE('/api/papers/summarize', { title: paper.title, abstract: paper.abstract, model }, (ev, data) => {
        if (ev === 'token') setSummary((s) => s + data)
        if (ev === 'error') toast(data.message, 'error')
      })
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSummarizing(false)
    }
  }

  const addToLibrary = async () => {
    setImporting(true)
    try {
      await api.post('/api/papers/import', { pdf_url: paper.pdf_url, title: paper.title })
      setImported(true)
      toast('PDF added to Documents – indexing now. Open the Documents tab to chat with it.', 'success')
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setImporting(false)
    }
  }

  const authors = paper.authors.slice(0, 4).join(', ') + (paper.authors.length > 4 ? ' et al.' : '')

  return (
    <article id={`paper-${paper.n}`} className={`card paper ${highlight ? 'highlight' : ''}`}>
      <div className="paper-top">
        <span className="source-n">{paper.n}</span>
        <div className="paper-main">
          <a className="paper-title" href={paper.url} target="_blank" rel="noreferrer">
            {paper.title}
          </a>
          <div className="paper-meta">
            {authors && <span>{authors}</span>}
            {paper.year && <span>· {paper.year}</span>}
            {paper.venue && <span>· {paper.venue}</span>}
          </div>
          <div className="paper-badges">
            <span className="tag">{paper.source}</span>
            {paper.citations != null && (
              <span className="tag tag-accent">
                <Quote size={11} /> {paper.citations.toLocaleString()} citations
              </span>
            )}
            {paper.pdf_url && <span className="tag tag-green">Open access PDF</span>}
          </div>
        </div>
      </div>

      {paper.abstract ? (
        <p className={`abstract ${open ? 'open' : ''}`}>{paper.abstract}</p>
      ) : (
        <p className="abstract muted">No abstract available.</p>
      )}

      {summary && (
        <div className="summary-box">
          <Markdown text={summary} streaming={summarizing} />
        </div>
      )}

      <div className="paper-actions">
        {paper.abstract && (
          <button className="btn btn-ghost btn-sm" onClick={() => setOpen((o) => !o)}>
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {open ? 'Less' : 'Abstract'}
          </button>
        )}
        {paper.abstract && (
          <button className="btn btn-ghost btn-sm" onClick={summarize} disabled={summarizing}>
            {summarizing ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />} Summarize
          </button>
        )}
        {paper.pdf_url && (
          <>
            <button className="btn btn-ghost btn-sm" onClick={addToLibrary} disabled={importing || imported}>
              {importing ? <Loader2 size={14} className="spin" /> : <FileDown size={14} />}
              {imported ? 'Added' : 'Chat with PDF'}
            </button>
            <a className="btn btn-ghost btn-sm" href={paper.pdf_url} target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> PDF
            </a>
          </>
        )}
      </div>
    </article>
  )
}

export default function Papers({ resetSignal }) {
  const { model } = useApp()
  const [query, setQuery] = useState('')
  const [asked, setAsked] = useState('')
  const [yearFrom, setYearFrom] = useState('')
  const [sort, setSort] = useState('relevance')
  const [limit, setLimit] = useState(10)
  const [srcs, setSrcs] = useState({ arxiv: true, s2: true })
  const [highlight, setHighlight] = useState(null)
  const r = useResearchStream()

  const submit = (q = query) => {
    const sources = Object.keys(srcs).filter((k) => srcs[k])
    if (q.trim().length < 2 || !sources.length || r.running) return
    setAsked(q.trim())
    r.run('/api/papers/research', {
      query: q.trim(),
      limit: Number(limit),
      sort,
      sources,
      year_from: yearFrom ? Number(yearFrom) : null,
      model,
    })
  }

  const started = r.running || r.papers.length || r.error

  const startOver = () => {
    r.reset()
    setQuery('')
    setAsked('')
    setHighlight(null)
  }
  useEffect(() => {
    if (resetSignal) startOver()
  }, [resetSignal]) // eslint-disable-line react-hooks/exhaustive-deps
  const sourcesForCites = r.papers.map((p) => ({ n: p.n, title: p.title }))

  return (
    <div className="view">
      <header className="view-header">
        <div>
          <h1>Paper Search</h1>
          <p className="muted">Finds papers on arXiv &amp; Semantic Scholar and writes a literature overview.</p>
        </div>
        {started && (
          <button className="btn btn-ghost" onClick={startOver}>
            <Plus size={16} /> New search
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
        <GraduationCap size={18} className="muted" />
        <input value={query} placeholder="Research topic, e.g. 'diffusion models for protein design'" onChange={(e) => setQuery(e.target.value)} />
        {r.running ? (
          <button type="button" className="btn btn-icon btn-danger" onClick={r.stop} title="Stop" disabled={r.stopping}>
            {r.stopping ? <Loader2 size={16} className="spin" /> : <Square size={16} />}
          </button>
        ) : (
          <button className="btn btn-icon btn-primary" disabled={query.trim().length < 2} title="Search">
            <Search size={17} />
          </button>
        )}
      </form>

      <div className="filters">
        <label>
          Since
          <input type="number" min="1900" max="2100" placeholder="any year" value={yearFrom} onChange={(e) => setYearFrom(e.target.value)} />
        </label>
        <label>
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="relevance">Relevance</option>
            <option value="citations">Most cited</option>
            <option value="recent">Newest</option>
          </select>
        </label>
        <label>
          Results
          <select value={limit} onChange={(e) => setLimit(e.target.value)}>
            {[5, 10, 15, 20].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={srcs.arxiv} onChange={(e) => setSrcs({ ...srcs, arxiv: e.target.checked })} /> arXiv
        </label>
        <label className="check">
          <input type="checkbox" checked={srcs.s2} onChange={(e) => setSrcs({ ...srcs, s2: e.target.checked })} /> Semantic Scholar
        </label>
      </div>

      {!started ? (
        <Empty icon={BookOpen} title="Search the literature">
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="chip" onClick={() => { setQuery(ex); submit(ex) }}>
                {ex}
              </button>
            ))}
          </div>
        </Empty>
      ) : (
        <div className="papers-layout">
          <section className="card answer-card">
            <div className="answer-top">
              <h2>
                <Library size={18} /> Literature overview: {asked}
              </h2>
            </div>
            <Steps steps={r.steps} running={r.running} />
            {r.warnings.map((w) => (
              <div key={w} className="alert alert-warn">{w}</div>
            ))}
            <ErrorBox message={r.error} />
            {r.answer && (
              <Markdown
                text={r.answer}
                sources={sourcesForCites}
                streaming={r.running}
                onCite={(n) => scrollToSource('paper', n, setHighlight)}
              />
            )}
            {r.entryId && (
              <div className="answer-footer">
                <span className="muted small">{r.stopped && '⏹ Stopped · '}Saved to Library · {r.papers.length} papers</span>
                <ExportButtons entryIds={[r.entryId]} />
              </div>
            )}
          </section>
          <div className="paper-list">
            {r.papers.map((p) => (
              <PaperCard key={p.id} paper={p} highlight={highlight === p.n} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
