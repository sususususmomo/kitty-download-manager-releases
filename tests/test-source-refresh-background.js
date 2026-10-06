const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const calls=[],timers=[],event=()=>({addListener:()=>{}});
const browser={runtime:{getManifest:()=>({version:'8.50'}),getURL:f=>'moz-extension://kitty/'+f,
  onMessage:event(),sendMessage:async()=>{},sendNativeMessage:async(_host,payload)=>{
    calls.push(payload);return payload.action==='compatibility'
      ? {ok:true,compatibility:{compatible:true,backend_version:'8.41'}} : {ok:true};}},
  tabs:{get:async id=>({id,url:'https://page.test/gallery',title:'Gallery'}),onRemoved:event(),onUpdated:event()},
  storage:{local:{get:async()=>({})}},webRequest:Object.fromEntries(
    ['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(k=>[k,event()]))};
const ctx=vm.createContext({URL,Date,browser,console,crypto:require('node:crypto').webcrypto,
  location:{href:'moz-extension://kitty/background.html'},setTimeout:f=>{timers.push(f);return timers.length;}});
for(const file of ['shared.js','request-context.js','media-resolver.js','hls-detector.js','background.js'])
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',file),'utf8'),ctx);
vm.runInContext(`
  const own={id:'candidate-one',type:'direct_video',url:'https://cdn.test/one.mp4?token=fresh',
    page_url:'https://page.test/gallery',tab_id:1,headers:{Referer:'https://page.test/gallery'}};
  const other={...own,id:'candidate-two',url:'https://cdn.test/two.mp4?token=fresh'};
  itemsForTab=async()=>[{id:'item-one',candidates:[own]},{id:'item-two',candidates:[other]}];
  hlsForTab=async()=>[own,other];
`,ctx);
(async()=>{
  await vm.runInContext(`serviceSourceRefresh({id:'job-one',source_refresh_request:{nonce:'fresh-request',
    candidate_id:'candidate-one',tab_id:1,media_item_id:'item-one'}})`,ctx);
  const request=calls.find(c=>c.action==='refresh_source');
  assert.equal(request.job_id,'job-one');assert.equal(request.nonce,'fresh-request');
  assert.equal(request.media_source.media_item_id,'item-one');
  assert.match(request.media_source.url,/one\.mp4/);
  assert.equal(calls.some(c=>c.action==='download'||c.action==='retry'),false);
  const before=calls.length;
  await vm.runInContext(`serviceSourceRefresh({id:'job-one',source_refresh_request:{nonce:'wrong-request',
    candidate_id:'candidate-two',tab_id:1,media_item_id:'item-one'}})`,ctx);
  assert.equal(calls.length,before,'Never borrow a candidate from the other MediaItem');
  await vm.runInContext(`serviceSourceRefresh({id:'job-one',source_refresh_request:{nonce:'classic-request',
    candidate_id:'candidate-one',tab_id:1}})`,ctx);
  assert.equal(calls.at(-1).action,'refresh_source');
  vm.runInContext('armSourceRefresh();armSourceRefresh()',ctx);
  assert.equal(timers.length,1,'One background timer also works with the popup closed');
  console.log('PASS source refresh background: scoped item/candidate, same job, nonce, classic source, no enqueue/retry, one background timer.');
})().catch(error=>{console.error(error);process.exitCode=1;});
