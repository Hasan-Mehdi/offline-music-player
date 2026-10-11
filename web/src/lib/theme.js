// Auto theme: dark when the OS asks for it OR during evening/night hours
// (19:00–07:00). Re-checked every minute so the flip happens on its own —
// no toggle to remember on the handheld.
const mq = window.matchMedia('(prefers-color-scheme: dark)')
const evening = () => { const h = new Date().getHours(); return h >= 19 || h < 7 }

function apply() {
  const dark = mq.matches || evening()
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  document.querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', dark ? '#141414' : '#f4f4f0')
}

apply()
mq.addEventListener('change', apply)
setInterval(apply, 60_000)
