// Runtime smoke test: click play, let it run, verify clock + audio decode + no errors.
const http=require('http'),fs=require('fs'),path=require('path');
const puppeteer=require(path.join(__dirname,'..','film','node_modules','puppeteer-core'));
const EDGE='C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const MIME={'.html':'text/html','.json':'application/json','.woff2':'font/woff2'};
const DIR=__dirname;
(async()=>{
  const target=process.argv[2]||'transit.html';
  const srv=await new Promise(res=>{const s=http.createServer((rq,rs)=>{
    let p=decodeURIComponent(rq.url.split('?')[0]);if(p==='/')p='/'+target;
    const f=path.join(DIR,p);
    if(!fs.existsSync(f)){rs.writeHead(404);return rs.end();}
    rs.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream'});
    fs.createReadStream(f).pipe(rs);});s.listen(0,'127.0.0.1',()=>res(s));});
  const browser=await puppeteer.launch({executablePath:EDGE,headless:'new',
    args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
  const page=await browser.newPage();
  await page.setViewport({width:1920,height:1080});
  const errs=[];
  page.on('pageerror',e=>errs.push('PAGEERR: '+e.message));
  page.on('console',m=>{if(m.type()==='error')errs.push('CONSOLE: '+m.text());});
  await page.goto(`http://127.0.0.1:${srv.address().port}/${target}`,{waitUntil:'load'});
  await page.waitForFunction('window.__ready===true',{timeout:30000});
  await page.click('#playbtn');
  await new Promise(r=>setTimeout(r,4000));
  const state=await page.evaluate(()=>({
    t:(performance.now()/1000),cur:document.getElementById('tc').textContent,
    buffers:Object.keys(buffers).length,heroes:heroes.length,
    playing:Object.keys(playing).length,cues:AUDIO_CUES.length,ac:AC?AC.state:'none'}));
  console.log(JSON.stringify(state));
  // seek into the departures board and night bus, let each run a beat
  for(const tt of [60,80,104]){
    await page.evaluate(t=>{seek(t);},tt);
    await new Promise(r=>setTimeout(r,1500));
    const s=await page.evaluate(()=>({cur:document.getElementById('tc').textContent,
      playing:Object.keys(playing).length}));
    console.log(tt,JSON.stringify(s));
  }
  console.log(errs.length?errs.join('\n'):'NO ERRORS');
  await browser.close();srv.close();
})().catch(e=>{console.error(e);process.exit(1);});
