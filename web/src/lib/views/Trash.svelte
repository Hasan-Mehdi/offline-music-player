<script>
  // What you threw out, still on disk. Files sit in <library>\_trash until you empty it;
  // the tracks rows are already gone, so nothing here can be played — only put back.
  import { api } from '../api.js'
  import { notice } from '../player.svelte.js'
  import Icon from '../Icon.svelte'

  let list = $state(null)
  let armed = $state(false)     // Clear is two-step: arm, then confirm within 4s
  let busy = $state(false)
  let armTimer = null

  const load = () => api.trash()
    .then((d) => (list = Array.isArray(d) ? d : [])).catch(() => (list = []))
  load()

  const total = $derived((list || []).reduce((n, t) => n + (t.bytes || 0), 0))
  function mb(n) {
    if (!n) return '0 MB'
    return n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.max(0.1, n / 1e6).toFixed(1)} MB`
  }
  function when(ts) {
    if (!ts) return ''
    const d = new Date(ts * 1000)
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ' ' +
      d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  }

  let restoring = $state({})
  async function restore(t) {
    restoring = { ...restoring, [t.id]: true }
    try {
      await api.trashRestore(t.id)
      setTimeout(() => (list = list.filter((x) => x.id !== t.id)), 240)
      notice(`Back in the library — ${t.title || t.id}`)
    } catch (e) {
      const r = { ...restoring }; delete r[t.id]; restoring = r
      notice(e?.message || "Couldn't put that back.", true)
    }
  }

  function disarm() { clearTimeout(armTimer); armed = false }
  async function clear() {
    if (!armed) {
      armed = true
      clearTimeout(armTimer)
      armTimer = setTimeout(() => (armed = false), 4000)
      return
    }
    disarm()
    busy = true
    try {
      const r = await api.trashClear()
      list = []
      notice(`Deleted ${r.deleted} file${r.deleted === 1 ? '' : 's'} · ${mb(r.bytes)} freed`)
    } catch (e) {
      notice(e?.message || 'Some files could not be deleted.', true)
      load()
    } finally { busy = false }
  }
</script>

<div class="view-head">
  <h2 class="title">Trash</h2>
  {#if list}<span class="head-count">{list.length} files · {mb(total)}</span>{/if}
</div>

{#if list === null}
  <div class="muted">Checking the bin…</div>
{:else if !list.length}
  <div class="muted">Nothing in the trash. Files you throw out wait here until you empty it.</div>
{:else}
  <div class="bar-actions">
    <button class="btn danger" class:armed disabled={busy} onclick={clear}
            onblur={disarm} onmouseleave={() => armed && disarm()}>
      <Icon name="trash" size={13} />
      {armed ? `Delete ${list.length} files · ${mb(total)} — click to confirm` : 'Empty trash'}
      {#if armed}<span class="arm-rule"></span>{/if}
    </button>
    <span class="muted" style="font-size:13px">Everything else is reversible.</span>
  </div>

  <div class="trash-list">
    {#each list as t (t.id)}
      <div class="trash-row" class:filing={restoring[t.id]}>
        <span class="tr-t" title={t.title}>{t.title || t.id}</span>
        <span class="tr-a" title={t.artist}>{t.artist}</span>
        <span class="tr-when">{when(t.trashed_at)}</span>
        <span class="tr-size">{mb(t.bytes)}</span>
        <button class="btn ghost tr-put" onclick={() => restore(t)}>
          <Icon name="undo" size={13} /> Put back</button>
      </div>
    {/each}
  </div>
{/if}
