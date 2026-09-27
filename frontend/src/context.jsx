import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'

const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

export function AppProvider({ children }) {
  const [health, setHealth] = useState(null)
  const [model, setModel] = useState(() => localStorage.getItem('sl-model') || '')
  const [toasts, setToasts] = useState([])
  const [libraryVersion, setLibraryVersion] = useState(0)

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.get('/api/health'))
    } catch {
      setHealth({ status: 'down', ollama: false, models: [] })
    }
  }, [])

  useEffect(() => {
    refreshHealth()
    const t = setInterval(refreshHealth, 15000)
    return () => clearInterval(t)
  }, [refreshHealth])

  useEffect(() => {
    try {
      localStorage.setItem('sl-model', model)
    } catch {}
  }, [model])

  const toast = useCallback((message, kind = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, message, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])

  const chatModels = (health?.models || []).filter((m) => !/embed|bge|minilm/i.test(m))
  const activeModel = model && chatModels.includes(model) ? model : ''

  return (
    <AppContext.Provider
      value={{
        health,
        refreshHealth,
        model: activeModel || null,
        setModel,
        chatModels,
        toast,
        libraryVersion,
        bumpLibrary: () => setLibraryVersion((v) => v + 1),
      }}
    >
      {children}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            {t.message}
          </div>
        ))}
      </div>
    </AppContext.Provider>
  )
}
