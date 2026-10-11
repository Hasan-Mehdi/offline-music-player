<script>
  // Full-screen Now Playing overlay — the main surface on the small-touchscreen
  // device build; opened from the NowBar on desktop too.
  import { player, toggle, next, prev, seek, like, dislike, isLiked, trashTrack,
           toggleShuffle, toggleRepeat } from './player.svelte.js'
  import Icon from './Icon.svelte'
  import { fly } from 'svelte/transition'
  import { cubicOut } from 'svelte/easing'

  function fmt(s) {
    if (!s && s !== 0) return '0:00'
    const m = Math.floor(s / 60), x = Math.floor(s % 60)
    return `${m}:${x < 10 ? '0' : ''}${x}`
  }

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
    stamping = true
    clearTimeout(stampT)
    stampT = setTimeout(() => (stamping = false), 260)
  }
  const onDislike = () => { feedback = 'dislike'; dislike() }
  const onTrash = () => { const t = player.current; if (t) trashTrack(t) }
  const close = () => (player.showFull = false)
  const pct = $derived(player.duration ? (player.time / player.duration) * 100 : 0)
</script>

<div class="npv"
     in:fly={{ y: 420, duration: 320, easing: cubicOut }}
     out:fly={{ y: 420, duration: 240, easing: cubicOut }}>
  <div class="npv-top">
    <button class="ib" title="Close" onclick={close} aria-label="Close">
      <Icon name="down-chevron" size={22} /></button>
    <span class="npv-hint">Now playing</span>
    <button class="ib" class:on={player.showQueue} title="Queue"
            onclick={() => (player.showQueue = !player.showQueue)}><Icon name="queue" size={20} /></button>
  </div>

  {#if player.current}
    <div class="npv-art">
      <Icon name="music" size={64} />
      <img src={`/art/${player.current.id}`} alt=""
           onerror={(e) => (e.currentTarget.style.display = 'none')} />
    </div>

    <div class="npv-meta">
      <div class="npv-t1">{player.current.title}</div>
      <div class="npv-t2">{player.current.artist}</div>
      <button class="npv-toss" title="Move to trash" onclick={onTrash}>
        <Icon name="trash" size={13} /> Throw out</button>
    </div>

    <div class="seek npv-seek" style="--pct:{pct}%">
      <span class="time">{fmt(player.time)}</span>
      <div class="track" style="--pct:{pct}%">
        <input type="range" min="0" max={player.duration || 0} step="0.1"
               value={player.time} oninput={(e) => seek(+e.target.value)} />
      </div>
      <span class="time">{fmt(player.duration)}</span>
    </div>

    <div class="npv-btns">
      <button class="ib" class:on={feedback === 'dislike'} title="Dislike (and skip)" onclick={onDislike}>
        <Icon name="down" size={20} /></button>
      <button class="ib" class:on={player.shuffle} title="Shuffle" onclick={toggleShuffle}>
        <Icon name="shuffle" size={20} /></button>
      <button class="ib big" title="Previous" onclick={prev}><Icon name="prev" size={26} fill /></button>
      <button class="pp npv-pp press" title={player.playing ? 'Pause' : 'Play'} onclick={toggle}>
        <Icon name={player.playing ? 'pause' : 'play'} size={28} fill /></button>
      <button class="ib big" title="Next" onclick={next}><Icon name="next" size={26} fill /></button>
      <button class="ib" class:on={player.repeat} title="Repeat one" onclick={toggleRepeat}>
        <Icon name="repeat" size={20} /></button>
      <button class="ib" class:on={liked} class:stamp={stamping}
              title={liked ? 'Unlike' : 'Like'} onclick={onLike}>
        <Icon name="up" size={20} fill={liked} /></button>
    </div>
  {:else}
    <div class="muted" style="margin:auto">Nothing playing</div>
  {/if}
</div>
