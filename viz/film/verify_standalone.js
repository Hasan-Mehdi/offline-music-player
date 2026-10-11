const puppeteer = require('puppeteer-core');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const url = 'file:///C:/Users/hasan/code/apps/offline-music-player/viz/film/embedding_space_film.html';
(async () => {
  const b = await puppeteer.launch({executablePath: EDGE, headless: 'new',
    args: ['--no-sandbox', '--allow-file-access-from-files']});
  const p = await b.newPage();
  await p.setViewport({width: 1920, height: 1080});
  let err = null; p.on('pageerror', e => err = e.message);
  await p.goto(url, {waitUntil: 'load'});
  const ok = await p.waitForFunction('window.__ready===true', {timeout: 20000}).then(() => true).catch(() => false);
  const info = await p.evaluate(() => ({ready: window.__ready,
    n: window.__FILM_DATA__ ? window.__FILM_DATA__.n : null,
    dur: window.__filmDuration, cues: (window.AUDIO_CUES || []).length}));
  await p.evaluate(t => window.__cap(t), 44);
  await p.screenshot({path: 'C:/Users/hasan/code/apps/offline-music-player/viz/film/preview/standalone_check.png'});
  console.log('pageerror:', err);
  console.log('ready:', ok, 'info:', JSON.stringify(info));
  await b.close();
})().catch(e => {console.error(e); process.exit(1);});
