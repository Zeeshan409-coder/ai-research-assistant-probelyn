import { useState } from 'react'
import { BookMarked, Cpu, FileText, Github, Globe, GraduationCap, RefreshCw, Terminal } from 'lucide-react'
import { AppProvider, useApp } from './context'
import WebResearch from './views/WebResearch'
import Papers from './views/Papers'
import Documents from './views/Documents'
import LibraryView from './views/Library'

const NAV = [
  { id: 'web', label: 'Web Research', icon: Globe, View: WebResearch },
  { id: 'papers', label: 'Paper Search', icon: GraduationCap, View: Papers },
  { id: 'docs', label: 'Documents', icon: FileText, View: Documents },
  { id: 'library', label: 'Library', icon: BookMarked, View: LibraryView },
]

function StatusPanel() {
  const { health, refreshHealth, model, setModel, chatModels } = useApp()
  const up = health?.ollama
  return (
    <div className="status-panel">
      <div className="status-line">
        <span className={`status-dot ${health == null ? '' : up ? 'ok' : 'bad'}`} />
        <span>{health == null ? 'Checking…' : up ? 'Ollama connected' : 'Ollama offline'}</span>
        <button className="btn btn-icon btn-ghost btn-xs" onClick={refreshHealth} title="Re-check">
          <RefreshCw size={12} />
        </button>
      </div>
      <label className="model-select">
        <Cpu size={13} />
        <select value={model || ''} onChange={(e) => setModel(e.target.value)} disabled={!chatModels.length}>
          <option value="">Default ({health?.chat_model || '…'})</option>
          {chatModels.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}

function SetupBanner() {
  const { health } = useApp()
  if (!health) return null
  let body = null
  if (health.status === 'down') {
    body = <>Backend not reachable. Start it with <code>uvicorn app.main:app --reload</code> inside <code>backend/</code>.</>
  } else if (!health.ollama) {
    body = <>Ollama isn't running at <code>{health.ollama_url}</code>. Install it from ollama.com, then run <code>ollama serve</code>.</>
  } else {
    const missing = [
      !health.chat_model_installed && health.chat_model,
      !health.embed_model_installed && health.embed_model,
    ].filter(Boolean)
    if (missing.length)
      body = <>Missing model{missing.length > 1 ? 's' : ''}: run {missing.map((m) => <code key={m}>ollama pull {m}</code>)}</>
  }
  if (!body) return null
  return (
    <div className="setup-banner">
      <Terminal size={16} />
      <span>{body}</span>
    </div>
  )
}

function Shell() {
  const [tab, setTab] = useState('web')
  const [resets, setResets] = useState({})
  const openTab = (id) => {
    if (id === tab) setResets((r) => ({ ...r, [id]: (r[id] || 0) + 1 }))
    setTab(id)
  }
  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width="30" height="30" />
          <div>
            <div className="brand-name">Probelyn</div>
            <div className="brand-sub">Local AI research assistant</div>
          </div>
        </div>
        <div className="nav">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} className={tab === id ? 'active' : ''} onClick={() => openTab(id)}>
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </div>
        <div className="sidebar-foot">
          <StatusPanel />
          <a className="gh-link" href="https://github.com/Zeeshan409-coder/ai-research-assistant-probelyn" target="_blank" rel="noreferrer">
            <Github size={13} /> Source on GitHub
          </a>
        </div>
      </nav>
      <main className="main">
        <SetupBanner />
        {/* views stay mounted so results survive tab switches */}
        {NAV.map(({ id, View }) => (
          <div key={id} hidden={tab !== id} className="view-wrap">
            <View active={tab === id} resetSignal={resets[id] || 0} />
          </div>
        ))}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
