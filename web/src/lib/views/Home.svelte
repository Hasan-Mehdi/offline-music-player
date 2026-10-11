<script>
  import { api } from '../api.js'
  import { startRadio } from '../player.svelte.js'
  import Card from '../Card.svelte'

  let dial = $state([])
  let stations = $state([])
  let chips = $state(['Shuffle'])

  fetch('/api/speeddial').then((r) => r.json()).then((d) => (dial = d)).catch(() => {})
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
  {#each dial as t (t.id)}<Card track={t} source="home" />{/each}
</div>

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
