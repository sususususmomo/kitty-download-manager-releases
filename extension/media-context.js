/* Debounced, frame-local DOM snapshots. No media bytes, fetches or blob download. */
(() => {
  let previous='',timer=0;
  async function scan() {
    timer=0;
    const items=KittyMediaDOM.scan();
    const signature=location.href+JSON.stringify(items.map(({timestamp,...item})=>item));
    if(signature===previous)return;
    previous=signature;
    await Promise.allSettled([browser.runtime.sendMessage({type:'kitty-media-dom',items}),
      browser.runtime.sendMessage({type:'kitty-media-context',hasBlob:items.some(i=>i.blob)})]);
  }
  function schedule(){if(!timer)timer=setTimeout(scan,150);}
  const observer=new MutationObserver(records=>{
    if(records.some(r=>!r.target?.closest?.('#kitty-download-manager-pill-host')))schedule();
  });
  const watch=()=>observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true,attributes:true,
    attributeFilter:['src','type','poster','title','aria-label','hidden','srcset','data-src','data-srcset','resource','data-durationhint']});
  watch();
  for(const event of ['loadedmetadata','durationchange','emptied','load'])document.addEventListener(event,schedule,true);
  browser.runtime.onMessage.addListener(m=>{if(m?.type==='kitty-media-rescan'){previous='';return scan().then(()=>({ok:true}));}});
  window.addEventListener('hashchange',schedule);window.addEventListener('popstate',schedule);
  window.addEventListener('pagehide',()=>{observer.disconnect();clearTimeout(timer);timer=0;previous='';browser.runtime.sendMessage({type:'kitty-media-dom',items:[],unload:true}).catch(()=>{});});
  window.addEventListener('pageshow',()=>{watch();schedule();});
  schedule();
})();
