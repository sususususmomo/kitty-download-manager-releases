const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const events={},calls=[],messages=[],logs=[];let receiver,version='8.35',now=1000000;
const event=name=>({addListener:f=>events[name]=f});
const page='https://page.test/player',popup='moz-extension://kitty/popup.html';
const browser={runtime:{getManifest:()=>({version:'8.41'}),getURL:f=>'moz-extension://kitty/'+f,
 onMessage:{addListener:f=>receiver=f},sendMessage:async m=>messages.push(m),
 sendNativeMessage:async(host,p)=>{calls.push(p);return p.action==='compatibility'?{ok:true,compatibility:{compatible:true,backend_version:version}}:{ok:true}}},
 tabs:{get:async id=>({id,url:page,title:'A readable page title'}),onRemoved:event('remove'),onUpdated:event('navigate')},
 storage:{local:{get:async()=>({selectedMode:'720'})}},
 webRequest:Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(k=>[k,event(k)]))};
const ctx=vm.createContext({setTimeout:()=>1,URL,Date,location:{href:'moz-extension://kitty/background.html'},crypto:require('node:crypto').webcrypto,browser,console:{debug:(...a)=>logs.push(a)}});
for(const f of ['shared.js','media-resolver.js','request-context.js','hls-detector.js','background.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),ctx);
const media=ctx.KittyMedia;
function details(url,mime='video/mp4',extra={}) { return {tabId:1,requestId:'request',method:'GET',type:'media',statusCode:200,url,
 requestHeaders:[{name:'Referer',value:page},{name:'Origin',value:'https://page.test'},{name:'User-Agent',value:'Firefox QA'},{name:'Range',value:'bytes=0-1023'},{name:'Cookie',value:'PRIVATE'}],
 responseHeaders:[{name:'Content-Type',value:mime},{name:'Content-Length',value:'3000000'}],...extra}; }
async function observe(d){events.onBeforeSendHeaders(d);await events.onHeadersReceived(d);events.onCompleted(d);}
function direct(store,url,mime,extra={}){const d=details(url,mime,extra);store.headers(d);return store.response(d);}
(async()=>{
 const store=new media.Store(()=>now);store.navigate(1,page);
 for(const [url,mime,kind] of [['movie.mp4','video/mp4','direct_video'],['movie.webm','video/webm','direct_video'],['opaque','video/quicktime','direct_video'],['track.mp3','audio/mpeg','direct_audio'],['track.m4a','','direct_audio'],['movie.mkv','application/octet-stream','direct_video'],['track.wav','audio/wav','direct_audio']])assert.equal(media.mediaType('https://cdn.test/'+url,mime),kind);
 for(const [url,mime] of [['blob:https://page.test/abc','video/mp4'],['https://cdn.test/image.mp4','image/png'],['https://cdn.test/init.mp4','video/mp4'],['https://cdn.test/seg-002.mp4','video/mp4'],['https://cdn.test/x.ts','video/mp2t'],['https://cdn.test/x.m4s','video/mp4']])assert.equal(media.mediaType(url,mime),null);
 for(let i=0;i<30;i++)await observe(details('https://cdn.test/movie.mp4?token=LATEST&cdn=keep',''));
 // A short Content-Length on 206 describes a slice, never the whole video.
 for(let i=0;i<100;i++)await observe(details('https://cdn.test/movie.mp4?token='+i+'&cdn=keep','video/mp4',{statusCode:206,responseHeaders:[{name:'Content-Type',value:'video/mp4'},{name:'Content-Length',value:'1024'},{name:'Content-Range',value:'bytes '+i+'-'+(i+1023)+'/3000000'}]}));
 assert.equal(logs.length,1);assert.equal(messages.length,1);
 let result=await receiver({type:'kitty-media-list',tabId:1},{url:popup});assert.equal(result.candidates.length,1);assert.equal(result.candidates[0].metadata.size,3000000);assert.equal(result.candidates[0].url,undefined);
 await receiver({type:'kitty-download-media',tabId:1,candidateId:result.candidates[0].id},{url:popup});const source=calls.at(-1).media_source;
 assert.ok(source.url.endsWith('token=99&cdn=keep'));assert.equal(source.headers.Range,undefined);assert.equal(source.headers.Cookie,undefined);assert.equal(source.headers.Referer,page);assert.equal(source.title,'A readable page title');
 assert.ok(!JSON.stringify(logs).includes('token='));
 await observe(details('https://cdn.test/track.mp3','audio/mpeg'));
 await receiver({type:'kitty-download-page',tabId:1,url:page,mode:'720'},{url:popup});
 assert.ok(calls.at(-1).media_fallbacks.every(c=>c.type!=='direct_audio'));
 await receiver({type:'kitty-download-page',tabId:1,url:page,mode:'audio'},{url:popup});
 assert.ok(calls.at(-1).media_fallbacks.some(c=>c.type==='direct_audio'));
 await receiver({type:'kitty-download-page',tabId:1,url:page,mode:'image'},{url:popup});
 assert.equal(calls.at(-1).media_fallbacks,undefined);
 await receiver({type:'kitty-download-page',tabId:1,url:'https://other.test/linked-video',mode:'720'},{url:popup});
 assert.equal(calls.at(-1).media_fallbacks,undefined);
 for(const name of ['spinner.mp4','icon.webm','preview.mp4'])assert.equal(direct(store,'https://cdn.test/'+name,'video/mp4',{responseHeaders:[{name:'Content-Type',value:'video/mp4'},{name:'Content-Length',value:'9000'}]}),null);
 assert.ok(direct(store,'https://cdn.test/short-but-real.mp4','video/mp4',{responseHeaders:[{name:'Content-Type',value:'video/mp4'},{name:'Content-Length',value:'9000'}]}));
 const unknown=direct(store,'https://cdn.test/stream','video/webm',{statusCode:206,responseHeaders:[{name:'Content-Type',value:'video/webm'},{name:'Content-Length',value:'1000'},{name:'Content-Range',value:'bytes 0-999/*'}]});assert.equal(unknown.metadata.size,undefined);
 for(const h of [360,720,1080])direct(store,'https://cdn.test/film_'+h+'p.mp4?token=secret','video/mp4');
 const grouped=store.list(1).find(c=>c.url.includes('film_'));assert.equal(grouped.variants.length,3);assert.match(grouped.url,/1080p/);assert.equal(grouped.metadata.height,1080);
 direct(store,'https://cdn.test/resource?quality=720&id=one','video/mp4');direct(store,'https://cdn.test/resource?quality=1080&id=two','video/mp4');assert.equal(store.list(1).filter(c=>c.url.includes('resource?')).length,2);
 direct(store,'https://cdn.test/master.m3u8','application/vnd.apple.mpegurl');direct(store,'https://cdn.test/manifest.mpd','application/dash+xml');assert.equal(store.list(1).at(-1).type,'direct_video');assert.ok(['hls','dash'].includes(store.list(1)[0].type));
 version='8.34';vm.runInContext('compatibilityCache=null',ctx);const refused=await receiver({type:'kitty-download-media',tabId:1,candidateId:result.candidates[0].id},{url:popup});assert.equal(refused.code,'direct_video_backend_update_required');
 await receiver({type:'kitty-download-page',tabId:1,url:page},{url:popup});assert.equal(calls.at(-1).media_fallbacks,undefined);
 const before=calls.length;assert.equal((await receiver({type:'kitty-probe-media',tabId:1,candidateId:result.candidates[0].id},{url:page})).ok,false);assert.equal(calls.length,before);
 events.remove(1);await receiver({type:'kitty-media-context',hasBlob:true},{tab:{id:1,url:page},url:page,frameId:0});result=await receiver({type:'kitty-media-list',tabId:1},{url:popup});assert.equal(result.blob_unavailable,true);assert.equal(result.candidates.length,0);
 store.navigate(1,page+'/new');assert.equal(store.list(1).length,0);assert.equal(store.tabs.get(1).hasBlob,undefined);
 direct(store,'https://cdn.test/new.mp4','video/mp4');now+=16*60*1000;assert.equal(store.list(1).length,0);
 // Exercise the actual pill matching function, including explicit network sources.
 const pill=fs.readFileSync(path.join(__dirname,'../extension/content-pill.js'),'utf8');
 const adopt=pill.slice(pill.indexOf('  function adoptMatchingJob('),pill.indexOf('  async function refreshStatus('));
 const pctx=vm.createContext({resolveMediaUrlForPage:()=>({ok:true,url:page}),comparableMediaUrl:url=>url});vm.runInContext('let trackedJobId=null;'+adopt+';adoptMatchingJob({active:{id:"direct-job",url:"https://cdn.test/movie.mp4",media_source:{page_url:"'+page+'"}}});globalThis.found=trackedJobId;',pctx);assert.equal(pctx.found,'direct-job');
 console.log('PASS direct detector: MIME/extensions, 100 ranges → one candidate/notification/log, signed URL and headers, conservative quality groups, fragment/UI exclusions, blob limitation, TTL/tabs, compatibility and pill source page.');
})().catch(e=>{console.error(e);process.exitCode=1});
