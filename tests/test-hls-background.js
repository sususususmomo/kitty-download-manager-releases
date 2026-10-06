const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
let listener,version='8.33';const calls=[];
const event=()=>({addListener:()=>{}}); let page='https://page.test/video',popup='moz-extension://kitty/popup.html';
const browser={runtime:{getManifest:()=>({version:'8.39'}),getURL:f=>'moz-extension://kitty/'+f,
 onMessage:{addListener:f=>{listener=f;}},sendMessage:async()=>{},
 sendNativeMessage:async(host,payload)=>{calls.push(payload);return payload.action==='compatibility' ? {ok:true,compatibility:{compatible:true,backend_version:version}}:{ok:true};}},
 tabs:{get:async id=>({id,url:page,title:'Fixture title'}),onRemoved:event(),onUpdated:event()},
 storage:{local:{get:async()=>({selectedMode:'720'})}},webRequest:Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(k=>[k,event()]))};
const ctx=vm.createContext({setTimeout:()=>1,URL,Date,location:{href:'moz-extension://kitty/background.html'},crypto:require('node:crypto').webcrypto,browser,console});
for(const f of ['shared.js','media-resolver.js','request-context.js','hls-detector.js','background.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),ctx);
vm.runInContext(`hlsStore.navigate(1,${JSON.stringify(page)});hlsStore.headers({tabId:1,requestId:'r',method:'GET',requestHeaders:[{name:'Referer',value:${JSON.stringify(page)}}]});hlsStore.response({tabId:1,requestId:'r',method:'GET',statusCode:200,url:'https://cdn.test/master.m3u8?token=FULL%2BVALUE&quality=original'});`,ctx);
(async()=>{
 const sender={url:popup};
 const list=await listener({type:'kitty-hls-list',tabId:1},sender);assert.equal(list.candidates.length,1);assert.equal(list.candidates[0].url,undefined);
 const id=list.candidates[0].id;
 await listener({type:'kitty-download-hls',tabId:1,candidateId:id,mode:'720'},sender);
 const explicit=calls.at(-1);assert.equal(explicit.action,'download');assert.equal(explicit.url,'https://cdn.test/master.m3u8?token=FULL%2BVALUE&quality=original');assert.equal(explicit.media_source.headers.Referer,page);
 await listener({type:'kitty-download-page',tabId:1,url:page,mode:'720'},sender);assert.equal(calls.at(-1).hls_fallbacks.length,1);
 await listener({type:'kitty-download-page',tabId:1,url:'https://elsewhere.test/unrelated',mode:'720'},sender);assert.equal(calls.at(-1).hls_fallbacks,undefined);
 const before=calls.length;const denied=await listener({type:'kitty-download-hls',tabId:1,candidateId:id},{url:page,tab:{id:1}});assert.equal(denied.ok,false);assert.equal(calls.length,before);
 version='8.32';vm.runInContext('compatibilityCache=null',ctx);const old=await listener({type:'kitty-download-hls',tabId:1,candidateId:id},sender);assert.equal(old.code,'hls_backend_update_required');
 version='8.33';const upgraded=await listener({type:'kitty-download-hls',tabId:1,candidateId:id},sender);assert.equal(upgraded.ok,true);
 version='8.36';vm.runInContext('compatibilityCache=null',ctx);
 await listener({type:'kitty-download-page',tabId:1,url:page,mode:'1080'},sender);
 const automatic=calls.at(-1);assert.equal(automatic.automatic,true);assert.equal(automatic.media_fallbacks.length,1);assert.equal(automatic.media_fallbacks[0].url,explicit.url);
 const modern=await listener({type:'kitty-media-list',tabId:1},sender);assert.equal(modern.automatic_available,true);
 await listener({type:'kitty-download-hls',tabId:1,candidateId:id,mode:'720'},sender);assert.equal(calls.at(-1).automatic,undefined);
 await listener({type:'kitty-download-page',tabId:1,url:'https://elsewhere.test/unrelated',mode:'720'},sender);assert.equal(calls.at(-1).media_fallbacks,undefined);
 page='https://www.reddit.com/r/videos/comments/abc123/video_title/?share_id=tracking';
 vm.runInContext(`hlsStore.navigate(1,${JSON.stringify(page)});hlsStore.response({tabId:1,requestId:'mp4',method:'GET',statusCode:206,url:'https://v.redd.it/id/DASH_1080.mp4?token=FULL',responseHeaders:[{name:'Content-Type',value:'video/mp4'},{name:'Content-Range',value:'bytes 0-999/999999'}]});`,ctx);
 const detected=await listener({type:'kitty-media-list',tabId:1},sender);assert.equal(detected.candidates[0].type,'direct_video');
 await listener({type:'kitty-download-page',tabId:1,url:'https://www.reddit.com/comments/abc123',mode:'1080'},sender);
 const reddit=calls.at(-1);assert.equal(reddit.media_fallbacks?.length,1,'Canonical Reddit page must retain its detected direct MP4');
 assert.equal(reddit.url,page);assert.equal(reddit.media_fallbacks[0].url,'https://v.redd.it/id/DASH_1080.mp4?token=FULL');
 await listener({type:'kitty-download-page',tabId:1,url:'https://www.reddit.com/comments/OTHER',mode:'1080'},sender);assert.equal(calls.at(-1).media_fallbacks,undefined);
 for(const [url,mime,kind,mode] of [['https://cdn.test/movie.webm','video/webm','direct_video','1080'],['https://cdn.test/get?id=123','video/mp4','direct_video','1080'],['https://cdn.test/track','audio/mp4','direct_audio','audio'],['https://cdn.test/master.m3u8','application/vnd.apple.mpegurl','hls','1080'],['https://cdn.test/manifest.mpd','application/dash+xml','dash','1080']]){
  vm.runInContext(`hlsStore.clear(1);hlsStore.navigate(1,${JSON.stringify(page)});hlsStore.response({tabId:1,requestId:'canonical',method:'GET',statusCode:200,url:${JSON.stringify(url)},responseHeaders:[{name:'Content-Type',value:${JSON.stringify(mime)}}]});`,ctx);
  await listener({type:'kitty-download-page',tabId:1,url:'https://www.reddit.com/comments/abc123',mode},sender);
  assert.equal(calls.at(-1).media_fallbacks[0].type,kind);assert.equal(calls.at(-1).url,page);
 }
 page='https://www.reddit.com/r/videos/';
 vm.runInContext(`hlsStore.clear(1);hlsStore.navigate(1,${JSON.stringify(page)});hlsStore.response({tabId:1,requestId:'feed',method:'GET',statusCode:200,url:'https://cdn.test/feed.mp4'});`,ctx);
 await listener({type:'kitty-download-page',tabId:1,url:'https://www.reddit.com/comments/abc123',mode:'1080'},sender);assert.equal(calls.at(-1).media_fallbacks,undefined,'A feed is not proof of a relationship to one post');
 console.log('PASS HLS background: trusted popup, private catalogue, complete signed URL/headers, same-page fallback, unrelated link unchanged, backend version guard, automatic routing and explicit override.');
})().catch(e=>{console.error(e);process.exitCode=1;});
