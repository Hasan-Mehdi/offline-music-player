<script>
  import Masthead from './lib/Masthead.svelte'
  import Nav from './lib/Nav.svelte'
  import NowBar from './lib/NowBar.svelte'
  import NowPlaying from './lib/NowPlaying.svelte'
  import Queue from './lib/Queue.svelte'
  import Home from './lib/views/Home.svelte'
  import Wheel from './lib/views/Wheel.svelte'
  import Explore from './lib/views/Explore.svelte'
  import OST from './lib/views/OST.svelte'
  import Library from './lib/views/Library.svelte'
  import { player, toggle, next, prev, restore, loadLikes } from './lib/player.svelte.js'
  import { onMount } from 'svelte'

  onMount(() => {
    restore()      // reload the last session (paused) after a browser refresh
    loadLikes()    // one fetch: every thumb in the app then shows the persistent truth
  })

  // hash routing: #/songs, #/artists/<name>… — deep-linkable, back button works
  const VIEWS = new Set(['home', 'wheel', 'explore', 'ost', 'library', 'songs', 'artists',
                         'genres', 'liked', 'history', 'trash'])
  function parseHash() {
    let [name, arg] = location.hash.replace(/^#\/?/, '').split('/')
    if (name === 'search') name = 'library'   // search folded into the Songs/library view
    return { name: VIEWS.has(name) ? name : 'wheel', arg: arg ? decodeURIComponent(arg) : null }
  }
  let view = $state(parseHash())
  const nav = (name, arg = null) => {
    location.hash = arg ? `/${name}/${encodeURIComponent(arg)}` : `/${name}`
  }

  function onKey(e) {
    const tag = (e.target?.tagName || '').toLowerCase()
    if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return
    if (e.code === 'Space') { e.preventDefault(); toggle() }
    else if (e.code === 'ArrowRight' && e.shiftKey) next()
    else if (e.code === 'ArrowLeft' && e.shiftKey) prev()
  }
</script>

<svelte:window onkeydown={onKey} onhashchange={() => (view = parseHash())} />

<div class="app">
  <Masthead {nav} />
  <Nav {view} {nav} />
  <main>
    {#key view.name}
      <div class="view-anim">
        {#if view.name === 'home'}<Home {nav} />
        {:else if view.name === 'wheel'}<Wheel />
        {:else if view.name === 'explore'}<Explore />
        {:else if view.name === 'ost'}<OST />
        {:else if view.name === 'library' || view.name === 'songs'}<Library {nav} tab="tracks" />
        {:else if view.name === 'artists'}<Library {nav} tab="artists" arg={view.arg} />
        {:else if view.name === 'genres'}<Library {nav} tab="genres" arg={view.arg} />
        {:else if view.name === 'liked'}<Library {nav} tab="liked" />
        {:else if view.name === 'history'}<Library {nav} tab="history" />
        {:else if view.name === 'trash'}<Library {nav} tab="trash" />
        {/if}
      </div>
    {/key}
    {#if player.showQueue}<Queue />{/if}
  </main>
  {#if player.notice}
    {#key player.notice.n}
      <div class="notice" class:bad={player.notice.bad} role="status">{player.notice.text}</div>
    {/key}
  {/if}
  <NowBar />
  {#if player.showFull}<NowPlaying />{/if}
</div>
