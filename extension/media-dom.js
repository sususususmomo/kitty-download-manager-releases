/* DOM identity only. Source classification/extraction remains in KittyMedia/yt-dlp. */
(() => {
  const ids=new WeakMap(),containers=new WeakMap(); let serial=0,containerSerial=0;
  const clean=value=>String(value || '').replace(/\s+/g,' ').trim().slice(0,1000);
  function url(value,base) {if(typeof value!=='string'||!value.trim())return null;try {const u=new URL(value,base);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password ? u.href : null;}catch{return null;}}
  function embed(value,base) {
    const raw=url(value,base);if(!raw)return null;const u=new URL(raw),host=u.hostname.toLowerCase();let id;
    if (['youtube.com','www.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com'].includes(host)
        && (id=u.pathname.match(/^\/embed\/([\w-]{6,})\/?$/)?.[1])) return 'https://www.youtube.com/watch?v='+id;
    if(host==='player.vimeo.com'&&(id=u.pathname.match(/^\/video\/(\d+)\/?$/)?.[1]))return 'https://vimeo.com/'+id;
    return null;
  }
  function image(node,base) {
    if(!node)return null;
    // Lazy sources precede a placeholder src; currentSrc already resolves srcset.
    const set=node.getAttribute('data-srcset') || node.getAttribute('srcset');
    const largest=set?.split(',').map(s=>s.trim().split(/\s+/)).sort((a,b)=>parseFloat(b[1]||0)-parseFloat(a[1]||0))[0]?.[0];
    return url(node.getAttribute('data-src') || largest || node.currentSrc || node.getAttribute('src'),base);
  }
  function scan(doc=document,now=Date.now()) {
    const base=doc.baseURI, result=[];
    for(const el of doc.querySelectorAll('video,audio,iframe,object,embed')) {
      if(el.closest('[hidden],[aria-hidden="true"],#kitty-download-manager-pill-host'))continue;
      if(el.closest('ytd-compact-video-renderer,ytd-rich-item-renderer,ytd-video-preview,#related'))continue;
      const tag=el.tagName.toLowerCase(),isPlayer=['video','audio'].includes(tag);
      if(tag!=='audio'&&doc.defaultView?.getComputedStyle(el).display==='none')continue;
      const embedded=isPlayer ? embed(base,base) : embed(el.getAttribute(tag==='object'?'data':'src'),base);
      if(!isPlayer&&!embedded)continue;
      if(!ids.has(el))ids.set(el,'dom-'+(++serial));
      let card=el.closest('figure,.thumb,.gallerybox,.media-card,.video-card,[data-media-item]');
      if(card&&card.querySelectorAll('video,audio,iframe,object,embed').length>1)card=null;
      // Only inspect the nearest small wrapper; never harvest an entire article.
      if(!card&&el.parentElement?.querySelectorAll('video,audio,iframe,object,embed').length===1)card=el.parentElement;
      const captionSelector='figcaption,.thumbcaption,.gallerytext,.caption,[data-caption]';
      // Wikimedia puts .gallerytext beside the inner .thumb, in .gallerybox.
      const outer=el.closest('.gallerybox,figure,.media-card,.video-card,.card,[data-media-item]');
      if(!card?.querySelector(captionSelector)&&outer?.querySelectorAll('video,audio,iframe,object,embed').length===1)card=outer;
      const caption=card?.querySelector(captionSelector);
      const img=card?.querySelector('img');
      const link=el.closest('a[href]') || card?.querySelector('a[href]');
      const titles=[['caption',clean(caption?.textContent)],['aria-label',clean(el.getAttribute('aria-label'))],
        ['title',clean(el.getAttribute('title'))],['link',clean(link?.textContent)],['thumbnail-alt',clean(img?.getAttribute('alt'))]];
      const [titleSource,title]=titles.find(([,value])=>value) || [null,''];
      const sources=[];
      for(const [value,mime] of [[el.currentSrc,el.getAttribute('type')],[el.getAttribute('src')||el.getAttribute('data-src'),el.getAttribute('type')],
        ...Array.from(el.querySelectorAll('source'),s=>[s.getAttribute('src')||s.getAttribute('data-src'),s.getAttribute('type')])]) {
        const full=url(value,base);if(!full)continue;const existing=sources.find(s=>s.url===full);
        if(!existing)sources.push({url:full,contentType:clean(mime)});else if(!existing.contentType)existing.contentType=clean(mime);
      }
      const blob=String(el.currentSrc||el.getAttribute('src')||'').startsWith('blob:');
      // TimedMediaHandler's childless placeholder retains this per-file URL,
      // even though the original video and all its <source>s are detached.
      const resourceUrl=url(el.getAttribute('resource'),base)||url(el.closest('.mw-tmh-player')?.querySelector('a.mw-tmh-play[href]')?.getAttribute('href'),base);
      const duration=el.duration||Number(el.getAttribute('data-durationhint'));
      const container=el.closest('figure,.gallerybox,.media-card,.video-card,[data-media-item],.mw-tmh-player')||card;
      if(container&&!containers.has(container))containers.set(container,'container-'+(++containerSerial));
      result.push({domId:ids.get(el),title,titleSource,thumbnail:url(el.getAttribute('poster'),base)||image(img,base),
        mediaKind:tag==='audio'?'audio':'video',duration:Number.isFinite(duration)&&duration>0?duration:null,
        width:el.videoWidth||null,height:el.videoHeight||null,embedUrl:embedded,resourceUrl,sources,blob,timestamp:now/1000,
        containerId:container?containers.get(container):null});
    }
    return result.slice(0,100);
  }
  globalThis.KittyMediaDOM=Object.freeze({scan,embed,url});
})();
