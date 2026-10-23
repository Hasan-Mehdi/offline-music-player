<script>
  import { api } from '../api.js'
  import { playList, startRadio } from '../player.svelte.js'
  import Card from '../Card.svelte'
  import Icon from '../Icon.svelte'

  let dial = $state([])
  let recs = $state([])
  let stations = $state([])
  let chips = $state(['Shuffle'])

  fetch('/api/speeddial?n=18').then((r) => r.json()).then((d) => (dial = d)).catch(() => {})
  fetch('/api/recommend?n=24').then((r) => r.json()).then((d) => (recs = d)).catch(() => {})
  api.genres().then((g) => {
    const real = g.filter((x) => x.genre && x.genre !== 'unlabeled')
    chips = ['Shuffle', ...real.slice(0, 9).map((x) => x.genre)]
    stations = real.slice(0, 12)
  }).catch(() => {})

  const chip = (c) => (c === 'Shuffle' ? startRadio('shuffle', '', 'home') : startRadio('genre', c, 'home'))
</script>

<div class="chips">
  {#each chips as c (c)}<button class="chip" onclick={() => chip(c)}>{c}</button>{/each}
</div>

<h2 class="title">Listen again</h2>
<div class="sd-grid">
  {#each dial as t (t.key ?? t.id)}<Card track={t} source="home" />{/each}
</div>

{#if recs.length}
  <div class="shelf-head" style="margin-top:40px">
    <div>
      <h2 class="title" style="margin:0">Recommended for you</h2>
      <div class="shelf-sub">new to you · from your last two weeks</div>
    </div>
    <button class="btn ghost" onclick={() => playList(recs, 0, 'home')}>
      <Icon name="play" size={13} fill /> Play</button>
  </div>
  <div class="sd-grid">
    {#each recs as t (t.id)}<Card track={t} source="home" />{/each}
  </div>
{/if}

<h2 class="title" style="margin-top:40px">Stations</h2>
<div class="station-list">
  {#each stations as s (s.genre)}
    <button class="station-row" onclick={() => startRadio('genre', s.genre, 'home')}>
      <span class="st-name">{s.genre}</span>
      <span class="st-leader"></span>
      <span class="st-count">{s.count} tracks</span>
      <span class="st-go">Play</span>
    </button>
  {/each}
</div>
