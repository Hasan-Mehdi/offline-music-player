<script module>
  // Soundtracks as crate dividers: an alphabetical-by-size stack of hairline-ruled rows,
  // each carrying a filmstrip of its own covers as the "spine" (the art is the wealth).
  // Clicking a divider unfurls that OST's tracklist inline, like reading liner notes.
  // Index is module-cached so switching tabs and back doesn't refetch (see Explore).
  let indexCache = $state(null)
  let loading = false
  function loadIndex() {
    if (indexCache !== null || loading) return
    loading = true
    fetch('/api/osts').then((r) => r.json())
      .then((d) => (indexCache = Array.isArray(d) ? d : []))
      .catch(() => (indexCache = []))
      .finally(() => (loading = false))
  }
</script>

<script>
  import { api } from '../api.js'
  import { playList } from '../player.svelte.js'
  import TrackList from '../TrackList.svelte'
  import Icon from '../Icon.svelte'
  loadIndex()

  let open = $state(null)      // name of the unfurled OST (accordion: one at a time)
  let tracks = $state([])
  let busy = $state(false)
  const trackCache = new Map()

  async function toggle(o) {
    if (open === o.name) { open = null; return }
    open = o.name; tracks = []
    if (trackCache.has(o.name)) { tracks = trackCache.get(o.name); return }
    busy = true
    try {
      const d = await api.ost(o.name)
      tracks = d.tracks || []
      trackCache.set(o.name, tracks)
    } catch { tracks = [] } finally { busy = false }
  }

  function fmtDur(s) {
    const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60)
    return h ? `${h}h${String(m).padStart(2, '0')}` : `${m}m`
  }
  function shuffled(list) {
    const c = list.slice()
    for (let i = c.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1)); [c[i], c[j]] = [c[j], c[i]]
    }
    return c
  }
</script>

<div class="view-head">
  <h2 class="title">Soundtracks</h2>
  {#if indexCache}<span class="head-count">{indexCache.length} OSTs</span>{/if}
</div>

{#if indexCache === null}
  <div class="muted">Reading the shelves…</div>
{:else if !indexCache.length}
  <div class="muted">No soundtracks found.</div>
{:else}
  <div class="ost-list">
    {#each indexCache as o, i (o.name)}
      {@const sec = o.section || ''}
      {#if sec !== (i ? (indexCache[i - 1].section || '') : null) && !(sec === '' && i === 0)}
        <div class="ost-franchise">{sec || 'More soundtracks'}</div>
      {/if}
      <div class="ost-item" class:open={open === o.name}>
        <button class="ost-row" onclick={() => toggle(o)}>
          <span class="ost-name">{o.name}</span>
          <span class="ost-spine" aria-hidden="true">
            {#each o.covers as v (v)}
              <img src={`/art/${v}`} alt="" loading="lazy"
                   onerror={(e) => e.currentTarget.remove()} />
            {/each}
          </span>
          <span class="ost-meta">{o.count} · {fmtDur(o.seconds)}</span>
          <span class="ost-caret" aria-hidden="true">▸</span>
        </button>
        {#if open === o.name}
          <div class="ost-body">
            {#if busy && !tracks.length}
              <div class="muted" style="padding:6px 0">Reading liner notes…</div>
            {:else}
              <div class="ost-actions">
                <button class="btn" onclick={() => playList(tracks, 0, 'ost')}>
                  <Icon name="play" size={13} fill /> Play</button>
                <button class="btn ghost" onclick={() => playList(shuffled(tracks), 0, 'ost')}>
                  <Icon name="shuffle" size={13} /> Shuffle</button>
              </div>
              <TrackList {tracks} source="ost" />
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}
