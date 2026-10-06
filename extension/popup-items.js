/* Compact logical-media chooser; batches enqueue through the existing pipeline. */
(() => {
  let tabId=null,items=[],current=null,checked=new Set(),generation=0,signature='',translate=x=>x,onSelect=()=>{},onBatch=()=>{},opened=false,probed=new Set(),batchBusy=false;
  const el=id=>document.getElementById(id);
  const preferences=new Map();
  function trackSelection(id,itemId=current){return id===tabId?{...(preferences.get(itemId)||{})}:{};}
  function trackSelections(){return Object.fromEntries([...checked].map(id=>[id,trackSelection(tabId,id)]));}
  function trackLabel(track){return [track.language,track.label,track.original?translate('Original'):null].filter(Boolean).join(' · ')||track.codec||translate('Audio');}
  function renderTracks(){
    const panel=el('mediaTracks');if(!panel)return;panel.replaceChildren();
    const item=items.find(i=>i.id===current),groups=new Map();
    for(const track of item?.audioTracks||[]){const key=JSON.stringify([track.language||null,track.label||null,track.original||null,track.role||null]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(track);}
    const audio=[...groups.values()].map(tracks=>tracks[0]),subtitleGroups=new Map();
    for(const track of item?.subtitleTracks||[]){const key=JSON.stringify([track.language||null,track.label||null,Boolean(track.automatic),track.original||null]);if(!subtitleGroups.has(key))subtitleGroups.set(key,track);}
    const subs=[...subtitleGroups.values()];
    panel.hidden=audio.length<2&&!subs.length;
    if(panel.hidden)return;
    const pref=trackSelection(tabId);
    if(audio.length>1){const label=document.createElement('label');label.textContent=translate('Piste audio');
      const select=document.createElement('select');select.id='mediaAudioTrack';select.setAttribute('aria-label',translate('Piste audio'));
      const auto=document.createElement('option');auto.value='';auto.textContent=translate('Automatique · original');select.append(auto);
      for(const track of audio){const option=document.createElement('option');option.value=track.id;option.textContent=trackLabel(track);select.append(option);}
      select.value=pref.audioTrackId||audio.find(t=>t.language&&t.language===pref.audioLanguage)?.id||'';select.addEventListener('change',()=>{const next=trackSelection(tabId),chosen=audio.find(t=>t.id===select.value);
        delete next.audioTrackId;delete next.audioLanguage;
        if(chosen?.language&&audio.filter(t=>t.language===chosen.language).length===1)next.audioLanguage=chosen.language;else if(chosen)next.audioTrackId=chosen.id;
        preferences.set(current,next);onSelect(item);});
      label.append(select);panel.append(label);}
    if(subs.length){const container=document.createElement(subs.length>1?'details':'div');
      if(subs.length>1){const summary=document.createElement('summary');summary.textContent=translate('Sous-titres');container.append(summary);}
      for(const track of subs){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.dataset.trackId=track.id;
        check.checked=(pref.subtitleTrackIds||[]).includes(track.id)||(pref.subtitleLanguages||[]).includes(track.language);check.addEventListener('change',()=>{const next=trackSelection(tabId),ids=new Set(next.subtitleTrackIds||[]),langs=new Set(next.subtitleLanguages||[]);
          langs.delete(track.language);for(const t of subs)if(t.language===track.language)ids.delete(t.id);
          if(check.checked){if(track.language&&subs.filter(t=>t.language===track.language).length===1)langs.add(track.language);else ids.add(track.id);}
          if(ids.size)next.subtitleTrackIds=[...ids];else delete next.subtitleTrackIds;
          if(langs.size)next.subtitleLanguages=[...langs];else delete next.subtitleLanguages;
          preferences.set(current,next);onSelect(item);renderTracks();});
        label.append(check,document.createTextNode(translate('Sous-titres')+' · '+trackLabel(track)+(track.automatic?' · '+translate('Automatiques'):'')));container.append(label);}
      panel.append(container);}
  }
  async function probeSelected(){const item=items.find(i=>i.id===current),id=tabId;
    if(!el('mediaTracks')||!item?.downloadable||probed.has(item.id))return;probed.add(item.id);
    try{const r=await browser.runtime.sendMessage({type:'kitty-probe-item',tabId:id,itemId:item.id});if(r?.ok&&tabId===id)await refresh(id);}catch{}}
  const wordCount=n=>n+' '+translate(n===1?'média détecté':'médias détectés');
  function thumbnail(item){const img=document.createElement('img');img.className='mediaThumbnail';img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';
    if(item.thumbnail&&/^https?:\/\//.test(item.thumbnail))img.src=item.thumbnail;else img.classList.add('missing');img.addEventListener('error',()=>{img.removeAttribute('src');img.classList.add('missing');});return img;}
  async function enrich(){
    const work=items.filter(i=>i.downloadable&&(!i.thumbnail||['filename',''].includes(i.titleSource))&&!probed.has(i.id));
    const id=tabId;
    // Lazy metadata only for an opened chooser; at most two simultaneous probes.
    async function next(){while(work.length&&tabId===id&&opened){const item=work.shift();probed.add(item.id);
      try{const r=await browser.runtime.sendMessage({type:'kitty-probe-item',tabId:id,itemId:item.id});if(r?.ok&&tabId===id)await refresh(id);}catch{}}}
    await Promise.all([next(),next()]);
  }
  function choose(id){current=id;onSelect(items.find(i=>i.id===id));renderSingle();probeSelected();}
  function renderSingle(){
    const one=items.length===1;el('mediaSingle').hidden=!one;
    if(one){const item=items[0];el('mediaSingle').replaceChildren(thumbnail(item));const title=document.createElement('span');title.textContent=item.title;title.title=item.title;el('mediaSingle').append(title);}
    el('mediaCount').hidden=items.length<2;el('mediaCount').textContent=wordCount(items.length);el('mediaCount').setAttribute('aria-expanded',String(opened));
    renderTracks();
  }
  const admissible=item=>item.selectable!==false;
  function toggle(item){if(!admissible(item))return;if(checked.has(item.id))checked.delete(item.id);else checked.add(item.id);}
  function selectionCount(){
    const available=items.filter(admissible),all=available.length>0&&available.every(i=>checked.has(i.id));
    el('mediaSelectAll').textContent=translate(all?'Tout désélectionner':'Tout sélectionner');el('mediaSelectAll').disabled=!available.length;
    el('mediaBatch').textContent=translate('Ajouter la sélection')+(checked.size?' · '+checked.size:'');el('mediaBatch').disabled=batchBusy||!checked.size;
  }
  function render(){
    renderSingle();el('mediaDrawer').hidden=!opened||items.length<2;
    el('mediaRows').replaceChildren();
    for(const item of items){
      const row=document.createElement('div');row.className='mediaRow';
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=checked.has(item.id);checkbox.disabled=!admissible(item);checkbox.setAttribute('aria-label',translate('Sélectionner')+' '+item.title);checkbox.dataset.itemId=item.id;
      checkbox.addEventListener('change',()=>{if(checkbox.checked){checked.add(item.id);choose(item.id);}else checked.delete(item.id);render();});
      const chooseButton=document.createElement('button');chooseButton.type='button';chooseButton.className='mediaChoose';chooseButton.dataset.itemId=item.id;chooseButton.setAttribute('aria-pressed',String(item.id===current));
      chooseButton.append(thumbnail(item));const info=document.createElement('span');info.className='mediaInfo';
      const title=document.createElement('span');title.className='mediaTitle';title.textContent=item.title;title.title=item.title;
      const detail=document.createElement('small');detail.textContent=!item.downloadable?translate('Source à résoudre au téléchargement'):translate(item.mediaKind==='audio'?'Audio':'Vidéo')+(item.duration?' · '+Math.floor(item.duration/60)+':'+String(Math.floor(item.duration%60)).padStart(2,'0'):'');
      info.append(title,detail);chooseButton.append(info);chooseButton.addEventListener('click',()=>{toggle(item);choose(item.id);render();});row.append(checkbox,chooseButton);el('mediaRows').append(row);
    }
    selectionCount();
  }
  async function refresh(id){
    const turn=++generation;
    try {const result=await browser.runtime.sendMessage({type:'kitty-media-items',tabId:id});if(turn!==generation)return;
      if(tabId!==id){probed.clear();preferences.clear();checked.clear();current=null;signature='';opened=false;}
      tabId=id;items=result?.ok&&Array.isArray(result.items)?result.items:[];
      checked=new Set([...checked].filter(id=>items.some(i=>i.id===id&&admissible(i))));
      if(!items.some(i=>i.id===current)){current=items.find(i=>i.downloadable)?.id||items[0]?.id||null;onSelect(items.find(i=>i.id===current));}
      const next=JSON.stringify(items);if(next!==signature){signature=next;render();}
      el('mediaItemsPanel').hidden=!items.length;
      if(items.length)el('hlsPanel').hidden=true;
      probeSelected();
    }catch{items=[];el('mediaItemsPanel').hidden=true;}
  }
  function start(options={}){
    translate=options.translate||translate;onSelect=options.onSelect||onSelect;onBatch=options.onBatch||onBatch;
    if(!el('mediaCount'))return;
    el('mediaCount').addEventListener('click',()=>{opened=!opened;render();if(opened)enrich();});
    el('mediaSelectAll').addEventListener('click',()=>{const available=items.filter(admissible);checked=available.length&&available.every(i=>checked.has(i.id))?new Set():new Set(available.map(i=>i.id));render();});
    el('mediaBatch').addEventListener('click',async()=>{const ids=[...checked],batchTab=tabId;if(!ids.length||batchBusy)return;batchBusy=true;selectionCount();
      try{const result=await onBatch({tabId,itemIds:ids,trackSelections:trackSelections()});if(tabId===batchTab)for(const id of ids){const entry=result?.results?.find(r=>r.itemId===id);
        if(!result?.results||entry?.ok||['already_queued','already_active','already_downloaded'].includes(entry?.code))checked.delete(id);}
      }catch(error){el("status").textContent=translate("Erreur :")+" "+error.message;}finally{batchBusy=false;render();}});
  }
  globalThis.KittyItemsPopup=Object.freeze({start,refresh,trackSelection,hasItems:id=>id===tabId&&items.length>0,selection:id=>id===tabId?current:null});
})();
