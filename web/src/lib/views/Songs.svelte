<script>
  // The Songs view doubles as the library's search surface: an empty box browses the
  // whole collection (paginated, sortable); typing flips to matches (songs + artists),
  // folding in what used to be a separate Search tab.
  import { api } from '../api.js'
  import { startRadio } from '../player.svelte.js'
  import TrackList from '../TrackList.svelte'
  import Icon from '../Icon.svelte'
  import { onDestroy } from 'svelte'
  let { nav } = $props()

  // browse state — the full library, paged in on scroll
  let tracks = $state([])
  let sort = $state('artist')
  let total = $state(null)
  let offset = 0, loading = $state(false), done = $state(false)
  let sentinel = $state(null)

  // search state — a non-empty query switches the view over to results
  let q = $state('')
  let res = $state([])
  let artists = $state([])
  let searching = $state(false)
  let td
  const query = $derived(q.trim())

  api.stats().then((s) => (total = s.tracks)).catch(() => {})
  api.artists().then((a) => (artists = a)).catch(() => {})

  async function more() {
    if (loading || done) return
    loading = true
    try {
      const batch = await api.tracks(sort, 500, offset)
      tracks = [...tracks, ...batch]
      offset += batch.length
      if (batch.length < 500) done = true
    } finally { loading = false }
  }
  function resort(s) { sort = s; tracks = []; offset = 0; done = false; more() }
  more()

  // infinite scroll: load the next page when the sentinel nears the viewport (browse
  // mode only — while searching the sentinel isn't rendered, so this stays idle)
  $effect(() => {
    if (!sentinel) return
    const io = new IntersectionObserver((es) => es[0].isIntersecting && more(),
                                        { rootMargin: '600px' })
    io.observe(sentinel)
    return () => io.disconnect()
  })

  // debounced song search
  $effect(() => {
    const term = query
    clearTimeout(td)
    if (!term) { res = []; searching = false; return }
    searching = true
    td = setTimeout(async () => {
      try { res = await api.search(term) } catch { res = [] } finally { searching = false }
    }, 180)
  })

  // ---- hum-to-search: record a short clip, POST it, render melodic matches ----
  // state machine: idle -> recording -> matching -> results | error
  let humState = $state('idle')
  let humError = $state('')
  let humSecs = $state(0)
  let humResults = $state([])
  let humQuery = $state(null)
  // long hums are what make sloppy or accompaniment-heavy humming recognizable (measured:
  // 15 s of a real hum ranked the song #100+; the same hum at 30-40 s ranked it #1)
  const MAX_HUM_MS = 60000
  const humScores = $derived.by(() =>
    Object.fromEntries(humResults.map((t) => [t.id, t.score])))

  let mediaRec = null, chunks = [], micStream = null, secTimer = null, autoStop = null

  function clearTimers() {
    clearInterval(secTimer); clearTimeout(autoStop); secTimer = autoStop = null
  }
  function releaseMic() {
    try { micStream?.getTracks().forEach((t) => t.stop()) } catch {}
    micStream = null
  }

  async function toggleHum() {
    if (humState === 'recording') { stopHum(); return }
    if (humState === 'matching') return
    humError = ''; humResults = []; humQuery = null; q = ''   // hum takes over from text search
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      humState = 'error'
      humError = 'Microphone blocked — allow mic access to hum a search.'
      return
    }
    micStream = stream
    chunks = []
    const mime = window.MediaRecorder?.isTypeSupported?.('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus' : ''
    try {
      mediaRec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
    } catch {
      mediaRec = new MediaRecorder(stream)
    }
    mediaRec.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data) }
    mediaRec.onstop = onHumStop
    mediaRec.start()
    humState = 'recording'
    humSecs = 0
    const t0 = Date.now()
    secTimer = setInterval(() => { humSecs = Math.floor((Date.now() - t0) / 1000) }, 250)
    autoStop = setTimeout(stopHum, MAX_HUM_MS)   // auto-stop at 60s
  }

  function stopHum() {
    clearTimers()
    try { if (mediaRec && mediaRec.state !== 'inactive') mediaRec.stop() } catch {}
  }

  async function onHumStop() {
    clearTimers()
    releaseMic()
    const type = mediaRec?.mimeType || 'audio/webm'
    const blob = new Blob(chunks, { type }); chunks = []
    if (!blob.size) { humState = 'error'; humError = 'Nothing recorded — try again.'; return }
    humState = 'matching'
    try {
      const data = await api.hum(blob)
      humResults = (data.results || []).map((r) => ({ ...r }))
      humQuery = data.query || null
      humState = 'results'
      if (!humResults.length && !humError) {
        humError = 'No close match — try humming the main melody a bit longer.'
      }
    } catch (e) {
      humState = 'error'
      if (e?.status === 400) {
        humError = (e.humMessage || "Couldn't hear a melody") +
          ' — hum louder and closer to the mic.'
      } else {
        humError = e?.humMessage || 'Match failed — is the server running?'
      }
    }
  }

  onDestroy(() => { clearTimers(); stopHum(); releaseMic() })

  // artist matches, resolved client-side from the cached artist list (starts-with first)
  const artistHits = $derived.by(() => {
    const term = query.toLowerCase()
    if (!term) return []
    const starts = [], contains = []
    for (const a of artists) {
      const n = a.artist.toLowerCase()
      if (n.startsWith(term)) starts.push(a)
      else if (n.includes(term)) contains.push(a)
      if (starts.length >= 6) break
    }
    return [...starts, ...contains].slice(0, 6)
  })
</script>

<div class="view-head">
  <h2 class="title">Songs</h2>
  {#if total}<span class="head-count">{total.toLocaleString()} tracks</span>{/if}
</div>

<div class="sv-input">
  <input class="search" placeholder="Search songs, artists, albums…" bind:value={q} />
  <button class="mic-btn" class:rec={humState === 'recording'} onclick={toggleHum}
          disabled={humState === 'matching'}
          title={humState === 'recording' ? 'Stop and match' : 'Hum to search'}
          aria-label={humState === 'recording' ? 'Stop and match' : 'Hum to search'}>
    <Icon name="mic" size={18} />
  </button>
  {#if humState === 'recording'}
    <span class="rec-ind"><span class="rec-dot"></span>{humSecs}s{#if humSecs < 20} · keep going, 20 s+ works best{/if}</span>
  {/if}
</div>

{#if query}
  {#if artistHits.length}
    <div class="sec-label">Artists</div>
    <div class="artist-row">
      {#each artistHits as a (a.artist)}
        <button class="artist-pill" onclick={() => nav('artists', a.artist)}>
          <span class="ava-art sm">
            <Icon name="mic" size={14} />
            {#if a.vid}
              <img src={`/art/${a.vid}`} alt="" loading="lazy"
                   onerror={(e) => (e.currentTarget.style.display = 'none')} />
            {/if}
          </span>
          {a.artist}
        </button>
      {/each}
    </div>
  {/if}
  {#if res.length}
    <div class="sec-label">Songs</div>
  {:else if !artistHits.length && !searching}
    <div class="muted">No matches for “{query}”.</div>
  {/if}
  <!-- search results are a lookup: play the picked track, then let autoplay continue -->
  <TrackList tracks={res} single source="search" />
{:else if humState !== 'idle'}
  <!-- hum-to-search results: same lookup semantics as text search -->
  {#if humResults.length}
    {#if humQuery}
      <div class="hum-heard">heard {humQuery.n_notes} notes over {Math.round(humQuery.duration_s || 0)}s</div>
    {/if}
    <div class="sec-label">Melodic matches</div>
    <TrackList tracks={humResults} single scores={humScores} source="search" />
  {:else if humState === 'recording'}
    <div class="muted">Listening… hum the melody, then tap the mic to match.</div>
  {:else if humState === 'matching'}
    <div class="muted">Matching…</div>
  {:else}
    <div class="muted">{humError || 'No matches found.'}</div>
  {/if}
{:else}
  <div class="bar-actions">
    <button class="btn" onclick={() => startRadio('shuffle', '', 'library')}>
      <Icon name="shuffle" size={15} /> Shuffle all</button>
    <select value={sort} onchange={(e) => resort(e.target.value)} title="Sort">
      <option value="artist">By artist</option>
      <option value="title">By title</option>
      <option value="album">By album</option>
      <option value="duration">By duration</option>
    </select>
  </div>

  <!-- browsing the whole library is a lookup too: play the pick, station follows -->
  <TrackList {tracks} single source="library" />

  {#if !done}
    <div bind:this={sentinel} class="muted" style="padding:16px 0 6px">
      {loading ? 'Loading…' : ''}
    </div>
  {/if}
{/if}
