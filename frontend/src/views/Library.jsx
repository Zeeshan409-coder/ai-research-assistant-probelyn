import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, BookMarked, CheckSquare, FileText, Globe, GraduationCap, Loader2, Search, Square, Trash2 } from 'lucide-react'
import { api } from '../api'
import { useApp } from '../context'
import Markdown from '../components/Markdown'
import { Empty, ExportButtons, SourceList, scrollToSource } from '../components/common'

const KINDS = {
  web: { label: 'Web', icon: Globe },
  papers: { label: 'Papers', icon: GraduationCap },
  documents: { label: 'Documents', icon: FileText },
}

function when(iso) {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' · ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function StatusBadge({ status }) {
  if (status === 'running')
    return (
      <span className="badge badge-running">
        <Loader2 size={10} className="spin" /> Writing
      </span>
    )
  if (status === 'stopped') return <span className="badge badge-stopped">Stopped</span>
  if (status === 'error')
    return (
      <span className="badge badge-error">
        <AlertCircle size={10} /> Failed
      </span>
    )
  return null
}

export default function LibraryView({ active }) {
  const { toast, libraryVersion } = useApp()
  const [entries, setEntries] = useState([])
  const [kind, setKind] = useState('all')
  const [filter, setFilter] = useState('')
  const [openId, setOpenId] = useState(null)
  const [picked, setPicked] = useState([])
  const [reportTitle, setReportTitle] = useState('')
  const [highlight, setHighlight] = useState(null)

  const load = useCallback(async () => {
    try {
      setEntries(await api.get('/api/history'))
    } catch (e) {
      toast(e.message, 'error')
    }
  }, [toast])

  useEffect(() => {
    if (active) load()
  }, [active, libraryVersion, load])

  // keep refreshing while answers are still being written in the background
  const anyRunning = entries.some((e) => e.status === 'running')
  useEffect(() => {
    if (!active || !anyRunning) return
    const t = setInterval(load, 1500)
    return () => clearInterval(t)
  }, [active, anyRunning, load])

  const shown = useMemo(
    () =>
      entries.filter(
        (e) =>
          (kind === 'all' || e.kind === kind) &&
          (!filter || (e.question + ' ' + e.answer).toLowerCase().includes(filter.toLowerCase())),
      ),
    [entries, kind, filter],
  )
  const current = entries.find((e) => e.id === openId) || shown[0]

  const togglePick = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  const deleteIds = async (ids, message) => {
    if (!ids.length || !confirm(message)) return
    try {
      const { deleted } = await api.post('/api/history/delete', { entry_ids: ids })
      toast(`Deleted ${deleted} entr${deleted === 1 ? 'y' : 'ies'}`, 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
    setPicked((p) => p.filter((x) => !ids.includes(x)))
    if (ids.includes(openId)) setOpenId(null)
    load()
  }

  const remove = (e) => deleteIds([e.id], `Delete "${e.question.slice(0, 80)}"?`)

  const deletePicked = () =>
    deleteIds(picked, `Delete ${picked.length} selected entr${picked.length === 1 ? 'y' : 'ies'}? This can't be undone.`)

  const clearAll = async () => {
    if (!confirm(`Delete ALL ${entries.length} entries from your Library? This can't be undone.`)) return
    try {
      const { deleted } = await api.del('/api/history?confirm=true')
      toast(`Library cleared (${deleted} entries)`, 'success')
    } catch (err) {
      toast(err.message, 'error')
    }
    setPicked([])
    setOpenId(null)
    load()
  }

  const allShownPicked = shown.length > 0 && shown.every((e) => picked.includes(e.id))
  const toggleAllShown = () =>
    setPicked((p) =>
      allShownPicked ? p.filter((id) => !shown.some((e) => e.id === id)) : [...p, ...shown.map((e) => e.id).filter((id) => !p.includes(id))],
    )

  return (
    <div className="view">
      <header className="view-header">
        <div>
          <h1>Library &amp; Reports</h1>
          <p className="muted">Every answer is saved here. Combine entries into a report, or tick them to delete.</p>
        </div>
        {entries.length > 0 && (
          <button className="btn btn-ghost btn-danger-ghost" onClick={clearAll}>
            <Trash2 size={15} /> Clear all
          </button>
        )}
      </header>

      {entries.length === 0 ? (
        <Empty icon={BookMarked} title="Nothing saved yet">
          Results from Web Research, Paper Search and Document chat appear here automatically.
        </Empty>
      ) : (
        <>
          <div className="report-bar card">
            <div className="report-info">
              <strong>Report builder</strong>
              <span className="muted small">
                {picked.length
                  ? `${picked.length} entr${picked.length > 1 ? 'ies' : 'y'} selected, in the order picked`
                  : 'Tick entries to export them as one report, or to delete them'}
              </span>
            </div>
            <input
              className="report-title"
              placeholder="Report title (optional)"
              value={reportTitle}
              onChange={(e) => setReportTitle(e.target.value)}
            />
            <ExportButtons entryIds={picked} title={reportTitle} />
            {picked.length > 0 && (
              <>
                <button className="btn btn-sm btn-danger-ghost" onClick={deletePicked}>
                  <Trash2 size={14} /> Delete {picked.length}
                </button>
                <button className="link-btn" onClick={() => setPicked([])}>
                  Unselect
                </button>
              </>
            )}
          </div>

          <div className="library-layout">
            <aside className="card library-list">
              <div className="library-tools">
                <div className="search-mini">
                  <Search size={14} />
                  <input placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
                </div>
                <div className="kind-tabs">
                  {['all', ...Object.keys(KINDS)].map((k) => (
                    <button key={k} className={kind === k ? 'active' : ''} onClick={() => setKind(k)}>
                      {k === 'all' ? 'All' : KINDS[k].label}
                    </button>
                  ))}
                  {shown.length > 0 && (
                    <button className="select-all" onClick={toggleAllShown}>
                      {allShownPicked ? 'Unselect all' : 'Select all'}
                    </button>
                  )}
                </div>
              </div>
              <div className="entries">
                {shown.map((e) => {
                  const K = KINDS[e.kind] || KINDS.web
                  const order = picked.indexOf(e.id)
                  return (
                    <div key={e.id} className={`entry ${current?.id === e.id ? 'active' : ''}`} onClick={() => setOpenId(e.id)}>
                      <button
                        className="doc-check"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          togglePick(e.id)
                        }}
                      >
                        {order >= 0 ? <span className="pick-n">{order + 1}</span> : <Square size={16} />}
                      </button>
                      <div className="entry-body">
                        <div className="entry-q">{e.question}</div>
                        <div className="entry-meta">
                          <K.icon size={11} /> {K.label} · {when(e.created_at)}
                          <StatusBadge status={e.status} />
                        </div>
                      </div>
                      <button
                        className="entry-delete"
                        title="Delete"
                        onClick={(ev) => {
                          ev.stopPropagation()
                          remove(e)
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  )
                })}
                {!shown.length && <p className="muted small pad">No matches.</p>}
              </div>
            </aside>

            {current && (
              <section className="card answer-card library-detail">
                <div className="answer-top">
                  <h2>{current.question}</h2>
                  <div className="btn-group">
                    <button className="btn btn-ghost btn-sm" onClick={() => togglePick(current.id)}>
                      {picked.includes(current.id) ? <CheckSquare size={14} /> : <Square size={14} />} Add to report
                    </button>
                    <ExportButtons entryIds={[current.id]} compact />
                    <button className="btn btn-ghost btn-sm btn-icon" onClick={() => remove(current)} title="Delete">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
                <div className="muted small">
                  {KINDS[current.kind]?.label} · {when(current.created_at)} {current.model && `· ${current.model}`}
                </div>
                {current.status === 'running' && !current.answer && (
                  <p className="muted small">
                    <Loader2 size={13} className="spin" /> Still researching… this updates automatically.
                  </p>
                )}
                <Markdown
                  text={current.answer}
                  sources={current.sources}
                  streaming={current.status === 'running'}
                  onCite={(n) => scrollToSource('lib', n, setHighlight)}
                />
                <h3 className="col-title">Sources</h3>
                <SourceList sources={current.sources} highlight={highlight} idPrefix="lib" />
              </section>
            )}
          </div>
        </>
      )}
    </div>
  )
}
