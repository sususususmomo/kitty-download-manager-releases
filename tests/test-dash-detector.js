const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const events={},calls=[],messages=[],logs=[];let receiver,version='8.34',now=Date.now();
const event=name=>({addListener:f=>events[name]=f});
const page='https://page.test/player',popup='moz-extension://kitty/popup.html';
const browser={runtime:{getManifest:()=>({version:'8.40'}),getURL:f=>'moz-extension://kitty/'+f,
 onMessage:{addListener:f=>receiver=f},sendMessage:async m=>messages.push(m),
 sendNativeMessage:async(host,p)=>{calls.push(p);return p.action==='compatibility'?{ok:true,compatibility:{compatible:true,backend_version:version}}:{ok:true}}},
 tabs:{get:async id=>({id,url:page,title:'Video title'}),onRemoved:event('remove'),onUpdated:event('navigate')},
 storage:{local:{get:async()=>({selectedMode:'720'})}},
 webRequest:Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(k=>[k,event(k)]))};
const ctx=vm.createContext({setTimeout:()=>1,URL,Date,location:{href:'moz-extension://kitty/background.html'},crypto:require('node:crypto').webcrypto,browser,console:{debug:(...a)=>logs.push(a)}});
for(const f of ['shared.js','media-resolver.js','request-context.js','hls-detector.js','background.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),ctx);
const media=ctx.KittyMedia;assert.equal(media,ctx.KittyHls);
for(const name of ['manifest.mpd','index.mpd','master.mpd?token=full'])assert.equal(media.manifestType('https://cdn.test/'+name),'dash');
assert.equal(media.manifestType('https://cdn.test/play','application/dash+xml; charset=utf-8'),'dash');
for(const name of ['chunk.m4s','init.mp4','audio.m4a','video.cmfv','audio.cmfa'])assert.equal(media.manifestType('https://cdn.test/'+name,'application/dash+xml'),null);
async function observe(url,mime='application/dash+xml',id='request'){
 const d={tabId:1,requestId:id,method:'GET',type:'xmlhttprequest',statusCode:200,url,
  requestHeaders:[{name:'Referer',value:page},{name:'Origin',value:'https://page.test'},{name:'Cookie',value:'PRIVATE'}],
  responseHeaders:[{name:'Content-Type',value:mime}]};
 events.onBeforeSendHeaders(d);await events.onHeadersReceived(d);events.onCompleted(d);
}
(async()=>{
 await observe('https://cdn.test/manifest.mpd?token=FIRST&quality=1080');
 for(let i=0;i<100;i++)await observe('https://cdn.test/manifest.mpd?token=LATEST&quality=1080');
 for(let i=0;i<100;i++)await observe('https://cdn.test/chunk-'+i+'.m4s','video/mp4');
 assert.equal(messages.length,1,'Repeated manifests/fragments must not trigger a refresh loop');
 assert.equal(logs.length,1);assert.ok(!JSON.stringify(logs).includes('LATEST'));
 const sender={url:popup};let list=await receiver({type:'kitty-media-list',tabId:1},sender);
 assert.equal(list.candidates.length,1);assert.equal(list.candidates[0].type,'dash');assert.equal(list.candidates[0].url,undefined);
 const id=list.candidates[0].id;
 await receiver({type:'kitty-probe-media',tabId:1,candidateId:id},sender);assert.equal(calls.at(-1).action,'media_probe');
 await receiver({type:'kitty-download-media',tabId:1,candidateId:id,mode:'720'},sender);
 assert.equal(calls.at(-1).media_source.url,'https://cdn.test/manifest.mpd?token=LATEST&quality=1080');
 assert.equal(calls.at(-1).media_source.headers.Referer,page);assert.equal(calls.at(-1).media_source.headers.Cookie,undefined);
 await receiver({type:'kitty-download-page',tabId:1,url:page},sender);assert.equal(calls.at(-1).media_fallbacks[0].type,'dash');
 version='8.33';vm.runInContext('compatibilityCache=null',ctx);
 const old=await receiver({type:'kitty-download-media',tabId:1,candidateId:id},sender);assert.equal(old.code,'dash_backend_update_required');
 await receiver({type:'kitty-download-page',tabId:1,url:page},sender);assert.equal(calls.at(-1).media_fallbacks,undefined);assert.equal(calls.at(-1).hls_fallbacks,undefined);
 version='8.34';const upgraded=await receiver({type:'kitty-download-media',tabId:1,candidateId:id},sender);assert.equal(upgraded.ok,true);
 const before=calls.length;assert.equal((await receiver({type:'kitty-probe-media',tabId:1,candidateId:id},{url:page})).ok,false);assert.equal(calls.length,before);
 await observe('https://cdn.test/manifest.mpd?token=LATEST&quality=720');await observe('https://cdn.test/play');
 list=await receiver({type:'kitty-media-list',tabId:1},sender);assert.equal(list.candidates.length,3);
 events.remove(1);assert.equal((await receiver({type:'kitty-media-list',tabId:1},sender)).candidates.length,0);
 console.log('PASS DASH shared detector/background: MPD/MIME, exact tokens, headers, 100 repeats + 100 fragments, one debug/notification, quality separation, trusted UI, backend upgrade and tab cleanup.');
})().catch(e=>{console.error(e);process.exitCode=1});
