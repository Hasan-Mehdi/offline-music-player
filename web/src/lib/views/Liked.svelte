<script>
  // The likes collection: everything whose latest thumb is up (/api/likes). The list is
  // fetched once per visit for metadata; the thumbs themselves read the shared `likes`
  // store, so a like made anywhere else in the app is already reflected here.
  import { api } from '../api.js'
  import { likes, playList } from '../player.svelte.js'
  import TrackList from '../TrackList.svelte'
  import Icon from '../Icon.svelte'

  let list = $state(null)
  api.likes().then((d) => {
    list = Array.isArray(d) ? d : []
    // if the boot fetch hasn't landed yet, seed the shared store from this one so the
    // thumbs are right on first paint instead of filling in a beat later
    if (!likes.loaded) {
      for (const t of list) likes.ids[t.id] = t.liked_at || Date.now() / 1000
    }
  }).catch(() => (list = []))

  // still-liked rows only for the play actions (a row un-liked in place stays visible
  // until you leave, but shouldn't sneak into the queue)
  const live = $derived((list || []).filter((t) => likes.ids[t.id] != null))
  function shuffled() {
    const c = live.slice()
    for (let i = c.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1)); [c[i], c[j]] = [c[j], c[i]]
    }
    return c
  }
</script>

<div class="view-head">
  <h2 class="title">Liked</h2>
  {#if list}<span class="head-count">{live.length} tracks</span>{/if}
</div>

{#if list === null}
  <div class="muted">Reading the log…</div>
{:else if !list.length}
  <div class="muted">Nothing liked yet — hit the thumb on a track you want to keep.</div>
{:else}
  <div class="bar-actions">
    <button class="btn" onclick={() => playList(live, 0, 'liked')}>
      <Icon name="play" size={13} fill /> Play</button>
    <button class="btn ghost" onclick={() => playList(shuffled(), 0, 'liked')}>
      <Icon name="shuffle" size={13} /> Shuffle</button>
  </div>
  <TrackList tracks={list} source="liked" likedList />
{/if}
