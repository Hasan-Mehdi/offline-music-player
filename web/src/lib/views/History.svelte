<script>
  // Listening sessions, printed like till receipts: a dated header per day, one receipt
  // per sitting, every line a track with the outcome it earned. Sessions come from the
  // plays log's session_id (older rows are inferred from 30-minute gaps).
  import { api } from '../api.js'
  import { playList, playTrackRadio, player } from '../player.svelte.js'
  import Icon from '../Icon.svelte'

  let sessions = $state(null)
  api.history(30).then((d) => (sessions = Array.isArray(d) ? d : [])).catch(() => (sessions = []))

  const dayKey = (ts) => new Date(ts * 1000).toDateString()
  function dayLabel(ts) {
    const d = new Date(ts * 1000), now = new Date()
    const diff = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000)
    if (diff === 0) return 'Today'
    if (diff === 1) return 'Yesterday'
    return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  }
  const clock = (ts) => new Date(ts * 1000)
    .toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  function span(s) {
    const mins = Math.max(1, Math.round((s.ended - s.started) / 60))
    return mins >= 60 ? `${Math.floor(mins / 60)}h${String(mins % 60).padStart(2, '0')}` : `${mins} min`
  }
</script>

<div class="view-head">
  <h2 class="title">History</h2>
  {#if sessions}<span class="head-count">{sessions.length} sessions</span>{/if}
</div>

{#if sessions === null}
  <div class="muted">Reading the log…</div>
{:else if !sessions.length}
  <div class="muted">No listening logged yet.</div>
{:else}
  {#each sessions as s, i (s.session_id || s.started)}
    {#if i === 0 || dayKey(s.started) !== dayKey(sessions[i - 1].started)}
      <div class="day-head">{dayLabel(s.started)}</div>
    {/if}
    <div class="receipt" style={`--n:${Math.min(i, 8)}`}>
      <div class="rc-head">
        <span class="rc-time">{clock(s.started)}–{clock(s.ended)}</span>
        <span class="rc-rule"></span>
        <span class="rc-meta">{s.count} tracks · {span(s)}</span>
        <button class="btn ghost rc-again" onclick={() => playList(s.tracks, 0, 'history')}>
          <Icon name="play" size={12} fill /> Play again</button>
      </div>
      {#each s.tracks as t, k (t.id + '-' + k)}
        <button class="rc-row" class:active={player.current?.id === t.id}
                onclick={() => playTrackRadio(t, 'history')}>
          <span class="rc-at">{clock(t.at)}</span>
          <span class="rc-t">{t.title}</span>
          <span class="rc-a">{t.artist}</span>
          <span class="rc-badge {t.outcome}">{t.outcome}</span>
        </button>
      {/each}
    </div>
  {/each}
{/if}
