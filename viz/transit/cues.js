// Dump the current AUDIO_CUES to audio_cues.json (for mux.py).
const http=require('http'),fs=require('fs'),path=require('path');
const puppeteer=require(path.join(__dirname,'..','film','node_modules','puppeteer-core'));
const EDGE='C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const DIR=__dirname;
(async()=>{
  const srv=await new Promise(res=>{const s=http.createServer((rq,rs)=>{
    let p=decodeURIComponent(rq.url.split('?')[0]);if(p==='/')p='/transit.html';
    const f=path.join(DIR,p);
    if(!fs.existsSync(f)){rs.writeHead(404);return rs.end();}
    rs.writeHead(200);fs.createReadStream(f).pipe(rs);});s.listen(0,'127.0.0.1',()=>res(s));});
  const browser=await puppeteer.launch({executablePath:EDGE,headless:'new',args:['--no-sandbox']});
  const page=await browser.newPage();
  await page.goto(`http://127.0.0.1:${srv.address().port}/transit.html?capture=1`,{waitUntil:'load'});
  await page.waitForFunction('window.__ready===true',{timeout:30000});
  const cues=await page.evaluate(()=>window.AUDIO_CUES);
  const dur=await page.evaluate(()=>window.__filmDuration);
  fs.writeFileSync(path.join(DIR,'audio_cues.json'),JSON.stringify({dur,cues},null,1));
  console.log('wrote audio_cues.json:',cues.length,'cues, dur',dur);
  await browser.close();srv.close();
})().catch(e=>{console.error(e);process.exit(1);});
