<script>
  // The library: everything that is "your collection" as tabs of one view instead of a
  // fistful of top-level nav words. Browsing (tracks/artists/genres) and the personal
  // collections (liked/history/trash) are the same kind of thing — a way into what you
  // own — so they share the tab row rather than growing the masthead nav.
  import Songs from './Songs.svelte'
  import Artists from './Artists.svelte'
  import Genres from './Genres.svelte'
  import Liked from './Liked.svelte'
  import History from './History.svelte'
  import Trash from './Trash.svelte'
  import { likeCount, likes } from '../player.svelte.js'
  let { nav, tab = 'tracks', arg = null } = $props()
  const TABS = [['tracks', 'Tracks'], ['artists', 'Artists'], ['genres', 'Genres'],
                ['liked', 'Liked'], ['history', 'History'], ['trash', 'Trash']]
  const go = (k) => (k === 'tracks' ? nav('library') : nav(k))
  // flip-counter: the count changes -> the digits roll over (see .flip in app.css)
  const n = $derived(likes.loaded ? likeCount() : 0)
</script>

<div class="lib-tabs">
  {#each TABS as [k, label] (k)}
    <button class="lib-tab" class:on={tab === k} onclick={() => go(k)}>
      {label}
      {#if k === 'liked' && n}{#key n}<span class="flip">{n}</span>{/key}{/if}
    </button>
  {/each}
</div>

{#if tab === 'artists'}
  <Artists {nav} initial={arg} />
{:else if tab === 'genres'}
  <Genres {nav} initial={arg} />
{:else if tab === 'liked'}
  <Liked />
{:else if tab === 'history'}
  <History />
{:else if tab === 'trash'}
  <Trash />
{:else}
  <Songs {nav} />
{/if}
