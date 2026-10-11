// Continuous-playback probe: seek to t0, play through t1, sample state every second.
const http=require('http'),fs=require('fs'),path=require('path');
const puppeteer=require(path.join(__dirname,'..','film','node_modules','puppeteer-core'));
const EDGE='C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const MIME={'.html':'text/html','.json':'application/json','.woff2':'font/woff2'};
const DIR=__dirname;
(async()=>{
  const t0=Number(process.argv[2]||55),t1=Number(process.argv[3]||80);
  const srv=await new Promise(res=>{const s=http.createServer((rq,rs)=>{
    let p=decodeURIComponent(rq.url.split('?')[0]);if(p==='/')p='/transit.html';
    const f=path.join(DIR,p);
    if(!fs.existsSync(f)){rs.writeHead(404);return rs.end();}
    rs.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream'});
    fs.createReadStream(f).pipe(rs);});s.listen(0,'127.0.0.1',()=>res(s));});
  const browser=await puppeteer.launch({executablePath:EDGE,headless:'new',
    args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
  const page=await browser.newPage();
  await page.setViewport({width:1920,height:1080});
  page.on('pageerror',e=>console.log('PAGEERR:',e.message));
  page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('404'))console.log('CONSOLE:',m.text());});
  await page.goto(`http://127.0.0.1:${srv.address().port}/transit.html`,{waitUntil:'load'});
  await page.waitForFunction('window.__ready===true',{timeout:30000});
  await page.click('#playbtn');
  await page.evaluate(t=>seek(t),t0);
  let last=-1,stuck=0;
  for(let i=0;i<(t1-t0)+3;i++){
    await new Promise(r=>setTimeout(r,1000));
    const s=await page.evaluate(()=>({cur:tOff+(t0===null?0:(performance.now()/1000-t0)),
      raf:rafId,playing:Object.keys(playing).length}));
    if(Math.abs(s.cur-last)<0.01){stuck++;console.log(`STUCK at ${s.cur.toFixed(1)}s`);if(stuck>2)break;}
    last=s.cur;
    if(i%5===0)console.log(`t=${s.cur.toFixed(1)} playing=${s.playing}`);
  }
  console.log('probe done');
  await browser.close();srv.close();
})().catch(e=>{console.error(e);process.exit(1);});
