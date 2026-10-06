// The pill and context menu must use the same persisted mode as the popup.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let listener;
let backendVersion='8.32';
const calls=[];
const saved={selectedMode:'mp3',imageOnlyMode:true};
const context=vm.createContext({setTimeout:()=>1,URL,browser:{
  tabs:{get:async id=>({id,url:'https://example.com/video'}),sendMessage:async()=>({ok:true,url:'https://example.com/video'})},
  runtime:{getManifest:()=>({version:'8.57'}),onMessage:{addListener:fn=>{listener=fn;}},
    sendNativeMessage:async(_host,payload)=>{
      calls.push(payload);
      return payload.action==='compatibility'
        ? {ok:true,compatibility:{compatible:true,backend_version:backendVersion}}
        : {ok:true};
    }},
  storage:{local:{get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys])
    .filter(key=>key in saved).map(key=>[key,saved[key]])),set:async values=>Object.assign(saved,values)}}
}});
for(const name of ['shared.js','background.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',name),'utf8'),context);
}
(async()=>{
  await listener({type:'kitty-add-download'},{tab:{id:1},frameId:0});
  assert.equal(calls.at(-1).mode,'image');
  assert.equal(calls.at(-1).action,'download');
  const fromMenu=await vm.runInContext('downloadFromContextMenu({pageUrl:"https://example.com/song"},{})',context);
  assert.equal(fromMenu.selectedMode,'image');
  assert.equal(calls.at(-1).mode,'image');
  saved.imageOnlyMode=false;
  await listener({type:'kitty-add-download'},{tab:{id:1},frameId:0});
  assert.equal(calls.at(-1).mode,'mp3');
  saved.imageOnlyMode=true;
  backendVersion='8.31';
  vm.runInContext('compatibilityCache=null',context);
  const before=calls.filter(call=>call.action==='download').length;
  const rejected=await listener({type:'kitty-add-download'},{tab:{id:1},frameId:0});
  assert.equal(rejected.code,'image_backend_update_required');
  assert.equal(calls.filter(call=>call.action==='download').length,before);
  console.log('Pill et clic droit : mode image, ancien format conservé et protection backend v8.31 OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
