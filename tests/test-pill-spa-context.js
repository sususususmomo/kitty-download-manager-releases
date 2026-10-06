// Authenticated network context stays scoped to a verified SPA document.
const {fixture,player}=require('./test-pill-download');const vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{const old='https://site.test/page',next=old+'?spa',media='https://cdn.test/main_720p.mp4?token=TEST';const f=fixture(old);f.setPage(next);f.sender.url=old;f.sender.documentId='same-document';
const original=f.context.browser.tabs.sendMessage;f.context.browser.tabs.sendMessage=async(id,m,o)=>m.type==='kitty-document-context'?{ok:true,pageUrl:next,documentToken:'doc'}:original(id,m,o);
f.setItems([player('main',media)]);f.setRescan(()=>f.receive({type:'kitty-media-dom',pageUrl:next,documentToken:'doc',items:[player('main',media)]}));
vm.runInContext(`hlsStore.navigate(1,${JSON.stringify(next)});hlsStore.before({tabId:1,requestId:'spa',url:${JSON.stringify(media)},frameId:0,documentUrl:${JSON.stringify(old)}});hlsStore.headers({tabId:1,requestId:'spa',url:${JSON.stringify(media)},method:'GET',requestHeaders:[{name:'Authorization',value:'Bearer TEST'}]});hlsStore.response({tabId:1,requestId:'spa',url:${JSON.stringify(media)},frameId:0,documentUrl:${JSON.stringify(old)},method:'GET',statusCode:200,responseHeaders:[{name:'Content-Type',value:'video/mp4'}]});`,f.context);
assert.equal(vm.runInContext('hlsStore.list(1).length',f.context),1);
const result=await f.receive({type:'kitty-add-download',pageUrl:next,documentToken:'doc'});assert.equal(result.ok,true);
assert.ok(f.downloads()[0].media_fallbacks.some(s=>s.request_context?.headers?.Authorization==='Bearer TEST'),'Authenticated captured request context must survive same-document URL normalization');console.log('PASS verified SPA request context');})().catch(e=>{console.error(e.message);process.exitCode=1;});
