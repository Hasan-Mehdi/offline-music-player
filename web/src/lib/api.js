// Thin client over the Flask player API (scripts/server.py).
async function j(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url} -> ${r.status}`)
  return r.json()
}

// POST JSON and surface the server's own message on failure (the trash endpoints
// answer 409 with a human-readable reason when Windows has the file locked).
async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok || (data && data.ok === false)) {
    const err = new Error((data && data.error) || `${url} -> ${r.status}`)
    err.status = r.status
    throw err
  }
  return data
}

export const api = {
  stats: () => j('/api/stats'),
  tracks: (sort = 'artist', limit = 500, offset = 0) =>
    j(`/api/tracks?sort=${sort}&limit=${limit}&offset=${offset}`),
  artists: () => j('/api/artists'),
  artist: (name) => j(`/api/artist?name=${encodeURIComponent(name)}`),
  genres: () => j('/api/genres'),
  genre: (name) => j(`/api/genre?name=${encodeURIComponent(name)}`),
  osts: () => j('/api/osts'),
  ost: (name) => j(`/api/ost?name=${encodeURIComponent(name)}`),
  search: (q) => j(`/api/search?q=${encodeURIComponent(q)}`),
  // Hum-to-search: POST the recorded blob, get back ranked matches + a query summary.
  // On a non-2xx, throw an Error carrying the server's human-readable message (.humMessage)
  // and status so the caller can phrase the right inline hint.
  hum: async (blob, top = 10) => {
    const r = await fetch(`/api/hum?top=${top}`, { method: 'POST', body: blob })
    let data = null
    try { data = await r.json() } catch {}
    if (!r.ok) {
      const err = new Error((data && data.error) || `hum -> ${r.status}`)
      err.status = r.status
      err.humMessage = data && data.error
      throw err
    }
    return data
  },
  // Every logged event carries WHERE it came from (source) and WHICH listening
  // session it belongs to — see player.svelte.js:sessionId().
  play: (id, event = 'play', seconds = null, source = null, session_id = null) => {
    fetch('/api/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, event, seconds, source, session_id }),
      keepalive: true, // let the outcome flush even as the page/track tears down
    }).catch(() => {})
  },

  likes: () => j('/api/likes'),
  history: (limit = 30) => j(`/api/history?limit=${limit}`),
  trash: () => j('/api/trash'),
  trashAdd: (id, session_id = null) => post('/api/trash', { id, session_id }),
  trashRestore: (id) => post('/api/trash/restore', { id }),
  trashClear: () => post('/api/trash/clear'),
}
