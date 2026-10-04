// Real Gecko rendering with offline native/storage fixtures. This complements
// the installed toolbar-popup captures on Windows and both macOS architectures.
// Usage: node tests/test-popup-render.js [baseline-extension-dir] [output-dir]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {firefox} = require('playwright');
const {PNG} = require('pngjs');
const current = path.resolve(__dirname, '../extension');
const baseline = process.argv[2] ? path.resolve(process.argv[2]) : null;
const output = path.resolve(process.argv[3] || 'artifacts/popup-render');
const state = {
  active:null, queue_paused:true,
  queue:[
    {id:'q1', status:'queued', title:'Français, accents & « guillemets » <sans HTML>', mode:'1080', url:'https://youtube.com/watch?v=q1'},
    {id:'q2', status:'queued', title:null, metadata_status:'loading', mode:'audio', url:'https://soundcloud.com/artist/track', paused:true, playlist_position:2, playlist_total:12},
    {id:'q3', status:'queued', title:null, metadata_status:'error', metadata_error:'Erreur : "titre" <introuvable> & indisponible', mode:'best', url:'https://example.com/video'},
    {id:'q4', status:'queued', title:'Un titre particulièrement long pour vérifier le retour à la ligne et les ellipses', mode:'720', url:'https://twitch.tv/videos/42'}
  ],
  history:[
    {id:'h1',status:'finished',title:'Téléchargement terminé & déjà présent',mode:'1080',url:'https://vimeo.com/42',finished_at:1790985600,already_present:true},
    {id:'h2',status:'error',title:'Échec <à relancer>',mode:'audio',url:'https://instagram.com/reel/42',finished_at:1790985540,error:'Connexion interrompue',error_hint:'Vérifie la connexion Internet puis relance le téléchargement.'},
    {id:'h3',status:'cancelled',title:'Élément annulé',mode:'mp3',url:'https://x.com/user/status/42',finished_at:1790985480},
    {id:'h4',status:'finished',title:null,mode:'best',url:'https://bandcamp.com/track/42'}
  ]
};
const diagnostic = {
  ok:true, overall:'warning',
  dependencies:{required_missing:[],optional_missing:['mutagen'],items:[
    {id:'python',label:'Python',required:true,ok:true,version:'3.13.16'},
    {id:'yt_dlp',label:'yt-dlp',required:true,ok:true,version:'2026.10.01'},
    {id:'ffmpeg',label:'FFmpeg',required:true,ok:true,version:'9.0.2'},
    {id:'mutagen',label:'Mutagen',required:false,ok:false,error:'Module <absent> & "optionnel"'}
  ]},
  compatibility:{compatible:true,frontend_version:'8.37',backend_version:'8.31',frontend_protocol:1,backend_protocol:1},
  system:{destination:{writable:true,write_tested:true,free_bytes:5368709120},runtime_files:{ok:true},state_ok:true,
    migration:{status:'completed',legacy_found:true},cache:{total_bytes:8388608,logs_bytes:1048576,reclaimable_bytes:2097152,
      orphan_partials:{count:2,bytes:12345},log_max_file_bytes:2097152,log_max_archives:4}},
  updates_cached:{updates_available:1,risky_updates:1,items:[{id:'yt_dlp',update_available:true,available:'2026.10.02',potential_incompatibility:true}]}
};

async function loadPopup(browser, directory, language, viewport) {
  const page = await browser.newPage({viewport, locale:'fr-FR', timezoneId:'UTC'});
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.setContent(fs.readFileSync(path.join(directory,'popup.html'),'utf8').replace(/<script src="[^"]+"><\/script>/g,''));
  await page.evaluate(({language,diagnostic}) => {
    Math.random = () => 0.25;
    // Freeze trajectories at a reproducible instant, without changing the DOM.
    window.requestAnimationFrame = () => 1;
    window.cancelAnimationFrame = () => {};
    window.__state = {active:null,queue:[],history:[],queue_paused:true};
    window.__diagnostic = diagnostic;
    window.__diagnosticError = null;
    window.__calls = [];
    window.__opened = [];
    window.__store = {uiLanguage:language,selectedMode:'1080',pillStyle:'cat'};
    window.browser = {
      runtime:{getManifest:()=>({version:'8.37'}),getPlatformInfo:async()=>({os:'linux',arch:'x86-64'}),
        sendNativeMessage:async(_host,payload)=>{
          window.__calls.push(payload);
          if(payload.action==='status') return {ok:true,state:window.__state};
          if(payload.action==='compatibility') return {ok:true,compatibility:diagnostic.compatibility};
          if(payload.action==='diagnostics') {
            if(window.__diagnosticError) throw new Error(window.__diagnosticError);
            return window.__diagnostic;
          }
          if(payload.action==='youtube_auth_status') return {ok:true,configured:false,enabled:false,state:'missing'};
          return {ok:true};
        },
        sendMessage:async()=>({ok:true,settings:{output_dir:'/tmp/Kitty & médias'}})},
      storage:{local:{get:async keys=>{
        const list=typeof keys==='string'?[keys]:Array.isArray(keys)?keys:Object.keys(keys||{});
        return Object.fromEntries(list.filter(key=>key in window.__store).map(key=>[key,window.__store[key]]));
      },set:async values=>Object.assign(window.__store,values)}},
      tabs:{query:async()=>[{id:1,url:'https://example.com/video'}],sendMessage:async()=>({ok:false}),
        create:async data=>{window.__opened.push(data);return data;}}
    };
  },{language,diagnostic});
  for(const name of ['i18n.js','shared.js','backend-installer.js','popup.js']) {
    await page.addScriptTag({content:fs.readFileSync(path.join(directory,name),'utf8')});
  }
  await page.waitForFunction(()=>!document.documentElement.classList.contains('popup-loading'),null,{polling:25});
  await page.evaluate(()=>clearTimeout(popupPollTimer));
  await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important} progress:indeterminate::-moz-progress-bar{visibility:hidden!important}'});
  return {page,errors};
}

async function scenario(page, name) {
  await page.evaluate(async({name,state,diagnostic})=>{
    window.__state=structuredClone(state);
    if(name==='empty'||name.startsWith('settings')) window.__state={active:null,queue:[],history:[],queue_paused:true};
    if(name==='metadata'||name==='download') window.__state.active={id:'active-1',status:name==='metadata'?'metadata':'downloading',
      title:name==='metadata'?null:'Téléchargement actif & vidéo',url:'https://youtube.com/watch?v=active',mode:'1080',
      downloaded:name==='metadata'?null:4194304,total:8388608,speed:1048576,eta:4};
    render(window.__state);
    await setSectionOpen('queue',name==='queue',false);
    await setSectionOpen('history',name==='history',false);
    if(name==='metadata'||name==='download') applyBallTransform(0.5);
    if(name.startsWith('settings')) {
      showSettings();
      await restoreDiagnostics();
      const group=name.split('-')[1];
      if(group&&group!=='collapsed') await setSettingsSectionOpen(group,true,false);
      if(group==='pill') renderPillStyle(name.split('-')[2]||'cat');
      if(group==='dependencies'||group==='diagnostic') {
        const kind=name.split('-')[2];
        const response=structuredClone(diagnostic);
        if(kind==='empty') response.dependencies.items=[];
        if(kind==='ready') {response.overall='ready';response.dependencies.items=response.dependencies.items.filter(dep=>dep.ok);response.updates_cached=null;}
        if(kind==='error') {window.__diagnosticError='Erreur <native> & "indisponible"';await restoreDiagnostics().catch(()=>{});}
        else renderDiagnosticsHealth(response);
      }
    }
    if(name==='icons') {
      await setSectionOpen('queue',true,false);
      const urls=['youtube.com','soundcloud.com','tiktok.com','instagram.com','x.com','vimeo.com','twitch.tv','dailymotion.com',
        'pinterest.com','bandcamp.com','reddit.com','facebook.com','audiomack.com','audius.co','example.com'];
      renderQueue(urls.map((host,i)=>({id:'icon-'+i,status:'queued',title:host,mode:'audio',url:'https://'+host+'/media'})),null);
    }
    KittyI18n.apply();
  },{name,state,diagnostic});
  // Flush the translation observer and layout before measuring or capturing.
  await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,0)));
}

async function layout(page) {
  return page.evaluate(()=>[...document.body.querySelectorAll('*')].filter(el=>el.getClientRects().length).map(el=>{
    const r=el.getBoundingClientRect();
    return {tag:el.tagName,cls:el.getAttribute('class'),x:r.x,y:r.y,w:r.width,h:r.height,text:el.children.length?null:el.textContent};
  }));
}

function comparePixels(before,after) {
  const a=PNG.sync.read(before),b=PNG.sync.read(after);
  assert.equal(b.width,a.width);assert.equal(b.height,a.height);
  let different=0;
  for(let i=0;i<a.data.length;i+=4) {
    if(a.data[i]!==b.data[i]||a.data[i+1]!==b.data[i+1]||a.data[i+2]!==b.data[i+2]||a.data[i+3]!==b.data[i+3]) different++;
  }
  return different;
}

async function interactionAndSecurityChecks(page) {
  await scenario(page,'queue');
  await page.locator('#queue .sourceGlyph').first().click();
  assert.equal(await page.evaluate(()=>window.__opened[0].url),state.queue[0].url);
  await page.locator('#queue .queueControl').first().click();
  assert.ok(await page.evaluate(()=>window.__calls.some(call=>call.action==='toggle_queue_item_pause'&&call.job_id==='q1')));
  await page.locator('#queue .queueRemove').first().click();
  assert.ok(await page.evaluate(()=>window.__calls.some(call=>call.action==='remove_queued'&&call.job_id==='q1')));
  await page.evaluate(()=>setSectionOpen('history',true,false));
  await page.locator('#history .retryButton').click();
  assert.ok(await page.evaluate(()=>window.__calls.some(call=>call.action==='retry'&&call.job_id==='h2')));

  const result=await page.evaluate(async()=>{
    const payload='<img src=x onerror="window.__injected=true"><svg onload="window.__injected=true"> & "quotes"';
    const job={id:'untrusted',title:payload,url:'javascript:window.__injected=true',mode:payload,status:'queued'};
    renderQueue([job],null);
    renderHistory([{...job,status:'error',error:payload,error_hint:payload}]);
    const dep=dependencyItem('error',payload,payload,payload);
    dependencyListEl.replaceChildren(dep);
    const before=window.__opened.length;
    for(const url of ['javascript:alert(1)','data:text/html,<script>alert(1)</script>','file:///tmp/kitty','not a URL']) {
      const button=sourceButtonElement(url,{key:'web',label:payload});
      if(!button.disabled||button.dataset.openSource!=='') throw new Error('Unsafe source is enabled');
      await openSourceUrl(url);
    }
    const roots=[queueEl,historyEl,dependencyListEl];
    const safe=roots.every(root=>!root.querySelector('img,script,[onerror],[onload]'))
      &&queueEl.querySelector('.itemTitle').textContent===payload
      &&historyEl.querySelector('.itemError').textContent===payload
      &&dep.querySelector('.dependencyValue').title===payload
      &&window.__opened.length===before&&!window.__injected;
    const urls=['https://example.com/a?x="quoted"&y=%3Ctag%3E','http://example.com/video'];
    for(const url of urls) await openSourceUrl(url);
    const allowed=window.__opened.slice(before).map(item=>item.url);

    // Unchanged state must retain nodes, focus and an in-flight animation.
    const active={id:'stable',status:'downloading',title:'Active',url:urls[0],mode:'1080',downloaded:1,total:10};
    showCatGame(active);
    const cat=catGameEl.firstElementChild;
    const ball=catGameEl.querySelector('.catBall');
    showCatGame(active);
    const catsStable=cat===catGameEl.firstElementChild&&ball===catGameEl.querySelector('.catBall');
    renderActive(active);
    updateSourceHost(activeSourceEl,urls[0]);
    const source=activeSourceEl.firstElementChild;
    source.focus();
    updateSourceHost(activeSourceEl,urls[0]);
    const sourceStable=source===activeSourceEl.firstElementChild&&document.activeElement===source;
    const queueNode=queueEl.firstElementChild,historyNode=historyEl.firstElementChild;
    renderQueue([job],null);
    renderHistory([{...job,status:'error',error:payload,error_hint:payload}]);
    const rowsStable=queueNode===queueEl.firstElementChild&&historyNode===historyEl.firstElementChild;
    hideCatGame();
    const cleared=!catGameEl.children.length&&!catAnim.rafId;

    for(const language of ['en','fr','en','fr']) {
      KittyI18n.setLanguage(language);KittyI18n.apply();
      renderPillStyle('classic');
      if(pillStyleCurrentPreviewEl.querySelectorAll('span').length!==3) throw new Error('Classic preview structure changed');
    }
    const icon=KittyShared.sourceIconElement('constructor');
    const svgSafe=icon.namespaceURI==='http://www.w3.org/2000/svg'&&icon.children.length===2
      &&[...icon.children].every(shape=>shape.namespaceURI===icon.namespaceURI);
    return {safe,allowed,catsStable,sourceStable,rowsStable,cleared,svgSafe};
  });
  for(const key of ['safe','catsStable','sourceStable','rowsStable','cleared','svgSafe']) assert.equal(result[key],true,key);
  assert.deepEqual(result.allowed,['https://example.com/a?x=%22quoted%22&y=%3Ctag%3E','http://example.com/video']);
}

(async()=>{
  fs.mkdirSync(output,{recursive:true});
  // This offline fixture runs inside an already isolated CI/container sandbox.
  const browser=await firefox.launch({headless:true,env:{...process.env,
    MOZ_DISABLE_CONTENT_SANDBOX:'1',MOZ_DISABLE_RDD_SANDBOX:'1'}});
  const report={engine:'Firefox '+browser.version(),baseline,viewportSizes:[],comparisons:[],interactionAndSecurity:false,
    captureControls:'Animations frozen. Indeterminate progress mode is compared, then fixed at zero for pixel capture on both versions. Production CSS unchanged.'};
  try {
    const scenarios=['empty','queue','history','metadata','download','icons','settings-collapsed',
      'settings-dependencies-ready','settings-dependencies-warning','settings-dependencies-empty','settings-dependencies-error',
      'settings-diagnostic','settings-pill-minimal','settings-pill-cat','settings-pill-classic'];
    for(const height of [320,520,900]) {
      const viewport={width:410,height};report.viewportSizes.push(viewport);
      for(const language of ['fr','en']) for(const name of scenarios) {
        const after=await loadPopup(browser,current,language,viewport);
        let before;
        try {
          await scenario(after.page,name);
          const indeterminate=await after.page.evaluate(()=>!progressEl.hasAttribute('value'));
          if(indeterminate) await after.page.evaluate(()=>{progressEl.value=0;});
          const label=`${height}-${language}-${name}`;
          const screenshot=await after.page.screenshot({path:path.join(output,label+'-after.png')});
          let differingPixels=null;
          if(baseline) {
            before=await loadPopup(browser,baseline,language,viewport);
            await scenario(before.page,name);
            assert.equal(await before.page.evaluate(()=>!progressEl.hasAttribute('value')),indeterminate,label+' progress mode');
            if(indeterminate) await before.page.evaluate(()=>{progressEl.value=0;});
            assert.deepEqual(await layout(after.page),await layout(before.page),label+' layout');
            differingPixels=comparePixels(await before.page.screenshot({path:path.join(output,label+'-before.png')}),screenshot);
            assert.equal(differingPixels,0,label+' pixels');
            assert.deepEqual(before.errors,[]);
          }
          assert.deepEqual(after.errors,[]);
          report.comparisons.push({label,differingPixels});
        } finally {await after.page.close();if(before) await before.page.close();}
      }
      console.log(`Firefox ${height}px : 30 états FR/EN OK`);
    }
    const check=await loadPopup(browser,current,'fr',{width:410,height:900});
    try {await interactionAndSecurityChecks(check.page);assert.deepEqual(check.errors,[]);report.interactionAndSecurity=true;}
    finally {await check.page.close();}
    console.log('Boutons, URLs, textes non fiables, stabilité des nodes et SVG : OK');
  } catch(error) {report.error=String(error.stack||error);throw error;}
  finally {fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
