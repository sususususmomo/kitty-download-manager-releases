const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={URL,crypto:require('node:crypto').webcrypto,Date,Map,Set};vm.createContext(context);
for(const f of ['request-context.js','hls-detector.js'])vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../extension',f),'utf8'),context);
const {Store,isManifest}=context.KittyHls;
let now=1000000;const store=new Store(()=>now);
store.navigate(1,'https://site.test/page');
function observe(url,mime='application/vnd.apple.mpegurl',id='r',tabId=1){
 const d={url,requestId:id,tabId,type:'xmlhttprequest',method:'GET',statusCode:200,
  requestHeaders:[{name:'Referer',value:'https://site.test/page'},{name:'Cookie',value:'PRIVATE'},
    {name:'Origin',value:'https://site.test'},{name:'User-Agent',value:'Firefox QA'}],
  responseHeaders:[{name:'Content-Type',value:mime}]};
 store.headers(d);return store.response(d);
}
for(const name of ['master.m3u8','index.m3u8','media.m3u8'])assert.ok(isManifest('https://cdn.test/'+name));
for(const mime of ['application/vnd.apple.mpegurl','application/x-mpegurl','audio/mpegurl','audio/x-mpegurl','application/mpegurl'])assert.ok(isManifest('https://cdn.test/play',mime+'; charset=utf-8'));
for(const name of ['seg.ts','frag.m4s','init.mp4'])assert.equal(observe('https://cdn.test/'+name),null);
const first=observe('https://cdn.test/master.m3u8?token=one&quality=1080');
for(let i=0;i<4;i++)assert.equal(observe(first.url).id,first.id);
assert.equal(store.list(1).length,1);
const refresh=observe('https://cdn.test/master.m3u8?token=two&quality=1080');
assert.equal(refresh.id,first.id);assert.ok(store.list(1)[0].url.endsWith('token=two&quality=1080'));
assert.equal(store.list(1)[0].headers.Cookie,undefined);
assert.equal(store.list(1)[0].headers.Referer,'https://site.test/page');
assert.equal(store.list(1)[0].headers.Origin,'https://site.test');
assert.equal(store.list(1)[0].headers['User-Agent'],'Firefox QA');
observe('https://cdn.test/master.m3u8?token=two&quality=720');assert.equal(store.list(1).length,2);
observe('https://cdn.test/index.m3u8');assert.match(store.list(1)[0].url,/master/);
observe('https://cdn.test/play','application/x-mpegurl');assert.equal(store.list(1).length,4);
store.navigate(2,'https://site.test/other');observe('https://cdn.test/other.m3u8',undefined,'tab2',2);
assert.equal(store.list(2).length,1);store.clear(2);assert.equal(store.list(2).length,0);assert.equal(store.list(1).length,4);
const late={requestId:'late',tabId:1,url:'https://cdn.test/old.m3u8',method:'GET',statusCode:200};store.headers(late);
store.navigate(1,'https://site.test/new');assert.equal(store.response(late),null);assert.equal(store.list(1).length,0);
observe('https://cdn.test/new.m3u8');now+=16*60*1000;assert.equal(store.list(1).length,0);
assert.equal(isManifest('file:///etc/secrets.m3u8'),false);
assert.equal(isManifest('https://u:p@cdn.test/master.m3u8'),false);
console.log('PASS HLS detector: URL/MIME, TS/fMP4 exclusion, full tokens, deduplication, quality separation, master priority, headers without cookies, tab isolation/navigation/close, expiry.');
