#!/usr/bin/env python3
"""Real Firefox extension + Native Messaging HLS test in isolated test directories.
Requires Selenium, Firefox >=140, geckodriver and yt-dlp/FFmpeg. Linux runner only.
Temporarily registers Kitty's native manifest; restores it even if assertions fail.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT=Path(__file__).resolve().parents[1]
EXTENSION_ROOT=Path(os.environ.get('KITTY_TEST_EXTENSION',ROOT/'extension'))
REPRODUCTION=os.environ.get('KITTY_TEST_PILL_REPRODUCTION')=='1'
EQUIVALENCE=REPRODUCTION or os.environ.get('KITTY_TEST_DOWNLOAD_EQUIVALENCE')=='1'
ITEMS=os.environ.get('KITTY_TEST_MEDIA_ITEMS')=='1'
TRACKS=os.environ.get('KITTY_TEST_MEDIA_TRACKS')
CONTEXT=os.environ.get('KITTY_TEST_REQUEST_CONTEXT')=='1'
CONTEXT_ONLY=CONTEXT or os.environ.get('KITTY_TEST_REQUEST_CONTEXT_ONLY')=='1'
DASH=os.environ.get('KITTY_TEST_DASH')=='1'
DIRECT=os.environ.get('KITTY_TEST_DIRECT')=='1'
GROUPS=os.environ.get('KITTY_TEST_HLS_GROUPS')=='1'
AUTOMATIC=os.environ.get('KITTY_TEST_AUTOMATIC')=='1'
OUTPUT=ROOT/('artifacts/download-equivalence' if EQUIVALENCE else 'artifacts/media-tracks-'+TRACKS if TRACKS else 'artifacts/media-items' if ITEMS else 'artifacts/automatic' if AUTOMATIC else 'artifacts/hls-groups' if GROUPS else 'artifacts/direct' if DIRECT else 'artifacts/dash' if DASH else 'artifacts/hls');OUTPUT.mkdir(parents=True,exist_ok=True)
assert sys.platform.startswith('linux'), 'This isolated native-host registration fixture is for Linux.'
spec=importlib.util.spec_from_file_location('networkfixtures',ROOT/('tests/test-media-item-download.py' if ITEMS else 'tests/test-automatic-download.py' if AUTOMATIC else 'tests/test-hls-group-download.py' if GROUPS else 'tests/test-direct-download.py' if DIRECT else 'tests/test-dash-download.py' if DASH else 'tests/test-hls-download.py'));fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
test=fixtures.MediaItemTests if ITEMS else fixtures.AutomaticTests if AUTOMATIC else fixtures.HlsGroupTests if GROUPS else fixtures.DirectTests if DIRECT else fixtures.DashTests if DASH else fixtures.HlsTests
if TRACKS:
 spec=importlib.util.spec_from_file_location('trackfixtures',ROOT/'tests/test-media-track-download.py');fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
 test=fixtures.HlsTracks if TRACKS=='hls' else fixtures.DashTracks
test.setUpClass()
if EQUIVALENCE:
 subprocess.run(['ffmpeg','-v','error','-i',str(test.media/'normal.mp4'),'-vn','-c:a','copy',str(test.media/'native.m4a')],check=True,timeout=20)
 original_response=test.extra_response
 def equivalence_response(cls,url,headers):
  if url.split('?')[0]=='/native.m4a':return 200,'audio/mp4',(cls.media/'native.m4a').read_bytes()
  return original_response(url,headers)
 test.extra_response=classmethod(equivalence_response)
report={'checks':[]}
driver=None
context_server=None
context_seen=[]
registry=Path.home()/'.mozilla/native-messaging-hosts/com.kitty.download_manager.json'
# A machine has one manifest for this native host. Parallel fixtures must not
# redirect each other's Firefox native messages to another temporary queue.
import fcntl
native_registry_lock=open('/tmp/kitty-native-firefox-qa.lock','a')
fcntl.flock(native_registry_lock,fcntl.LOCK_EX)
original=registry.read_bytes() if registry.exists() else None
try:
 with tempfile.TemporaryDirectory(prefix='kitty-hls-firefox-') as temp:
  scratch=Path(temp);native=scratch/'native';native.mkdir();cache=scratch/'cache';cache.mkdir();out=scratch/'downloads';out.mkdir()
  # Test-only launchers patch filesystem roots before invoking production modules.
  common=f'''import sys
from pathlib import Path
sys.path.insert(0,{str(ROOT/'native-host')!r})
import runtime_storage
cache=Path({str(cache)!r})
runtime_storage.CACHE_DIR=cache
runtime_storage.LOG_FILE=cache/'worker.log'
runtime_storage.LOG_LOCK_FILE=cache/'worker.log.lock'
'''
  for module in ('host','worker','metadata'):
   script=native/(module+'.py')
   text=common+f'''import {module} as target
for name,value in {{'CACHE_DIR':cache,'QUEUE_FILE':cache/'queue.json','LOCK_FILE':cache/'queue.lock','CONTROL_DIR':cache/'controls','CONFIG_DIR':cache/'config','SETTINGS_FILE':cache/'config/settings.json','DEFAULT_OUTPUT_DIR':Path({str(out)!r}),'INSTALL_DIR':Path({str(native)!r}),'WORKER':Path({str(native/'worker.py')!r}),'META_WORKER':Path({str(native/'metadata.py')!r}),'LOG_FILE':cache/'worker.log','AUTH_JOB_DIR':cache/'auth-jobs'}}.items():
 if hasattr(target,name):setattr(target,name,value)
'''
   if module=='host' and ITEMS:
    text+='import faulthandler\ntrace=open(cache/"native-stacks.log","a")\nfaulthandler.dump_traceback_later(8,file=trace)\n'
   text+=('target.main()\n' if module=='host' else 'raise SystemExit(target.main())\n')
   script.write_text('#!'+sys.executable+'\n'+text);script.chmod(0o755)
  registry.parent.mkdir(parents=True,exist_ok=True)
  registry.write_text(json.dumps({'name':'com.kitty.download_manager','description':'Isolated Kitty HLS QA','path':str(native/'host.py'),'type':'stdio','allowed_extensions':['kitty-download-manager@local']}))
  harness_js=r'''
window.qa=async function(action,args={}) {
 const popup=()=>browser.extension.getViews({type:'popup'}).find(v=>v.location.pathname==='/popup.html');
 if(action==='items'){const bg=await browser.runtime.getBackgroundPage();return (await bg.itemsForTab(window.testTab)).map(bg.publicItem);}
 if(action==='stored-dom'){const bg=await browser.runtime.getBackgroundPage();return bg.qaStoredDom(window.testTab);}
 if(action==='association-logs'){const bg=await browser.runtime.getBackgroundPage();return bg.qaAssociationLogs();}
 if(action==='clickstate')return {disabled:popup()?.document.getElementById('download')?.disabled,item:popup()?.KittyItemsPopup?.selection(window.testTab)};
 if(action==='single')return {visible:!popup()?.document.getElementById('mediaSingle')?.hidden,technicalHidden:popup()?.document.getElementById('hlsPanel')?.hidden};
 if(action==='images')return Array.from(popup()?.document.querySelectorAll('#mediaRows img')||[],el=>({complete:el.complete,width:el.naturalWidth,src:el.src}));
 if(action==='rows')return Array.from(popup()?.document.querySelectorAll('.mediaTitle')||[],el=>el.textContent);
 if(action==='selection'){const d=popup().document;return {all:d.getElementById('mediaSelectAll').textContent,batchDisabled:d.getElementById('mediaBatch').disabled,rows:Array.from(d.querySelectorAll('.mediaRow'),row=>{const c=row.querySelector('input'),r=c.getBoundingClientRect();return {id:c.dataset.itemId,checked:c.checked,disabled:c.disabled,pointerEvents:popup().getComputedStyle(c).pointerEvents,hit:d.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===c,detail:row.querySelector('small').textContent};})};}
 if(action==='check'){popup().document.querySelectorAll('.mediaRow input')[args.index||0].click();return true;}
 if(action==='row'){popup().document.querySelectorAll('.mediaChoose')[args.index||0].click();return true;}
 if(action==='all'){popup().document.getElementById('mediaSelectAll').click();return true;}
 if(action==='addbatch'){popup().document.getElementById('mediaBatch').click();return true;}
 if(action==='drawer'){popup().document.getElementById('mediaCount').click();return true;}
 if(action==='batch'){popup().document.getElementById('mediaSelectAll').click();popup().document.getElementById('mediaBatch').click();return true;}
 if(action==='native')return browser.runtime.sendNativeMessage('com.kitty.download_manager',args.payload);
 if(action==='dom'){return browser.tabs.sendMessage(window.testTab,{type:'qa-dom',html:args.html,mutate:args.mutate});}
 if(action==='update'){return browser.tabs.sendMessage(window.testTab,{type:'qa-update',index:args.index||0,attrs:args.attrs});}
 if(action==='clone'){return browser.tabs.sendMessage(window.testTab,{type:'qa-clone'});}
 if(action==='scan'){return browser.tabs.sendMessage(window.testTab,{type:'qa-scan'});}
 if(action==='tab'){const t=await browser.tabs.create({url:args.url,active:true});window.testTab=t.id;return t.id;}
 if(action==='navigate'){await browser.tabs.update(window.testTab,{url:args.url,active:true});return true;}
 if(action==='switch'){window.testTab=args.tabId;await browser.tabs.update(window.testTab,{active:true});return true;}
 if(action==='activate'){await browser.tabs.update(window.testTab,{active:true});return true;}
 if(action==='open'){await browser.action.openPopup();return true;}
 if(action==='close'){popup()?.close();return true;}
 if(action==='options')return popup()?.document.getElementById('hlsSource')?.options.length || 0;
 if(action==='labels')return Array.from(popup()?.document.getElementById('hlsSource')?.options || [],o=>o.textContent);
 if(action==='phase')return popup()?.document.getElementById('status')?.textContent || '';
 if(action==='detail')return popup()?.document.getElementById('hlsDetail')?.textContent || '';
 if(action==='source'){const v=popup(),s=v.document.getElementById('hlsSource');s.value=args.id || s.options[args.index || 1].value;s.dispatchEvent(new v.Event('change',{bubbles:true}));return true;}
 if(action==='mode')return popup()?.document.getElementById('mode')?.value;
 if(action==='ready')return Boolean(popup()&&!popup().document.documentElement.classList.contains('popup-loading'));
 if(action==='saved-mode')return (await browser.storage.local.get('selectedMode')).selectedMode;
 if(action==='catalogue'){const bg=await browser.runtime.getBackgroundPage();return (await bg.hlsForTab(args.tabId || window.testTab)).map(c=>({id:c.id,type:c.type,metadata:c.metadata,hls:c.hls && {kind:c.hls.kind,maxResolution:c.hls.maxResolution,variants:c.hls.variants.length,audioTracks:c.hls.audioTracks.length,subtitles:c.hls.subtitles.length},variants:c.variants?.length || 1}));}
 if(action==='diagnostics'){const bg=await browser.runtime.getBackgroundPage();return bg.qaHlsDiagnostics(Boolean(args.full));}
 if(action==='sourceurl')return popup()?.document.querySelector('#activeSource [data-open-source]')?.dataset.openSource || '';
 if(action==='preferences'){const bg=await browser.runtime.getBackgroundPage();return bg.serialDownloadOperation(()=>bg.downloadSettings(window.testTab));}
 if(action==='spa')return browser.tabs.sendMessage(window.testTab,{type:'qa-spa',url:args.url});
 if(action==='senders'){const bg=await browser.runtime.getBackgroundPage();return bg.qaSenders;}
 if(action==='empty-catalogue'){const bg=await browser.runtime.getBackgroundPage();return bg.qaEmptyCatalogue(window.testTab);}
 if(action==='pill'){return browser.tabs.sendMessage(window.testTab,{type:'qa-pill-click'});}
 if(action==='pill-state'){return browser.tabs.sendMessage(window.testTab,{type:'qa-pill-state'});}
 if(action==='pill-detail'){return browser.tabs.sendMessage(window.testTab,{type:'qa-pill-detail'});}
 if(action==='style'){await browser.storage.local.set({pillEnabled:true,pillScope:'all',pillStyle:args.style,uiLanguage:args.language});return true;}
 if(action==='mode-click'){const v=popup();v.document.querySelector('.modeMenuItem[data-mode="'+args.mode+'"]').click();return true;}
 if(action==='download'){popup().document.getElementById('download').click();return true;}
 if(action==='tracks'){const d=popup()?.document;return {hidden:d?.getElementById('mediaTracks')?.hidden,audio:Array.from(d?.querySelectorAll('#mediaAudioTrack option')||[],e=>({id:e.value,label:e.textContent})),selected:d?.getElementById('mediaAudioTrack')?.value,subtitles:Array.from(d?.querySelectorAll('#mediaTracks input')||[],e=>({id:e.dataset.trackId,checked:e.checked})),selection:popup()?.KittyItemsPopup?.trackSelection(window.testTab)};}
 if(action==='audio-track'){const v=popup(),s=v.document.getElementById('mediaAudioTrack');s.value=args.id||'';s.dispatchEvent(new v.Event('change',{bubbles:true}));return true;}
 if(action==='subtitle-track'){const c=popup().document.querySelector('#mediaTracks input');if(args.checked===undefined||c.checked!==args.checked)c.click();return true;}
 if(action==='mode-change'){const v=popup();v.document.querySelector('.modeMenuItem[data-mode="'+args.mode+'"]').click();return true;}
 if(action==='status')return browser.runtime.sendNativeMessage('com.kitty.download_manager',{action:'status'});
 if(action==='context-summary'){const bg=await browser.runtime.getBackgroundPage();const c=(await bg.hlsForTab(window.testTab))[0];return {id:c.id,headers:Object.keys(c.requestContext?.headers||{}),session:Boolean(c.requestContext?.cookies)};}
 if(action==='context-download'){const bg=await browser.runtime.getBackgroundPage();return bg.chosenHls({type:'kitty-download-media',tabId:window.testTab,candidateId:args.id,mode:'best'});}
 if(action==='fetch'){await browser.tabs.sendMessage(window.testTab,{type:'qa-fetch',urls:args.urls});return true;}
 if(action==='blob'){await browser.tabs.sendMessage(window.testTab,{type:'qa-blob',url:args.url});return true;}
 if(action==='remove'){await browser.tabs.remove(window.testTab);return true;}
 if(action==='prepare'){await browser.storage.local.set({selectedMode:args.mode || '720',uiLanguage:'fr'});return true;}
 if(action==='reset-download-settings'){await browser.storage.local.remove(['selectedMode','imageOnlyMode','playlistMode','kittyTrackPreferences','kittyDownloadTargets']);return true;}
};
'''
  # A test-only content listener loads manifests as a browser player would.
  content_js='''browser.runtime.onMessage.addListener(async m=>{
   if(m.type==="qa-spa"){history.pushState({},'',m.url);return location.href;}
   if(m.type==="qa-pill-click"){const b=globalThis.qaPillShadow?.getElementById('download');if(!b)throw Error('Pill not mounted');b.click();return true;}
   if(m.type==="qa-pill-detail")return {state:globalThis.qaPillShadow?.getElementById('pill')?.dataset.state,title:globalThis.qaPillShadow?.getElementById('download')?.title};
   if(m.type==="qa-pill-state")return globalThis.qaPillShadow?.getElementById('pill')?.dataset.state || null;
   if(m.type==="qa-scan")return KittyMediaDOM.scan();
  if(m.type==="qa-dom"){if(m.mutate)document.body.insertAdjacentHTML('beforeend',m.html);else document.body.innerHTML=m.html;return true;}
  if(m.type==="qa-clone"){for(const v of document.querySelectorAll('video')){const clone=v.cloneNode();clone.id=v.id+'_placeholder';clone.setAttribute('disabled','');clone.removeAttribute('src');v.replaceWith(clone);}return true;}
  if(m.type==="qa-update"){const v=document.querySelectorAll('video')[m.index];for(const [key,value] of Object.entries(m.attrs))if(value===null)v.removeAttribute(key);else v.setAttribute(key,value);return true;}
   if(m.type==="qa-fetch"){for(const item of m.urls){const url=typeof item==='string'?item:item.url;await fetch(url,{credentials:"include",headers:{...(item.headers||{}),...(item.range?{Range:item.range}:{})}}).then(r=>r.arrayBuffer());}return true;}
   if(m.type==="qa-blob"){const body=m.url?await fetch(m.url).then(r=>r.blob()):new Blob([new Uint8Array(16)],{type:'video/mp4'});const v=document.createElement('video');v.src=URL.createObjectURL(body);document.body.append(v);return true;}
  });'''
  xpi=scratch/'test.xpi'
  with zipfile.ZipFile(xpi,'w',zipfile.ZIP_DEFLATED) as z:
   for p in EXTENSION_ROOT.rglob('*'):
    if p.is_file() and p.name!='manifest.json':
     if EQUIVALENCE and p.name=='content-pill.js':
      # Only expose its closed shadow tree to the QA listener. Event handlers,
      # dispatch and production settings code remain byte-for-byte unchanged.
      z.writestr('content-pill.js',p.read_text().replace('shadow = host.attachShadow({ mode: "closed" });','shadow = host.attachShadow({ mode: "closed" }); globalThis.qaPillShadow = shadow;'))
     else:z.write(p,p.relative_to(EXTENSION_ROOT))
   manifest=json.loads((EXTENSION_ROOT/'manifest.json').read_text());manifest['content_scripts'].append({'matches':['http://127.0.0.1/*'],'js':['qa-content.js'],'run_at':'document_idle'})
   manifest['background']['scripts'].append('qa-background.js')
   z.writestr('qa-background.js','''function qaEmptyCatalogue(tabId){hlsStore.clear(tabId);mediaItems.clear(tabId);return true;}globalThis.qaSenders=[];browser.runtime.onMessage.addListener((m,s)=>{if(m?.type==='kitty-add-download'||m?.type==='kitty-media-dom')qaSenders.push({type:m.type,url:s.url,tabUrl:s.tab?.url,documentId:s.documentId,frameId:s.frameId});});const qaRequests=[];const qaNative=nativeMessage;nativeMessage=async function(p){const row={action:p.action,url:p.url?new URL(p.url).pathname:null,item:p.media_item?.id};qaRequests.push(row);row.payload=p.action==='download'?JSON.parse(JSON.stringify(p)):null;try{const r=await qaNative(p);row.ok=r?.ok;row.code=r?.code;row.error=r?.error;return r;}catch(e){row.error=String(e);throw e;}};function qaHlsDiagnostics(full=false){return {parser:Boolean(globalThis.KittyHlsParser),reader:hlsReader?.stats,active:hlsReader?.active.size,requests:full?qaRequests:qaRequests.map(({payload,...r})=>r)};}function qaStoredDom(tabId){return Array.from(mediaItems.tabs.get(tabId)?.frames.values()||[]).flatMap(f=>f.items.map(i=>i.domId));}const qaAssociations=[];const qaMediaLog=mediaItems?.log;if(mediaItems)mediaItems.log=(event,data)=>{qaAssociations.push(data);if(qaAssociations.length>1000)qaAssociations.shift();qaMediaLog(event,data);};function qaAssociationLogs(){return qaAssociations;}''')
   z.writestr('manifest.json',json.dumps(manifest));z.writestr('qa-content.js',content_js)
   z.writestr('hls-harness.html','<!doctype html><html><script src="hls-harness.js"></script><body>Isolated HLS QA</body></html>');z.writestr('hls-harness.js',harness_js)
  options=Options();options.binary_location=os.environ['KITTY_FIREFOX_BINARY'];options.add_argument('-headless')
  options.set_preference('extensions.openPopupWithoutUserGesture.enabled',True);options.set_preference('ui.popup.disable_autohide',True)
  options.set_preference('network.proxy.type',0)
  os.environ['MOZ_DISABLE_CONTENT_SANDBOX']='1';os.environ['MOZ_DISABLE_RDD_SANDBOX']='1'
  service=Service(os.environ['KITTY_GECKODRIVER'],service_args=['--allow-system-access'],log_output=str(OUTPUT/'geckodriver.log'))
  driver=webdriver.Firefox(options=options,service=service);driver.set_script_timeout(25);driver.set_window_size(1100,800)
  report['firefox']=driver.capabilities.get('browserVersion');driver.install_addon(str(xpi),temporary=True)
  with driver.context(driver.CONTEXT_CHROME):
   extension_host=WebDriverWait(driver,15).until(lambda d:d.execute_script("return WebExtensionPolicy.getByID('kitty-download-manager@local')?.mozExtensionHostname"))
  driver.get(f'moz-extension://{extension_host}/hls-harness.html')
  def command(action,**args):
   return driver.execute_async_script('const [action,args,done]=arguments;window.qa(action,args).then(v=>done({ok:true,value:v}),e=>done({ok:false,error:String(e)}));',action,args)
  def value(action,**args):
   result=command(action,**args);assert result['ok'],result;return result.get('value')
  def wait(predicate):
   try:return WebDriverWait(driver,40,poll_frequency=.2).until(lambda d:predicate())
   except Exception:
    if (cache/'worker.log').exists():(OUTPUT/'worker-failure.log').write_bytes((cache/'worker.log').read_bytes())
    if (cache/'native-stacks.log').exists():(OUTPUT/'native-stacks.log').write_bytes((cache/'native-stacks.log').read_bytes())
    try:(OUTPUT/'state-failure.json').write_text(json.dumps({'state':value('status'),'phase':value('phase'),'single':value('single'),'click':value('clickstate'),'diagnostics':value('diagnostics',full=ITEMS)},ensure_ascii=False,indent=2))
    except Exception:pass
    raise
  def finished(previous=None):
   result=value('status');history=result.get('state',{}).get('history',[])
   return history[0] if history and history[0].get('status') in ('finished','error') and history[0]['id']!=previous else False
  def streams(entry):
   assert entry['status']=='finished',entry
   media=Path(entry['filepath']);assert media.is_file()
   return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(media)],timeout=15))['streams']
  def verify_context(previous_id,spa=False):
   global context_server
   class ContextHandler(BaseHTTPRequestHandler):
    def cors(self):
     self.send_header('Access-Control-Allow-Origin',test.base);self.send_header('Access-Control-Allow-Credentials','true')
    def do_OPTIONS(self):
     self.send_response(204);self.cors();self.send_header('Access-Control-Allow-Headers','authorization,x-media-key');self.end_headers()
    def do_GET(self):
     headers={name:self.headers.get(name) for name in ['Referer','Origin','User-Agent','Cookie','Authorization','X-Media-Key']};context_seen.append(headers)
     allowed=headers.get('Referer')==test.base+'/' and headers.get('Origin')==test.base and 'context_session=PRIVATE-CONTEXT-SESSION' in (headers.get('Cookie') or '') and headers.get('Authorization')=='Bearer PRIVATE-CONTEXT-AUTH' and headers.get('X-Media-Key')=='PRIVATE-CONTEXT-KEY'
     data=(test.media/'normal.mp4').read_bytes() if allowed else b'Context required'
     self.send_response(200 if allowed else 403);self.cors();self.send_header('Content-Type','video/mp4' if allowed else 'text/plain');self.send_header('Content-Length',str(len(data)));self.end_headers()
     try:self.wfile.write(data)
     except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass
   context_server=ThreadingHTTPServer(('127.0.0.1',0),ContextHandler)
   threading.Thread(target=context_server.serve_forever,daemon=True).start()
   value('navigate',url=test.base+'/unsupported?request-context');wait(lambda:value('catalogue')==[]);time.sleep(.6)
   context_page=test.base+'/unsupported?request-context'
   if spa:
    context_page=test.base+'/unsupported?request-context-spa';value('spa',url=context_page);time.sleep(.3)
   harness_handle=driver.current_window_handle
   source_handle=None
   for handle in driver.window_handles:
    driver.switch_to.window(handle)
    if driver.current_url==context_page:source_handle=handle;break
   assert source_handle,'Source page tab missing'
   loaded=driver.execute_async_script("const [url,done]=arguments;document.cookie='context_session=PRIVATE-CONTEXT-SESSION; path=/';fetch(url,{credentials:'include',headers:{Authorization:'Bearer PRIVATE-CONTEXT-AUTH','X-Media-Key':'PRIVATE-CONTEXT-KEY'}}).then(async r=>{await r.arrayBuffer();done({ok:r.ok,status:r.status});}).catch(()=>done({ok:false,error:'page_fetch_failed'}));",f'http://127.0.0.1:{context_server.server_port}/protected.mp4')
   driver.switch_to.window(harness_handle)
   assert loaded['ok'],loaded
   wait(lambda:bool(context_seen))
   assert context_seen and all(h.get('Authorization')=='Bearer PRIVATE-CONTEXT-AUTH' and 'context_session=PRIVATE-CONTEXT-SESSION' in (h.get('Cookie') or '') and h.get('Referer')==test.base+'/' and h.get('Origin')==test.base for h in context_seen),{'requests':len(context_seen),'signals':[{name:bool(h.get(name)) for name in ['Referer','Origin','User-Agent','Cookie','Authorization']} for h in context_seen]}
   wait(lambda:len(value('catalogue'))==1)
   summary=value('context-summary');assert summary['session'] and {'Referer','Origin','User-Agent','Authorization','x-media-key'}.issubset(summary['headers']),summary
   if spa:
    value('dom',html=f'<video preload="none" src="http://127.0.0.1:{context_server.server_port}/protected.mp4"></video>')
    value('pill')
   else:
    result=value('context-download',id=summary['id']);assert result['ok'],result
   entry=wait(lambda:finished(previous_id));streams(entry)
   assert context_seen and all(h.get('Authorization')=='Bearer PRIVATE-CONTEXT-AUTH' for h in context_seen),len(context_seen)
   assert all(h.get('User-Agent')==context_seen[0].get('User-Agent') for h in context_seen)
   assert 'PRIVATE-CONTEXT' not in json.dumps(value('status'))
   report['checks'].append('Real Firefox captures Referer/Origin/User-Agent, cookie, Authorization and application header; common RequestContext reaches protected direct probe and transfer; valid file and secret-free native status')


  value('prepare',mode='1080' if GROUPS else '720');original_tab=value('tab',url=test.base+'/unsupported');time.sleep(.5)
  if REPRODUCTION:
   # No popup has ever been opened in this browser session.
   value('reset-download-settings')
   value('navigate',url=test.base+'/normal');time.sleep(.8)
   value('pill');cold=wait(finished);cold_streams=streams(cold)
   assert cold['mode']=='1080',cold
   report['checks'].append('Cold pill with never-opened popup creates and completes a real native job')
   wait(lambda:value('pill-state')=='idle');value('native',payload={'action':'clear_history'})
   value('spa',url=test.base+'/normal?spa-second');time.sleep(.4)
   report['sendersBeforeSPA']=value('senders')
   report['pillBeforeSPA']=value('pill-state')
   value('pill');time.sleep(.5);report['spaClick']=value('pill-detail');report['sendersAfterSPA']=value('senders');spa=wait(finished);streams(spa)
   report['checks'].append('Real same-document navigation produces a completed download from pill')
   report['senders']=value('senders')
   report['coldRequest']=[r['payload'] for r in value('diagnostics',full=True)['requests'] if r.get('payload')][0]
   report['spaRequest']=[r['payload'] for r in value('diagnostics',full=True)['requests'] if r.get('payload')][-1]
   assert report['spaRequest']['media_item']['page_url']==test.base+'/normal?spa-second'
   # Clear a completed job before the pill has necessarily consumed it.
   value('native',payload={'action':'clear_history'});wait(lambda:value('pill-state')=='idle')
   report['checks'].append('Removing an accepted job from history releases pill tracking')
   value('open');wait(lambda:value('ready'));value('mode-click',mode='mp3');wait(lambda:value('saved-mode')=='mp3');value('close')
   before=len([r for r in value('diagnostics',full=True)['requests'] if r.get('payload')])
   value('pill');value('pill');audio=wait(finished);audio_streams=streams(audio)
   after=len([r for r in value('diagnostics',full=True)['requests'] if r.get('payload')])
   assert after==before+1,(before,after)
   assert audio['mode']=='mp3' and {s['codec_type'] for s in audio_streams}=={'audio'},audio
   report['checks'].append('Popup MP3 setting survives closure; two rapid pill clicks enqueue one actual transfer')
   wait(lambda:value('pill-state')=='idle');value('native',payload={'action':'clear_history'})
   # Real missing Native Host, with restoration for the recovery click.
   launcher=native/'host.py';disabled=native/'host.py.disabled';launcher.rename(disabled)
   try:
    value('pill');wait(lambda:value('pill-state')=='error');time.sleep(3)
    detail=value('pill-detail');assert detail['state']=='error' and 'Diagnostic:' in detail['title'],detail
    report['nativeHostFailure']=detail
   finally:disabled.rename(launcher)
   value('pill');recovery=wait(finished);streams(recovery)
   report['checks'].append('Real Native Host unavailable error persists, exposes its diagnostic ID and recovers on explicit retry')
   wait(lambda:value('pill-state')=='idle');value('native',payload={'action':'clear_history'})
   second=value('tab',url=test.base+'/normal');time.sleep(.5)
   value('pill');tab_job=wait(finished);streams(tab_job)
   assert tab_job['media_item']['page_url']==test.base+'/normal'
   value('switch',tabId=original_tab);assert value('pill-state')=='idle'
   report['checks'].append('Two tabs keep native job target and pill state isolated')
   value('switch',tabId=second);wait(lambda:value('pill-state')=='idle');value('native',payload={'action':'clear_history'})
   value('navigate',url=test.base+'/normal?extractor-only');time.sleep(.5)
   value('dom',html='<p>Page with no initialized player</p>');value('empty-catalogue')
   value('pill');extracted=wait(finished);streams(extracted)
   assert extracted['url']==test.base+'/normal?extractor-only' and extracted['selected_source_type']=='ytdlp',extracted
   report['checks'].append('Pill without DOM metadata downloads a supported page through the real yt-dlp extractor')
   wait(lambda:value('pill-state')=='idle');value('native',payload={'action':'clear_history'})
   value('navigate',url=test.base+'/unsupported?metadata-error');time.sleep(.5)
   value('dom',html='<video src="/expired.m3u8"></video>');value('pill');failed=wait(finished)
   assert failed['status']=='error',failed
   wait(lambda:value('pill-state')=='error');time.sleep(3);detail=value('pill-detail')
   assert detail['state']=='error' and failed.get('error') in detail['title'],detail
   report['metadataFailure']={k:failed.get(k) for k in ('status','error_code','error','error_detail')}
   report['checks'].append('Actual failed metadata/source produces a persistent pill error from the tracked backend job')
   value('native',payload={'action':'clear_history'});verify_context(None,spa=True)
   report['checks'].append('After same-document navigation, pill preserves captured Authorization/cookie/header context and completes a real protected transfer')
  elif EQUIVALENCE:
   def clear_equivalence_history():
    # Let the visible pill consume completion before removing that job from
    # history. Clearing it first can strand its test-only tracked job ID.
    value('close');value('activate')
    wait(lambda:value('pill-state') in ('idle','finished','duplicate','error'))
    value('native',payload={'action':'clear_history'})
   report['pairs']=[]
   for style in ('minimal','cat','classic'):
    for language in ('fr','en'):
     value('close');value('style',style=style,language=language)
     value('navigate',url=test.base+'/unsupported?'+style+'-'+language);time.sleep(.6)
     value('dom',html=f'<figure><video controls preload="none" src="{test.track_path}"></video><figcaption>Multilingual player</figcaption></figure>')
     value('fetch',urls=[test.base+test.track_path]);wait(lambda:len(value('items'))==1)
     value('open');wait(lambda:len(value('tracks')['audio'])==3)
     french=next(t['id'] for t in value('tracks')['audio'] if t['label'].startswith('fr'))
     value('audio-track',id=french);value('subtitle-track',checked=True);value('mode-click',mode='mp3')
     preference=value('preferences');assert preference['trackPreferences']=={'audioLanguage':'fr','subtitleLanguages':['fr']},preference
     previous=value('status')['state']['history'][0]['id'] if value('status')['state']['history'] else None
     value('download');first=wait(lambda:finished(previous));first_streams=streams(first)
     first_payload=[r['payload'] for r in value('diagnostics',full=True)['requests'] if r.get('payload')][-1]
     assert first_streams[0]['codec_name']=='mp3' and {t['codec_type'] for t in first_streams}=={'audio'},first_streams
     assert first['download_plan']['audioLanguage']=='fr' and first['download_plan']['subtitleLanguages']==['fr'],first
     clear_equivalence_history();value('close');time.sleep(.3)
     wait(lambda:value('pill-state') in ('idle','finished','duplicate','error'));value('pill')
     second=wait(finished);second_streams=streams(second)
     second_payload=[r['payload'] for r in value('diagnostics',full=True)['requests'] if r.get('payload')][-1]
     assert first_payload==second_payload,{'popup':first_payload,'pill':second_payload}
     assert second_streams[0]['codec_name']=='mp3' and second['download_plan']['audioLanguage']=='fr',second
     assert second['download_plan']['subtitleLanguages']==['fr'],second
     report['pairs'].append({'style':style,'language':language,'requestsIdentical':True,'closedPopup':True,
        'popupCodec':first_streams[0]['codec_name'],'pillCodec':second_streams[0]['codec_name'],
        'audioLanguage':second['download_plan']['audioLanguage'],'subtitleLanguages':second['download_plan']['subtitleLanguages']})
     clear_equivalence_history()
   # This DASH fixture advertises a single 1080p representation; 720p is
   # correctly unavailable. The HLS fixture covers both quality choices.
   quality_cases=(('best',1080),) if TRACKS=='dash' else (('720',720),('best',1080))
   for mode,height in quality_cases:
    value('open');wait(lambda:len(value('tracks')['audio'])==3);value('mode-click',mode=mode)
    value('preferences');value('download');video_popup=wait(finished);video_streams=streams(video_popup)
    payload=[r['payload'] for r in value('diagnostics',full=True)['requests'] if r.get('payload')][-1]
    assert next(t['height'] for t in video_streams if t['codec_type']=='video')==height,video_streams
    clear_equivalence_history();value('close');wait(lambda:value('pill-state') in ('idle','finished','duplicate','error'));value('pill')
    video_pill=wait(finished);pill_streams=streams(video_pill)
    assert next(t['height'] for t in pill_streams if t['codec_type']=='video')==height,pill_streams
    assert payload==[r['payload'] for r in value('diagnostics',full=True)['requests'] if r.get('payload')][-1]
    report['checks'].append('Popup and pill both produce '+str(height)+'p video with audio and captions for mode '+mode)
    clear_equivalence_history()
   value('open');wait(lambda:len(value('tracks')['audio'])==3);value('mode-click',mode='mp3');value('preferences');value('close')
   # A new audio-only page has no subtitle options. Preferences survive, and
   # the native planner adapts the actual tracks before converting to MP3.
   value('navigate',url=test.base+'/unsupported?audio-only');time.sleep(.6)
   value('dom',html='<figure><audio controls preload="none" src="/native.m4a"></audio><figcaption>Audio-only song</figcaption></figure>')
   value('fetch',urls=[test.base+'/native.m4a']);wait(lambda:len(value('items'))==1)
   wait(lambda:value('pill-state') in ('idle','finished','duplicate','error'));value('pill');audio_entry=wait(finished);audio_streams=streams(audio_entry)
   assert audio_streams[0]['codec_name']=='mp3' and {t['codec_type'] for t in audio_streams}=={'audio'},audio_streams
   assert audio_entry['download_plan']['subtitleLanguages']==[],audio_entry
   assert value('preferences')['trackPreferences']['subtitleLanguages']==['fr']
   report['checks'].append('Actual popup controls and closed-popup pill: identical native requests and real MP3/French audio/French captions for every variant and language; audio-only page safely ignores unavailable tracks while retaining preferences')
  elif CONTEXT_ONLY:verify_context(None)
  elif TRACKS:
   value('prepare',mode='best');value('dom',html=f'<figure><video controls preload="none" src="{test.track_path}"></video><figcaption>Multilingual player</figcaption></figure>')
   value('fetch',urls=[test.base+test.track_path]);wait(lambda:len(value('items'))==1)
   value('open');wait(lambda:len(value('tracks')['audio'])==3)
   tracks=value('tracks');assert not tracks['hidden'] and len(tracks['subtitles'])==1,tracks
   french=next(t['id'] for t in tracks['audio'] if t['label'].startswith('fr'))
   value('audio-track',id=french);value('subtitle-track');before=value('tracks')['selection']
   value('update',attrs={'title':'Async title update','poster':'/poster-new.png'});value('scan');time.sleep(2)
   assert value('tracks')['selection']==before and value('tracks')['selected']==french,value('tracks')
   report['checks'].append('Real popup shows only meaningful audio choices and optional caption; language and subtitle selection survive asynchronous DOM metadata refresh')
   import capture_firefox,base64
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture;(OUTPUT/'popup-tracks.png').write_bytes(base64.b64decode(capture['value']['png']))
   value('download');entry=wait(finished);actual=streams(entry)
   assert entry['download_plan']['audioLanguage']=='fr' and entry['download_plan']['subtitleLanguages']==['fr'],entry
   assert next(s['height'] for s in actual if s['codec_type']=='video')==1080,actual
   assert list(out.glob('*.fr.vtt'))
   report['checks'].append('Real '+TRACKS.upper()+' path: MediaItem → language/subtitle selection → Automatic → pinned plan → native host → 1080p video plus French audio and caption')
   value('audio-track');value('subtitle-track');value('mode-change',mode='audio');previous=entry['id'];test.requests.clear()
   value('download');entry=wait(lambda:finished(previous));actual=streams(entry)
   assert {s['codec_type'] for s in actual}=={'audio'} and entry['download_plan']['audioLanguage']=='en',entry
   assert not any('/video/' in p and p.endswith(('.mp4','.m4s')) for p,_ in test.requests)
   report['checks'].append('Real audio-original UI download chooses the original native AAC without requesting video segments; track choices do not collide with previous video job')
  elif ITEMS:
   if os.environ.get('KITTY_REPRO_MEDIA_SELECTION')=='1':
    value('dom',html='<div class="gallerybox"><div class="thumb"><video disabled poster="/poster-a.png" resource="https://commons.wikimedia.org/wiki/File:Film_A.webm"></video></div><div class="gallerytext">Film A</div></div><div class="gallerybox"><div class="thumb"><video disabled poster="/poster-b.png" resource="https://commons.wikimedia.org/wiki/File:Film_B.webm"></video></div><div class="gallerytext">Film B</div></div>')
    wait(lambda:len(value('items'))==2);value('open');wait(lambda:len(value('rows'))==2);value('drawer')
    before=value('selection');value('check');value('all');after=value('selection')
    assert all(r['disabled'] and r['pointerEvents']=='auto' and r['hit'] for r in before['rows']),before
    assert not any(r['checked'] for r in after['rows']) and after['batchDisabled'],after
    report.update(ok=True,reproduction={'before':before,'after_checkbox_and_select_all':after},checks=['v8.45 bug reproduced in actual Firefox: disabled checkboxes with no CSS/overlay obstruction; Select all selects zero unresolved items'])
    raise SystemExit(0)
   # The same unresolved items that were disabled in v8.45 are selectable.
   value('dom',html='<figure><video poster="/poster-a.png" aria-label="Pending A"></video></figure><figure><video poster="/poster-b.png" aria-label="Pending B"></video></figure>')
   wait(lambda:len(value('items'))==2);value('open');wait(lambda:len(value('rows'))==2);value('drawer')
   before=value('selection');assert all(not r['disabled'] and r['hit'] and r['pointerEvents']=='auto' for r in before['rows']),before
   value('check');assert value('selection')['rows'][0]['checked']
   value('check');assert not value('selection')['rows'][0]['checked']
   value('row');assert value('selection')['rows'][0]['checked']
   value('row');assert not value('selection')['rows'][0]['checked']
   value('all');selected=value('selection');assert all(r['checked'] for r in selected['rows']) and selected['all']=='Tout désélectionner',selected
   value('all');assert not any(r['checked'] for r in value('selection')['rows'])
   value('all');value('update',attrs={'aria-label':'Async caption A','poster':'/poster-b.png'})
   wait(lambda:value('rows')[0]=='Async caption A')
   after=value('selection');assert [r['id'] for r in after['rows']]==[r['id'] for r in before['rows']] and all(r['checked'] for r in after['rows']),after
   value('addbatch');wait(lambda:'2 indisponibles' in value('phase'));assert all(r['checked'] for r in value('selection')['rows']),'Unresolved failed items stay selected for retry'
   value('update',attrs={'src':'/b_360p.mp4'});wait(lambda:value('items')[0]['downloadable'])
   assert value('selection')['rows'][0]['id']==before['rows'][0]['id'] and all(r['checked'] for r in value('selection')['rows'])
   value('all');value('close')
   report['checks'].append('Checkbox on/off, row toggle, Select all/Deselect all include unresolved items; selection IDs survive async title/poster/source updates; failed unresolved batch keeps selection for retry')
   # Real DOM scanner: source ownership, titles, lazy thumbnails and true embeds.
   value('dom',html='<figure><video preload="none" poster="/poster-a.png" aria-label="Wrong aria"><source src="/a_720p.webm" type="video/webm"><source src="/a_1080p.mp4" type="video/mp4"></video><figcaption>Caption wins</figcaption></figure><audio src="/native.m4a" aria-label="Native audio"></audio>')
   scan=value('scan');assert len(scan)==2 and scan[0]['title']=='Caption wins' and len(scan[0]['sources'])==2 and scan[0]['thumbnail']==test.base+'/poster-a.png' and scan[1]['mediaKind']=='audio',scan
   value('dom',html='<figure><video preload="none" src="/b_360p.mp4" title="Element title"></video><img data-src="/poster-b.png" src="/placeholder.png" alt="Alt title"></figure><iframe src="https://www.youtube-nocookie.com/embed/AbcDef12345" title="YouTube embed"></iframe><iframe src="https://player.vimeo.com/video/123456" title="Vimeo embed"></iframe><a href="https://youtube.com/watch?v=AnotherOne">Simple link</a><div id="related"><ytd-compact-video-renderer><video src="/normal.mp4"></video></ytd-compact-video-renderer></div>')
   scan=value('scan');assert len(scan)==3 and scan[0]['title']=='Element title' and scan[0]['thumbnail']==test.base+'/poster-b.png',scan
   assert scan[1]['embedUrl']=='https://www.youtube.com/watch?v=AbcDef12345' and scan[2]['embedUrl']=='https://vimeo.com/123456',scan
   wait(lambda:len(value('items'))==3)
   value('dom',html='<video preload="none" src="/normal.mp4" aria-label="Dynamic player"></video>',mutate=True);wait(lambda:len(value('items'))==4)
   report['checks'].append('Real DOM: MP4, audio, WebM/MP4 sources, caption hierarchy, poster, lazy image, YouTube/nocookie/Vimeo embeds, simple links and recommendations ignored, MutationObserver dynamic player')
   value('dom',html='<figure><video preload="none" src="/a_1080p.mp4" aria-label="First complete film"></video><video preload="none" aria-label="First complete film"><source src="/a_1080p.mp4" type="video/mp4"><source src="/a_720p.webm" type="video/webm"></video></figure>')
   wait(lambda:len(value('items'))==1 and len([c for c in value('items')[0]['candidates'] if c['sourceType']=='direct'])==2)
   scanned=value('scan');assert len(scanned)==2 and scanned[0]['containerId']==scanned[1]['containerId'] and scanned[0]['containerId'],scanned
   report['checks'].append('Real DOM partial source sets and network variants deduplicate to one logical item; both players share a stable figure container ID')
   value('dom',html='<figure><video preload="none" src="/a_1080p.mp4" aria-label="Shared caption"></video><video preload="none" src="/b_360p.mp4" aria-label="Shared caption"></video></figure>')
   wait(lambda:len(value('items'))==2)
   report['checks'].append('Two different real videos with the same figure and label stay separate; a container alone never merges them')
   value('dom',html='');value('blob');value('fetch',urls=[test.base+'/master.m3u8']);wait(lambda:len(value('items'))==1 and any(c['type']=='hls' for c in value('items')[0]['candidates']))
   report['checks'].append('Blob DOM evidence attaches observed HLS master without downloading blob URL')
   value('navigate',url=test.base+'/gallery');wait(lambda:len(value('items'))==2 and all(i['duration'] for i in value('items')))
   items=value('items');assert [i['title'] for i in items]==['Éruption du volcan — premier film','Le second film : océan'],items
   assert [i['thumbnail'] for i in items]==[test.base+'/poster-a.png',test.base+'/poster-b.png']
   assert len([c for c in items[0]['candidates'] if c['sourceType']=='direct'])==2,items
   # Exactly the Wikimedia transformation: shallow clone drops <source>s/src.
   value('clone');wait(lambda:all(not i['sources'] for i in value('scan')))
   wait(lambda:value('stored-dom')==[i['domId'] for i in value('scan')])
   cloned=wait(lambda:value('items') if all(i['downloadable'] for i in value('items')) else False)
   assert [i['id'] for i in cloned]==[i['id'] for i in items] and len([c for c in cloned[0]['candidates'] if c['sourceType']=='direct'])==2,cloned
   value('native',payload={'action':'pause_queue'});value('prepare',mode='best');value('open');wait(lambda:value('rows')==[i['title'] for i in items]);value('drawer');wait(lambda:len(value('images'))==2 and all(i['width']>0 for i in value('images')))
   value('check');assert value('selection')['rows'][0]['checked'];value('check');assert not value('selection')['rows'][0]['checked']
   value('all');assert all(r['checked'] for r in value('selection')['rows']) and value('selection')['all']=='Tout désélectionner'
   import capture_firefox,base64
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture;(OUTPUT/'popup-media-items.png').write_bytes(base64.b64decode(capture['value']['png']))
   value('all');assert not any(r['checked'] for r in value('selection')['rows'])
   value('batch');wait(lambda:len(value('status').get('state',{}).get('queue',[]))==2)
   wait(lambda:not any(r['checked'] for r in value('selection')['rows']))
   queued=value('status')['state']['queue'];assert {j['title'] for j in queued}=={i['title'] for i in items};assert len({j['url'] for j in queued})==2
   assert all(j['automatic'] and j['media_item']['page_url']==test.base+'/gallery' for j in queued),queued
   report['checks'].append('Wikimedia-style gallery: exactly two logical rows, correct captions/posters, grouped variants; batch inserts two distinct scoped requests into the paused existing queue')
   value('native',payload={'action':'resume_queue'});wait(lambda:len(value('status')['state']['history'])==2)
   history=value('status')['state']['history'];assert all(j['status']=='finished' for j in history),history
   assert len({j['download_plan']['mediaItemId'] for j in history})==2 and len({tuple(j['download_plan']['downloadUrls']) for j in history})==2,history
   for entry in history:
    result=streams(entry);height=next(s['height'] for s in result if s['codec_type']=='video');assert height==(1080 if entry['title']==items[0]['title'] else 360),(height,entry)
    assert any(s['codec_type']=='audio' for s in result);assert Path(entry['filepath']).stem==entry['title']
   report['checks'].append('Both batch entries reach the existing real downloader and valid audio/video files; Automatic chooses A 1080p over its WebM 720p, B remains B 360p, correct filenames and one history entry per video')
   report['batchPlans']=[j['download_plan'] for j in history]
   # Real main Download button, one checked item at a time, in best mode.
   value('close');value('native',payload={'action':'clear_history'});value('open');wait(lambda:value('rows')==[i['title'] for i in items]);value('drawer')
   report['individualPlans']=[]
   for index,expected in enumerate((1080,360)):
    value('check',index=index);assert value('clickstate')['item']==items[index]['id'],value('clickstate')
    value('download');wait(lambda:len(value('status')['state']['history'])==index+1)
    entry=value('status')['state']['history'][0];assert entry['status']=='finished' and entry['media_item']['id']==items[index]['id'],entry
    assert next(s['height'] for s in streams(entry) if s['codec_type']=='video')==expected,entry
    assert entry['download_plan']['downloadUrls']==[test.base+('/a_1080p.mp4' if index==0 else '/b_360p.mp4')],entry
    report['individualPlans'].append(entry['download_plan']);value('check',index=index)
   report['checks'].append('Actual checkbox selection A then B -> main Download -> separate best-quality plans -> correct A 1080p and B 360p files; no gallery/File-page transfer or candidate sharing')
   value('close');value('navigate',url=test.base+'/normal');wait(lambda:len(value('items'))==1);value('open');wait(lambda:value('single')=={'visible':True,'technicalHidden':True})
   value('download');wait(lambda:len(value('status')['state']['history'])==3)
   single=value('status')['state']['history'][0];assert single['status']=='finished' and single['url']==test.base+'/normal.mp4' and single['selected_source_type']=='direct_video',single;streams(single)
   report['checks'].append('Single visible video retains the compact UI and downloads its attached direct source without a top-level page probe; final audio/video file verified')
   value('close');page_result=value('native',payload={'action':'download','url':test.base+'/normal','mode':'best','automatic':True});assert page_result['ok'],page_result
   wait(lambda:len(value('status')['state']['history'])==4)
   ordinary=value('status')['state']['history'][0];assert ordinary['status']=='finished' and ordinary['url']==test.base+'/normal' and ordinary['selected_source_type']=='ytdlp' and not ordinary.get('download_plan'),ordinary;streams(ordinary)
   report['checks'].append('Ordinary current-page Automatic download remains yt-dlp page extraction with the historical format selector; valid output verified')
  elif AUTOMATIC:
   value('close');value('navigate',url=test.base+'/automatic-slow');time.sleep(2.2)
   value('fetch',urls=[test.base+'/master.m3u8',test.base+'/dash/manifest.mpd',test.base+'/normal.mp4'])
   value('prepare',mode='1080');value('open');wait(lambda:value('options')==4)
   assert value('labels')[0]=='Automatique · meilleure source',value('labels')
   report['checks'].append('Actual Firefox toolbar shows Automatic with shared HLS master, DASH and direct candidates')
   import capture_firefox,base64
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture
   (OUTPUT/'popup-automatic.png').write_bytes(base64.b64decode(capture['value']['png']))
   test.slow=True
   value('download');wait(lambda:'meilleure source' in value('phase'))
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture
   (OUTPUT/'popup-finding.png').write_bytes(base64.b64decode(capture['value']['png']))
   report['checks'].append('Actual popup shows Finding best source during concurrent metadata discovery')
   wait(lambda:'Source sélectionnée · HLS · 1080p' in value('phase'))
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture
   (OUTPUT/'popup-selected.png').write_bytes(base64.b64decode(capture['value']['png']))
   report['checks'].append('Actual popup shows Selected HLS 1080p during the sole transfer')
   entry=wait(lambda:finished())
   assert entry['automatic'] and entry['selected_source_type']=='hls',entry
   assert next(s['height'] for s in streams(entry) if s['codec_type']=='video')==1080
   assert len(value('status')['state']['history'])==1
   report['checks'].append('Failed page probe and 720p DASH/direct lose to HLS 1080p; one finished history entry, no red Error')
   logs=(cache/'worker.log').read_text()
   assert 'resolver failed: ytdlp' in logs and 'selected candidate: hls' in logs,logs
   assert 'candidate discovered: dash' in logs and 'candidate discovered: direct_video' in logs
   report['checks'].append('All four resolvers appear in safe production logs; selection uses the existing native queue and FFmpeg output')
   value('close');second_tab=value('tab',url=test.base+'/unsupported?other');time.sleep(.5);value('open');wait(lambda:value('options')==1)
   value('close');value('switch',tabId=original_tab);value('open');wait(lambda:value('options')==4)
   value('remove');wait(lambda:value('catalogue',tabId=original_tab)==[])
   report['checks'].append('Automatic catalogue remains isolated per tab and is cleaned on tab closure')
  elif GROUPS:
   master=test.base+'/vimeo/master.m3u8?token=MASTER%2BSECRET&asset=one'
   children=[test.base+f'/vimeo/video/{h}/media.m3u8?token=VIDEO{h}&asset=one' for h in (1080,720,360)]
   children+=[test.base+'/vimeo/audio/media.m3u8?token=AUDIO%2BSECRET&asset=one',test.base+'/vimeo/subtitles/media.m3u8?token=SUB&asset=one']
   value('fetch',urls=children);wait(lambda:len(value('catalogue'))==5)
   value('fetch',urls=[master]);wait(lambda:len(value('catalogue'))==1 and value('catalogue')[0].get('hls',{}).get('kind')=='master')
   catalogue=value('catalogue');assert catalogue[0]['hls']=={'kind':'master','maxResolution':1080,'variants':3,'audioTracks':1,'subtitles':1},catalogue
   value('fetch',urls=[master]*3+children*3+[test.base+'/vimeo/video/1080/init.mp4',test.base+'/vimeo/video/1080/seg000.m4s',test.base+'/low/seg000.ts'])
   assert len(value('catalogue'))==1
   value('open');wait(lambda:value('options')==2);labels=value('labels');assert '1080p max' in labels[1] and '3 qualités' in labels[1],labels
   assert 'stream 1' not in labels[1]
   report['checks'].append('Actual Firefox response bodies: five children loaded before a Vimeo-like master become one HLS group; repeated signed manifests and TS/fMP4 fragments keep one source')
   value('source');wait(lambda:all(str(h)+'p' in value('detail') for h in (360,720,1080)) and 'vidéo + audio' in value('detail'))
   import capture_firefox,base64
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture
   (OUTPUT/'popup-hls-groups.png').write_bytes(base64.b64decode(capture['value']['png']))
   value('download');entry=wait(finished);result_streams=streams(entry)
   assert next(s['height'] for s in result_streams if s['codec_type']=='video')==1080
   assert any(s['codec_type']=='audio' for s in result_streams)
   assert entry['media_source']['url']==master,entry
   assert any('/audio/media.m3u8?token=AUDIO%2BSECRET&asset=one' in p for p,_ in test.requests)
   report['checks'].append('Toolbar uses the complete master through Native Messaging; real yt-dlp selects 1080p and separate audio, FFmpeg merges them, history records the master')
   previous=entry['id'];value('close');value('open');wait(lambda:value('options')==2);value('download');fallback=wait(lambda:finished(previous));streams(fallback)
   assert fallback['media_source']['url']==master and fallback['url']==test.base+'/unsupported'
   report['checks'].append('Default yt-dlp page extraction still runs first and falls back to the grouped master in the same job')
   value('close');value('fetch',urls=[test.base+'/master.m3u8']);wait(lambda:len(value('catalogue'))==2)
   report['checks'].append('A different HLS video in the same tab remains a separate source')
   value('navigate',url=test.base+'/unsupported?standalone');time.sleep(.5)
   value('fetch',urls=[test.base+'/vimeo/standalone/audio.m3u8',test.base+'/vimeo/video/720/media.m3u8'])
   wait(lambda:len(value('catalogue'))==2);value('open');wait(lambda:value('options')==3)
   wait(lambda:any('Audio uniquement' in label for label in value('labels')))
   report['checks'].append('Navigation clears groups; standalone audio is labelled Audio only and standalone video remains available without inventing missing codec metadata')
   value('remove');wait(lambda:value('catalogue',tabId=original_tab)==[])
   report['checks'].append('Closing the source tab clears all HLS groups')
  elif DIRECT:
   signed=test.base+'/direct.mp4?signed=1&token=DO-NOT-LOG-DIRECT&cdn=KEEP'
   value('fetch',urls=[{'url':signed,'range':f'bytes={i*1024}-{(i+1)*1024-1}'} for i in range(30)])
   catalogue=value('catalogue');assert len(catalogue)==1,catalogue
   assert catalogue[0]['metadata']['size']==(test.media/'direct.mp4').stat().st_size
   assert sum(h.get('Range','').startswith('bytes=') for _,h in test.requests)>=30
   value('open');wait(lambda:value('options')==2);value('source');wait(lambda:'720p' in value('detail'))
   report['checks'].append('Real Firefox webRequest: 30 signed MP4 Range/206 requests produce one source and the complete file size')
   value('download');entry=wait(finished);assert next(s['height'] for s in streams(entry) if s['codec_type']=='video')==720
   wait(lambda:value('sourceurl')==test.base+'/unsupported')
   report['checks'].append('Actual direct MP4: toolbar → native host → yt-dlp → playable 720p audio/video → history and source-page link')
   value('close');value('fetch',urls=[test.base+'/browser-referer.mp4']);value('open');wait(lambda:value('options')==3)
   value('source');wait(lambda:'720p' in value('detail'));value('download');previous=entry['id'];entry=wait(lambda:finished(previous));streams(entry)
   headers=[h for url,h in test.requests if url.startswith('/browser-referer.mp4')]
   assert len(headers)>2 and all(h.get('Referer')==test.base+'/unsupported' for h in headers),headers
   report['checks'].append('Real Firefox Referer captured and reused by native metadata, ffprobe and yt-dlp download on a server which rejects requests without it')
   value('close');value('navigate',url=test.base+'/unsupported?qualities');time.sleep(.5)
   value('fetch',urls=[test.base+'/clip_'+str(h)+'p.mp4' for h in (360,720,1080)])
   catalogue=value('catalogue');group=next(c for c in catalogue if c['variants']==3);assert len(catalogue)==1,catalogue
   value('open');wait(lambda:value('options')==2);value('source',id=group['id'])
   wait(lambda:all(str(h)+'p' in value('detail') for h in (360,720,1080)))
   assert 'Kio' in value('detail') and '0.0 Mo' not in value('detail'),value('detail')
   import capture_firefox,base64
   with driver.context(driver.CONTEXT_CHROME):capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture
   (OUTPUT/'popup-direct.png').write_bytes(base64.b64decode(capture['value']['png']))
   value('download');previous=entry['id'];entry=wait(lambda:finished(previous))
   assert next(s['height'] for s in streams(entry) if s['codec_type']=='video')==720
   report['checks'].append('Three direct qualities form one source; metadata and the existing 720p quality selection choose the actual 720p file')
   value('close');value('fetch',urls=[test.base+'/direct.mp3']);audio=next(c for c in value('catalogue') if c['type']=='direct_audio')
   value('open');wait(lambda:value('options')==3);value('source',id=audio['id']);wait(lambda:value('mode')=='audio' and 'Analyse' not in value('detail'))
   value('download');previous=entry['id'];entry=wait(lambda:finished(previous));assert {s['codec_type'] for s in streams(entry)}=={'audio'}
   report['checks'].append('Direct audio selection switches the existing picker to audio; actual output has only an audio stream')
   value('close');value('navigate',url=test.base+'/unsupported?blob-empty');time.sleep(.5);value('blob');value('open')
   wait(lambda:'Lecteur blob' in value('detail'));assert value('catalogue')==[]
   report['checks'].append('Blob without an observable HTTP media resource displays the limitation and creates no downloadable blob URL')
   value('close');value('navigate',url=test.base+'/unsupported?blob-network');time.sleep(.5);value('blob',url=test.base+'/direct.webm');value('open');wait(lambda:value('options')==2)
   assert [c['type'] for c in value('catalogue')]==['direct_video']
   # Leave the page selected: the unsupported page falls back to the observed WebM.
   value('download');previous=entry['id'];entry=wait(lambda:finished(previous));streams(entry)
   assert entry['media_used']=='direct_video' and entry['url']==test.base+'/unsupported?blob-network',entry
   report['checks'].append('Blob fed by a real HTTP WebM is detected through its HTTP source; default page download falls back in the same worker job')
   value('close');second_tab=value('tab',url=test.base+'/unsupported?other');time.sleep(.5);value('open');wait(lambda:value('options')==1)
   value('close');value('switch',tabId=original_tab);value('open');wait(lambda:value('options')==2)
   value('close');value('navigate',url=test.base+'/unsupported?clean');time.sleep(.5);assert value('catalogue')==[]
   value('fetch',urls=[test.base+'/direct-stream']);value('open');wait(lambda:value('options')==2)
   assert value('catalogue')[0]['type']=='direct_video'
   value('download');previous=entry['id'];entry=wait(lambda:finished(previous));actual=streams(entry)
   assert entry['automatic'] and entry['selected_source_type']=='direct_video',entry
   assert {s['codec_type'] for s in actual}=={'video','audio'}
   report['checks'].append('Extensionless video/mp4: real Firefox catalogue -> Automatic -> direct plan -> valid video/audio file and one finished history entry')
   value('remove');wait(lambda:value('catalogue',tabId=original_tab)==[])
   report['checks'].append('MIME-only resource detected; tab switching, navigation and tab closure isolate and clean direct candidates')
  else:
   urls=([test.base+'/dashmulti/manifest.mpd?token=one',test.base+'/dashmulti/manifest.mpd?token=two',
     test.base+'/dash/manifest.mpd',test.base+'/dash/init-stream0.m4s',test.base+'/dash/chunk-stream0-00001.m4s',
     test.base+'/dash-stream',test.base+'/dashmulti/manifest.mpd?token=two'] if DASH else
     [test.base+'/master.m3u8?token=one',test.base+'/master.m3u8?token=two',test.base+'/master.m3u8?token=two',test.base+'/low/index.m3u8',test.base+'/low/seg000.ts',test.base+'/fmp4/init.mp4',test.base+'/fmp4/seg000.m4s',test.base+'/stream'])
   value('fetch',urls=urls)
   expected=4 if DASH else 3 # HLS referenced child is internal; MIME-only standalone remains.
   value('open');wait(lambda:value('options')==expected)
   report['checks'].append('Real webRequest: URL, '+('DASH' if DASH else 'HLS')+' Content-Type, signed URL dedupe, TS/fMP4 fragments excluded')
   value('source');wait(lambda:'720p' in value('detail') and '1080p' in value('detail'))
   report['checks'].append('Real popup '+('DASH' if DASH else 'HLS')+' probe: both quality heights, existing quality menu reused')
   import capture_firefox,base64
   with driver.context(driver.CONTEXT_CHROME):
    capture=driver.execute_async_script(capture_firefox.CAPTURE_SCRIPT,extension_host)
   assert capture['ok'],capture
   (OUTPUT/'popup-hls.png').write_bytes(base64.b64decode(capture['value']['png']))
   value('download')
   def finished():
    result=value('status');history=result.get('state',{}).get('history',[])
    return history[0] if history and history[0].get('status') in ('finished','error') else False
   entry=wait(finished);assert entry['status']=='finished',entry
   media=Path(entry['filepath']);assert media.is_file()
   streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(media)],timeout=15))['streams']
   assert next(s['height'] for s in streams if s['codec_type']=='video')==720
   wait(lambda:value('sourceurl')==test.base+'/unsupported')
   report['checks'].append('Actual popup → Native Messaging → worker → yt-dlp → FFmpeg → playable 720p video with audio → history')
   # Reopening chooses the page again; its unsupported extractor falls back in the same job.
   previous_id=entry['id'];value('close');value('open');wait(lambda:value('options')==expected);value('download')
   def fallback_finished():
    last=finished()
    return last if last and last['id']!=previous_id else False
   fallback=wait(fallback_finished);assert fallback['status']=='finished',fallback
   assert fallback.get('media_used')==('dash' if DASH else 'hls') and fallback['url']==test.base+'/unsupported'
   report['checks'].append('Default page download actually falls back to '+('DASH' if DASH else 'HLS')+' after extraction failure')
   value('close');second_tab=value('tab',url=test.base+'/normal');time.sleep(.5);value('fetch',urls=[test.base+'/normal.mp4']);value('open');wait(lambda:value('options')==2)
   value('close');value('switch',tabId=original_tab);value('open');wait(lambda:value('options')==expected)
   report['checks'].append('Switching tabs isolates the source selector and preserves the other tab candidates')
   value('close');value('navigate',url=test.base+'/normal');time.sleep(.5);value('fetch',urls=[test.base+'/normal.mp4']);value('open');wait(lambda:value('options')==2)
   report['checks'].append('Navigation clears previous network candidates')
   value('close');value('fetch',urls=[test.base+('/dash/manifest.mpd' if DASH else '/master.m3u8')]);value('open');wait(lambda:value('options')==3)
   if DASH:
    value('fetch',urls=[test.base+'/dash-drm.mpd',test.base+'/dash-denied.mpd'])
    wait(lambda:value('options')==4) # denied HTTP response is not a detected candidate
    value('source',index=1);wait(lambda:'DRM' in value('detail'))
    assert value('options')==4
    report['checks'].append('DRM is reported in the real popup; the raw MPD candidate is retained after probe failure')
   value('remove');wait(lambda:value('catalogue',tabId=original_tab)==[])
   report['checks'].append('Closing the source tab clears its candidates')
  log=(cache/'worker.log').read_text() if (cache/'worker.log').exists() else ''
  if ITEMS and not CONTEXT_ONLY:(OUTPUT/'media-item-trace.log').write_text('\n'.join(line for line in log.splitlines() if 'mediaItem trace ' in line)+'\n')
  assert 'PRIVATE-CONTEXT' not in log
  assert 'token=' not in log and 'DO-NOT-LOG-DIRECT' not in log and 'SECRET' not in log
  assert log.count('fallback DASH:')<=1
  report['checks'].append('Native logs have no manifest tokens and no repeated fallback loop')
  report['observation']=value('diagnostics')
  if ITEMS and not CONTEXT_ONLY:
   report['associationLogs']=value('association-logs')
   assert any(l['reason']=='shared_source' and l['action']=='merge' for l in report['associationLogs']),report['associationLogs']
   assert any(l['reason']=='container_without_identity' and l['action']=='reject' for l in report['associationLogs']),report['associationLogs']
   assert 'token=' not in json.dumps(report['associationLogs'])
  assert report['observation']['active']==0,report['observation']
  if GROUPS:assert report['observation']['reader']['completed']>=6,report['observation']
  report['ok']=True
finally:
 if driver:
  if not report.get('ok'):
   try:report['state']=value('status');report['phase']=value('phase');report['images']=value('images');report['diagnostics']=value('diagnostics');report['catalogue']=value('catalogue');print(json.dumps(report,ensure_ascii=False))
   except Exception as e:print('Diagnostics unavailable:',str(e))
   if REPRODUCTION:
    for name,action in [('senders','senders'),('pillState','pill-state'),('nativeRequests','diagnostics')]:
     try:report[name]=value(action)
     except Exception as e:report[name]=str(e)
  driver.quit()
 if original is None:registry.unlink(missing_ok=True)
 else:registry.write_bytes(original)
 if context_server:context_server.shutdown();context_server.server_close()
 test.tearDownClass()
 (OUTPUT/'firefox-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 native_registry_lock.close()
print(json.dumps(report,ensure_ascii=False,indent=2))
