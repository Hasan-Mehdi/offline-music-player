<script>
  import { api } from '../api.js'
  import { playList } from '../player.svelte.js'
  import TrackList from '../TrackList.svelte'
  import Icon from '../Icon.svelte'
  let { nav, initial = null } = $props()
  let list = $state([])
  let sel = $state(null)
  let tracks = $state([])
  let q = $state('')
  let sort = $state('count')   // 'count' | 'name'

  api.artists().then((a) => (list = a)).catch(() => {})

  const shown = $derived.by(() => {
    const f = q.trim().toLowerCase()
    const out = f ? list.filter((a) => a.artist.toLowerCase().includes(f)) : list.slice()
    if (sort === 'name') out.sort((x, y) => x.artist.localeCompare(y.artist))
    return out
  })

  async function open(name) {
    sel = name; tracks = []
    const d = await api.artist(name)
    tracks = d.tracks
  }
  // react to hash navigation (#/artists/<name>) including in-place changes
  $effect(() => { if (initial) open(initial); else sel = null })

  function shuffled() {
    const c = tracks.slice()
    for (let i = c.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1)); [c[i], c[j]] = [c[j], c[i]]
    }
    return c
  }
  const totalSecs = $derived(tracks.reduce((s, t) => s + (t.duration || 0), 0))
</script>

{#if sel}
  <button class="crumb" onclick={() => nav('artists')}>← Artists</button>
  <div class="detail-head">
    <div class="detail-art round">
      <Icon name="mic" size={34} />
      {#if tracks[0]}
        <img src={`/art/${tracks[0].id}`} alt=""
             onerror={(e) => (e.currentTarget.style.display = 'none')} />
      {/if}
    </div>
    <div class="detail-meta">
      <div class="sd-sub">Artist</div>
      <h2 class="detail-title">{sel}</h2>
      <div class="muted detail-stats">{tracks.length} tracks · {Math.round(totalSecs / 60)} min</div>
      <div class="detail-actions">
        <button class="btn" onclick={() => playList(tracks, 0, 'library')}>
          <Icon name="play" size={14} fill /> Play all</button>
        <button class="btn ghost" onclick={() => playList(shuffled(), 0, 'library')}>
          <Icon name="shuffle" size={14} /> Shuffle</button>
      </div>
    </div>
  </div>
  <TrackList {tracks} />
{:else}
  <div class="view-head">
    <h2 class="title">Artists</h2>
    <span class="head-count">{list.length.toLocaleString()}</span>
  </div>
  <div class="bar-actions">
    <div class="filter-box">
      <span class="si"><Icon name="search" size={15} /></span>
      <input class="search" placeholder="Filter artists…" bind:value={q} />
    </div>
    <select bind:value={sort} title="Sort">
      <option value="count">Most tracks</option>
      <option value="name">A – Z</option>
    </select>
  </div>
  <div class="grid">
    {#each shown.slice(0, 400) as a (a.artist)}
      <button class="card artist-card" onclick={() => nav('artists', a.artist)}>
        <span class="ava-art">
          <Icon name="mic" size={20} />
          {#if a.vid}
            <img src={`/art/${a.vid}`} alt="" loading="lazy"
                 onerror={(e) => (e.currentTarget.style.display = 'none')} />
          {/if}
        </span>
        <span class="card-body">
          <span class="nm">{a.artist}</span>
          <span class="sub">{a.count} track{a.count === 1 ? '' : 's'}{a.genre ? ' · ' + a.genre : ''}</span>
        </span>
      </button>
    {/each}
  </div>
  {#if shown.length > 400}
    <div class="muted" style="padding:14px 2px">Showing 400 of {shown.length.toLocaleString()} — type to narrow down.</div>
  {/if}
{/if}
