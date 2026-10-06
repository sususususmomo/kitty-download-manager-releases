// Production content script in a controllable DOM/runtime: clicks, polling,
// loading, duplicate confirmation, variants and player targeting.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=process.env.KITTY_TEST_EXTENSION||path.join(__dirname,'../extension');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
async function fixture(variant='cat',language='fr',page='https://gallery.test/post') {
  const nodes=new Map(),timers=new Map(),messages=[],storageListeners=[];let serial=0,media=[],handler=async()=>({ok:true,state:{queue:[],history:[]}});
  class Element {
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.dataset={};this.style={};this.listeners={};this.disabled=false;this.paused=true;this.ended=false;this.hidden=false;
      const classes=new Set();this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)};}
    set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
    get isConnected(){return this===document.documentElement||Boolean(this.parentElement?.isConnected);}
    set textContent(value){this._text=String(value);this.children=[];}get textContent(){return (this._text||'')+this.children.map(c=>c.textContent||'').join('');}
    append(...children){for(const child of children){child.parentElement=this;this.children.push(child);}}
    appendChild(child){this.append(child);return child;}
    replaceChildren(...children){this._text='';this.children=[];this.append(...children);}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(c=>c!==this);this.parentElement=null;}
    attachShadow(){const shadow=new Element();shadow.parentElement=this;this.shadow=shadow;return shadow;}
    setAttribute(name,value){this.attrs[name]=String(value);}getAttribute(name){return this.attrs[name]??null;}removeAttribute(name){delete this.attrs[name];}
    getBoundingClientRect(){return this.rect||{left:20,right:210,top:14,bottom:58,width:190,height:44};}
    closest(){return null;}querySelector(){return null;}querySelectorAll(){return [];}
    contains(node){return this===node||this.children.some(c=>c.contains?.(node));}
    addEventListener(type,fn){(this.listeners[type]||=[]).push(fn);}
    dispatch(type,event={}){for(const fn of this.listeners[type]||[])fn({button:0,target:this,preventDefault(){},stopPropagation(){},...event});}
  }
  const document={visibilityState:'visible',getElementById:id=>nodes.get(id)||null,createElement:tag=>new Element(tag),
    querySelector:()=>null,querySelectorAll:selector=>selector==='video, audio'||selector==='video,audio,iframe,object,embed'?media:selector==='iframe'?media.filter(el=>el.tagName==='IFRAME'):[],addEventListener(){},baseURI:page};
  document.documentElement=new Element('html');
  const setTimer=(fn,delay)=>{const id=++serial;timers.set(id,{fn,delay});return id;};
  const window={innerWidth:1280,innerHeight:720,scrollY:0,setTimeout:setTimer,addEventListener(){},
    getComputedStyle:el=>({display:'block',visibility:'visible',opacity:'1',...el.computedStyle})};window.top=window;document.defaultView=window;
  const browser={storage:{local:{get:async()=>({pillEnabled:true,pillScope:'all',pillStyle:variant,uiLanguage:language})},onChanged:{addListener:f=>storageListeners.push(f)}},
    runtime:{onMessage:{addListener(){}},sendMessage:async message=>{messages.push(message);return handler(message);}}};
  const context=vm.createContext({document,window,location:new URL(page),URL,performance,console,browser,
    setTimeout:setTimer,clearTimeout:id=>timers.delete(id),requestAnimationFrame:fn=>fn()});
  for(const name of ['i18n.js','shared.js','media-resolver.js','media-dom.js','content-pill.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),context);
  await flush();
  return {nodes,timers,messages,context,setHandler:f=>handler=f,
    player:(tag,src,top=100,extra={})=>{const el=new Element(tag);el.rect={left:50,right:650,top,bottom:top+400,width:600,height:400};el.currentSrc=src;el.setAttribute('src',src);Object.assign(el,extra);media.push(el);return el;},
    clearPlayers:()=>media=[],change:(changes)=>storageListeners.forEach(fn=>fn(changes,'local')),
    poll:async()=>{const entry=[...timers].find(([,timer])=>timer.delay<=15000);assert.ok(entry,'A polling timer must exist');timers.delete(entry[0]);await entry[1].fn();await flush();}};
}
async function main(){
  for(const variant of ['minimal','cat','classic'])for(const language of ['fr','en']) {
    const f=await fixture(variant,language),pill=f.nodes.get('pill'),button=f.nodes.get('download');
    const offscreen=f.player('video','https://cdn.test/first.mp4',-800,{paused:false});
    const hidden=f.player('video','https://cdn.test/hidden.mp4',100,{computedStyle:{visibility:'hidden'},paused:false});
    const target=f.player('video','https://cdn.test/second.mp4',100);
    assert.ok(offscreen&&hidden);const selection=f.context.KittyMediaDOM.selection();
    assert.equal(f.context.KittyMediaDOM.scan()[2].domId,selection.domId,'Use the visible player, not a hidden/offscreen playing video');
    const pendingStatus=deferred(),pendingDownload=deferred();
    f.setHandler(message=>message.type==='kitty-pill-status'?pendingStatus.promise:pendingDownload.promise);
    const poll=f.poll();await flush();button.dispatch('click');await flush();
    const request=f.messages.find(m=>m.type==='kitty-add-download');assert.equal(request.domId,undefined);
    assert.equal(pill.dataset.state,'metadata');assert.equal(button.dataset.actionDisabled,'true');
    const dots=variant==='classic'?f.nodes.get('status').children[0]:button.children[0];
    assert.equal(dots.className,'kittyLoadingDots');assert.equal(dots.children.length,3);
    assert.equal(dots.attrs.role,'status');assert.ok(dots.attrs['aria-label']);
    pendingStatus.resolve({ok:true,state:{queue:[],history:[]}});await poll;
    assert.equal(pill.dataset.state,'metadata','An older status response must not reset an in-flight click to idle');
    button.dispatch('click');await flush();assert.equal(f.messages.filter(m=>m.type==='kitty-add-download').length,1);
    pendingDownload.resolve({ok:true,job_id:'own'});await flush();
    for(const [state,expected] of [
      [{queue:[{id:'own',status:'queued'}]},'queued'],
      [{active:{id:'own',status:'starting'}},'metadata'],
      [{active:{id:'own',status:'downloading',downloaded:50,total:100}},'downloading'],
      [{history:[{id:'own',status:'finished'}]},'finished']
    ]){f.setHandler(async()=>({ok:true,state}));await f.poll();assert.equal(pill.dataset.state,expected);}
    assert.equal(button.children.length,0,'Remove loading dots when transfer leaves metadata');
    assert.ok(target);
  }
  const duplicate=await fixture();duplicate.player('video','https://cdn.test/a.mp4');
  duplicate.setHandler(async()=>({ok:false,code:'already_downloaded',requestKey:'same-media-and-options'}));duplicate.nodes.get('download').dispatch('click');await flush();
  assert.equal(duplicate.nodes.get('pill').dataset.state,'duplicate');
  duplicate.nodes.get('download').dispatch('click');await flush();assert.equal(duplicate.messages.at(-1).forceToken,'same-media-and-options');
  duplicate.clearPlayers();duplicate.player('video','https://cdn.test/b.mp4');
  duplicate.nodes.get('download').dispatch('click');await flush();assert.equal(duplicate.messages.at(-1).forceToken,'same-media-and-options','The background validates the request key against the current media and settings');
  const failed=await fixture();failed.setHandler(async()=>({ok:false,error:'Accès refusé'}));failed.nodes.get('download').dispatch('click');await flush();
  assert.equal(failed.nodes.get('pill').dataset.state,'error');assert.equal(failed.nodes.get('download').dataset.actionDisabled,'false');
  const active=await fixture();active.setHandler(async()=>({ok:true,state:{active:{id:'existing',status:'downloading',downloaded:20,total:100,url:'https://cdn.test/file.mp4',media_item:{page_url:'https://gallery.test/post'}}}}));
  await active.poll();assert.equal(active.nodes.get('pill').dataset.state,'downloading','Adopt a scoped media-item job after reload');
  const feed=await fixture('cat','fr','https://www.instagram.com/reels/');feed.player('video','https://cdn.test/feed.mp4');
  feed.setHandler(async()=>({ok:true,job_id:'feed'}));feed.nodes.get('download').dispatch('click');await flush();
  assert.equal(feed.messages.at(-1).type,'kitty-add-download');assert.equal(feed.messages.at(-1).url,undefined);
  const embeds=await fixture();const iframe=embeds.player('iframe','https://player.vimeo.com/video/123456');
  assert.equal(embeds.context.KittyMediaDOM.selection().domId,embeds.context.KittyMediaDOM.scan()[0].domId);assert.ok(iframe);
  const genericFrame=await fixture();genericFrame.player('iframe','https://player.test/embed');
  genericFrame.setHandler(async()=>({ok:true,job_id:'frame'}));genericFrame.nodes.get('download').dispatch('click');await flush();
  assert.equal(genericFrame.messages.at(-1).type,'kitty-add-download','Resolve the same catalogue target in the background');
  const audio=await fixture();audio.player('audio','https://cdn.test/song.mp3',-800,{paused:false});assert.ok(audio.context.KittyMediaDOM.selection(),'Playing hidden audio remains selectable');
  console.log('PASS pill UI: 3 variants × 2 languages, animated dots, visible targeting, polling/click race, progress, completion, duplicate isolation, errors, job adoption, feeds, embeds and audio.');
}
module.exports={fixture};
if(require.main===module)main().catch(error=>{console.error(error);process.exitCode=1;});
