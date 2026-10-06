// Production background + session UI -> real Windows Native Messaging launcher.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {spawn}=require('node:child_process');
if(process.platform!=='win32'||process.env.KITTY_WINDOWS_AUDIT!=='1')throw Error('Dedicated Windows audit only');
const root=process.argv[2],mode=process.argv[3]||'healthy',extension=path.resolve(__dirname,'../extension');
const traffic=[];
function native(_host,payload){return new Promise((resolve,reject)=>{
  const data=Buffer.from(JSON.stringify(payload)),frame=Buffer.alloc(4);frame.writeUInt32LE(data.length);
  const child=spawn(path.join(process.env.SystemRoot,'System32','cmd.exe'),['/d','/s','/c','.\\native-host.bat'],{cwd:root,windowsHide:true});
  const chunks=[],errors=[];child.stdout.on('data',d=>chunks.push(d));child.stderr.on('data',d=>errors.push(d));child.on('error',reject);
  const timer=setTimeout(()=>{child.kill();reject(Error('Native timeout'));},45000);
  child.on('close',code=>{clearTimeout(timer);try{
    const bytes=Buffer.concat(chunks);assert.equal(code,0,Buffer.concat(errors).toString());assert.ok(bytes.length>=4);
    assert.equal(bytes.readUInt32LE(),bytes.length-4,'exactly one binary UTF-8 frame');
    const response=JSON.parse(bytes.subarray(4).toString('utf8'));traffic.push({action:payload.action,ok:response.ok,code:response.error_code||response.code});resolve(response);
  }catch(e){reject(e);}});child.stdin.end(Buffer.concat([frame,data]));
});}
let handler;const store={};const manifest=JSON.parse(fs.readFileSync(path.join(extension,'manifest.json')));
const browser={runtime:{getManifest:()=>manifest,getURL:p=>'moz-extension://audit/'+p,sendNativeMessage:native,
  onMessage:{addListener:fn=>handler=fn},sendMessage:message=>handler(message,{url:'moz-extension://audit/popup.html'})},
  storage:{local:{get:async()=>store,set:async x=>Object.assign(store,x)}},tabs:{query:async()=>[]}};
const background=vm.createContext({browser,console,URL,Date,setTimeout,clearTimeout});
for(const file of ['shared.js','background.js'])vm.runInContext(fs.readFileSync(path.join(extension,file),'utf8'),background);
const node=()=>({textContent:'',disabled:false,hidden:false,checked:false,listeners:{},classList:{add(){},remove(){}},addEventListener(type,fn){this.listeners[type]=fn;}});
const ui={browser,nativeMessage:payload=>background.nativeMessage(payload),setTimeout,clearTimeout,
  updateCookiesHeaderState(){},formatYoutubeAuthDate(){return '';},setSettingsStatus(message,kind){ui.status=message;ui.kind=kind;}};
for(const id of ['youtubeAuthStateEl','youtubeAuthStateTextEl','youtubeAuthDetailEl','youtubeAuthHintEl','youtubeAuthConfigureBtn','youtubeAuthEnabledEl','youtubeAuthDeleteBtn'])ui[id]=node();
vm.createContext(ui);const popup=fs.readFileSync(path.join(extension,'popup.js'),'utf8');
vm.runInContext(popup.slice(popup.indexOf('let youtubeAuthLastStatus'),popup.indexOf('\nfunction compactVersion')),ui);
(async()=>{
  const settings=await handler({type:'kitty-get-output-dir'},{url:'moz-extension://audit/popup.html'});assert.equal(settings.ok,true);
  if(mode==='corrupt'){
    // No synthetic backend reply: the private package on disk is faulty.
    await ui.restoreYoutubeAuth();
    await ui.youtubeAuthConfigureBtn.listeners.click();
    assert.equal(ui.youtubeAuthStateTextEl.textContent,'Erreur');
    assert.equal(ui.youtubeAuthDetailEl.textContent,'Support des processus indisponible');
    assert.match(ui.youtubeAuthHintEl.textContent,/Réinstalle/);assert.equal(ui.youtubeAuthConfigureBtn.disabled,false);
    const status=await background.nativeMessage({action:'status'});assert.equal(status.ok,false);assert.equal(status.error_code,'process_support_invalid');
    const diagnostics=await background.nativeMessage({action:'diagnostics'});assert.equal(diagnostics.ok,true);
    assert.ok(diagnostics.dependencies.required_missing.includes('psutil'));
  }else{
    const changed=await background.nativeMessage({action:'set_output_dir',output_dir:path.join(root,'médias & 100% !')});assert.equal(changed.ok,true);
    const saved=await handler({type:'kitty-get-output-dir'},{url:'moz-extension://audit/popup.html'});
    assert.equal(saved.settings.output_dir,changed.output_dir);assert.equal(store.kittyOutputDir,changed.output_dir);
    await ui.restoreYoutubeAuth();
    ui.youtubeAuthEnabledEl.checked=true;
    await ui.youtubeAuthEnabledEl.listeners.change();
    assert.equal(ui.youtubeAuthStateTextEl.textContent,'Erreur');assert.match(ui.youtubeAuthDetailEl.textContent,/Session YouTube/);
    assert.equal(ui.youtubeAuthEnabledEl.checked,false);
    await ui.youtubeAuthDeleteBtn.listeners.click();await ui.youtubeAuthDeleteBtn.listeners.click();
    assert.equal(ui.youtubeAuthStateTextEl.textContent,'Non configurée');
    const invalid=await background.nativeMessage({action:'set_output_dir',output_dir:'relative-path'});assert.equal(invalid.ok,false);
    const queue=await background.nativeMessage({action:'pause_queue'});assert.equal(queue.ok,true);assert.equal(queue.state.queue_paused,true);
    const clear=await background.nativeMessage({action:'clear_queue'});assert.equal(clear.ok,true);
  }
  const report={platform:process.platform,mode,traffic,frontend_version:manifest.version,passed:true};
  const evidence=path.resolve(__dirname,'../artifacts/windows-audit');fs.mkdirSync(evidence,{recursive:true});
  fs.writeFileSync(path.join(evidence,mode+'-bridge.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1;});
