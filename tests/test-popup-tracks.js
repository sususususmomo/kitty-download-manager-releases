// Production selector: conditional UI, stable per-item preferences and batch.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map();
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.classList={add(){}};this.hidden=false;this.checked=false;this.disabled=false;}
  set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
  append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
  setAttribute(){}removeAttribute(){}
  addEventListener(type,callback){this.listeners[type]=callback;}
  async click(){if(this.disabled)return;if(this.type==='checkbox'){this.checked=!this.checked;await this.listeners.change?.();}else await this.listeners.click?.();}
}
for(const id of ['mediaSingle','mediaCount','mediaDrawer','mediaRows','mediaSelectAll','mediaBatch','mediaItemsPanel','hlsPanel','mediaTracks','status']){const node=new Element();node.id=id;}
const audio=(id,language)=>({id,language,codec:'aac',native:true}),sub=(id,language)=>({id,language});
let items=[{id:'one',title:'First',thumbnail:'https://test/first.jpg',downloadable:true,selectable:true,
  audioTracks:[audio('en-one','en'),audio('fr-one','fr')],subtitleTracks:[sub('sub-fr-one','fr'),sub('sub-de-one','de')]},
  {id:'two',title:'Second',thumbnail:'https://test/second.jpg',downloadable:true,selectable:true,
  audioTracks:[audio('en-two','en'),audio('fr-two','fr')],subtitleTracks:[]}];
let batch;
const context=vm.createContext({console,document:{getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})},
  browser:{runtime:{sendMessage:async msg=>msg.type==='kitty-media-items'?{ok:true,items}: {ok:false}}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension/popup-items.js'),'utf8'),context);
const api=context.KittyItemsPopup,clone=x=>JSON.parse(JSON.stringify(x));
(async()=>{
 api.start({onBatch:async selection=>{batch=clone(selection);return {results:selection.itemIds.map(itemId=>({itemId,ok:true}))};}});
 await api.refresh(1);assert.equal(nodes.get('mediaAudioTrack').children.length,3);assert.equal(nodes.get('mediaTracks').hidden,false);
 const select=nodes.get('mediaAudioTrack');select.value='fr-one';select.listeners.change();
 let checks=nodes.get('mediaTracks').children[1].children.slice(1).map(label=>label.children[0]);await checks[0].click();await checks[1].click();
 assert.deepEqual(clone(api.trackSelection(1)),{audioLanguage:'fr',subtitleLanguages:['fr','de']});
 items=items.map(i=>({...i,title:i.title+' async',thumbnail:i.thumbnail+'?new',audioTracks:i.audioTracks.map(t=>({...t,bitrate:192}))}));
 await api.refresh(1);assert.equal(nodes.get('mediaAudioTrack').value,'fr-one');
 assert.deepEqual(clone(api.trackSelection(1)).subtitleLanguages,['fr','de']);
 await nodes.get('mediaCount').click();
 const row2=nodes.get('mediaRows').children[1].children[1];await row2.click();
 const second=nodes.get('mediaAudioTrack');second.value='en-two';second.listeners.change();
 assert.deepEqual(clone(api.trackSelection(1,'one')).audioLanguage,'fr');
 await nodes.get('mediaSelectAll').click();assert.equal(nodes.get('mediaSelectAll').textContent,'Tout désélectionner');
 await nodes.get('mediaBatch').click();assert.equal(batch.trackSelections.one.audioLanguage,'fr');assert.equal(batch.trackSelections.two.audioLanguage,'en');
 assert.deepEqual(batch.itemIds,['one','two']);
 items=[{id:'single',title:'Simple',downloadable:true,audioTracks:[audio('only','en')],subtitleTracks:[]}];await api.refresh(2);
 assert.equal(nodes.get('mediaTracks').hidden,true);assert.deepEqual(clone(api.trackSelection(2)),{});
 items=[{...items[0],subtitleTracks:[sub('single-sub','fr')]}];await api.refresh(2);
 assert.equal(nodes.get('mediaTracks').hidden,false);assert.equal(nodes.get('mediaTracks').children[0].tagName,'div');
 items=[{...items[0],audioTracks:[audio('only','en'),audio('quality-variant','en')],subtitleTracks:[]}];await api.refresh(2);
 assert.equal(nodes.get('mediaTracks').hidden,true,'Quality/source variants of one language must not create track choices');
 console.log('Popup tracks: conditional controls, multiple captions, stable async choices, per-item isolation, batch preferences and tab reset PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
