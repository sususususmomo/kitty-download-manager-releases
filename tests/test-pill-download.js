// Exercise production pill routing against the real scoped media catalogue.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=process.env.KITTY_TEST_EXTENSION||path.join(__dirname,'../extension');
function fixture(page) {
  let receiver,snapshot=[],rescan=async()=>{},frameTarget=null,nativeHandler=null;
  const calls=[],saved={selectedMode:'720'},event=()=>({addListener(){}});
  const sender={tab:{id:1,url:page},url:page,frameId:0};
  const browser={runtime:{getManifest:()=>({version:'8.57'}),getURL:p=>'moz-extension://kitty/'+p,
    onMessage:{addListener:f=>receiver=f},sendMessage:async()=>{},sendNativeMessage:async(h,p)=>{
      calls.push(p);if(nativeHandler)return nativeHandler(p);return p.action==='compatibility'?{ok:true,compatibility:{compatible:true,backend_version:'8.49'}}:{ok:true,job_id:'job-'+calls.length};}},
    tabs:{get:async id=>({id,url:page,title:'Page title'}),onRemoved:event(),onUpdated:event(),sendMessage:async(id,msg,options)=>{
      assert.equal(id,1);if(msg.type==='kitty-resolve-media-url')return {ok:true,url:page};if(msg.type==='kitty-media-target')return {ok:true,target:frameTarget};
      if(options)assert.equal(options.frameId,0);await rescan();receiver({type:'kitty-media-dom',items:snapshot},sender);return {ok:true};}},
    storage:{local:{get:async()=>saved,set:async values=>Object.assign(saved,values)}},webRequest:Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived','onCompleted','onErrorOccurred'].map(k=>[k,event()]))};
  const context=vm.createContext({URL,Date,setTimeout:()=>1,crypto:require('node:crypto').webcrypto,
    console:{debug(){}},browser,location:{href:'moz-extension://kitty/background.html'}});
  for(const name of ['shared.js','media-resolver.js','hls-parser.js','request-context.js','hls-detector.js','media-items.js','background.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),context);
  return {calls,saved,context,sender,setPage:url=>{page=url;sender.url=url;sender.tab.url=url;vm.runInContext('mediaItems.clear(1);hlsStore.clear(1)',context);},setNativeHandler:f=>nativeHandler=f,native:payload=>browser.runtime.sendNativeMessage('',payload),setItems:items=>snapshot=items,setRescan:f=>rescan=f,setFrameTarget:target=>frameTarget=target,
    receive:(message,from=sender)=>receiver(message,from),downloads:()=>calls.filter(p=>p.action==='download')};
}
function player(domId,source,title='',extra={}) {
  return {domId,title,titleSource:title?'caption':'',mediaKind:'video',sources:source?[{url:source,contentType:'video/mp4'}]:[],...extra};
}
async function main(){
  const page='https://gallery.test/post',a='https://cdn.test/first.mp4?signature=first',b='https://cdn.test/second.mp4?signature=second';
  const gallery=fixture(page),ui={url:'moz-extension://kitty/popup.html'};
  gallery.setItems([player('a',a,'First'),player('b',b,'Second')]);
  const items=(await gallery.receive({type:'kitty-media-items',tabId:1},ui)).items;
  await gallery.receive({type:'kitty-download-settings',tabId:1,change:{itemId:items[1].id,track_selection:{audioLanguage:'fr',subtitleLanguages:['de']}}},ui);
  const popup=await gallery.receive({type:'kitty-add-download',tabId:1},ui);
  const popupPayload=JSON.stringify(gallery.downloads().at(-1));
  const pill=await gallery.receive({type:'kitty-add-download'});
  assert.equal(JSON.stringify(gallery.downloads().at(-1)),popupPayload);
  assert.equal(popup.requestKey,pill.requestKey);assert.equal(gallery.downloads().at(-1).url,b);
  assert.equal(gallery.downloads().at(-1).track_policy,'prefer_available');
  assert.ok(gallery.downloads().at(-1).media_fallbacks.every(c=>c.media_item_id===items[1].id));
  assert.equal((await gallery.receive({type:'kitty-add-download'},{...gallery.sender,frameId:2})).ok,false);
  gallery.saved.selectedMode='mp3';
  await gallery.receive({type:'kitty-add-download',forceToken:pill.requestKey});
  assert.equal(gallery.downloads().at(-1).force,false,'Changed settings invalidate duplicate confirmation');
  const duplicate=await gallery.receive({type:'kitty-add-download'});
  await gallery.receive({type:'kitty-add-download',forceToken:duplicate.requestKey});
  assert.equal(gallery.downloads().at(-1).force,true);
  gallery.setPage('https://soundcloud.com/artist/song');
  gallery.setItems([player('audio','https://cdn.test/song.mp3','Song',{mediaKind:'audio',sources:[{url:'https://cdn.test/song.mp3',contentType:'audio/mpeg'}]})]);
  await gallery.receive({type:'kitty-add-download'});
  assert.equal(gallery.downloads().at(-1).mode,'mp3');
  assert.equal(gallery.downloads().at(-1).track_selection.subtitleLanguages[0],'de');
  assert.equal(gallery.downloads().at(-1).track_selection.audioTrackId,undefined);
  const youtube=fixture('https://www.youtube.com/watch?v=dQw4w9WgXcQ');youtube.setItems([player('youtube',a,'Video player')]);
  await youtube.receive({type:'kitty-add-download'});
  assert.equal(youtube.downloads().at(-1).url,youtube.sender.url);
  assert.equal(youtube.downloads().at(-1).media_item.prefer_extractor,true);
  const embed=fixture('https://article.test/story');embed.setItems([player('iframe',null,'Embedded clip',{embedUrl:'https://vimeo.com/123456'})]);
  await embed.receive({type:'kitty-add-download'});assert.equal(embed.downloads().at(-1).url,'https://vimeo.com/123456');
  const audio=fixture('https://music.test/listen');audio.setItems([player('audio','https://cdn.test/song.mp3','Song',{mediaKind:'audio',sources:[{url:'https://cdn.test/song.mp3',contentType:'audio/mpeg'}]})]);
  const audioResult=await audio.receive({type:'kitty-add-download'});assert.equal(audioResult.selectedMode,'audio');assert.equal(audio.saved.selectedMode,'720');
  gallery.saved.imageOnlyMode=true;await gallery.receive({type:'kitty-add-download'});
  assert.equal(gallery.downloads().at(-1).mode,'image');assert.equal(gallery.downloads().at(-1).media_item,undefined);
  const dynamic=fixture(page);dynamic.setItems([player('late',null,'Late source')]);
  dynamic.setRescan(async()=>dynamic.setItems([player('late',b,'Late source')]));
  await dynamic.receive({type:'kitty-add-download'});assert.equal(dynamic.downloads().at(-1).url,b);
  const collection=fixture('https://music.test/collection');collection.saved.playlistMode=true;
  await collection.receive({type:'kitty-download-settings',tabId:1,change:{collectionUrl:'https://music.test/sets/list'}},ui);
  await collection.receive({type:'kitty-add-download',tabId:1},ui);const playlistPayload=JSON.stringify(collection.calls.at(-1));
  await collection.receive({type:'kitty-add-download'});assert.equal(JSON.stringify(collection.calls.at(-1)),playlistPayload);
  assert.equal(collection.calls.at(-1).action,'download_playlist');
  collection.setPage('https://music.test/another-song');collection.setItems([player('song','https://cdn.test/song.mp3')]);
  await collection.receive({type:'kitty-add-download'});assert.equal(collection.calls.at(-1).action,'download','A collection URL cannot migrate to a new page');
  const opaque=fixture(page);opaque.setItems([player('one',a)]);
  const opaqueItems=(await opaque.receive({type:'kitty-media-items',tabId:1},ui)).items;
  await opaque.receive({type:'kitty-download-settings',tabId:1,change:{itemId:opaqueItems[0].id,track_selection:{audioTrackId:'specific-to-this-source',subtitleTrackIds:['specific-caption']}}},ui);
  opaque.setPage('https://other.test/song');opaque.setItems([player('new',b)]);await opaque.receive({type:'kitty-add-download'});
  assert.equal(opaque.downloads().at(-1).track_selection.audioTrackId,undefined);
  assert.equal(opaque.downloads().at(-1).track_selection.subtitleTrackIds,undefined);
  const batch=fixture(page);batch.setItems([player('v',a),player('s','https://cdn.test/song.mp3','Song',{mediaKind:'audio',sources:[{url:'https://cdn.test/song.mp3',contentType:'audio/mpeg'}]})]);
  const batchItems=(await batch.receive({type:'kitty-media-items',tabId:1},ui)).items;
  const result=await batch.receive({type:'kitty-download-items',tabId:1,mode:'720',itemIds:batchItems.map(i=>i.id),
    trackSelections:Object.fromEntries(batchItems.map(i=>[i.id,{subtitleLanguages:['de']}]))},ui);
  assert.equal(result.added,2);assert.deepEqual(batch.downloads().map(p=>p.mode),['720','audio']);
  assert.ok(batch.downloads().every(p=>p.track_policy==='prefer_available'));
  console.log('PASS shared dispatch: identical requests, closed-popup preferences, selected gallery item, page isolation, quality/MP3/image, extractors, late sources and duplicate confirmation.');
}
module.exports={fixture,player};
if(require.main===module)main().catch(error=>{console.error(error);process.exitCode=1;});
