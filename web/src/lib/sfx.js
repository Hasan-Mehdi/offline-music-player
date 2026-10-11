// Tiny synthesized UI sounds (WebAudio, no assets): the wheel's detent tick and a
// confirm blip. Volumes are deliberately low — texture, not noise.
let ctx = null
function ac() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)()
  if (ctx.state === 'suspended') ctx.resume().catch(() => {})
  return ctx
}

// iPod-style detent: a 6ms filtered click.
export function tick() {
  try {
    const c = ac(), t = c.currentTime
    const o = c.createOscillator(), g = c.createGain()
    o.type = 'square'
    o.frequency.setValueAtTime(2600, t)
    o.frequency.exponentialRampToValueAtTime(900, t + 0.008)
    g.gain.setValueAtTime(0.06, t)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.012)
    o.connect(g).connect(c.destination)
    o.start(t); o.stop(t + 0.015)
  } catch {}
}

// Selection confirm: quick rising two-tone blip.
export function blip() {
  try {
    const c = ac(), t = c.currentTime
    const o = c.createOscillator(), g = c.createGain()
    o.type = 'triangle'
    o.frequency.setValueAtTime(660, t)
    o.frequency.setValueAtTime(990, t + 0.05)
    g.gain.setValueAtTime(0.08, t)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12)
    o.connect(g).connect(c.destination)
    o.start(t); o.stop(t + 0.13)
  } catch {}
}

// Rubber-stamp thunk (a like): a hard low knock, gone in 60ms. Wood-block, not a chime.
export function stamp() {
  try {
    const c = ac(), t = c.currentTime
    const o = c.createOscillator(), g = c.createGain(), f = c.createBiquadFilter()
    o.type = 'triangle'
    o.frequency.setValueAtTime(320, t)
    o.frequency.exponentialRampToValueAtTime(70, t + 0.05)
    f.type = 'lowpass'
    f.frequency.setValueAtTime(1400, t)
    g.gain.setValueAtTime(0.09, t)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.06)
    o.connect(f).connect(g).connect(c.destination)
    o.start(t); o.stop(t + 0.07)
  } catch {}
}

// Filing a card into a slot (a trash): a short bandpassed noise swish.
export function fileAway() {
  try {
    const c = ac(), t = c.currentTime, n = Math.floor(c.sampleRate * 0.16)
    const buf = c.createBuffer(1, n, c.sampleRate)
    const d = buf.getChannelData(0)
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n)
    const s = c.createBufferSource(), g = c.createGain(), f = c.createBiquadFilter()
    s.buffer = buf
    f.type = 'bandpass'
    f.Q.value = 1.2
    f.frequency.setValueAtTime(2400, t)
    f.frequency.exponentialRampToValueAtTime(700, t + 0.15)
    g.gain.setValueAtTime(0.05, t)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16)
    s.connect(f).connect(g).connect(c.destination)
    s.start(t)
  } catch {}
}

// Peek engage: soft short swell (played when a preview starts).
export function swell() {
  try {
    const c = ac(), t = c.currentTime
    const o = c.createOscillator(), g = c.createGain()
    o.type = 'sine'
    o.frequency.setValueAtTime(220, t)
    o.frequency.exponentialRampToValueAtTime(440, t + 0.09)
    g.gain.setValueAtTime(0.0001, t)
    g.gain.exponentialRampToValueAtTime(0.05, t + 0.05)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.18)
    o.connect(g).connect(c.destination)
    o.start(t); o.stop(t + 0.2)
  } catch {}
}
