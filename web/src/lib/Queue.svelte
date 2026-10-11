<script>
  import { player, jumpTo, removeAt } from './player.svelte.js'
  import Icon from './Icon.svelte'
  import { fly } from 'svelte/transition'
  import { cubicOut } from 'svelte/easing'
</script>

<aside class="queue"
       in:fly={{ x: 360, duration: 280, easing: cubicOut }}
       out:fly={{ x: 360, duration: 220, easing: cubicOut }}>
  <h4>Queue · {player.queue.length}</h4>
  {#if player.queue.length === 0}
    <div class="muted">Queue is empty.</div>
  {/if}
  {#each player.queue as t, i (t.id + '-' + i)}
    <div class="qrow" class:active={i === player.index}>
      <button class="qmain" onclick={() => jumpTo(i, 'queue')}>
        <span class="ava-art sm sq">
          <Icon name="music" size={13} />
          <img src={`/art/${t.id}`} alt="" loading="lazy"
               onerror={(e) => (e.currentTarget.style.display = 'none')} />
        </span>
        <span class="qtext">
          <span class="qt">{t.title}</span>
          <span class="qa">{t.artist}</span>
        </span>
      </button>
      {#if i !== player.index}
        <button class="qx" title="Remove" onclick={() => removeAt(i)}>
          <Icon name="close" size={14} /></button>
      {:else}
        <span class="qnow"><Icon name="volume" size={14} /></span>
      {/if}
    </div>
  {/each}
</aside>
