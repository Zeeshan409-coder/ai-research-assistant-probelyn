import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, CheckSquare, Plus, FileText, Loader2, MessageSquareText, Square, Trash2, UploadCloud, AlertCircle } from 'lucide-react'
import { api, streamSSE } from '../api'
import { useApp } from '../context'
import Markdown from '../components/Markdown'
import { Empty, ExportButtons, SourceList, scrollToSource, autoGrow } from '../components/common'

function DocRow({ doc, selected, onToggle, onDelete }) {
  const ready = doc.status === 'ready'
  return (
    <div className={`doc-row ${selected ? 'selected' : ''} ${ready ? '' : 'disabled'}`}>
      <button className="doc-check" disabled={!ready} onClick={() => onToggle(doc.id)} title={ready ? 'Include in chat' : doc.status}>
        {selected ? <CheckSquare size={16} /> : <Square size={16} />}
      </button>
      <div className="doc-info" onClick={() => ready && onToggle(doc.id)}>
        <div className="doc-title" title={doc.title}>{doc.title}</div>
        <div className="doc-meta">
          {doc.status === 'processing' && (
            <span className="status-processing">
              <Loader2 size={11} className="spin" /> Indexing…
            </span>
          )}
          {doc.status === 'error' && (
            <span className="status-error" title={doc.error}>
              <AlertCircle size={11} /> {doc.error?.slice(0, 60) || 'Failed'}
            </span>
          )}
          {ready && `${doc.pages} pages · ${doc.chunks} chunks`}
        </div>
      </div>
      <button className="btn btn-icon btn-ghost btn-xs" onClick={() => onDelete(doc)} title="Delete">
        <Trash2 size={14} />
      </button>
    </div>
  )
}

export default function Documents({ active, resetSignal }) {
  const { model, toast, bumpLibrary } = useApp()
  const [docs, setDocs] = useState([])
  const [selected, setSelected] = useState(new Set())
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(0)
  const [drag, setDrag] = useState(false)
  const [highlight, setHighlight] = useState(null)
  const fileInput = useRef(null)
  const threadEnd = useRef(null)
  const abortRef = useRef(null)
  const runEntryRef = useRef(null)
  const [stopping, setStopping] = useState(false)

  const load = useCallback(async () => {
    try {
      const list = await api.get('/api/documents')
      setDocs(list)
      // auto-select newly ready documents
      setSelected((sel) => {
        const next = new Set([...sel].filter((id) => list.some((d) => d.id === id && d.status === 'ready')))
        if (!sel.size) list.filter((d) => d.status === 'ready').forEach((d) => next.add(d.id))
        return next
      })
    } catch {}
  }, [])

  useEffect(() => {
    if (active) load()
  }, [active, load])

  // poll while anything is indexing
  useEffect(() => {
    if (!docs.some((d) => d.status === 'processing')) return
    const t = setInterval(load, 1500)
    return () => clearInterval(t)
  }, [docs, load])

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const uploadFiles = async (files) => {
    for (const f of files) {
      setUploading((n) => n + 1)
      try {
        const doc = await api.upload('/api/documents', f)
        setDocs((d) => [doc, ...d])
        setSelected((s) => new Set([...s, doc.id]))
      } catch (e) {
        toast(`${f.name}: ${e.message}`, 'error')
      } finally {
        setUploading((n) => n - 1)
      }
    }
    load()
  }

  const toggle = (id) =>
    setSelected((s) => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  const remove = async (doc) => {
    if (!confirm(`Delete "${doc.title}"?`)) return
    await api.del(`/api/documents/${doc.id}`).catch((e) => toast(e.message, 'error'))
    load()
  }

  const ask = async () => {
    const q = question.trim()
    if (q.length < 2 || busy || !selected.size) return
    setQuestion('')
    const history = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.content }))
    const idx = messages.length + 1
    setMessages((m) => [...m, { role: 'user', content: q }, { role: 'assistant', content: '', sources: [], pending: true }])
    setBusy(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    // ignore late events from a run that 'New chat' already cleared
    const update = (fn) =>
      abortRef.current === ctrl && setMessages((m) => m.map((msg, i) => (i === idx ? fn(msg) : msg)))
    try {
      await streamSSE(
        '/api/documents/ask',
        { question: q, document_ids: [...selected], history, model },
        (ev, data) => {
          if (ev === 'entry') {
            runEntryRef.current = data.entry_id
            bumpLibrary()
          }
          if (ev === 'stopped') {
            update((m) => ({ ...m, entryId: data.entry_id, stopped: true }))
            bumpLibrary()
          }
          if (ev === 'sources') update((m) => ({ ...m, sources: data }))
          if (ev === 'token') update((m) => ({ ...m, content: m.content + data }))
          if (ev === 'error') update((m) => ({ ...m, error: data.message }))
          if (ev === 'done') {
            update((m) => ({ ...m, entryId: data.entry_id }))
            bumpLibrary()
          }
        },
        ctrl.signal,
      )
    } catch (e) {
      if (e.name !== 'AbortError') update((m) => ({ ...m, error: e.message }))
    } finally {
      update((m) => ({ ...m, pending: false }))
      if (abortRef.current === ctrl) {
        setBusy(false)
        setStopping(false)
      }
    }
  }

  const stop = async () => {
    const ctrl = abortRef.current
    setStopping(true)
    if (runEntryRef.current) await api.post(`/api/runs/${runEntryRef.current}/stop`, {}).catch(() => {})
    setTimeout(() => {
      if (abortRef.current === ctrl && ctrl && !ctrl.signal.aborted) ctrl.abort()
    }, 3000)
  }

  const newChat = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setBusy(false)
    setStopping(false)
    setMessages([])
    setQuestion('')
    setHighlight(null)
  }
  useEffect(() => {
    if (resetSignal) newChat()
  }, [resetSignal]) // eslint-disable-line react-hooks/exhaustive-deps

  const readyCount = docs.filter((d) => d.status === 'ready').length

  return (
    <div className="view view-docs">
      <header className="view-header">
        <div>
          <h1>Chat with Documents</h1>
          <p className="muted">Upload papers or notes. Answers cite the exact document and page.</p>
        </div>
        {messages.length > 0 && (
          <button className="btn btn-ghost" onClick={newChat}>
            <Plus size={16} /> New chat
          </button>
        )}
      </header>

      <div className="docs-layout">
        <aside className="card docs-panel">
          <div
            className={`dropzone ${drag ? 'drag' : ''}`}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDrag(true)
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDrag(false)
              uploadFiles([...e.dataTransfer.files])
            }}
          >
            {uploading ? <Loader2 size={22} className="spin" /> : <UploadCloud size={22} />}
            <strong>{uploading ? 'Uploading…' : 'Drop files or click to upload'}</strong>
            <span className="muted small">PDF, TXT, Markdown · up to 25 MB</span>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.markdown"
              hidden
              onChange={(e) => {
                uploadFiles([...e.target.files])
                e.target.value = ''
              }}
            />
          </div>
          <div className="docs-list-head">
            <span>Library ({docs.length})</span>
            {readyCount > 0 && (
              <button
                className="link-btn"
                onClick={() =>
                  setSelected(selected.size === readyCount ? new Set() : new Set(docs.filter((d) => d.status === 'ready').map((d) => d.id)))
                }
              >
                {selected.size === readyCount ? 'Clear' : 'Select all'}
              </button>
            )}
          </div>
          <div className="docs-list">
            {docs.length === 0 && <p className="muted small pad">No documents yet.</p>}
            {docs.map((d) => (
              <DocRow key={d.id} doc={d} selected={selected.has(d.id)} onToggle={toggle} onDelete={remove} />
            ))}
          </div>
        </aside>

        <section className="card chat">
          <div className="thread">
            {messages.length === 0 ? (
              <Empty icon={MessageSquareText} title="Ask about your documents">
                {readyCount ? `${selected.size} of ${readyCount} documents selected.` : 'Upload a document to get started.'}
                <br />
                Try: “What is the main contribution?” or “Summarize the methodology section.”
              </Empty>
            ) : (
              messages.map((m, i) =>
                m.role === 'user' ? (
                  <div key={i} className="msg msg-user">{m.content}</div>
                ) : (
                  <div key={i} className="msg msg-ai">
                    {m.pending && !m.content && !m.error && (
                      <div className="muted small">
                        <Loader2 size={13} className="spin" /> {m.sources.length ? 'Writing…' : 'Searching documents…'}
                      </div>
                    )}
                    {m.error && <div className="alert alert-error">{m.error}</div>}
                    {m.content && (
                      <Markdown
                        text={m.content}
                        sources={m.sources}
                        streaming={m.pending}
                        onCite={(n) => scrollToSource(`doc${i}`, n, setHighlight)}
                      />
                    )}
                    {m.sources.length > 0 && (
                      <details className="msg-sources" open={!!highlight}>
                        <summary>{m.sources.length} excerpts used</summary>
                        <SourceList sources={m.sources} highlight={highlight} idPrefix={`doc${i}`} />
                      </details>
                    )}
                    {m.entryId && (
                      <div className="msg-actions">
                        {m.stopped && <span className="muted small">⏹ Stopped</span>}
                        <ExportButtons entryIds={[m.entryId]} compact />
                      </div>
                    )}
                  </div>
                ),
              )
            )}
            <div ref={threadEnd} />
          </div>
          <form
            className="ask-box chat-input"
            onSubmit={(e) => {
              e.preventDefault()
              ask()
            }}
          >
            <FileText size={18} className="muted" />
            <textarea
              rows={1}
              value={question}
              disabled={!selected.size}
              placeholder={selected.size ? `Ask about ${selected.size} selected document${selected.size > 1 ? 's' : ''}…` : 'Select at least one ready document'}
              onChange={(e) => setQuestion(e.target.value)}
          onInput={autoGrow}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  ask()
                }
              }}
            />
            {busy ? (
              <button type="button" className="btn btn-icon btn-danger" onClick={stop} disabled={stopping} title="Stop">
                {stopping ? <Loader2 size={16} className="spin" /> : <Square size={16} />}
              </button>
            ) : (
              <button className="btn btn-icon btn-primary" disabled={!selected.size || question.trim().length < 2}>
                <ArrowUp size={18} />
              </button>
            )}
          </form>
        </section>
      </div>
    </div>
  )
}
