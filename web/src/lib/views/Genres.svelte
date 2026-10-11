<script>
  import { api } from '../api.js'
  import { playList, startRadio } from '../player.svelte.js'
  import TrackList from '../TrackList.svelte'
  import Icon from '../Icon.svelte'
  let { nav, initial = null } = $props()
  let list = $state([])
  let sel = $state(null)
  let tracks = $state([])

  // real genres first (server sorts by count); the unlabeled bucket goes last
  api.genres().then((g) => (list = [...g.filter((x) => x.genre !== 'unlabeled'),
                                    ...g.filter((x) => x.genre === 'unlabeled')])).catch(() => {})

  async function open(name) {
    sel = name; tracks = []
    const d = await api.genre(name)
    tracks = d.tracks
  }
  $effect(() => { if (initial) open(initial); else sel = null })

  function shuffled() {
    const c = tracks.slice()
    for (let i = c.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1)); [c[i], c[j]] = [c[j], c[i]]
    }
    return c
  }
</script>

{#if sel}
  <button class="crumb" onclick={() => nav('genres')}>← Genres</button>
  <div class="detail-head">
    <div class="detail-art stamp">{sel.slice(0, 1).toUpperCase()}</div>
    <div class="detail-meta">
      <div class="sd-sub">Genre</div>
      <h2 class="detail-title" style="text-transform:uppercase">{sel}</h2>
      <div class="muted detail-stats">{tracks.length} tracks</div>
      <div class="detail-actions">
        <button class="btn" onclick={() => startRadio('genre', sel, 'library')}>
          <Icon name="play" size={14} fill /> Start station</button>
        <button class="btn ghost" onclick={() => playList(shuffled(), 0, 'library')}>
          <Icon name="shuffle" size={14} /> Shuffle all</button>
      </div>
    </div>
  </div>
  <!-- the genre's full track list is a lookup: play the pick, station follows -->
  <TrackList {tracks} single source="library" />
{:else}
  <div class="view-head">
    <h2 class="title">Genres</h2>
    <span class="head-count">{list.length}</span>
  </div>
  <div class="station-list">
    {#each list as g (g.genre)}
      <button class="station-row" onclick={() => nav('genres', g.genre)}>
        <span class="st-name">{g.genre}</span>
        <span class="st-leader"></span>
        <span class="st-count">{g.count} tracks</span>
        <span class="st-go">Open</span>
      </button>
    {/each}
  </div>
{/if}
