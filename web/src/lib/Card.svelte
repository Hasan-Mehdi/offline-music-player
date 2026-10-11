<script>
  import { playTrackRadio } from './player.svelte.js'
  import Icon from './Icon.svelte'
  let { track, source = 'home' } = $props()
</script>

<button class="sd-card press" onclick={() => playTrackRadio(track, source)}
        title={track.title + ' — ' + track.artist}>
  <div class="art">
    <span class="ph"><Icon name="music" size={30} /></span>
    <img src={`/art/${track.id}`} alt="" loading="lazy" onerror={(e) => (e.currentTarget.style.display = 'none')} />
    <span class="pov"><Icon name="play" size={17} fill /></span>
  </div>
  <div class="sd-t">{track.title}</div>
  <div class="sd-a">{track.artist}</div>
</button>
