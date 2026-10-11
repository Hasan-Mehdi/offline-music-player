<script>
  // Section words, poster-style. Sits under the masthead on desktop,
  // becomes the bottom word-row on the handheld build (CSS re-areas it).
  let { view, nav } = $props()
  const LIB = new Set(['library', 'songs', 'artists', 'genres', 'liked', 'history', 'trash'])
  const items = [
    ['wheel', 'Wheel'],
    ['home', 'Home'],
    ['explore', 'Explore'],
    ['library', 'Library'],
    ['ost', 'OST'],
  ]
  const isActive = (k) => (k === 'library' ? LIB.has(view.name) : view.name === k)
</script>

<nav class="nav">
  {#each items as [k, label] (k)}
    <button class:active={isActive(k)} onclick={() => nav(k)}>{label}</button>
  {/each}
</nav>
