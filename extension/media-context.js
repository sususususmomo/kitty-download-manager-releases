/* Debounced, frame-local DOM snapshots. No media bytes, fetches or blob download. */
(() => {
  let previous='',timer=0,inFlight=null,retries=0;
  async function scan() {
    timer=0;
    if(inFlight){await inFlight;return scan();}
    const items=KittyMediaDOM.scan();
    const signature=location.href+JSON.stringify(items.map(({timestamp,...item})=>item));
    if(signature===previous)return {ok:true};
    const context={pageUrl:location.href,documentToken:KittyShared.documentToken()};
    inFlight=Promise.allSettled([browser.runtime.sendMessage({type:'kitty-media-dom',items,...context}),
      browser.runtime.sendMessage({type:'kitty-media-context',hasBlob:items.some(i=>i.blob),...context})]);
    try {
      const results=await inFlight;
      const failed=results.find(r=>r.status==='rejected'||r.value?.ok!==true);
      if(failed){
        // Retry a rejected startup publication even if the DOM is unchanged.
        if(retries++<3&&!timer)timer=setTimeout(scan,1500);
        return {ok:false,error:failed.reason?.message||failed.value?.error||'Catalogue non confirmé par le background.'};
      }
      previous=signature;retries=0;return {ok:true};
    }finally{inFlight=null;}
  }
  function schedule(){if(!timer)timer=setTimeout(scan,150);}
  const observer=new MutationObserver(records=>{
    if(records.some(r=>!r.target?.closest?.('#kitty-download-manager-pill-host')))schedule();
  });
  const watch=()=>observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true,attributes:true,
    attributeFilter:['src','type','poster','title','aria-label','hidden','srcset','data-src','data-srcset','resource','data-durationhint']});
  watch();
  for(const event of ['loadedmetadata','durationchange','emptied','load'])document.addEventListener(event,schedule,true);
  browser.runtime.onMessage.addListener(m=>{
    if(m?.type==='kitty-document-context')return Promise.resolve({ok:true,pageUrl:location.href,documentToken:KittyShared.documentToken()});
    if(m?.type==='kitty-media-rescan'||m?.type==='kitty-media-target'){
      previous='';return scan().then(result=>({...result,...(m.type==='kitty-media-target'?{target:KittyMediaDOM.selection()}: {})}));
    }
  });
  window.addEventListener('hashchange',schedule);window.addEventListener('popstate',schedule);
  window.addEventListener('pagehide',()=>{observer.disconnect();clearTimeout(timer);timer=0;previous='';browser.runtime.sendMessage({type:'kitty-media-dom',items:[],unload:true}).catch(()=>{});});
  window.addEventListener('pageshow',()=>{watch();schedule();});
  schedule();
})();
