/* Production parser/store/background/StreamFilter, with deterministic events. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ctx=vm.createContext({setTimeout:()=>1,URL,Date,Map,Set,TextDecoder,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto});
for(const f of ['hls-parser.js','request-context.js','hls-detector.js','hls-response.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),ctx);
const {Store,key,rank}=ctx.KittyMedia,parse=ctx.KittyHlsParser.parse;
const page='https://page.test/watch',master='https://cdn.test/video/master.m3u8?token=MASTER%2BSECRET&asset=one';
const body=`#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio-low",NAME="Original, stereo",LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,URI="audio/media.m3u8?token=AUDIO&asset=one"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Français",LANGUAGE="fr",DEFAULT=NO,AUTOSELECT=YES,URI="../subs/media.m3u8?token=SUB&asset=one"
#EXT-X-STREAM-INF:BANDWIDTH=5000000,AVERAGE-BANDWIDTH=4500000,FRAME-RATE=29.970,RESOLUTION=1920x1080,CODECS="avc1.640028",AUDIO="audio-low",SUBTITLES="subs"
video/1080/media.m3u8?token=HIGH&asset=one
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.640028",AUDIO="audio-low",SUBTITLES="subs"
video/720/media.m3u8?token=MID&asset=one
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=640x360,CODECS="avc1.64001e",AUDIO="audio-low"
video/360/media.m3u8?token=LOW&asset=one
`;
const media='#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:2,\nseg000.m4s\n#EXT-X-ENDLIST\n';
let count=0;
function check(name,fn){fn();count++;console.log('PASS '+name);}
function observe(store,url,text,mime='application/vnd.apple.mpegurl',tabId=1){
 const d={tabId,requestId:url,method:'GET',statusCode:200,url,
  requestHeaders:[{name:'Referer',value:page},{name:'Cookie',value:'DO-NOT-CAPTURE'}],responseHeaders:[{name:'Content-Type',value:mime}]};
 store.headers(d);const c=store.response(d);if(text!==undefined)store.manifest(c,text);store.complete(d);return c;
}
let now=1000000;const store=new Store(()=>now);store.navigate(1,page);
const group=parse(body,master);
check('Vimeo-like master: 1080/720/360, separate audio, subtitles, all attributes',()=>{
 assert.equal(group.kind,'master');assert.equal(group.maxResolution,1080);assert.equal(group.variants.length,3);
 const v=group.variants[0];assert.equal(v.bandwidth,5000000);assert.equal(v.averageBandwidth,4500000);assert.equal(v.frameRate,29.97);
 assert.equal(v.width,1920);assert.equal(v.audio,'audio-low');assert.equal(v.subtitles,'subs');assert.equal(group.codecs[0],'avc1.640028');
 const a=group.audioTracks[0];assert.equal(a.groupId,'audio-low');assert.equal(a.name,'Original, stereo');assert.equal(a.language,'en');assert.equal(a.default,true);assert.equal(a.autoselect,true);
 assert.equal(group.subtitles[0].language,'fr');assert.equal(group.subtitles[0].default,false);
});
check('Relative paths and complete signed query strings',()=>{
 assert.equal(group.variants[0].url,'https://cdn.test/video/video/1080/media.m3u8?token=HIGH&asset=one');
 assert.equal(group.subtitles[0].url,'https://cdn.test/subs/media.m3u8?token=SUB&asset=one');
 assert.equal(parse('#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1280x720\nblob:https://x/one\n',master).variants.length,0);
});
for(const v of [...group.variants,...group.audioTracks,...group.subtitles])observe(store,v.url,media);
const m=observe(store,master,body);
check('One logical HLS source; all referenced children retained and typed internally',()=>{
 assert.equal(store.list(1).length,1);assert.equal(store.tabs.get(1).candidates.size,6);assert.equal(store.list(1)[0].url,master);
 assert.equal(store.summary(m).quality_count,3);assert.equal(store.summary(m).audio_tracks,1);assert.equal(store.summary(m).subtitles,1);
 const children=[...store.tabs.get(1).candidates.values()].filter(c=>c.id!==m.id);
 assert.equal(children.filter(c=>c.hls.kind==='video').length,3);assert.equal(children.filter(c=>c.hls.kind==='audio').length,1);assert.equal(children.filter(c=>c.hls.kind==='subtitles').length,1);
});
check('Repeated master/children and refreshed signing tokens do not create sources',()=>{
 for(let i=0;i<30;i++){
  observe(store,master.replace('MASTER%2BSECRET','NEW'+i),body.replaceAll('token=HIGH','token=HIGH'+i));
  for(const v of group.variants)observe(store,v.url.replace(/token=\w+/,`token=CHILD${i}`),media);
 }
 assert.equal(store.list(1).length,1);assert.equal(store.tabs.get(1).candidates.size,6);
 assert.equal(store.list(1)[0].id,m.id);assert.ok(store.list(1)[0].url.includes('token=NEW29'));
 assert.equal(store.list(1)[0].hls.originalMasterUrl,master);
});
check('Independent videos and meaningful query parameters remain separate',()=>{
 observe(store,master.replace('asset=one','asset=two'),body.replaceAll('asset=one','asset=two'));
 observe(store,'https://cdn.test/other/media.m3u8',media);
 assert.equal(store.list(1).length,3);
 assert.notEqual(key(master),key(master.replace('asset=one','asset=two')));
 assert.equal(key(master),key(master.replace('MASTER%2BSECRET','EXPIRED')));
});
check('Standalone TS/fMP4 kept with honest unknown classification; audio and I-frame evidence',()=>{
 assert.equal(parse(media,master).kind,'unknown');
 assert.equal(parse(media.replace('seg000.m4s','seg000.ts'),master).kind,'unknown');
 assert.equal(parse('#EXTM3U\n#EXTINF:2,\naudio.aac\n',master).kind,'audio');
 assert.equal(parse('#EXTM3U\n#EXT-X-I-FRAMES-ONLY\n#EXTINF:2,\nseg.ts\n',master).kind,'video');
 assert.equal(parse('#EXTM3U\n#EXTINF:2,\nsub.vtt\n',master).kind,'subtitles');
 assert.equal(parse('not HLS',master),null);
});
check('DRM flagged, identity AES-128 unchanged; protected child marks whole group',()=>{
 const audio=group.audioTracks[0].url;
 observe(store,audio,'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://secret",KEYFORMAT="com.apple.streamingkeydelivery"\n#EXTINF:2,\nseg.m4s\n');
 assert.equal(store.summary(store.list(1).find(c=>c.id===m.id)).protected,true);
 assert.equal(parse('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key",KEYFORMAT="identity"\n#EXTINF:2,\nseg.ts\n',master).protected,false);
});
check('Proven masters outrank guessed names, DASH and direct media; stale body ignored',()=>{
 assert.ok(rank(m)>rank({type:'dash',url:'https://cdn.test/manifest.mpd'}));
 store.navigate(1,page+'?new');assert.equal(store.manifest(m,body),null);assert.equal(store.list(1).length,0);
 observe(store,master,body);store.clear(1);assert.equal(store.manifest(m,body),null);
});
check('Master expiry reveals still-current standalone children, with bounded catalogue',()=>{
 store.navigate(1,page);observe(store,master,body);now+=14*60*1000;observe(store,group.variants[0].url,media);
 now+=2*60*1000;assert.equal(store.list(1).length,1);assert.equal(store.list(1)[0].hls.kind,'unknown');
 for(let i=0;i<150;i++)observe(store,'https://cdn.test/distinct/'+i+'.m3u8',media);
 assert.ok(store.list(1).length<=20);assert.ok(store.tabs.get(1).candidates.size<=128);
});
check('Nested masters prefer top level; malformed cyclic masters never hide everything',()=>{
 const s=new Store(()=>now);s.navigate(1,page);
 observe(s,'https://cdn.test/top.m3u8','#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nmid.m3u8\n');
 observe(s,'https://cdn.test/mid.m3u8','#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nleaf.m3u8\n');
 observe(s,'https://cdn.test/leaf.m3u8',media);assert.equal(s.list(1).length,1);assert.match(s.list(1)[0].url,/top/);
 observe(s,'https://cdn.test/leaf.m3u8','#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\ntop.m3u8\n');assert.equal(s.list(1).length,3);
});

(async()=>{
 const filters=new Map(),api={filterResponseData:id=>{
  const f={writes:[],closed:false,disconnected:false,write:data=>f.writes.push(Buffer.from(data)),close:()=>{f.closed=true;},disconnect:()=>{f.disconnected=true;}};
  filters.set(id,f);return f;
 }};
 const reader=new ctx.KittyHlsResponse.Reader(api,{timeout:30,maxBytes:1000,maxActive:1});
 const details={requestId:'tee',tabId:1,method:'GET',statusCode:200};
 let p=reader.read(details),f=filters.get('tee');const data=Buffer.from('#EXTM3U\n# Français\n');
 f.ondata({data:data.subarray(0,13)});f.ondata({data:data.subarray(13)});f.onstop();
 assert.equal(await p,data.toString());assert.equal(Buffer.concat(f.writes).equals(data),true);assert.equal(f.closed,true);assert.equal(reader.active.size,0);
 console.log('PASS StreamFilter exact byte pass-through, split UTF-8, close and cleanup');count++;
 p=reader.read({...details,requestId:'oversize'});f=filters.get('oversize');f.ondata({data:Buffer.alloc(1001)});
 assert.equal(await p,null);assert.equal(f.disconnected,true);assert.equal(f.writes[0].length,1001);
 p=reader.read({...details,requestId:'timeout'});f=filters.get('timeout');assert.equal(reader.read({...details,requestId:'extra'}),null);
 assert.equal(await p,null);assert.equal(f.disconnected,true);assert.equal(reader.active.size,0);
 p=reader.read({...details,requestId:'close-tab'});f=filters.get('close-tab');reader.clear(1);assert.equal(await p,null);assert.equal(f.disconnected,true);
 p=reader.read({...details,requestId:'error'});f=filters.get('error');f.onerror();assert.equal(await p,null);assert.equal(f.disconnected,true);
 console.log('PASS Oversize/slow/error/tab cleanup disconnect observation, preserve player, bounded active filters');count++;

 const events={},calls=[],logs=[],sent=[];
 const event=name=>({addListener:fn=>{events[name]=fn;}});
 const browser={runtime:{getManifest:()=>({version:'8.42'}),getURL:f=>'moz-extension://kitty/'+f,onMessage:event('message'),
  sendMessage:async m=>{sent.push(m);},sendNativeMessage:async(_host,payload)=>{calls.push(payload);return payload.action==='compatibility' ? {ok:true,compatibility:{compatible:true,backend_version:'8.35'}} : {ok:true};}},
  tabs:{get:async id=>({id,url:page,title:'Vimeo-like test'}),onRemoved:event('removed'),onUpdated:event('updated')},storage:{local:{get:async()=>({})}},
  webRequest:{...api,...Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(n=>[n,event(n)]))}};
 const bg=vm.createContext({URL,Date,Map,Set,TextDecoder,setTimeout,clearTimeout,crypto:require('node:crypto').webcrypto,browser,console:{debug:(...args)=>logs.push(args),warn:()=>{},error:()=>{}}});
 for(const file of ['shared.js','media-resolver.js','hls-parser.js','request-context.js','hls-detector.js','hls-response.js','background.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',file),'utf8'),bg);
 async function load(url,text,id){
  const d={url,requestId:id,tabId:1,method:'GET',statusCode:200,responseHeaders:[{name:'Content-Type',value:'application/vnd.apple.mpegurl'}],requestHeaders:[{name:'Referer',value:page}]};
  events.onBeforeSendHeaders(d);await events.onHeadersReceived(d);filters.get(id).ondata({data:Buffer.from(text)});filters.get(id).onstop();
  await new Promise(setImmediate);events.onCompleted(d);
 }
 for(let i=0;i<4;i++){await load(master,body,'master'+i);for(const v of group.variants)await load(v.url,media,'child'+i+v.height);}
 const sender={url:'moz-extension://kitty/popup.html'},list=await events.message({type:'kitty-media-list',tabId:1},sender);
 assert.equal(list.candidates.length,1);assert.equal(list.candidates[0].hls.quality_count,3);assert.equal(list.candidates[0].hls.max_height,1080);
 assert.equal(JSON.stringify(list).includes('SECRET'),false);assert.equal(JSON.stringify(list).includes('token='),false);
 await events.message({type:'kitty-download-media',tabId:1,candidateId:list.candidates[0].id,mode:'1080'},sender);
 assert.equal(calls.at(-1).url,master);assert.equal(calls.at(-1).media_source.url,master);assert.equal(calls.at(-1).media_source.headers.Referer,page);
 assert.equal(calls.at(-1).media_source.hls,undefined);assert.equal(calls.at(-1).media_source.variants,undefined);
 await events.message({type:'kitty-download-page',tabId:1,url:page,mode:'1080'},sender);
 assert.equal(calls.at(-1).media_fallbacks.length,1);assert.equal(calls.at(-1).media_fallbacks[0].url,master);
 assert.equal(JSON.stringify(logs).includes('token='),false);assert.ok(logs.length<20,JSON.stringify(logs));
 await load(master,body+'#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="skd://secret"\n','drm');
 const before=calls.length,protectedSource=await events.message({type:'kitty-download-media',tabId:1,candidateId:list.candidates[0].id},sender);
 assert.equal(protectedSource.code,'drm_protected');assert.equal(calls.length,before);
 await events.message({type:'kitty-download-page',tabId:1,url:page,mode:'1080'},sender);
 assert.equal(calls.at(-1).url,page);assert.equal(calls.at(-1).media_fallbacks,undefined);
 events.removed(1);assert.equal((await events.message({type:'kitty-media-list',tabId:1},sender)).candidates.length,0);
 console.log('PASS Shared background: one safe logical source, explicit/fallback native payload uses master, correct headers, finite secret-free logs, tab cleanup');count++;
 console.log(`PASS ${count} HLS hierarchy scenarios`);
})().catch(e=>{console.error(e);process.exitCode=1;});
