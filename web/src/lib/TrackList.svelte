<script>
  import { playList, playNext, addToQueue, playTrackRadio, trashTrack,
           toggleLike, isLiked, player } from './player.svelte.js'
  import Icon from './Icon.svelte'
  // `single`: the list is a lookup (search results, browse-all, genre track list) — not
  // a playlist you want to hear front-to-back. Clicking plays that track and queues a
  // vibe-walk station behind it. Lists that ARE deliberate sequences (artist page, OST
  // album order) omit it and keep playing through in order.
  // `scores`: optional { id: 0..1 } map (hum-to-search). When present, the genre column
  // is replaced by a quiet match-confidence meter instead.
  // `source`: provenance stamped on every play started from this list.
  // `likedList`: this list IS the likes collection, so un-liking a row files it out.
  let { tracks = [], single = false, scores = null, source = 'library',
        likedList = false } = $props()
  const playAt = (i) =>
    (single ? playTrackRadio(tracks[i], source) : playList(tracks, i, source))

  // Rows animate out of the list before they disappear: a trashed (or un-liked) row
  // slides away like a card dropped into a slot, then stops taking up space.
  let filing = $state({})
  let filed = $state({})

  async function onTrash(t) {
    filing = { ...filing, [t.id]: true }
    const ok = await trashTrack(t)
    // let the card finish going into the slot before the row stops taking up space;
    // a failed move springs the row back instead (with a notice explaining why).
    if (ok) setTimeout(() => (filed = { ...filed, [t.id]: true }), 240)
    else { const f = { ...filing }; delete f[t.id]; filing = f }
  }

  function onLike(t) {
    const on = toggleLike(t)
    if (!on && likedList) {
      filing = { ...filing, [t.id]: true }
      setTimeout(() => (filed = { ...filed, [t.id]: true }), 240)
    }
  }

  function fmt(s) {
    if (!s && s !== 0) return ''
    const m = Math.floor(s / 60), x = Math.floor(s % 60)
    return `${m}:${x < 10 ? '0' : ''}${x}`
  }
  const pct = (id) => {
    const s = scores?.[id]
    return s == null ? 0 : Math.round(Math.max(0, Math.min(1, s)) * 100)
  }
</script>

<div class="tl">
  {#each tracks as t, i (t.id + '-' + i)}
    <div class="row" class:active={player.current?.id === t.id}
         class:filing={filing[t.id]} class:filed={filed[t.id]}>
      <button class="cover press" title="Play" onclick={() => playAt(i)}>
        <Icon name="music" size={15} />
        <img src={`/art/${t.id}`} alt="" loading="lazy"
             onerror={(e) => (e.currentTarget.style.display = 'none')} />
        {#if player.current?.id === t.id}
          <span class="eq" class:paused={!player.playing}><i></i><i></i><i></i></span>
        {/if}
        <span class="cov-play"><Icon name="play" size={14} fill /></span>
      </button>
      <span class="ti" title={t.title}>{t.title}</span>
      <span class="ar" title={t.artist}>{t.artist}</span>
      {#if scores}
        <span class="mt" title={`${pct(t.id)}% melodic match`}>
          <span class="mt-bar"><i style={`width:${pct(t.id)}%`}></i></span>
          <span class="mt-pct">{pct(t.id)}%</span>
        </span>
      {:else}
        <span class="ge">{t.genre || ''}</span>
      {/if}
      <span class="du">{fmt(t.duration)}</span>
      <span class="act">
        <button class="like-btn" class:on={isLiked(t.id)}
                title={isLiked(t.id) ? 'Unlike' : 'Like'}
                onclick={() => onLike(t)}>
          <Icon name="up" size={14} fill={isLiked(t.id)} /></button>
        <button class="qact" title="Play next" onclick={() => playNext(t, source)}>
          <Icon name="next" size={14} fill /></button>
        <button class="qact" title="Add to queue" onclick={() => addToQueue(t, source)}>
          <Icon name="plus" size={14} /></button>
        <button class="trash-btn" title="Move to trash" onclick={() => onTrash(t)}>
          <Icon name="trash" size={14} /></button>
      </span>
    </div>
  {/each}
</div>
