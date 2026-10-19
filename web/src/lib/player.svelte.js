// Player engine: a single <audio> element + a reactive queue, with MediaSession.
import { api } from './api.js'
import { stamp, fileAway } from './sfx.js'

export const player = $state({
  queue: [],        // track objects
  index: -1,        // current position in queue
  current: null,
  playing: false,
  time: 0,
  duration: 0,
  volume: 1,
  showQueue: false,
  showFull: false,  // full-screen Now Playing (the primary surface on the handheld)
  peeking: false,   // a wheel preview is sounding (drives the visualizer too)
  autoplay: true,
  shuffle: false,
  repeat: false,   // repeat-one: loop the current track
  albumMode: false, // queue was launched as an OST sleeve -> album gain, not track gain
  radioSeed: null,  // the song the current radio started on: autoplay keeps choosing for it
  notice: null,     // { text, bad, n } — transient printed notice (see App.svelte)
})

let audio = null
let naturalEnd = false   // did the current track finish on its own (complete) vs get skipped?

// ---- Listening session id ----------------------------------------------------
// Every logged event carries one, so /api/history can group a night's listening
// instead of inferring it. Rotates after 30 minutes idle — the same gap the engine
// uses to split sessions (personalize.SESSION_GAP_SECONDS), so both halves of the
// system agree on where one sitting ends and the next begins.
const SESSION_KEY = 'omp:session:v1'
const SESSION_IDLE_MS = 30 * 60 * 1000
function sessionId() {
  const now = Date.now()
  let s = null
  try { s = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null') } catch {}
  if (!s?.id || now - (s.ts || 0) > SESSION_IDLE_MS) {
    const id = crypto.randomUUID ? crypto.randomUUID()
      : `s-${now.toString(36)}-${Math.random().toString(36).slice(2, 10)}`
    s = { id, ts: now }
  } else {
    s.ts = now
  }
  try { localStorage.setItem(SESSION_KEY, JSON.stringify(s)) } catch {}
  return s.id
}

// Single funnel for the plays log: id + event + seconds + provenance.
function log(id, event, seconds = null, source = null) {
  if (id) api.play(id, event, seconds, source, sessionId())
}

// ---- Provenance --------------------------------------------------------------
// `source` = the surface a track entered playback from ('wheel' | 'home' | 'explore' |
// 'library' | 'search' | 'ost' | 'radio' | 'queue' | 'autoplay' | 'liked' | 'history').
// Queued tracks are shallow COPIES carrying `src`, so the same track object rendered in
// a view can't have its provenance rewritten by a later queue action somewhere else.
// `walk` marks tracks a station PLANNED in advance (a vibe-walk) — the ones a skip
// streak may redraw (see next()).
const tag = (t, src, walk = false) => (walk ? { ...t, src, walk: true } : { ...t, src })

// ---- Loudness normalization (YouTube-style). Tracks carry `gain`: the R128 track
// gain in dB to reach the -23 LUFS reference (from library.db). We retarget to
// -14 LUFS and only ever attenuate — loud masters come down, quiet tracks play
// untouched — so the multiplier stays ≤ 1 and nothing can clip.
// Inside an OST sleeve we prefer `album_gain_db`: one gain for the whole record keeps
// the quiet cue quiet and the boss theme loud, which is the point of a soundtrack.
const LOUDNESS_OFFSET_DB = 9   // -14 LUFS target sits 9 dB above the -23 reference
function gainMult(track) {
  const album = player.albumMode ? track?.album_gain_db : null
  const g = album != null ? album : track?.gain
  return g == null ? 1 : Math.min(1, Math.pow(10, (g + LOUDNESS_OFFSET_DB) / 20))
}
// The element volume is always userVolume × current track's normalization.
function applyVolume() { if (audio) audio.volume = player.volume * gainMult(player.current) }

// ---- Session persistence: survive a browser refresh (like YT Music) ----
// Stash the queue + current position in localStorage; restore() reloads it on boot but
// leaves the track PAUSED at its saved offset (browsers block autoplay without a gesture).
const PERSIST_KEY = 'omp:player:v1'
let lastPersist = 0
function persist() {
  try {
    localStorage.setItem(PERSIST_KEY, JSON.stringify({
      queue: player.queue, index: player.index, time: player.time,
      albumMode: player.albumMode, radioSeed: player.radioSeed,
    }))
  } catch {}
}

// Reload the last session (paused). Safe to call once on app start; no-op with no saved
// state. Does NOT log a play event or autoplay — the user resumes with a gesture.
export function restore() {
  ensureAudio()
  let s
  try { s = JSON.parse(localStorage.getItem(PERSIST_KEY) || 'null') } catch { return }
  if (!s || !Array.isArray(s.queue) || !s.queue.length) return
  player.queue = s.queue
  player.index = Math.min(Math.max(0, s.index | 0), s.queue.length - 1)
  player.albumMode = !!s.albumMode
  player.radioSeed = s.radioSeed || null
  const track = player.queue[player.index]
  if (!track) return
  player.current = track
  player.time = s.time > 0 ? s.time : 0
  naturalEnd = false
  applyVolume()
  audio.src = `/audio/${track.id}`
  audio.addEventListener('loadedmetadata', () => {
    if (s.time > 0 && s.time < (audio.duration || Infinity)) audio.currentTime = s.time
  }, { once: true })
  setMetadata(track)
}

function ensureAudio() {
  if (audio) return audio
  audio = new Audio()
  applyVolume()
  audio.addEventListener('timeupdate', () => {
    player.time = audio.currentTime
    const now = Date.now()
    if (now - lastPersist > 4000) { lastPersist = now; persist() }   // throttle position saves
  })
  audio.addEventListener('durationchange', () => { player.duration = audio.duration || 0 })
  audio.addEventListener('play', () => { player.playing = true; sessionState('playing') })
  audio.addEventListener('pause', () => { player.playing = false; sessionState('paused'); persist() })
  audio.addEventListener('ended', () => {
    if (player.repeat && audio) {
      log(player.current?.id, 'complete', Math.round(player.duration || 0), srcOf(player.current))
      audio.currentTime = 0; audio.play().catch(() => {}); return
    }
    naturalEnd = true; next()
  })
  setupSessionHandlers()
  return audio
}

export function toggleShuffle() { player.shuffle = !player.shuffle }
export function toggleRepeat() { player.repeat = !player.repeat }

// Log the OUTGOING track's outcome for the personalization layer, exactly once per
// playback. Three outcomes, because only one of them is a judgement of the music:
//   complete — it ran out;
//   skip     — you pressed Next (or disliked / trashed it): a verdict on THIS track;
//   switch   — you started something else (clicked a song, jumped in the queue, went
//              back): navigation. Logged so history stays complete; worth nothing as a
//              taste signal. Before this split, clicking through search results logged
//              every abandoned track as a strong skip.
// `seconds` lets the server grade skips by completion fraction. Returns {event, secs}
// (null if there was nothing to settle) so next() can hand it to /api/next directly.
const srcOf = (t) => t?.src || null
let settled = false
const STRONG_SKIP = 0.15   // = personalize.STRONG_SKIP
function earlySkip(secs) {
  const d = player.duration
  return d > 0 ? secs / d < STRONG_SKIP : secs < 10
}
function settle(how) {
  if (!player.current || settled) return null
  settled = true
  const secs = Math.round((naturalEnd ? (player.duration || player.time) : player.time) || 0)
  const event = naturalEnd ? 'complete' : how === 'next' ? 'skip' : 'switch'
  log(player.current.id, event, secs, srcOf(player.current))
  const q = player.queue[player.index]
  if (q && q.id === player.current.id) {
    q.outcome = event === 'skip' && earlySkip(secs) ? 'rejected' : event
  }
  return { event, secs, early: event === 'skip' && earlySkip(secs) }
}

// ---- Likes -------------------------------------------------------------------
// There is no likes table: a like is a row in the plays log, and a track's state is
// its LATEST like/unlike event (/api/likes). The id map below is the client mirror,
// loaded once at boot so every thumbs-up in the app shows the persistent truth
// instead of a per-session guess.
export const likes = $state({ ids: {}, loaded: false })

export async function loadLikes() {
  try {
    const list = await api.likes()
    const m = {}
    for (const t of list) m[t.id] = t.liked_at || Date.now() / 1000
    likes.ids = m
  } catch {}
  likes.loaded = true
}

export const isLiked = (id) => !!id && likes.ids[id] != null
export const likeCount = () => Object.keys(likes.ids).length

/** Toggle like <-> unlike for any track, anywhere. Returns the new state. */
export function setLiked(track, on) {
  const id = track?.id
  if (!id) return false
  if (on) {
    likes.ids[id] = Date.now() / 1000
    log(id, 'like', Math.round(player.current?.id === id ? player.time || 0 : 0), srcOf(track))
    stamp()
  } else {
    delete likes.ids[id]
    log(id, 'unlike', 0, srcOf(track))
  }
  return on
}
export const toggleLike = (track) => setLiked(track, !isLiked(track?.id))

// Explicit thumbs for the CURRENT track — the strongest signal, from the transport bars.
export function like() { return toggleLike(player.current) }
export function dislike() {
  if (!player.current) return
  log(player.current.id, 'dislike', Math.round(player.time || 0), srcOf(player.current))
  advance('dislike')
}

// ---- Trash -------------------------------------------------------------------
// Quarantine a track out of the library (reversible from the Trash view). The audio
// file has to stop being read before Windows will let the server move it, so a
// currently-playing track advances first and gets a beat to let go of the handle.
export async function trashTrack(track) {
  const id = track?.id
  if (!id) return false
  const wasCurrent = player.current?.id === id
  if (wasCurrent) {
    await advance('trash')
    await new Promise((r) => setTimeout(r, 260))   // let the stream close
  }
  try {
    await api.trashAdd(id, sessionId())
  } catch (e) {
    notice(e?.message || "Couldn't file that away.", true)
    return false
  }
  // it must not be able to come back from the queue
  for (let i = player.queue.length - 1; i >= 0; i--) {
    if (player.queue[i].id === id && i !== player.index) removeAt(i)
  }
  delete likes.ids[id]
  fileAway()
  notice(`Filed away — ${track.title || id}`)
  persist()
  return true
}

// A short printed notice at the foot of the page (see App.svelte). `n` makes every
// call a distinct value so the same text twice still re-animates.
let noticeTimer = null
export function notice(text, bad = false) {
  player.notice = { text, bad, n: (player.notice?.n || 0) + 1 }
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => (player.notice = null), bad ? 6000 : 3200)
}

function load(track, how = 'switch') {
  ensureAudio()
  settle(how)           // record how the previous track ended before switching
  settled = false
  naturalEnd = false
  player.current = track
  player.time = 0
  applyVolume()
  audio.src = `/audio/${track.id}`
  audio.play().catch(() => {})
  setMetadata(track)
  log(track.id, 'play', 0, srcOf(track))
  persist()             // remember the new current track + queue for a browser refresh
}

export function playList(list, i = 0, source = 'library', walk = false) {
  player.queue = list.map((t) => tag(t, source, walk))
  player.index = i
  player.radioSeed = null   // a new list: autoplay past its end follows its last song
  player.albumMode = source === 'ost'   // album gain only inside a sleeve
  if (player.queue[i]) load(player.queue[i])
}

export function playNext(track, source = 'queue') {
  if (player.index < 0) return playList([track], 0, source)
  player.queue.splice(player.index + 1, 0, tag(track, source))
  persist()
}

export function addToQueue(track, source = 'queue') {
  if (player.index < 0) return playList([track], 0, source)
  player.queue.push(tag(track, source))
  persist()
}

export function jumpTo(i, source = null) {
  if (i < 0 || i >= player.queue.length) return
  player.index = i
  if (source) player.queue[i].src = source
  load(player.queue[i])
}

export function removeAt(i) {
  if (i < 0 || i >= player.queue.length || i === player.index) return
  player.queue.splice(i, 1)
  if (i < player.index) player.index--
  persist()
}

// A station's tracks are planned up front, so on their own they never hear a skip. Two
// early skips in a row of PLANNED tracks means the plan is wrong: the rest of it is
// dropped, autoplay (which does hear skips — the outcome rides along to /api/next and
// the server continues from the last track you kept) picks right away, and a fresh plan
// is drawn from wherever that lands. Anything you queued by hand stays.
const REPLAN_AFTER = 2
let walkSkips = 0
function rejectStreak(o, outgoing) {
  if (!o || !outgoing?.walk) return false
  if (!o.early) { walkSkips = 0; return false }
  if (++walkSkips < REPLAN_AFTER) return false
  walkSkips = 0
  return true
}

// `next` is also wired straight to onclick (which passes an event), so the verdict
// variant is a separate entry point: dislike/trash advance with an explicit rejection.
export function next() { return advance(null) }

async function advance(verdict) {
  const outgoing = player.current
  const o = settle('next')
  if (o && verdict) {
    o.event = verdict
    o.early = true                       // a rejection, however late it came
    const q = player.queue[player.index]
    if (q && q.id === outgoing?.id) q.outcome = 'rejected'
  }
  const replan = rejectStreak(o, outgoing)
  if (replan) {
    player.queue = [...player.queue.slice(0, player.index + 1),
                    ...player.queue.slice(player.index + 1).filter((t) => !t.walk)]
  }
  if (player.index < player.queue.length - 1) {
    // Shuffle: jump to a random not-yet-played track ahead in the queue.
    if (player.shuffle && player.queue.length - player.index > 2) {
      const lo = player.index + 1
      player.index = lo + Math.floor(Math.random() * (player.queue.length - lo))
    } else {
      player.index++
    }
    load(player.queue[player.index], 'next'); return
  }
  // end of queue -> autoplay: fetch an on-vibe track and keep going forever
  if ((player.autoplay || replan) && player.current) {
    const ex = player.queue.map((t) => t.id).slice(-50).join(',')
    const oc = o ? `&outcome=${o.event}&secs=${o.secs}` : ''
    const sd = player.radioSeed ? `&seed=${encodeURIComponent(player.radioSeed)}` : ''
    try {
      const r = await fetch(`/api/next?id=${player.current.id}&exclude=${encodeURIComponent(ex)}${oc}${sd}`)
      const t = await r.json()
      if (t && t.id) {
        if (t.radio_seed) player.radioSeed = t.radio_seed   // a run of skips moved the radio
        const q = tag(t, 'autoplay')
        player.queue.push(q); player.index = player.queue.length - 1; load(q, 'next')
        if (replan) appendWalk(q, radioToken = {})
        return
      }
    } catch {}
  }
  player.playing = false
}

export async function startRadio(kind, name = '', source = 'radio') {
  try {
    const r = await fetch(`/api/radio?kind=${kind}&name=${encodeURIComponent(name)}`)
    const list = await r.json()
    // genre / track stations are planned; shuffle and recent are not
    if (Array.isArray(list) && list.length) {
      playList(list, 0, source, kind === 'genre' || kind === 'track')
      if (kind === 'track') player.radioSeed = name
    }
  } catch {}
}

// "Click a song anywhere that isn't a deliberate sequence" (search result, browse row,
// speed-dial card, wheel pick): play it NOW, then quietly append a ~30-track radio for it
// behind it so the queue shows the whole upcoming journey (YT-Music style). The song is
// the radio's seed: autoplay past the 30, and any re-plan after skips, stay on its radio.
// The token guards the append against the user starting something else mid-fetch.
let radioToken = null
export async function playTrackRadio(track, source = 'library') {
  playList([track], 0, source)
  player.radioSeed = track.id
  appendWalk(player.queue[0], radioToken = {})
}

// Append a planned stretch of radio behind `from` — the track that is playing — unless the
// user has moved on (token replaced, or `from` no longer the last queued track). It is
// the radio of the seed when there is one, else of `from`.
async function appendWalk(from, tok) {
  const ex = player.queue.map((t) => t.id).slice(-50).join(',')
  const seed = player.radioSeed || from.id
  try {
    const r = await fetch(`/api/radio?kind=track&name=${encodeURIComponent(seed)}` +
                          `&exclude=${encodeURIComponent(ex)}`)
    const list = await r.json()
    if (radioToken === tok && Array.isArray(list) && list.length &&
        player.queue[player.queue.length - 1]?.id === from.id && player.current?.id === from.id) {
      player.queue.push(...list.map((t) => tag(t, 'radio', true)))
      persist()
    }
  } catch {}
}

export function prev() {
  if (audio && audio.currentTime > 3) { audio.currentTime = 0; return }
  if (player.index > 0) { player.index--; load(player.queue[player.index]) }
}

export function toggle() {
  if (!audio || !player.current) return
  audio.paused ? audio.play() : audio.pause()
}

export function seek(t) { if (audio) audio.currentTime = t }
export function setVolume(v) { player.volume = v; applyVolume() }

// ---- Spectrum analyser for the wheel's visualizer. Created lazily (needs a user
// gesture for the AudioContext); the main <audio> is rerouted through it once. ----
let actx = null, analyser = null
export function getAnalyser() {
  ensureAudio()
  try {
    if (!actx) {
      actx = new (window.AudioContext || window.webkitAudioContext)()
      const src = actx.createMediaElementSource(audio)
      analyser = actx.createAnalyser()
      analyser.fftSize = 128
      analyser.smoothingTimeConstant = 0.78
      src.connect(analyser)
      analyser.connect(actx.destination)
    }
    if (actx.state === 'suspended') actx.resume().catch(() => {})
    return analyser
  } catch { return null }
}

// ---- Peek preview (wheel): audition ~35% into a track, without losing your
// place — the main track keeps playing but ducks under the preview. ----
let peekAudio = null

// Per-element fade: each call owns its interval, so a new peek's fade-in can never
// cancel the previous peek's fade-out (which left ghost tracks playing forever).
function fadeTo(el, target, ms, then) {
  clearInterval(el._fade)
  const start = el.volume, t0 = performance.now()
  el._fade = setInterval(() => {
    const k = Math.min(1, (performance.now() - t0) / ms)
    el.volume = start + (target - start) * k
    if (k === 1) { clearInterval(el._fade); then && then() }
  }, 16)
}

function killPeekAudio(pa, fadeMs = 140) {
  if (!pa) return
  fadeTo(pa, 0, fadeMs, () => {
    pa.pause(); pa.removeAttribute('src'); pa.load()
    if (pa._src) { try { pa._src.disconnect() } catch {} pa._src = null }
  })
}

export function peekStart(track) {
  killPeekAudio(peekAudio)                    // hard-stop any previous preview
  if (audio) audio.volume = 0                 // main track goes silent under the peek
  const pa = (peekAudio = new Audio(`/audio/${track.id}`))
  pa.volume = 0
  player.peeking = true
  // Route the preview through the analyser so the visualizer dances to it too.
  // Only when the graph is already running — if routing isn't safe, the preview
  // plays direct to the speakers and the viz just idles (sound must never break).
  const an = getAnalyser()
  if (an && actx?.state === 'running') {
    try { pa._src = actx.createMediaElementSource(pa); pa._src.connect(an) } catch {}
  }
  pa.addEventListener('loadedmetadata', () => {
    if (peekAudio !== pa) { killPeekAudio(pa, 10); return }   // stale: already moved on
    pa.currentTime = hookPoint(track, pa.duration)
    pa.play().catch(() => {})
    fadeTo(pa, 0.9 * gainMult(track), 220)   // previews are normalized too
  })
  pa.load()
  log(track.id, 'peek', 0, srcOf(track))   // a peek that doesn't convert is soft signal
}

// Where a preview drops in: the analysed hook point when the sweep has reached this
// track, else the old 35%-of-duration guess. Out-of-range hooks fall back too, so a
// stale analysis row can never audition silence past the end.
function hookPoint(track, duration) {
  const d = duration || track?.duration || 90
  const h = track?.hook_sec
  if (h != null && h > 0 && h < d - 2) return h
  return Math.max(0, d * 0.35)
}

export function peekStop() {
  applyVolume()                               // un-duck (back to normalized volume)
  player.peeking = false
  const pa = peekAudio
  peekAudio = null
  killPeekAudio(pa)
}

// ---- MediaSession (OS media keys / lock-screen) ----
function setMetadata(t) {
  if (!('mediaSession' in navigator)) return
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title || '', artist: t.artist || '', album: t.album || '',
    })
  } catch {}
}
function sessionState(s) {
  if ('mediaSession' in navigator) navigator.mediaSession.playbackState = s
}
let handlersSet = false
function setupSessionHandlers() {
  if (handlersSet || !('mediaSession' in navigator)) return
  handlersSet = true
  const ms = navigator.mediaSession
  const set = (a, fn) => { try { ms.setActionHandler(a, fn) } catch {} }
  set('play', () => toggle())
  set('pause', () => toggle())
  set('nexttrack', () => next())
  set('previoustrack', () => prev())
}
