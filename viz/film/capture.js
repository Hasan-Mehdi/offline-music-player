// Headless-Edge harness for the embedding film.
//   node capture.js preview [t1 t2 ...]   -> screenshots at key times -> preview/*.png
//   node capture.js render  [fps]         -> every frame -> frames/%05d.png
// Deterministic: drives window.__cap(t) (frame-driven clock), sequential for trails.
const http = require('http');
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const DIR = __dirname;
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const MIME = {'.html':'text/html','.json':'application/json','.js':'text/javascript',
  '.woff2':'font/woff2','.m4a':'audio/mp4','.png':'image/png','.jpg':'image/jpeg'};

function serve(){
  return new Promise(res=>{
    const s=http.createServer((req,rq)=>{
      let p=decodeURIComponent(req.url.split('?')[0]); if(p==='/')p='/film.html';
      const f=path.join(DIR,p);
      if(!f.startsWith(DIR)||!fs.existsSync(f)){rq.writeHead(404);return rq.end();}
      rq.writeHead(200,{'Content-Type':MIME[path.extname(f)]||'application/octet-stream'});
      fs.createReadStream(f).pipe(rq);
    });
    s.listen(0,'127.0.0.1',()=>res(s));
  });
}

(async()=>{
  const mode=process.argv[2]||'preview';
  const srv=await serve();
  const port=srv.address().port;
  const browser=await puppeteer.launch({executablePath:EDGE,headless:'new',
    args:['--no-sandbox','--force-color-profile=srgb','--hide-scrollbars']});
  const page=await browser.newPage();
  await page.setViewport({width:1920,height:1080,deviceScaleFactor:1});
  page.on('pageerror',e=>console.log('PAGEERR:',e.message));
  page.on('console',m=>{ if(m.type()==='error')console.log('CONSOLE:',m.text()); });
  await page.goto(`http://127.0.0.1:${port}/film.html?capture=1`,{waitUntil:'load'});
  await page.waitForFunction('window.__ready===true',{timeout:30000});
  await new Promise(r=>setTimeout(r,300));

  if(mode==='cues'){
    const cues=await page.evaluate(()=>window.AUDIO_CUES);
    const dur=await page.evaluate(()=>window.__filmDuration);
    fs.writeFileSync(path.join(DIR,'audio_cues.json'),JSON.stringify({dur,cues},null,1));
    console.log('wrote audio_cues.json:',cues.length,'cues, dur',dur);
  } else if(mode==='preview'){
    const out=path.join(DIR,'preview'); fs.mkdirSync(out,{recursive:true});
    let times=process.argv.slice(3).map(Number);
    if(!times.length) times=[3.5,6,10,15,22,30,37,42,47,55,62,66,74,82,92,97];
    for(const t of times){
      await page.evaluate(()=>window.__clear&&window.__clear());
      await page.evaluate(tt=>window.__cap(tt),t);
      await page.evaluate(tt=>window.__cap(tt),t); // 2nd pass so trail-based scenes read in a still
      await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>r())));
      const nm=path.join(out,`t${String(t).padStart(5,'0')}.png`);
      await page.screenshot({path:nm});
      console.log('  wrote',nm);
    }
  } else {
    const fps=Number(process.argv[3]||30);
    const dur=await page.evaluate(()=>window.__filmDuration);
    const N=Math.ceil(dur*fps);
    const out=path.join(DIR,'frames'); fs.rmSync(out,{recursive:true,force:true}); fs.mkdirSync(out);
    console.log(`rendering ${N} frames @ ${fps}fps ...`);
    const t0=Date.now();
    for(let f=0;f<N;f++){
      await page.evaluate(tt=>window.__cap(tt),f/fps);
      await page.screenshot({path:path.join(out,String(f).padStart(5,'0')+'.png')});
      if(f%60===0){const el=(Date.now()-t0)/1000; console.log(`  ${f}/${N}  ${(f/Math.max(el,1)).toFixed(1)} fps  ${el.toFixed(0)}s`);}
    }
    // dump audio cue list for the muxer
    const cues=await page.evaluate(()=>window.AUDIO_CUES);
    fs.writeFileSync(path.join(DIR,'audio_cues.json'),JSON.stringify(cues,null,1));
    console.log('wrote audio_cues.json ('+cues.length+' cues)');
  }
  await browser.close(); srv.close();
  console.log('done');
})().catch(e=>{console.error(e);process.exit(1);});
