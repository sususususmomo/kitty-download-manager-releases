const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const ctx=vm.createContext({URL,Date,console,crypto:require('node:crypto').webcrypto});
for(const f of ['request-context.js','hls-detector.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',f),'utf8'),ctx);
const api=ctx.KittyRequestContext,url='https://cdn.test/master.m3u8?token=PRIVATE-TOKEN';
const headers=[{name:'Referer',value:'https://page.test/watch'},{name:'Origin',value:'https://page.test'},
 {name:'User-Agent',value:'Firefox QA'},{name:'Cookie',value:'session=PRIVATE-COOKIE'},
 {name:'Authorization',value:'Bearer PRIVATE-AUTH'},{name:'X-Media-Key',value:'PRIVATE-KEY'},
 {name:'Range',value:'bytes=1-2'},{name:'Host',value:'other.test'},{name:'If-None-Match',value:'stale'},
 {name:'X-Forwarded-For',value:'1.2.3.4'},{name:'X-Bad',value:'unsafe\r\nInjected: yes'}];
const context=api.capture(url,headers);
assert.equal(context.source_url,url);assert.equal(context.cookies,'session=PRIVATE-COOKIE');
assert.equal(context.headers.Authorization,'Bearer PRIVATE-AUTH');assert.equal(context.headers['x-media-key'],'PRIVATE-KEY');
for(const name of ['Range','Host','If-None-Match','x-forwarded-for','x-bad','Cookie'])assert.equal(context.headers[name],undefined);
assert.equal(Object.keys(api.legacy(context)).length,3);assert.equal(api.requiresBackend(context),true);
assert.equal(api.capture('blob:unsafe',headers),null);
const store=new ctx.KittyMedia.Store();store.navigate(1,'https://page.test/watch');
function source(type,url,mime,id) {
 const d={tabId:1,frameId:0,documentUrl:'https://page.test/watch',method:'GET',url,requestId:id,requestHeaders:headers,statusCode:200,responseHeaders:[{name:'Content-Type',value:mime}]};
 store.headers(d);return store.response(d);
}
for(const [type,u,mime] of [['hls',url,'application/vnd.apple.mpegurl'],['dash','https://cdn.test/video.mpd','application/dash+xml'],['direct_video','https://cdn.test/video.mp4','video/mp4']]) {
 const c=source(type,u,mime,type);assert.equal(c.type,type);assert.equal(c.requestContext.source_url,u);assert.equal(c.requestContext.cookies,context.cookies);
 assert.equal(c.headers.Cookie,undefined);assert.equal(c.headers.Authorization,undefined);
 const publicValue=JSON.stringify(store.summary(c)||{type:c.type});for(const secret of ['PRIVATE-TOKEN','PRIVATE-COOKIE','PRIVATE-AUTH','PRIVATE-KEY'])assert.ok(!publicValue.includes(secret));
}
const low=source('direct_video','https://cdn.test/clip_360p.mp4','video/mp4','low');
const high=source('direct_video','https://cdn.test/clip_1080p.mp4','video/mp4','high');
assert.equal(high.requestContext.source_url,high.url);assert.equal(high.variants.length,2);
assert.ok(high.variants.every(v=>v.requestContext.source_url===v.url));
store.navigate(1,'https://page.test/other');assert.equal(store.list(1).length,0);
console.log('PASS RequestContext: observed headers/session, transport exclusions, HLS/DASH/direct, per-quality context, private summaries, navigation cleanup.');
