<script>
  import { player, toggle, next, prev, seek, setVolume, like, dislike,
           toggleShuffle, toggleRepeat, isLiked } from './player.svelte.js'
  import Icon from './Icon.svelte'

  function fmt(s) {
    if (!s && s !== 0) return '0:00'
    const m = Math.floor(s / 60), x = Math.floor(s % 60)
    return `${m}:${x < 10 ? '0' : ''}${x}`
  }

  // The thumb is PERSISTENT state now (the likes store, mirrored from the plays log);
  // only the dislike stays a transient in-the-moment marker, since disliking skips on.
  const liked = $derived(isLiked(player.current?.id))
  let feedback = $state(null)
  let stamping = $state(false)
  let lastId = null
  let stampT = null
  $effect(() => {
    if (player.current?.id !== lastId) { lastId = player.current?.id; feedback = null }
  })
  const onLike = () => {
    like()
    stamping = true                       // rubber-stamp thunk (see .stamp in app.css)
    clearTimeout(stampT)
    stampT = setTimeout(() => (stamping = false), 260)
  }
  const onDislike = () => { feedback = 'dislike'; dislike() }

  // Letterpress ticker: the title travels only when it genuinely doesn't fit — measured
  // on the plain (ellipsised) render, then swapped for the moving one. Never starts at
  // all under prefers-reduced-motion, so that case keeps its ellipsis.
  const stillPreferred = () =>
    window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
  let t1 = $state(null)
  let over = $state(false)
  let shift = $state(0)
  $effect(() => {
    const _id = player.current?.id
    over = false
    if (!t1 || stillPreferred()) return
    const raf = requestAnimationFrame(() => {
      if (!t1) return
      const extra = t1.scrollWidth - t1.clientWidth
      if (extra > 2) { shift = extra + 8; over = true }
    })
    return () => cancelAnimationFrame(raf)
  })

  let preMute = 1
  const toggleMute = () => {
    if (player.volume > 0) { preMute = player.volume; setVolume(0) }
    else setVolume(preMute || 0.8)
  }
  const pct = $derived(player.duration ? (player.time / player.duration) * 100 : 0)
</script>

<footer class="bar">
  <!-- Left: artwork + track + thumbs -->
  <div class="np">
    {#if player.current}
      <button class="np-open" title="Now playing" onclick={() => (player.showFull = true)}>
        {#key player.current.id}
          <div class="art np-swap">
            <Icon name="music" size={18} />
            <img src={`/art/${player.current.id}`} alt="" onerror={(e) => (e.currentTarget.style.display = 'none')} />
          </div>
          <div class="meta np-swap">
            <span class="t1" class:tick={over} bind:this={t1} title={player.current.title}
              >{#if over}<span class="t1-in" style={`--shift:${shift}px`}
                >{player.current.title}</span>{:else}{player.current.title}{/if}</span>
            <span class="t2" title={player.current.artist}>{player.current.artist}</span>
          </div>
        {/key}
      </button>
      <div class="thumbs">
        <button class="ib" class:on={liked} class:stamp={stamping}
                title={liked ? 'Unlike' : 'Like'} onclick={onLike}>
          <Icon name="up" size={17} fill={liked} /></button>
        <button class="ib" class:on={feedback === 'dislike'} title="Dislike (and skip)" onclick={onDislike}>
          <Icon name="down" size={17} /></button>
      </div>
    {:else}
      <span class="t2">Nothing playing</span>
    {/if}
  </div>

  <!-- Center: transport + progress -->
  <div class="ctl">
    <div class="btns">
      <button class="ib" class:on={player.shuffle} title="Shuffle" onclick={toggleShuffle}>
        <Icon name="shuffle" size={18} /></button>
      <button class="ib" title="Previous" onclick={prev}><Icon name="prev" size={20} fill /></button>
      <button class="pp press" class:playing={player.playing} title={player.playing ? 'Pause' : 'Play'} onclick={toggle}>
        <Icon name={player.playing ? 'pause' : 'play'} size={20} fill /></button>
      <button class="ib" title="Next" onclick={next}><Icon name="next" size={20} fill /></button>
      <button class="ib" class:on={player.repeat} title="Repeat one" onclick={toggleRepeat}>
        <Icon name="repeat" size={18} /></button>
    </div>
    <div class="seek">
      <span class="time">{fmt(player.time)}</span>
      <div class="track" style="--pct:{pct}%">
        <input type="range" min="0" max={player.duration || 0} step="0.1"
               value={player.time} oninput={(e) => seek(+e.target.value)} />
      </div>
      <span class="time">{fmt(player.duration)}</span>
    </div>
  </div>

  <!-- Right: volume + queue -->
  <div class="right">
    <button class="ib" title="Mute" onclick={toggleMute}>
      <Icon name={player.volume === 0 ? 'mute' : 'volume'} size={19} /></button>
    <input class="vol" type="range" min="0" max="1" step="0.01"
           value={player.volume} oninput={(e) => setVolume(+e.target.value)} />
    <button class="ib" class:on={player.showQueue} title="Queue"
            onclick={() => (player.showQueue = !player.showQueue)}><Icon name="queue" size={19} /></button>
  </div>
</footer>
