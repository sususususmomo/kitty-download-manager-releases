// Independent regression scenarios; uses production scripts, no alternate pipeline.
const assert=require('node:assert/strict');
const {fixture,player}=require('./test-pill-download');
const {fixture:uiFixture}=require('./test-pill-ui');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const ui={url:'moz-extension://kitty/popup.html'};
const cases=[];
const test=(name,run)=>cases.push({name,run});
const page='https://www.youtube.com/watch?v=AbcDef12345';
for(const mode of [undefined,'audio','mp3','720','1080','best'])test(`cold YouTube ${mode||'default'}`,async()=>{
 const f=fixture(page);if(mode)f.saved.selectedMode=mode;else delete f.saved.selectedMode;
 f.setItems([player('youtube',null,'Main player')]);const r=await f.receive({type:'kitty-add-download'});
 assert.equal(r.ok,true);assert.equal(f.downloads().length,1);assert.equal(f.downloads()[0].mode,mode||'1080');
 assert.equal(f.downloads()[0].url,page);
});
test('invalid saved mode uses same popup default',async()=>{
 const f=fixture(page);f.saved.selectedMode='broken';f.setItems([player('youtube',null)]);
 await f.receive({type:'kitty-add-download'});assert.equal(f.downloads()[0].mode,'1080');
});
test('popup and pill payload identical including saved tracks and automatic source',async()=>{
 const f=fixture('https://gallery.test/post');f.setItems([player('one','https://cdn.test/one.mp4'),player('two','https://cdn.test/two.mp4')]);
 const items=(await f.receive({type:'kitty-media-items',tabId:1},ui)).items;
 await f.receive({type:'kitty-download-settings',tabId:1,change:{itemId:items[1].id,track_selection:{audioLanguage:'fr'}}},ui);
 f.saved.selectedMode='mp3';await f.receive({type:'kitty-add-download',tabId:1},ui);const a=JSON.stringify(f.downloads()[0]);
 await f.receive({type:'kitty-add-download'});assert.equal(JSON.stringify(f.downloads()[1]),a);
});
test('simultaneous requests join one enqueue',async()=>{
 const f=fixture('https://site.test/video');f.setItems([player('main','https://cdn.test/main.mp4')]);
 let release;const gate=new Promise(r=>release=r);f.setRescan(()=>gate);
 const a=f.receive({type:'kitty-add-download'}),b=f.receive({type:'kitty-add-download'});release();
 const [first,second]=await Promise.all([a,b]);assert.equal(first.job_id,second.job_id);assert.equal(f.downloads().length,1);
});
test('same-document navigation uses live verified URL and identical popup payload',async()=>{
 const f=fixture(page),next='https://www.youtube.com/watch?v=NewVideo',token='isolated-document-token';
 f.setPage(next);f.sender.url=page;f.sender.documentId='same-document';f.setItems([player('main',null)]);
 const original=f.context.browser.tabs.sendMessage;
 f.context.browser.tabs.sendMessage=async(id,m,o)=>m.type==='kitty-document-context'?{ok:true,pageUrl:next,documentToken:token}:original(id,m,o);
 f.setRescan(()=>f.receive({type:'kitty-media-dom',pageUrl:next,documentToken:token,items:[player('main',null)]}));
 const pill=await f.receive({type:'kitty-add-download',pageUrl:next,documentToken:token});assert.equal(pill.ok,true);
 const a=JSON.stringify(f.downloads()[0]);await f.receive({type:'kitty-add-download',tabId:1},ui);assert.equal(JSON.stringify(f.downloads()[1]),a);assert.equal(f.downloads()[0].url,next);
});
test('replaced document token is rejected even without Firefox documentId',async()=>{
 const f=fixture(page),next='https://www.youtube.com/watch?v=NewVideo';f.setPage(next);f.sender.url=page;
 f.context.browser.tabs.sendMessage=async()=>({ok:true,pageUrl:next,documentToken:'replacement-document'});
 const r=await f.receive({type:'kitty-add-download',pageUrl:next,documentToken:'old-document'});assert.equal(r.code,'stale_document');assert.equal(f.downloads().length,0);
});
test('multiple tabs keep URL, item and selections scoped to their originating tab',async()=>{
 const f=fixture('https://tab-one.test/watch'),second='https://tab-two.test/watch';f.setItems([player('one','https://cdn.test/one.mp4')]);
 const get=f.context.browser.tabs.get,send=f.context.browser.tabs.sendMessage;
 f.context.browser.tabs.get=id=>id===2?Promise.resolve({id:2,url:second}):get(id);
 f.context.browser.tabs.sendMessage=(id,m,o)=>id===2?Promise.resolve({ok:true,url:second}):send(id,m,o);
 const first=f.receive({type:'kitty-add-download'}),other=f.receive({type:'kitty-add-download'},{tab:{id:2,url:second},url:second,frameId:0});
 assert.ok((await first).ok);assert.ok((await other).ok);assert.equal(f.downloads().length,2);
 assert.equal(f.downloads()[0].media_item.page_url,'https://tab-one.test/watch');assert.equal(f.downloads()[1].url,second);
});
test('backend unavailable preserves native exception',async()=>{
 const f=fixture(page);f.setItems([player('youtube',null)]);f.setNativeHandler(async()=>{throw new Error('Native host disconnected: fixture');});
 const r=await f.receive({type:'kitty-add-download'});assert.equal(r.ok,false);assert.match(JSON.stringify(r),/Native host disconnected: fixture/);
 assert.equal(r.code,'native_host_unavailable');assert.ok(r.stage);
});
test('enqueue invalidates an older status promise without overwriting the new cache',async()=>{
 const f=fixture(page);f.setItems([player('youtube',null)]);let resolveOld,statusCalls=0;
 const oldStatus=new Promise(r=>resolveOld=r);
 f.setNativeHandler(async p=>p.action==='compatibility'?{ok:true,compatibility:{compatible:true,backend_version:'8.49'}}:
   p.action==='status'?(++statusCalls===1?oldStatus:{ok:true,state:{active:{id:'accepted',status:'downloading'}}}):{ok:true,job_id:'accepted'});
 const pending=f.receive({type:'kitty-pill-status'});await flush();await f.receive({type:'kitty-add-download'});
 const currentRequest=f.receive({type:'kitty-pill-status'});await flush();assert.equal(statusCalls,2);
 const current=await currentRequest;assert.equal(current.state.active.id,'accepted');
 resolveOld({ok:true,state:{active:null,queue:[],history:[]}});await pending;
 const cached=await f.receive({type:'kitty-pill-status'});assert.equal(cached.state.active.id,'accepted');assert.equal(statusCalls,2);
});
test('metadata/backend error retains HTTP detail and stage',async()=>{
 const f=fixture(page);f.setItems([player('youtube',null)]);f.setNativeHandler(async p=>p.action==='compatibility'?{ok:true,compatibility:{compatible:true,backend_version:'8.49'}}:{ok:false,code:'metadata_failed',error:'Metadata failed',error_detail:'HTTP Error 403: Forbidden',error_hint:'Check session'});
 const r=await f.receive({type:'kitty-add-download'});assert.equal(r.code,'metadata_failed');assert.equal(r.error_detail,'HTTP Error 403: Forbidden');assert.equal(r.stage,'native_response');assert.equal(f.downloads().length,1);
});
test('old document rejected without download and with precise stage',async()=>{
 const f=fixture(page);f.setPage('https://www.youtube.com/watch?v=NewDocument');f.sender.url=page;
 const r=await f.receive({type:'kitty-add-download'});assert.equal(r.ok,false);assert.equal(f.downloads().length,0);assert.equal(r.stage,'tab');
});
test('rescan failure is diagnostic but yt-dlp fallback still downloads',async()=>{
 const f=fixture('https://vimeo.com/123456');f.setRescan(async()=>{throw new Error('Content listener unavailable');});
 const r=await f.receive({type:'kitty-add-download'});assert.equal(r.ok,true);
 const trace=await f.receive({type:'kitty-download-diagnostics'},ui);assert.ok(trace.events.some(e=>e.stage==='rescan'&&e.error));
});
test('sanitized trace reports fields, defaults, stage, request and job IDs',async()=>{
 const f=fixture('https://site.test/watch?token=SECRET');delete f.saved.selectedMode;f.setItems([player('main','https://cdn.test/file.mp4?token=SECRET')]);
 await f.receive({type:'kitty-add-download'});const trace=await f.receive({type:'kitty-download-diagnostics'},ui);
 assert.equal(trace.ok,true);const text=JSON.stringify(trace);assert.ok(!text.includes('SECRET'));assert.ok(!text.includes('token='));
 assert.ok(trace.events.some(e=>e.stage==='settings'&&e.defaults?.includes('mode:1080')));
 assert.ok(trace.events.some(e=>e.stage==='native_request'&&e.fields.includes('media_item')));
 assert.ok(trace.events.some(e=>e.stage==='accepted'&&e.jobId));assert.ok(trace.events.every(e=>e.requestId));
 assert.equal((await f.receive({type:'kitty-download-diagnostics'})).ok,false);
});
test('error detail stays visible across idle polls; retry is enabled',async()=>{
 const f=await uiFixture();f.setHandler(async m=>m.type==='kitty-add-download'?{ok:false,code:'metadata_failed',error:'Metadata failed',error_detail:'HTTP Error 403: Forbidden',error_hint:'Check session',stage:'native_response',requestId:'trace-1'}:{ok:true,state:{queue:[],history:[]}});
 f.nodes.get('download').dispatch('click');await flush();assert.equal(f.nodes.get('pill').dataset.state,'error');
 assert.match(f.nodes.get('download').title,/403/);assert.match(f.nodes.get('download').title,/trace-1/);
 for(let i=0;i<3;i++)await f.poll();assert.equal(f.nodes.get('pill').dataset.state,'error');assert.equal(f.nodes.get('download').dataset.actionDisabled,'false');
});
test('accepted job removed from queue/history releases the pill',async()=>{
 const f=await uiFixture();f.setHandler(async()=>({ok:true,job_id:'own'}));f.nodes.get('download').dispatch('click');await flush();
 f.setHandler(async()=>({ok:true,state:{active:{id:'own',status:'downloading',downloaded:20,total:100}}}));await f.poll();
 f.setHandler(async()=>({ok:true,state:{queue:[],history:[]}}));for(let i=0;i<3;i++)await f.poll();
 assert.equal(f.nodes.get('download').dataset.actionDisabled,'false');
});
test('job ID from accepted state and transient status failure',async()=>{
 const f=await uiFixture();f.setHandler(async()=>({ok:true,state:{active:{id:'own',status:'starting'}}}));f.nodes.get('download').dispatch('click');await flush();
 f.setHandler(async()=>{throw new Error('temporary native disconnect');});await f.poll();assert.equal(f.nodes.get('pill').dataset.state,'metadata');
 f.setHandler(async()=>({ok:true,state:{history:[{id:'own',status:'finished'}]}}));await f.poll();assert.equal(f.nodes.get('pill').dataset.state,'finished');
});
(async()=>{let failed=0;for(const {name,run}of cases){try{await run();console.log('PASS',name);}catch(e){failed++;console.error('FAIL',name,e.message);}}console.log(`${cases.length-failed}/${cases.length} passed`);process.exitCode=failed?1:0;})();
