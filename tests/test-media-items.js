/* Catalogue grouping, scope, privacy and batch routing with real background code. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
let listener;const calls=[],event=()=>({addListener:()=>{}}),page='https://commons.wikimedia.org/wiki/Gallery';
const browser={runtime:{getManifest:()=>({version:'8.49'}),getURL:p=>'moz-extension://kitty/'+p,onMessage:{addListener:f=>listener=f},sendMessage:async()=>{},
 sendNativeMessage:async(h,p)=>{calls.push(p);return p.action==='compatibility'?{ok:true,compatibility:{compatible:true,backend_version:'8.39'}}:{ok:true,job_id:'queued-'+calls.length};}},
 tabs:{get:async id=>({id,url:page,title:'Gallery'}),onRemoved:event(),onUpdated:event()},storage:{local:{get:async()=>({})}},
 webRequest:Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(k=>[k,event()]))};
const ctx=vm.createContext({setTimeout:()=>1,URL,Date,crypto:require('node:crypto').webcrypto,console,browser,location:{href:'moz-extension://kitty/background.html'}});
for(const f of ['shared.js','media-resolver.js','hls-parser.js','request-context.js','hls-detector.js','media-items.js','background.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),ctx);
const dom=(id,urls,title=id,extra={})=>({domId:id,title,titleSource:'caption',thumbnail:'https://cdn.test/'+id+'.jpg',mediaKind:'video',sources:urls.map(url=>({url,contentType:'video/mp4'})),...extra});
(async()=>{
 assert.equal(vm.runInContext("KittyShared.supportsMediaItems({compatible:true,backend_version:'8.38'})",ctx),false);
 assert.equal(vm.runInContext("KittyShared.supportsMediaItems({compatible:true,backend_version:'8.39'})",ctx),true);
 const sender={tab:{id:1,url:page},url:page,frameId:0},ui={url:'moz-extension://kitty/popup.html'};
 listener({type:'kitty-media-dom',items:[dom('a',['https://cdn.test/a.mp4?token=secret','https://cdn.test/a.webm']),dom('b',['https://cdn.test/b.mp4'])]},sender);
 vm.runInContext(`hlsStore.navigate(1,${JSON.stringify(page)});hlsStore.response({tabId:1,frameId:0,method:'GET',statusCode:206,url:'https://cdn.test/a.mp4?token=secret',responseHeaders:[{name:'Content-Type',value:'video/mp4'},{name:'Content-Range',value:'bytes 0-999/1000000'}]});`,ctx);
 const list=await listener({type:'kitty-media-items',tabId:1},ui);assert.equal(list.items.length,2);assert.equal(list.items[0].candidates.filter(c=>c.type==='direct_video').length,2);
 assert.ok(!JSON.stringify(list).includes('secret'));assert.ok(!JSON.stringify(list).includes('cdn.test/a.mp4'));
 assert.equal((await listener({type:'kitty-download-item',tabId:1,itemId:list.items[0].id},sender)).ok,false);
 const result=await listener({type:'kitty-download-items',tabId:1,itemIds:list.items.map(i=>i.id),mode:'1080'},ui);
 assert.equal(result.added,2);const payloads=calls.filter(c=>c.action==='download');assert.equal(payloads.length,2);
 assert.equal(payloads[0].media_item.title,'a');assert.equal(payloads[0].media_item.explicit_sources,true);assert.equal(payloads[1].media_item.title,'b');assert.notEqual(payloads[0].url,payloads[1].url);
 assert.ok(payloads[0].media_fallbacks.every(c=>!c.url.includes('/b.mp4')));assert.ok(payloads[1].media_fallbacks.every(c=>!c.url.includes('/a.')));
 assert.ok(payloads.every(p=>p.media_fallbacks.every(c=>c.media_item_id===p.media_item.id)));
 assert.ok(payloads.flatMap(p=>p.media_fallbacks).every(c=>Object.values(c.metadata||{}).every(v=>v!==null)), 'Unknown height must be omitted from validated native metadata');
 assert.equal(payloads[0].media_fallbacks[0].url,'https://cdn.test/a.mp4?token=secret');
 // Same video/source/network represented once; separate frame blob not crossed.
 const s=vm.runInContext('new KittyMediaItems.Store()',ctx);
 // TimedMediaHandler uses cloneNode() without children and removes src. The
 // placeholder keeps resource/poster; sources already exist in the catalogue.
 const wm='https://upload.wikimedia.org/wikipedia/commons/',a='Film_A.webm',b='Film_B.webm';
 const placeholder=(id,file)=>dom(id,[],file,{resourceUrl:'https://commons.wikimedia.org/wiki/File:'+file,
   thumbnail:'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/'+file+'/400px-seek=1-'+file+'.jpg'});
 const observed=(id,file,ext,height)=>({id,type:'direct_video',url:wm+'transcoded/a/ab/'+file+'/'+file+'.'+height+'p.'+ext,
   tab_id:1,page_url:page,frame_id:0,document_url:page,timestamp:Date.now()/1000,metadata:{height}});
 s.update(sender,[placeholder('placeholder-a',a),placeholder('placeholder-b',b)]);
 const wmItems=s.list(1,page,[observed('a-webm',a,'vp9.webm',720),observed('a-mp4',a,'mp4',1080),observed('b-mp4',b,'mp4',360)]);
 assert.deepEqual(Array.from(wmItems,i=>i.candidates.filter(c=>c.type==='direct_video').length),[2,1],'Wikimedia childless placeholders must own observed transcodes');
 assert.ok(wmItems.every(i=>i.downloadable&&i.selectable&&i.explicitSources));
 assert.ok(wmItems[0].candidates.every(c=>!c.url.includes(b)));
 assert.ok(s.list(1,page,[{...observed('wrong-tab',a,'mp4',1080),tab_id:2}])[0].candidates.every(c=>c.type==='ytdlp'));
 assert.ok(s.list(1,page,[{...observed('wrong-frame',a,'mp4',1080),frame_id:2}])[0].candidates.every(c=>c.type==='ytdlp'));
 assert.ok(s.list(1,page,[{...observed('other-file','Film_C.webm','mp4',1080)}]).every(i=>i.candidates.every(c=>c.type==='ytdlp')));
 const beforeId=wmItems[0].id;
 // Cold Wikipedia gallery: resource is a Wikipedia File page, but the poster
 // identifies Commons. The dedicated extractor resolves this file, not a
 // generic collection of duplicate preview players and never the gallery.
 const wikiPlaceholder=placeholder('cold-a',a);wikiPlaceholder.resourceUrl='https://en.wikipedia.org/wiki/File:'+a;
 s.update(sender,[wikiPlaceholder,placeholder('cold-b',b)]);
 const cold=s.list(1,page,[]);
 assert.equal(cold[0].extractionUrl,'https://commons.wikimedia.org/wiki/File:'+a);
 assert.ok(cold.every(i=>i.downloadable&&i.candidates.length===1));
 s.update(sender,[{...placeholder('placeholder-a',a),title:'Updated caption',sources:[{url:observed('late',a,'mp4',1080).url,contentType:'video/mp4'}]},placeholder('placeholder-b',b)]);
 assert.equal(s.list(1,page,[])[0].id,beforeId,'Source updates must not change selection IDs');
 s.update(sender,[placeholder('replacement-a',a),placeholder('placeholder-b',b)]);
 assert.equal(s.list(1,page,[])[0].id,beforeId,'Wikimedia original -> clone must retain the item ID');
 assert.ok(s.list(1,page,[])[0].candidates.some(c=>c.type==='direct_video'),'Clone retains previously declared sources');
 s.update(sender,[dom('pending-a',[]),dom('pending-b',[])]);
 const pending=s.list(1,page,[]);assert.ok(pending.every(i=>i.selectable&&!i.downloadable));
 s.update(sender,[dom('pending-a',['https://cdn.test/late.mp4'],'Async title'),dom('pending-b',[])]);
 assert.equal(s.list(1,page,[])[0].id,pending[0].id,'Unresolved -> resolved preserves identity');
 // Late-start extension: no original DOM declarations were ever seen. Batch
 // still sends each Wikimedia file's observed candidates to the existing host.
 listener({type:'kitty-media-dom',items:[placeholder('late-a',a),placeholder('late-b',b)]},sender);
 for(const candidate of [observed('a-webm',a,'vp9.webm',720),observed('a-mp4',a,'mp4',1080),observed('b-mp4',b,'mp4',360)]) {
   vm.runInContext(`hlsStore.response(${JSON.stringify({tabId:1,frameId:0,documentUrl:page,method:'GET',statusCode:200,url:candidate.url,responseHeaders:[{name:'Content-Type',value:candidate.url.endsWith('.webm')?'video/webm':'video/mp4'}]})});`,ctx);
 }
 const lateItems=(await listener({type:'kitty-media-items',tabId:1},ui)).items,start=calls.length;
 assert.equal((await listener({type:'kitty-download-items',tabId:1,itemIds:lateItems.map(i=>i.id)},ui)).added,2);
 const latePayloads=calls.slice(start).filter(c=>c.action==='download');assert.equal(latePayloads.length,2);
 assert.ok(latePayloads.every(p=>p.automatic&&p.media_item.explicit_sources));
 assert.equal(latePayloads[0].media_fallbacks.length,2);assert.equal(latePayloads[1].media_fallbacks.length,1);
 assert.ok(latePayloads[0].media_fallbacks.every(c=>c.url.includes(a)));assert.ok(latePayloads[1].media_fallbacks.every(c=>c.url.includes(b)));
 // Retry rescans unresolved DOM at download time and uses its newly available
 // source, keeping the original selected ID. Never substitutes the gallery.
 listener({type:'kitty-media-dom',items:[dom('retry-a',[]),dom('retry-b',[])]},sender);
 const retryItems=(await listener({type:'kitty-media-items',tabId:1},ui)).items;
 browser.tabs.sendMessage=async(tabId,message,options)=>{
   assert.equal(message.type,'kitty-media-rescan');assert.equal(options.frameId,0);
   listener({type:'kitty-media-dom',items:[dom('retry-a',['https://cdn.test/retry.mp4']),dom('retry-b',[])]},sender);
 };
 const retry=await listener({type:'kitty-download-item',tabId:1,itemId:retryItems[0].id},ui);assert.ok(retry.ok);
 const retryPayload=calls.filter(c=>c.action==='download').at(-1);assert.equal(retryPayload.url,'https://cdn.test/retry.mp4');assert.equal(retryPayload.media_item.id,retryItems[0].id);
 s.update(sender,[dom('one',['https://cdn.test/a.mp4']),dom('dup',['https://cdn.test/a.mp4'])]);assert.equal(s.list(1,page,[]).length,1);
 assert.equal(s.list(1,page,[])[0].extractionUrl,'https://cdn.test/a.mp4','Even a single item with a direct source must not use the page URL');
 // More than three transcodes must not discard an original whose height is
 // unknown until probing. Automatic considers all these item-owned sources.
 listener({type:'kitty-media-dom',items:[dom('many',['https://cdn.test/original.webm',...Array.from({length:4},(_,i)=>'https://cdn.test/film_'+(240+i*240)+'p.mp4')])]},sender);
 const many=(await listener({type:'kitty-media-items',tabId:1},ui)).items;
 await listener({type:'kitty-download-item',tabId:1,itemId:many[0].id,mode:'best'},ui);
 assert.equal(calls.filter(c=>c.action==='download').at(-1).media_fallbacks.length,5);
 assert.ok(calls.filter(c=>c.action==='download').at(-1).media_fallbacks.some(c=>c.url.endsWith('/original.webm')));
 s.update(sender,[dom('blob',[],'Blob',{blob:true})]);
 const c={id:'hls',type:'hls',url:'https://cdn.test/master.m3u8',page_url:page,tab_id:1,frame_id:0,timestamp:Date.now()/1000,hls:{kind:'master',variants:[]}};
 assert.equal(s.list(1,page,[c])[0].candidates.filter(c=>c.type==='hls').length,1);
 assert.ok(s.list(1,page,[{...c,frame_id:2}])[0].candidates.every(c=>c.sourceType==='ytdlp'));
 s.update(sender,[dom('blob1',[],'One',{blob:true}),dom('blob2',[],'Two',{blob:true})]);assert.ok(s.list(1,page,[c]).every(i=>!i.downloadable));
 s.update(sender,[dom('embed',[],'Embedded',{embedUrl:'https://www.youtube.com/watch?v=AbcDef12345'})]);
 s.update({tab:sender.tab,url:'https://www.youtube.com/embed/AbcDef12345',frameId:2},[dom('child',[],'',{embedUrl:'https://www.youtube.com/watch?v=AbcDef12345',blob:true})]);assert.equal(s.list(1,page,[]).length,1);
 s.update(sender,[dom('dash',['https://cdn.test/video.mpd'],'DASH item')]);
 assert.equal(s.list(1,page,[])[0].candidates.filter(c=>c.sourceType==='dash').length,1);
 s.update(sender,[dom('b1',[],'One',{blob:true,duration:20,height:720}),dom('b2',[],'Two',{blob:true,duration:60,height:1080})]);
 const durationCandidate={...c,type:'dash',id:'duration',url:'https://cdn.test/manifest.mpd',metadata:{duration:60,height:1080},hls:undefined};
 assert.ok(s.list(1,page,[durationCandidate])[1].candidates.some(c=>c.type==='dash'));
 assert.equal(s.list(1,page,[{...durationCandidate,document_url:'https://other.test/old-frame'}])[1].candidates.length,0);
 assert.equal(s.list(1,'https://other.test/',[]).length,0);
 // Known single-player provider pages keep their site extractor, metadata
 // and formats; a raw CDN name must not become the video's permanent title.
 for(const provider of ['https://www.youtube.com/watch?v=jNQXAC9IVRw','https://soundcloud.com/artist/track']) {
   const providerSender={tab:{id:2,url:provider},url:provider,frameId:0};
   const store=vm.runInContext('new KittyMediaItems.Store({log:()=>{}})',ctx);
   store.update(providerSender,[dom('player',['https://cdn.test/stream.mp4'],'Média',{titleSource:'aria-label'})]);
   let item=store.list(2,provider,[])[0];assert.equal(item.extractionUrl,provider);assert.equal(item.preferExtractor,true);
   store.enrich(item.id,{title:'Actual provider title'});item=store.list(2,provider,[])[0];
   assert.equal(item.title,'Actual provider title');assert.equal(item.titleSource,'metadata');
   store.update(providerSender,[dom('one',['https://cdn.test/one.mp4']),dom('two',['https://cdn.test/two.mp4'])]);
   assert.ok(store.list(2,provider,[]).every(i=>i.extractionUrl!==provider&&!i.preferExtractor));
 }
 const provider='https://soundcloud.com/artist/track';
 browser.tabs.get=async id=>({id,url:provider,title:'Actual provider title'});
 browser.runtime.sendNativeMessage=async (_host,payload)=>{calls.push(payload);return payload.action==='compatibility'
   ? {ok:true,compatibility:{compatible:true,backend_version:'8.44'}}
   : payload.action==='media_item_probe'?{ok:true,title:'Actual provider title',videoTracks:[],audioTracks:[],subtitleTracks:[]}
   : {ok:true,job_id:'provider-download'};};
 vm.runInContext('compatibilityCache=null',ctx);
 listener({type:'kitty-media-dom',items:[dom('soundcloud',['https://cdn.test/stream.mp4'],'Média',{titleSource:'aria-label'})]},
   {tab:{id:2,url:provider},url:provider,frameId:0});
 const providerItems=(await listener({type:'kitty-media-items',tabId:2},ui)).items;
 await listener({type:'kitty-probe-item',tabId:2,itemId:providerItems[0].id},ui);
 const probePayload=calls.filter(c=>c.action==='media_item_probe').at(-1);
 assert.equal(probePayload.url,provider);assert.equal(probePayload.media_item.prefer_extractor,true);
 await listener({type:'kitty-download-item',tabId:2,itemId:providerItems[0].id,mode:'audio'},ui);
 const providerPayload=calls.filter(c=>c.action==='download').at(-1);
 assert.equal(providerPayload.url,provider);assert.equal(providerPayload.media_item.prefer_extractor,true);
 assert.equal(providerPayload.media_item.title,'Actual provider title');assert.equal(providerPayload.media_fallbacks.length,1);
 console.log('PASS MediaItem: Wikimedia childless placeholders/transcodes, late-start scoped batch, stable async/clone IDs, unresolved download-time rescan, variants, exact URLs/Range, separate videos, frame isolation, blob/HLS, ambiguous blobs, embed deduplication, private list and existing Automatic dispatch.');
})().catch(e=>{console.error(e);process.exitCode=1});
