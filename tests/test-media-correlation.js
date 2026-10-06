/* Evidence-based logical-media grouping; uses the production classifier/store. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
let now=1000;class Clock extends Date{static now(){return now*1000;}}
const context=vm.createContext({URL,Date:Clock,console});
for(const f of ['request-context.js','hls-detector.js','media-items.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),context);
const page='https://page.test/gallery',sender={tab:{id:1,url:page},frameId:0,url:page};
const dom=(id,sources=[],extra={})=>({domId:id,mediaKind:'video',title:'Film '+id,titleSource:'caption',sources:sources.map(url=>({url})),...extra});
const candidate=(id,url,extra={})=>({id,url,type:'direct_video',tab_id:1,page_url:page,frame_id:0,document_url:page,timestamp:now,...extra});
const native=item=>item.candidates.filter(c=>c.type!=='ytdlp');
let passed=0;const results=[];
function test(name,run){now=1000;const logs=[],s=vm.runInContext('new KittyMediaItems.Store({log:(event,data)=>globalThis.logs.push({event,...data})})',Object.assign(context,{logs}));run(s,logs);passed++;results.push(name);}
const a='https://cdn.test/a.mp4',b='https://cdn.test/b.mp4',webm='https://cdn.test/a.webm',hls='https://cdn.test/a.m3u8',dash='https://cdn.test/a.mpd';
test('partial source sets produce one logical item and keep all variants',s=>{
 s.update(sender,[dom('a',[a]),dom('duplicate',[a,webm])]);const list=s.list(1,page,[candidate('a',a),candidate('webm',webm)]);
 assert.equal(list.length,1);assert.equal(native(list[0]).length,2);
});
test('DOM source network MP4 WebM HLS DASH and extractor stay under one item',s=>{
 s.update(sender,[dom('a',[a,webm,hls,dash]),dom('duplicate',[a])]);
 const list=s.list(1,page,[candidate('mp4',a),candidate('webm',webm),candidate('hls',hls,{type:'hls'}),candidate('dash',dash,{type:'dash'}),candidate('extractor',page+'/file-a',{type:'ytdlp',formats:[{url:a},{url:webm}]})]);
 assert.equal(list.length,1);assert.equal(list[0].candidates.length,5);assert.equal(list[0].candidates.filter(c=>c.type==='ytdlp').length,1);
});
test('declared master and child relationship joins duplicate DOM players',s=>{
 s.update(sender,[dom('a',[a]),dom('master',[hls])]);
 const list=s.list(1,page,[candidate('master',hls,{type:'hls',hls:{kind:'master',variants:[{url:a}]}})]);assert.equal(list.length,1);
});
test('out-of-order linked responses reach the same item',s=>{
 const child='https://cdn.test/child.m3u8';s.update(sender,[dom('a',[a])]);
 const list=s.list(1,page,[candidate('child',child,{type:'hls'}),candidate('master',hls,{type:'hls',hls:{variants:[{url:child},{url:a}]}})]);
 assert.equal(list.length,1);assert.ok(list[0].candidates.some(c=>c.id==='child'));
});
test('shared audio track cannot bridge two distinct video presentations',s=>{
 const audio='https://cdn.test/shared-audio.m3u8';s.update(sender,[dom('a',[a]),dom('b',[b])]);
 const list=s.list(1,page,[candidate('hls-a',hls,{type:'hls',hls:{variants:[{url:a}],audioTracks:[{url:audio}]}}),candidate('hls-b','https://cdn.test/b.m3u8',{type:'hls',hls:{variants:[{url:b}],audioTracks:[{url:audio}]}})]);
 assert.equal(list.length,2);assert.ok(list[0].candidates.some(c=>c.id==='hls-a'));assert.ok(!list[0].candidates.some(c=>c.id==='hls-b'));assert.ok(list[1].candidates.some(c=>c.id==='hls-b'));
});
test('extractor collections never group separate DOM videos',(s,logs)=>{
 s.update(sender,[dom('a',[a]),dom('b',[b])]);const list=s.list(1,page,[candidate('collection',page,{type:'ytdlp',_type:'playlist',entries:[],formats:[{url:a},{url:b}]})]);
 assert.equal(list.length,2);assert.ok(list.every(i=>!i.candidates.some(c=>c.id==='collection')));assert.ok(logs.some(l=>l.reason==='candidate_is_collection'));
});
test('audio and video DOM controls retain their logical kind',s=>{
 s.update(sender,[dom('a',[a]),dom('audio',[a],{mediaKind:'audio'})]);assert.equal(s.list(1,page).length,2);
});
for(const [name,extra] of [['tab',{tab_id:2}],['frame',{frame_id:2}],['document',{document_url:'https://other.test/'}],['page',{page_url:'https://other.test/'}]])test('exact URL cannot bypass '+name+' scope',(s,logs)=>{
 s.update(sender,[dom('a',[a])]);const list=s.list(1,page,[candidate('wrong',a,extra)]);assert.ok(!list[0].candidates.some(c=>c.id==='wrong'));assert.ok(logs.some(l=>l.reason==='wrong_'+name));
});
test('two videos with identical title duration resolution container and time stay separate',(s,logs)=>{
 const details={title:'Shared caption',duration:20,height:720,containerId:'one-card'};
 s.update(sender,[dom('a',[a],details),dom('b',[b],details)]);const list=s.list(1,page,[candidate('a',a),candidate('b',b)]);
 assert.equal(list.length,2);assert.ok(list[0].candidates.every(c=>c.url!==b));assert.ok(logs.some(l=>l.reason==='container_without_identity'));
});
test('shared preview with different primary sources does not merge two videos',s=>{
 const preview='https://cdn.test/preview.mp4';s.update(sender,[dom('a',[a,preview]),dom('b',[b,preview])]);const list=s.list(1,page,[candidate('preview',preview)]);
 assert.equal(list.length,2);assert.ok(list.every(i=>!i.candidates.some(c=>c.id==='preview')));
});
test('ambiguous metadata remains unattached',(s,logs)=>{
 const details={title:'Shared caption',duration:20,height:720};s.update(sender,[dom('a',[a],details),dom('b',[b],details)]);
 const c=candidate('unknown',hls,{type:'hls',metadata:{title:'Shared caption',duration:20,height:720}});
 assert.ok(s.list(1,page,[c]).every(i=>!i.candidates.some(c=>c.id==='unknown')));assert.ok(logs.some(l=>l.reason==='ambiguous_match'));
});
test('duration resolution and fresh timing identify one of two blob players',s=>{
 s.update(sender,[dom('a',[],{blob:true,duration:20,height:720}),dom('b',[],{blob:true,duration:60,height:1080})]);
 const list=s.list(1,page,[candidate('match',dash,{type:'dash',metadata:{duration:60,height:1080}})]);assert.ok(!list[0].candidates.some(c=>c.id==='match'));assert.ok(list[1].candidates.some(c=>c.id==='match'));
});
test('resolved title breaks an otherwise equal metadata match',s=>{
 s.update(sender,[dom('a',[],{blob:true,title:'First complete film',duration:20,height:720}),dom('b',[],{blob:true,title:'Second complete film',duration:20,height:720})]);
 const list=s.list(1,page,[candidate('match',dash,{type:'dash',metadata:{duration:20,height:720,title:'Second complete film'}})]);assert.ok(!list[0].candidates.some(c=>c.id==='match'));assert.ok(list[1].candidates.some(c=>c.id==='match'));
});
test('metadata title alone cannot attach another video',s=>{
 s.update(sender,[dom('a',[a],{title:'Same complete title'})]);assert.ok(!s.list(1,page,[candidate('b',b,{metadata:{title:'Same complete title'}})])[0].candidates.some(c=>c.id==='b'));
});
test('duration contradiction defeats temporal blob heuristic',(s,logs)=>{
 s.update(sender,[dom('a',[],{blob:true,duration:20,height:720})]);assert.ok(!s.list(1,page,[candidate('wrong',hls,{type:'hls',metadata:{duration:60,height:720}})])[0].candidates.some(c=>c.id==='wrong'));assert.ok(logs.some(l=>l.reason==='duration_conflict'));
});
test('one fresh manifest group may attach to one unresolved blob',s=>{
 s.update(sender,[dom('blob',[],{blob:true})]);assert.ok(s.list(1,page,[candidate('hls',hls,{type:'hls'})])[0].candidates.some(c=>c.id==='hls'));
});
test('two unrelated manifests cannot both attach by same frame and time',(s,logs)=>{
 s.update(sender,[dom('blob',[],{blob:true})]);const list=s.list(1,page,[candidate('hls',hls,{type:'hls'}),candidate('dash',dash,{type:'dash'})]);assert.equal(native(list[0]).length,0);assert.ok(logs.some(l=>l.reason==='ambiguous_blob_sources'));
});
test('recent unrelated direct resource cannot attach to a blob',s=>{
 s.update(sender,[dom('blob',[],{blob:true})]);assert.ok(!s.list(1,page,[candidate('ad',b)])[0].candidates.some(c=>c.id==='ad'));
});
test('stale timing cannot attach a manifest without identity',s=>{
 s.update(sender,[dom('blob',[],{blob:true})]);now=1100;assert.equal(native(s.list(1,page,[candidate('old',hls,{type:'hls',timestamp:1000})])[0]).length,0);
});
test('caption updates do not refresh proximity but player activity does',s=>{
 s.update(sender,[dom('blob',[],{blob:true})]);now=1060;s.update(sender,[dom('blob',[],{blob:true,title:'Updated caption'})]);
 assert.equal(native(s.list(1,page,[candidate('hls',hls,{type:'hls'})])[0]).length,0);
 s.update(sender,[dom('blob',[],{blob:true,title:'Updated caption',duration:60,height:720})]);assert.equal(native(s.list(1,page,[candidate('hls',hls,{type:'hls'})])[0]).length,1);
});
test('explicit URL identity remains valid independently of timing',s=>{
 s.update(sender,[dom('a',[a])]);now=1100;assert.ok(s.list(1,page,[candidate('a',a,{timestamp:1000})])[0].candidates.some(c=>c.id==='a'));
});
test('quality families reuse the detector normalization without losing variants',s=>{
 const low='https://cdn.test/film_720p.mp4',high='https://cdn.test/film_1080p.mp4';s.update(sender,[dom('low',[low]),dom('high',[high])]);
 const list=s.list(1,page,[candidate('low',low),candidate('high',high)]);assert.equal(list.length,1);assert.equal(native(list[0]).length,2);
});
test('quality normalization never drops distinct video IDs',s=>{
 s.update(sender,[dom('a',['https://cdn.test/film_720p.mp4?id=1']),dom('b',['https://cdn.test/film_1080p.mp4?id=2'])]);assert.equal(s.list(1,page).length,2);
});
test('same URL in separate ordinary frames does not collapse DOM scope',s=>{
 s.update(sender,[dom('a',[a])]);s.update({tab:sender.tab,url:page+'/frame',frameId:2},[dom('b',[a])]);assert.equal(s.list(1,page).length,2);
});
test('iframe and its child player use one embed identity with scoped candidates',s=>{
 const embed='https://www.youtube.com/watch?v=AbcDef12345',frame='https://www.youtube.com/embed/AbcDef12345';
 s.update(sender,[dom('iframe',[],{embedUrl:embed})]);s.update({tab:sender.tab,url:frame,frameId:2},[dom('child',[],{embedUrl:embed,blob:true})]);
 const list=s.list(1,page,[candidate('own',embed,{type:'ytdlp',frame_id:2,document_url:frame})]);assert.equal(list.length,1);assert.equal(list[0].candidates.filter(c=>c.type==='ytdlp').length,1);
});
test('Wikimedia Wikipedia and Commons links with the same repository poster deduplicate',s=>{
 const file='Film.webm',poster='https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/'+file+'/300px-'+file+'.jpg';
 s.update(sender,[dom('wiki',[],{resourceUrl:'https://en.wikipedia.org/wiki/File:'+file,thumbnail:poster}),dom('commons',[],{resourceUrl:'https://commons.wikimedia.org/wiki/File:'+file,thumbnail:poster})]);assert.equal(s.list(1,page).length,1);
});
test('contradictory Wikimedia poster cannot override explicit file identity',s=>{
 s.update(sender,[dom('a',[],{resourceUrl:'https://commons.wikimedia.org/wiki/File:A.webm',thumbnail:'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/B.webm/300px-B.webm.jpg'})]);
 const list=s.list(1,page,[candidate('wrong','https://upload.wikimedia.org/wikipedia/commons/a/ab/B.webm')]);assert.ok(!list[0].candidates.some(c=>c.id==='wrong'));
});
test('one candidate per type and URL keeps the freshest token without log secrets',(s,logs)=>{
 const url=a+'?token=SECRET';s.update(sender,[dom('a',[url])]);const newer=a+'?token=NEW_SECRET';
 const list=s.list(1,page,[candidate('old',url,{timestamp:999}),candidate('new',newer)]);assert.equal(native(list[0]).length,1);assert.equal(native(list[0])[0].url,newer);
 const output=JSON.stringify(logs);assert.ok(!output.includes('SECRET')&&!output.includes('cdn.test')&&!output.includes('token='));assert.ok(logs.some(l=>l.reason==='duplicate_candidate'));
 const count=logs.length;s.list(1,page,[candidate('old',url,{timestamp:999}),candidate('new',newer)]);assert.equal(logs.length,count,'Polling must not repeat unchanged decisions');
});
test('stable selection survives candidate title thumbnail and variant updates',s=>{
 s.update(sender,[dom('a',[a])]);const id=s.list(1,page)[0].id;now=1001;s.update(sender,[dom('a',[a,webm],{title:'New caption',thumbnail:'https://cdn.test/new.jpg'})]);assert.equal(s.list(1,page)[0].id,id);
});
test('reused DOM node with a distinct resource receives a distinct identity',s=>{
 s.update(sender,[dom('player',[a])]);const id=s.list(1,page)[0].id;s.update(sender,[dom('player',[b])]);assert.notEqual(s.list(1,page)[0].id,id);
});
test('association logs change when an explicit source becomes available',(s,logs)=>{
 const c=candidate('b',b);s.update(sender,[dom('a',[a])]);s.list(1,page,[c]);assert.ok(logs.some(l=>l.action==='reject'));
 s.update(sender,[dom('a',[b])]);s.list(1,page,[c]);assert.ok(logs.some(l=>l.action==='merge'&&l.reason==='linked_url'));
});
console.log(JSON.stringify({passed,failed:0,checks:results},null,2));
