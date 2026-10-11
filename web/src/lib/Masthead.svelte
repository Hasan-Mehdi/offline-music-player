<script>
  // Newspaper-style masthead: wordmark + printer's mark, dateline stats on the right.
  import { api } from './api.js'
  import { APP_NAME } from './brand.js'
  let { nav } = $props()
  let stats = $state(null)
  api.stats().then((s) => (stats = s)).catch(() => {})
</script>

<header class="mast">
  <button class="mast-brand" onclick={() => nav('wheel')}>
    {APP_NAME}<span class="dot"></span>
  </button>
  {#if stats}
    <div class="mast-stats">
      {stats.tracks.toLocaleString()} tracks · {stats.artists.toLocaleString()} artists · {stats.genres} genres
    </div>
  {/if}
</header>
