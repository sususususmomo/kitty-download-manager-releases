// Production popup/pill routing with TikTok's preloaded players and feed URLs.
const assert=require('node:assert/strict');
const {fixture,player}=require('./test-pill-download.js');
const A='https://www.tiktok.com/@alice/video/7660560870455840021';
const B='https://www.tiktok.com/@bob/video/7660560870455840022';
const feed='https://www.tiktok.com/foryou',cdn='https://cdn.test/tiktok.mp4?signature=test';
const ui={url:'moz-extension://kitty/popup.html'};
let passed=0,failed=0;
async function check(name,fn){try{await fn();console.log('PASS',name);passed++;}catch(e){console.error('FAIL',name,e.message);failed++;}}
(async()=>{
 await check('Single TikTok page keeps its extractor and item-owned direct fallback',async()=>{
  const f=fixture(A);f.setItems([player('a',cdn,'Player')]);await f.receive({type:'kitty-add-download'});
  const p=f.downloads().at(-1);assert.equal(p.url,A);assert.equal(p.media_item.prefer_extractor,true);
  assert.equal(p.media_fallbacks.length,1);assert.equal(p.media_fallbacks[0].url,cdn);
 });
 await check('Feed blob player resolves its own permalink, never the whole feed',async()=>{
  const f=fixture(feed);f.setItems([player('a',null,'A',{blob:true,resourceUrl:A}),player('b',null,'B',{blob:true,resourceUrl:B})]);
  f.setFrameTarget({domId:'b'});const result=await f.receive({type:'kitty-add-download'});
  assert.equal(result.ok,true);assert.equal(f.downloads().at(-1).url,B);
 });
 await check('A visible TikTok is selected over a preloaded first player',async()=>{
  const f=fixture(feed);f.setItems([player('a',cdn,'A',{resourceUrl:A}),player('b','https://cdn.test/active.mp4','B',{resourceUrl:B})]);
  f.setFrameTarget({domId:'b'});await f.receive({type:'kitty-add-download'});
  const p=f.downloads().at(-1);assert.equal(p.url,B);assert.equal(p.media_fallbacks.length,1);
  assert.equal(p.media_fallbacks[0].url,'https://cdn.test/active.mp4');
 });
 await check('Popup selection still wins; pill and popup produce equal payloads',async()=>{
  const f=fixture(feed);f.setItems([player('a',cdn,'A',{resourceUrl:A}),player('b','https://cdn.test/active.mp4','B',{resourceUrl:B})]);
  const items=(await f.receive({type:'kitty-media-items',tabId:1},ui)).items;
  await f.receive({type:'kitty-download-settings',tabId:1,change:{itemId:items[0].id}},ui);f.setFrameTarget({domId:'b'});
  await f.receive({type:'kitty-add-download',tabId:1},ui);const popup=JSON.stringify(f.downloads().at(-1));
  await f.receive({type:'kitty-add-download'});assert.equal(JSON.stringify(f.downloads().at(-1)),popup);assert.equal(f.downloads().at(-1).url,A);
 });
 await check('Unknown blob identity cannot silently submit a TikTok feed',async()=>{
  const f=fixture(feed);f.setItems([player('unknown',null,'',{blob:true})]);f.setFrameTarget({domId:'unknown'});
  const result=await f.receive({type:'kitty-add-download'});assert.equal(result.ok,false);assert.equal(f.downloads().length,0);
 });
 for(const mode of ['720','1080','best','audio','mp3'])await check('Saved TikTok mode '+mode,async()=>{
  const f=fixture(A);f.saved.selectedMode=mode;f.setItems([player('a',cdn)]);await f.receive({type:'kitty-add-download'});
  assert.equal(f.downloads().at(-1).url,A);assert.equal(f.downloads().at(-1).mode,mode);
 });
 await check('Thumbnail mode keeps the shared page resolver',async()=>{
  const f=fixture(A);f.saved.imageOnlyMode=true;await f.receive({type:'kitty-add-download'});assert.equal(f.downloads().at(-1).mode,'image');assert.equal(f.downloads().at(-1).url,A);
 });
 console.log(`TikTok routing: ${passed} passed, ${failed} failed`);if(failed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
