<script>
  // Inline SVG icon set (Lucide-style, currentColor). No emoji anywhere in the UI.
  let { name, size = 20, fill = false } = $props()
  const P = {
    play: '<polygon points="6 4 20 12 6 20 6 4"/>',
    pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    prev: '<polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/>',
    next: '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/>',
    shuffle: '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.4 0 2.8.9 3.5 2.1l.6.9"/><path d="M22 18h-2.1c-1.4 0-2.8-.9-3.5-2.1l-.6-.9"/><path d="m18 14 4 4-4 4"/>',
    repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    repeatOne: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v4" stroke-width="2.2"/>',
    volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
    mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" y1="9" x2="16" y2="15"/><line x1="16" y1="9" x2="22" y2="15"/>',
    queue: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    up: '<path d="M7 10v11"/><path d="M15 5.9 14 10h5.4a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 18 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h3l4.8-8.2A2.6 2.6 0 0 1 15 5.9Z"/>',
    down: '<path d="M17 14V3"/><path d="M9 18.1 10 14H4.6a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 6 2h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-3l-4.8 8.2A2.6 2.6 0 0 1 9 18.1Z"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    home: '<path d="M3 9.5 12 3l9 6.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.2"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M6 11a6 6 0 0 0 12 0"/><line x1="12" y1="17" x2="12" y2="21"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    'down-chevron': '<polyline points="6 9 12 15 18 9"/>',
    close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    trash: '<path d="M3 6h18"/><path d="M9 6V4h6v2"/><path d="M18 6 17 20a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L6 6"/>',
    undo: '<path d="M3 8h11a6 6 0 0 1 0 12H8"/><polyline points="7 4 3 8 7 12"/>',
    clock: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>',
  }
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"
     fill={fill ? 'currentColor' : 'none'} stroke={fill ? 'none' : 'currentColor'}
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  {@html P[name] || ''}
</svg>

<style>
  .icon { display: block; flex: none; }
</style>
