<script module>
  // Discovery shelves from the taste model (/api/explore): fresh finds, deep cuts,
  // forgotten favorites. Each shelf is playable as a batch.
  //
  // Cached at MODULE scope (not per-instance) so switching to another tab and back
  // reuses the same shelves. App.svelte's {#key view.name} destroys this view on
  // navigate, and /api/explore reshuffles on every call, so a per-mount fetch made
  // the whole grid jump around on each visit. Fetch once; a full page reload (which
  // clears module scope) is the way to pull a fresh set.
  let shelves = $state(null)
  let loading = false
  function ensureShelves() {
    if (shelves !== null || loading) return
    loading = true
    fetch('/api/explore').then((r) => r.json())
      .then((d) => (shelves = Array.isArray(d) ? d : []))
      .catch(() => (shelves = []))
      .finally(() => (loading = false))
  }
</script>

<script>
  import { playList } from '../player.svelte.js'
  import Card from '../Card.svelte'
  import Icon from '../Icon.svelte'
  ensureShelves()
</script>

<h2 class="title">Explore</h2>

{#if shelves === null}
  <div class="muted">Reading the taste model…</div>
{:else if !shelves.length}
  <div class="muted">Not enough listening history yet — play some music and come back.</div>
{:else}
  {#each shelves as sh (sh.key)}
    <div class="shelf-head">
      <div>
        <div class="sec-label" style="margin:0">{sh.title}</div>
        <div class="shelf-sub">{sh.sub}</div>
      </div>
      <button class="btn ghost" onclick={() => playList(sh.tracks, 0, 'explore')}>
        <Icon name="play" size={13} fill /> Play</button>
    </div>
    <div class="sd-grid shelf-grid">
      {#each sh.tracks as t (t.id)}<Card track={t} source="explore" />{/each}
    </div>
  {/each}
{/if}
