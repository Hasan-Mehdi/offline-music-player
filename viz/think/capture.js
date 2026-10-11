// Headless-Edge harness for the "Watching it think" film.
// Reuses viz/film's puppeteer-core (no new node_modules).
//
//   node viz/think/capture.js preview [t1 t2 ...]   -> preview/*.png at key times
//   node viz/think/capture.js render  [fps]         -> frames/%05d.png + audio_cues.json
//   node viz/think/capture.js smoke                 -> load + controls + font check
const http = require('http');
const fs = require('fs');
const path = require('path');
const puppeteer = require(path.join(__dirname, '..', 'film', 'node_modules', 'puppeteer-core'));

const DIR = __dirname;
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const MIME = {'.html':'text/html','.json':'application/json','.js':'text/javascript',
  '.woff2':'font/woff2','.m4a':'audio/mp4','.png':'image/png','.jpg':'image/jpeg'};

function serve(){
  return new Promise(res=>{
    const s=http.createServer((req,rq)=>{
      let p=decodeURIComponent(req.url.split('?')[0]); if(p==='/')p='/think.html';
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
  const page_file=process.env.THINK_PAGE||'think.html';
  const srv=await serve();
  const port=srv.address().port;
  const browser=await puppeteer.launch({executablePath:EDGE,headless:'new',
    args:['--no-sandbox','--force-color-profile=srgb','--hide-scrollbars',
          '--autoplay-policy=no-user-gesture-required']});
  const page=await browser.newPage();
  await page.setViewport({width:1920,height:1080,deviceScaleFactor:1});
  const errs=[];
  page.on('pageerror',e=>{errs.push('PAGEERR: '+e.message);console.log('PAGEERR:',e.message);});
  page.on('console',m=>{if(m.type()==='error'){errs.push('CONSOLE: '+m.text());console.log('CONSOLE:',m.text());}});
  const q = mode==='smoke' ? '' : '?capture=1';
  await page.goto(`http://127.0.0.1:${port}/${page_file}${q}`,{waitUntil:'load'});
  await page.waitForFunction('window.__ready===true',{timeout:60000});
  await new Promise(r=>setTimeout(r,400));

  if(mode==='smoke'){
    const info=await page.evaluate(async()=>{
      const loaded=document.fonts.check('120px "Archivo Black"');
      const marks=window.__MARKS__?window.__MARKS__.length:null;
      // exercise the controls the way a person would
      document.getElementById('nb').click();
      const afterNext=document.getElementById('tc').textContent;
      document.getElementById('nb').click(); document.getElementById('nb').click();
      const beat=document.getElementById('beat').textContent;
      document.getElementById('pb').click();
      const afterPrev=document.getElementById('tc').textContent;
      document.getElementById('rp').click();
      await new Promise(r=>setTimeout(r,350));
      const playing=document.getElementById('pp').textContent.trim();
      document.getElementById('pp').click();
      // decode every music cue the way the play button does, and report what landed
      document.getElementById('playbtn').click();
      await new Promise(r=>setTimeout(r,2500));
      const dec=await Promise.all([...new Set(window.AUDIO_CUES.map(c=>c.id))].map(async id=>{
        try{
          const ac=new (window.AudioContext||window.webkitAudioContext)();
          const b=await (await fetch(window.__THINK_DATA__?
            window.__THINK_DATA__.media[id].clip:document.__m)).arrayBuffer();
          const buf=await ac.decodeAudioData(b); ac.close();
          return +buf.duration.toFixed(2);
        }catch(e){ return 'ERR '+e.message; }
      }));
      return {fontLoaded:loaded, dur:window.__filmDuration, cues:window.AUDIO_CUES.length,
              sfx:window.SFX_CUES.length, afterNext, afterPrev, beat, playing,
              marks:document.querySelectorAll('#marks i').length,
              clipSeconds:dec, standalone:!!window.__THINK_DATA__};
    });
    console.log(JSON.stringify(info,null,1));
    console.log(errs.length?('ERRORS:\n'+errs.join('\n')):'no console/page errors');
    await browser.close(); srv.close();
    process.exit(errs.length?1:0);
  }

  if(mode==='preview'){
    const out=path.join(DIR,'preview'); fs.mkdirSync(out,{recursive:true});
    let times=process.argv.slice(3).map(Number);
    if(!times.length){
      const marks=await page.evaluate(()=>window.__filmDuration);
      // the v3 beats: gap · retrieval · the three rows · each term · the reveal · the chain
      times=[2,6,10,13,15.5,17.5,19.5,22.2,24.8,26.5,29.8,31.2,33.5,37,40,43.5,46.5,50,
             52,54.5,57,60.5,62.5,65,68,71,75.6,78.6,80.4,82.5,86.5,90,92.5,97,
             104,110,118,125,137,142,147].filter(t=>t<marks);
    }
    for(const t of times){
      await page.evaluate(tt=>window.__cap(tt),t);
      await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>r())));
      const nm=path.join(out,`t${String(t.toFixed(1)).padStart(6,'0')}.png`);
      await page.screenshot({path:nm});
      console.log('  wrote',nm);
    }
  } else {
    const fps=Number(process.argv[3]||30);
    const dur=await page.evaluate(()=>window.__filmDuration);
    const N=Math.ceil(dur*fps);
    const out=path.join(DIR,'frames');
    fs.rmSync(out,{recursive:true,force:true}); fs.mkdirSync(out);
    console.log(`rendering ${N} frames @ ${fps}fps (${dur}s) ...`);
    const t0=Date.now();
    for(let f=0;f<N;f++){
      await page.evaluate(tt=>window.__cap(tt),f/fps);
      await page.screenshot({path:path.join(out,String(f).padStart(5,'0')+'.png')});
      if(f%120===0){const el=(Date.now()-t0)/1000;
        console.log(`  ${f}/${N}  ${(f/Math.max(el,0.001)).toFixed(1)} fps  ${el.toFixed(0)}s`);}
    }
    const cues=await page.evaluate(()=>({audio:window.AUDIO_CUES,sfx:window.SFX_CUES,
                                         dur:window.__filmDuration,fps:0}));
    cues.fps=fps;
    fs.writeFileSync(path.join(DIR,'audio_cues.json'),JSON.stringify(cues,null,1));
    console.log(`wrote audio_cues.json (${cues.audio.length} music cues, ${cues.sfx.length} sfx)`);
    if(errs.length){console.log('ERRORS during render:\n'+errs.join('\n'));}
  }
  await browser.close(); srv.close();
  console.log('done');
})().catch(e=>{console.error(e);process.exit(1);});
