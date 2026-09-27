// Small API layer: JSON helpers + a Server-Sent-Events reader for POST streams.

const BASE = import.meta.env.VITE_API_URL || ''

async function handle(res) {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {}
    throw new Error(msg)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  get: (path) => fetch(BASE + path).then(handle),
  post: (path, body) =>
    fetch(BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),
  del: (path) => fetch(BASE + path, { method: 'DELETE' }).then(handle),
  upload: (path, file, title) => {
    const fd = new FormData()
    fd.append('file', file)
    if (title) fd.append('title', title)
    return fetch(BASE + path, { method: 'POST', body: fd }).then(handle)
  },
}

/**
 * POST a JSON body and consume the text/event-stream response.
 * `onEvent(eventName, data)` is called for each event.
 */
export async function streamSSE(path, body, onEvent, signal) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) await handle(res)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      try {
        onEvent(event, data ? JSON.parse(data) : null)
      } catch (e) {
        console.error('bad SSE payload', e, data)
      }
    }
  }
}

export async function downloadExport(entryIds, format, title) {
  const res = await fetch(BASE + '/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entry_ids: entryIds, format, title: title || null }),
  })
  if (!res.ok) await handle(res)
  const blob = await res.blob()
  const cd = res.headers.get('content-disposition') || ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1] || `report.${format}`
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
