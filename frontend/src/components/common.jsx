import { useState } from 'react'
import { Check, Download, ExternalLink, FileText, Globe, Loader2, AlertTriangle } from 'lucide-react'
import { downloadExport } from '../api'
import { useApp } from '../context'

export function Steps({ steps, running }) {
  if (!steps.length) return null
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={i} className={s.done ? 'done' : running ? 'active' : 'stopped'}>
          {s.done ? <Check size={14} /> : running ? <Loader2 size={14} className="spin" /> : <span className="dot" />}
          {s.message}
        </li>
      ))}
    </ol>
  )
}

export function SourceList({ sources, highlight, idPrefix = 'src' }) {
  if (!sources?.length) return null
  return (
    <div className="sources">
      {sources.map((s) => {
        const Tag = s.url ? 'a' : 'div'
        return (
          <Tag
            key={s.n}
            id={`${idPrefix}-${s.n}`}
            className={`source ${highlight === s.n ? 'highlight' : ''}`}
            {...(s.url ? { href: s.url, target: '_blank', rel: 'noreferrer' } : {})}
          >
            <div className="source-head">
              <span className="source-n">{s.n}</span>
              {s.url ? <Globe size={13} /> : <FileText size={13} />}
              <span className="source-domain">{s.domain}</span>
              {s.url && <ExternalLink size={12} className="muted" />}
            </div>
            <div className="source-title">{s.title}</div>
            {s.snippet && <div className="source-snippet">{s.snippet}</div>}
          </Tag>
        )
      })}
    </div>
  )
}

export function ExportButtons({ entryIds, title, compact }) {
  const { toast } = useApp()
  const [busy, setBusy] = useState(null)
  const go = async (fmt) => {
    setBusy(fmt)
    try {
      await downloadExport(entryIds, fmt, title)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(null)
    }
  }
  const disabled = !entryIds?.length || busy
  return (
    <div className="btn-group">
      {['md', 'pdf'].map((fmt) => (
        <button key={fmt} className="btn btn-ghost btn-sm" disabled={disabled} onClick={() => go(fmt)}>
          {busy === fmt ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
          {compact ? fmt.toUpperCase() : fmt === 'md' ? 'Markdown' : 'PDF'}
        </button>
      ))}
    </div>
  )
}

export function ErrorBox({ message }) {
  if (!message) return null
  return (
    <div className="alert alert-error">
      <AlertTriangle size={16} />
      <span>{message}</span>
    </div>
  )
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={26} />
      </div>
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  )
}

export function scrollToSource(prefix, n, setHighlight) {
  setHighlight(n)
  document.getElementById(`${prefix}-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  setTimeout(() => setHighlight((h) => (h === n ? null : h)), 1800)
}

export function elapsed(start, end) {
  if (!start || !end) return null
  return `${((end - start) / 1000).toFixed(1)}s`
}

export function autoGrow(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 180) + 'px'
}
