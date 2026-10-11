<script>
  // The click-wheel: the app's main surface. A spinnable wheel of album-art slices
  // over what you played on YouTube Music, newest first (Home's "Listen again" list).
  // It doesn't loop: it starts at your latest song and keeps going back through your
  // history, a page at a time, as you spin; spin back to revisit what you passed.
  //   spin the ring       -> browse with detent ticks
  //   settle on a track   -> it auto-PEEKS (~35% in, main audio ducks)
  //   tap the hub / slice -> play it (tap focused slice or hub = select)
  //   visualizer ring     -> live spectrum of whatever is playing
  import { player, playTrackRadio, toggle, peekStart, peekStop, getAnalyser } from '../player.svelte.js'
  import { tick, blip, swell } from '../sfx.js'
  import Icon from '../Icon.svelte'

  let pool = $state([])
  let more = $state(true)          // the server has older listens past the end of `pool`
  let loading = false
  const PAGE = 40
  // no-store so a refresh always re-reads it after a new Takeout is merged
  function loadMore() {
    if (!more || loading) return
    loading = true
    fetch(`/api/speeddial?n=${PAGE}&offset=${pool.length}`, { cache: 'no-store' })
      .then((r) => r.json())
      .then((l) => {
        if (!Array.isArray(l)) { more = false; return }
        const have = new Set(pool.map((t) => t.id))
        const add = l.filter((t) => !have.has(t.id))
        if (add.length) pool = [...pool, ...add]
        if (l.length < PAGE || !add.length) more = false
      })
      .catch(() => { more = false })
      .finally(() => { loading = false })
  }
  loadMore()

  const SLICE = 30                 // degrees per detent
  const R2 = 300, R1 = 128         // outer / hub radius (svg units)
  const HALF = 13.6                // wedge half-angle

  let s = $state(0)                // continuous wheel position, in index units
  let settled = $state(true)
  let interacted = $state(false)
  const len = $derived(pool.length)
  // the ends are hard stops (a little give past them, then it settles back)
  const GIVE = 0.4
  const clampIdx = (i) => Math.max(0, Math.min(len - 1, i))
  const clampS = (x) => Math.max(-GIVE, Math.min(len - 1 + GIVE, x))
  const focused = $derived(len ? clampIdx(Math.round(s)) : 0)
  const focusedTrack = $derived(len ? pool[focused] : null)
  const isCurrent = $derived(focusedTrack && player.current?.id === focusedTrack.id)

  // past either end the slot is drawn empty (t: null) rather than wrapping around
  const visible = $derived.by(() => {
    if (!len) return []
    const base = Math.round(s)
    const out = []
    for (let d = -5; d <= 5; d++) {
      const idx = base + d
      out.push({ d, idx, t: idx >= 0 && idx < len ? pool[idx] : null, ang: (base + d - s) * SLICE })
    }
    return out
  })
  // fetch the next page while there are still a dozen slices to go
  $effect(() => { if (len && focused >= len - 12) loadMore() })

  // ---- name reel: a fixed, horizontal column the pointer reads into. Scrolls
  // vertically with the wheel (tied to the continuous position `s`) so the
  // titles stay upright and legible instead of riding the spinning wedges. ----
  const REEL_ROW = 40
  const reel = $derived.by(() => {
    if (!len) return []
    const base = Math.round(s)
    const frac = s - base                        // sub-detent offset, for smooth scroll
    const span = 3
    const out = []
    for (let d = -span; d <= span; d++) {
      const idx = base + d
      if (idx < 0 || idx >= len) continue
      const dist = Math.abs(d - frac)
      out.push({ d, t: pool[idx], y: (d - frac) * REEL_ROW,
                 op: Math.max(0, 1 - dist / (span + 0.6)) })
    }
    return out
  })

  // ---- wedge geometry ----
  const RAD = Math.PI / 180
  const px = (r, a) => (r * Math.cos(a * RAD)).toFixed(1)
  const py = (r, a) => (r * Math.sin(a * RAD)).toFixed(1)
  const WEDGE = `M ${px(R1, -HALF)} ${py(R1, -HALF)} L ${px(R2, -HALF)} ${py(R2, -HALF)}
    A ${R2} ${R2} 0 0 1 ${px(R2, HALF)} ${py(R2, HALF)}
    L ${px(R1, HALF)} ${py(R1, HALF)} A ${R1} ${R1} 0 0 0 ${px(R1, -HALF)} ${py(R1, -HALF)} Z`
  const MID = (R1 + R2) / 2
  const ART = R2 - R1 + 24

  // ---- pointer handling: ALL through the svg (pointer capture retargets events,
  // so per-slice handlers never fire reliably — taps are resolved geometrically) ----
  let svgEl = $state(null)
  let dragging = $state(false)
  let downInfo = null, moved = 0, lastAng = 0, lastT = 0, vel = 0, raf = 0, lastDetent = 0

  function polar(e) {
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svgEl.getScreenCTM().inverse())
    return { r: Math.hypot(pt.x, pt.y), a: (Math.atan2(pt.y, pt.x) * 180) / Math.PI }
  }
  function checkDetent() {
    const d = Math.round(s)
    if (d !== lastDetent) {
      lastDetent = d
      tick()
      try { navigator.vibrate && navigator.vibrate(6) } catch {}
    }
  }
  function down(e) {
    if (!len) return
    interacted = true
    cancelAnimationFrame(raf)
    stopAutoPeek()
    const p = polar(e)
    downInfo = p; moved = 0; vel = 0; lastAng = p.a; lastT = performance.now()
    if (p.r > R1 - 10) { dragging = true; settled = false }   // hub press isn't a drag
    svgEl.setPointerCapture?.(e.pointerId)
  }
  function move(e) {
    if (!dragging) return
    const p = polar(e)
    if (p.r < 30) return                                       // too near center: angles blow up
    let dA = p.a - lastAng
    if (dA > 180) dA -= 360
    if (dA < -180) dA += 360
    dA = Math.max(-25, Math.min(25, dA))                       // clamp glitchy jumps
    const now = performance.now(), dt = Math.max(8, now - lastT) / 1000
    let ds = dA / SLICE
    if (s + ds < 0 || s + ds > len - 1) ds *= 0.35                // resist past an end
    s = clampS(s + ds); moved += Math.abs(ds)
    vel = 0.65 * vel + 0.35 * (ds / dt)
    lastAng = p.a; lastT = now
    checkDetent()
  }
  function up() {
    if (!downInfo) return
    const info = downInfo
    downInfo = null
    const wasDrag = dragging
    dragging = false
    if (moved < 0.08) {                                        // a tap, not a spin
      if (info.r < R1 - 12) select()
      else if (info.r <= R2 + 14) {
        const d = Math.round(info.a / SLICE + (s - Math.round(s)))
        if (d === 0) select()
        else spinTo(d)
      }
      if (Math.abs(s - Math.round(s)) < 0.01) { s = Math.round(s); settled = true }
      else glide()
      return
    }
    if (wasDrag) glide()
  }
  function glide() {
    cancelAnimationFrame(raf)
    settled = false
    let prev = performance.now()
    const step = (now) => {
      const dt = Math.min(0.05, (now - prev) / 1000); prev = now
      if (Math.abs(vel) > 0.8 && s >= 0 && s <= len - 1) {
        vel *= Math.pow(0.10, dt)
        s = clampS(s + vel * dt)
      } else {
        vel = 0
        const target = clampIdx(Math.round(s))
        s += (target - s) * Math.min(1, dt * 14)
        if (Math.abs(target - s) < 0.003) { s = target; checkDetent(); settled = true; return }
      }
      checkDetent()
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  }
  // Ease toward an absolute detent target. `spinTarget` can be updated mid-flight
  // (e.g. more scroll notches) and the loop retargets smoothly.
  let spinTarget = null
  function runToTarget() {
    cancelAnimationFrame(raf)
    settled = false; vel = 0
    let prev = performance.now()
    const step = (now) => {
      const dt = Math.min(0.05, (now - prev) / 1000); prev = now
      s += (spinTarget - s) * Math.min(1, dt * 12)
      checkDetent()
      if (Math.abs(spinTarget - s) < 0.003) { s = spinTarget; checkDetent(); settled = true; spinTarget = null; return }
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
  }
  function spinTo(d) {
    spinTarget = clampIdx(Math.round(s) + d)
    runToTarget()
  }

  // Mouse-wheel / trackpad: one detent per notch. deltaY is normalised across
  // deltaMode (pixels / lines / pages) and accumulated so trackpads step cleanly.
  let wheelAcc = 0
  function onWheel(e) {
    if (!len) return
    e.preventDefault()
    interacted = true
    stopAutoPeek()
    const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY
    wheelAcc += px
    const STEP = 90
    let n = 0
    while (Math.abs(wheelAcc) >= STEP && n < 4) {   // cap giant deltas
      const dir = wheelAcc > 0 ? 1 : -1
      wheelAcc -= dir * STEP
      spinTarget = clampIdx((spinTarget != null ? spinTarget : Math.round(s)) + dir)
      n++
    }
    if (n) runToTarget()
  }

  // ---- select & auto-peek ----
  let peeking = $state(false)
  let peekTimer = 0
  function stopAutoPeek() {
    clearTimeout(peekTimer)
    if (peeking) { peeking = false; peekStop() }
  }
  function select() {
    if (!focusedTrack) return
    stopAutoPeek()
    blip()
    if (isCurrent) { toggle(); return }
    // a wheel pick is a single-song choice: play it + queue a vibe-walk station behind
    // it, rather than playing out the rest of the wheel pool in dial order
    playTrackRadio(pool[focused], 'wheel')
  }
  // Auto-peek fires ONLY when the wheel moves to a new slice — not when the
  // background track advances (next/prev would otherwise trigger a phantom preview
  // that ducks the track you just skipped to).
  let lastFocus = -1
  $effect(() => {
    const f = focused
    if (!settled || !interacted) return          // mid-spin: wait for it to settle
    if (f === lastFocus) return                  // focus didn't change -> not our event
    lastFocus = f
    clearTimeout(peekTimer)
    if (peeking) { peeking = false; peekStop() }
    const t = pool[f]
    if (!t || player.current?.id === t.id) return  // already the playing track: no peek
    peekTimer = setTimeout(() => { peeking = true; swell(); peekStart(t) }, 350)
  })
  $effect(() => () => { cancelAnimationFrame(raf); stopAutoPeek() })

  // ---- visualizer: 24-bar spectrum ring inside the hub ----
  // 48 bars mirrored left/right (24 real samples reflected), radiating from the
  // record out toward the bezel, with slow-falling PEAK-HOLD dots (hi-fi VU style).
  // When nothing plays, a soft sine ripple travels the ring so it never looks dead.
  const NBARS = 48
  const HALFB = NBARS / 2
  const BARPOS = Array.from({ length: NBARS }, (_, i) => {
    const a = (i * 360) / NBARS - 90            // start at 12 o'clock
    return { c: Math.cos(a * RAD), s: Math.sin(a * RAD) }
  })
  // RGB spectrum ring: hue follows the bar's angle around the hub. Only the hue
  // is set here (as a CSS var); each theme picks its own lightness in app.css so
  // the bars stay legible on both the black day-hub and the white night-hub.
  const BARHUE = Array.from({ length: NBARS }, (_, i) => Math.round((i * 360) / NBARS))
  let bars = $state(new Array(NBARS).fill(0))
  let peaks = $state(new Array(NBARS).fill(0))
  $effect(() => {
    let run = true, buf = null, raf2 = 0, frame = 0, phase = 0
    const loop = () => {
      if (!run) return
      if (++frame % 2 === 0) {                     // ~30fps is plenty
        let out
        if (player.playing || player.peeking) {    // previews drive the ring too
          const an = getAnalyser()
          if (an) {
            buf ||= new Uint8Array(an.frequencyBinCount)
            an.getByteFrequencyData(buf)
            out = new Array(NBARS)
            for (let i = 0; i < NBARS; i++) {
              const k = i < HALFB ? i : NBARS - 1 - i          // mirror symmetry
              out[i] = buf[2 + Math.floor((k * (buf.length - 8)) / HALFB)] / 255
            }
          }
        } else {
          phase += 0.055                                        // idle: travelling ripple
          out = BARPOS.map((_, i) => 0.045 + 0.04 * (1 + Math.sin(phase + i * 0.52)) / 2)
        }
        if (out) {
          bars = out
          peaks = peaks.map((p, i) => Math.max(p - 0.016, out[i]))  // slow fall, instant rise
        }
      }
      raf2 = requestAnimationFrame(loop)
    }
    raf2 = requestAnimationFrame(loop)
    return () => { run = false; cancelAnimationFrame(raf2) }
  })

  const REC = 58              // record label (album art) radius
  const VIZ0 = 68             // visualizer base radius

  function fmt(x) {
    if (!x && x !== 0) return '--:--'
    const m = Math.floor(x / 60), ss = Math.floor(x % 60)
    return `${m}:${ss < 10 ? '0' : ''}${ss}`
  }
</script>

<svelte:window onpointermove={move} onpointerup={up} onpointercancel={up} />

<div class="wheelview">
  <div class="wheelstage">
  <div class="wheelbox">
    {#if len}
      <svg bind:this={svgEl} viewBox="-330 -330 660 660" class="wheel" class:dragging
           onpointerdown={down} onwheel={onWheel} role="slider" aria-label="Track wheel"
           aria-valuenow={focused} aria-valuemin="0" aria-valuemax={len - 1} tabindex="0">
        <defs>
          <clipPath id="wedge-clip"><path d={WEDGE} /></clipPath>
          <clipPath id="rec-clip"><circle r={REC} /></clipPath>
        </defs>
        {#each visible as v (v.idx)}
          {#if !v.t}
            <g transform="rotate({v.ang})" class="slice empty"><path class="wedge-bg" d={WEDGE} /></g>
          {:else}
          {@const isF = v.d === 0 && settled}
          <g transform="rotate({v.ang})" class="slice" class:focused={isF}>
            <path class="wedge-bg" d={WEDGE} />
            <g clip-path="url(#wedge-clip)">
              <image href={`/art/${v.t.id}`} x={MID - ART / 2} y={-ART / 2}
                     width={ART} height={ART} preserveAspectRatio="xMidYMid slice" />
              <path class="wedge-shade" d={WEDGE}
                    style="opacity:{isF ? 0 : Math.min(0.75, 0.28 + Math.abs(v.ang) / 160)}" />
            </g>
            <path class="wedge-rim" d={WEDGE} />
          </g>
          {/if}
        {/each}
        <path class="cursor" d="M {R2 + 8} -14 L {R2 + 30} 0 L {R2 + 8} 14 Z" />
        <g class="hub" class:playing={isCurrent && player.playing} class:peekstate={peeking}>
          <circle r={R1 - 12} class="hub-bg" class:peeking />
          <!-- ink sunburst: mirrored spectrum + peak-hold dots -->
          <g class="viz">
            {#each bars as b, i (i)}
              <line style="--h:{BARHUE[i]}"
                    x1={VIZ0 * BARPOS[i].c} y1={VIZ0 * BARPOS[i].s}
                    x2={(VIZ0 + 2.5 + b * 27) * BARPOS[i].c}
                    y2={(VIZ0 + 2.5 + b * 27) * BARPOS[i].s} />
            {/each}
            {#each peaks as p, i (i)}
              <circle class="pk" r="1.6" style="--h:{BARHUE[i]}"
                      cx={(VIZ0 + 4 + p * 27) * BARPOS[i].c}
                      cy={(VIZ0 + 4 + p * 27) * BARPOS[i].s} />
            {/each}
          </g>
          <!-- the record label: focused track's art, spinning while it plays -->
          <g class="rec-spin">
            {#if focusedTrack}
              {#key focusedTrack.id}
                <g clip-path="url(#rec-clip)" class="rec-art">
                  <image href={`/art/${focusedTrack.id}`} x={-REC} y={-REC}
                         width={REC * 2} height={REC * 2} preserveAspectRatio="xMidYMid slice" />
                </g>
              {/key}
            {/if}
            <circle r="7.5" class="spindle" />
            <circle r="2.4" class="spindle-hole" />
          </g>
          <circle r={REC} class="rec-rim" />
          {#if !(isCurrent && player.playing)}
            <g class="rec-overlay">
              <circle r={REC} class="rec-scrim" />
              <g class="hub-ico"><Icon name="play" size={34} fill /></g>
            </g>
          {/if}
        </g>
      </svg>
    {:else}
      <div class="muted" style="padding:40px">Loading the wheel…</div>
    {/if}
  </div>

    {#if len}
      <!-- names live here: a still, upright column the pointer aims at -->
      <div class="namereel" aria-hidden="true" onwheel={onWheel}>
        <span class="nr-caret"></span>
        {#each reel as r (r.d)}
          <button class="nr-item" class:on={r.d === 0}
                  style="transform:translateY({r.y}px);opacity:{r.op}"
                  tabindex="-1" onclick={() => spinTo(r.d)}>
            <span class="nr-t">{r.t.title}</span>
            <span class="nr-a">{r.t.artist}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  {#if focusedTrack}
    <div class="wheelinfo">
      <div class="wi-pos">{String(focused + 1).padStart(2, '0')} / {len}{more ? '+' : ''}
        <span class="wi-src">recently played</span></div>
      <div class="wi-title">{focusedTrack.title}</div>
      <div class="wi-artist">{focusedTrack.artist}</div>
      <div class="wi-meta">
        {#if focusedTrack.genre}<span class="wi-genre">{focusedTrack.genre}</span>{/if}
        <span class="wi-dur">{fmt(focusedTrack.duration)}</span>
        {#if isCurrent}<span class="wi-live">● playing</span>
        {:else if peeking}<span class="wi-live peek">● peeking</span>{/if}
      </div>
      <div class="wi-actions">
        <button class="btn" onclick={select}>
          <Icon name={isCurrent && player.playing ? 'pause' : 'play'} size={14} fill />
          {isCurrent ? (player.playing ? 'Pause' : 'Resume') : 'Play'}</button>
      </div>
    </div>
  {/if}
</div>
