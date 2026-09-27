import { useCallback, useRef, useState } from 'react'
import { api, streamSSE } from '../api'
import { useApp } from '../context'

const initial = {
  running: false,
  steps: [],
  queries: [],
  sources: [],
  papers: [],
  warnings: [],
  answer: '',
  error: null,
  entryId: null,
  stopped: false,
  stopping: false,
  startedAt: null,
  finishedAt: null,
}

/** Runs a streaming research pipeline and accumulates its events into state. */
export function useResearchStream() {
  const [state, setState] = useState(initial)
  const abortRef = useRef(null)
  const runEntryRef = useRef(null) // id of the Library entry for the run in progress
  const { bumpLibrary } = useApp()
  const bumpRef = useRef(bumpLibrary)
  bumpRef.current = bumpLibrary

  const run = useCallback(async (path, body) => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    runEntryRef.current = null
    setState({ ...initial, running: true, startedAt: Date.now() })

    const onEvent = (event, data) => {
      if (abortRef.current !== ctrl) return // a newer run (or reset) replaced this one
      // the server saves every run to the Library, even if we navigate away
      if (event === 'entry') runEntryRef.current = data.entry_id
      if (['entry', 'done', 'error', 'stopped'].includes(event)) bumpRef.current?.()
      setState((s) => {
        switch (event) {
          case 'status':
            return {
              ...s,
              steps: [...s.steps.map((st) => ({ ...st, done: true })), { ...data, done: false }],
            }
          case 'queries':
            return { ...s, queries: data }
          case 'sources':
            return { ...s, sources: data }
          case 'papers':
            return { ...s, papers: data }
          case 'warning':
            return { ...s, warnings: [...s.warnings, data.message] }
          case 'token':
            return { ...s, answer: s.answer + data }
          case 'done':
            return {
              ...s,
              entryId: data?.entry_id ?? null,
              running: false,
              finishedAt: Date.now(),
              steps: s.steps.map((st) => ({ ...st, done: true })),
            }
          case 'stopped':
            return {
              ...s,
              entryId: data?.entry_id ?? null,
              running: false,
              stopping: false,
              stopped: true,
              finishedAt: Date.now(),
              steps: s.steps.map((st) => ({ ...st, done: true })),
            }
          case 'error':
            return { ...s, error: data.message, running: false }
          default:
            return s
        }
      })
    }

    try {
      await streamSSE(path, body, onEvent, ctrl.signal)
    } catch (e) {
      if (e.name !== 'AbortError' && abortRef.current === ctrl) setState((s) => ({ ...s, error: e.message }))
    } finally {
      if (abortRef.current === ctrl) setState((s) => ({ ...s, running: false }))
    }
  }, [])

  /** Stop the model on the server. The partial answer stays on screen and in the Library. */
  const stop = useCallback(async () => {
    const ctrl = abortRef.current
    const entryId = runEntryRef.current
    setState((s) => ({ ...s, stopping: true }))
    if (entryId) {
      try {
        await api.post(`/api/runs/${entryId}/stop`, {})
      } catch {}
    }
    // the server answers with a 'stopped' event; if it doesn't arrive quickly, just disconnect
    setTimeout(() => {
      if (abortRef.current === ctrl && ctrl && !ctrl.signal.aborted) {
        ctrl.abort()
        setState((s) => ({ ...s, running: false, stopping: false, stopped: true }))
      }
    }, 3000)
  }, [])
  const reset = useCallback(() => {
    // Only stops *watching* the stream – the server finishes the answer and saves it to the Library.
    abortRef.current?.abort()
    abortRef.current = null
    setState(initial)
  }, [])

  return { ...state, run, stop, reset }
}
