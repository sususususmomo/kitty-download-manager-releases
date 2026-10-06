/* Shared media catalogue. HLS relations come from observed manifest bodies;
 * no extra fetch, cookies, response rewriting or segment downloading. */
(() => {
  const TYPES = new Set(['application/vnd.apple.mpegurl', 'application/x-mpegurl',
    'application/mpegurl', 'audio/mpegurl', 'audio/x-mpegurl']);
  const VOLATILE = new Set(['token', 'access_token', 'auth', 'signature', 'sig', 'expires',
    'expiry', 'exp', 'policy', 'key-pair-id', 'hdnea', 'hdnts', 'x-amz-signature',
    'x-amz-date', 'x-amz-expires', 'x-amz-credential', 'x-amz-security-token']);
  const TTL = 15 * 60 * 1000;
  function http(value) {
    if (typeof value !== 'string' || value.length > 16384 || /[\x00-\x20\x7f]/.test(value)) return null;
    try { const u = new URL(value); return /^https?:$/.test(u.protocol) && !u.username && !u.password ? u : null; } catch { return null; }
  }
  function manifestType(url, mime = '') {
    const u = http(url);
    if (!u || /\.(?:ts|m4s|mp4|m4a|cmfv|cmfa)$/i.test(u.pathname)) return null;
    const type = mime.split(';')[0].trim().toLowerCase();
    if (type === 'application/dash+xml') return 'dash';
    if (TYPES.has(type)) return 'hls';
    if (/\.mpd(?:$|[?#/])/i.test(url)) return 'dash';
    return /\.m3u8/i.test(url) ? 'hls' : null;
  }
  function isManifest(url, mime = '') { return Boolean(manifestType(url, mime)); }
  const VIDEO = new Set(['mp4','webm','m4v','mov','mkv']);
  const AUDIO = new Set(['mp3','m4a','ogg','opus','wav','flac','aac']);
  function technical(url) {
    const u = http(url);
    return !u || /\.(?:ts|m4s|cmfv|cmfa)$/i.test(u.pathname)
      || /(?:^|[/_.-])init(?:ialization)?(?:[-_.][\w.-]+)?\.(?:mp4|m4a|webm)$/i.test(u.pathname)
      || /(?:^|\/)(?:chunk|segment|seg|fragment|frag)[-_]?(?:stream\d+[-_])?\d+[._-]/i.test(u.pathname);
  }
  function directType(url, mime = '') {
    const u = http(url), type = String(mime).split(';')[0].trim().toLowerCase();
    if (!u || technical(url) || TYPES.has(type) || type === 'application/dash+xml') return null;
    if (/^video\//.test(type) && type !== 'video/mp2t') return 'direct_video';
    if (/^audio\//.test(type)) return 'direct_audio';
    // A known incompatible MIME wins over a filename. Octet-stream remains useful.
    if (type && !['application/octet-stream','binary/octet-stream'].includes(type)) return null;
    const ext = u.pathname.match(/\.([a-z0-9]+)$/i)?.[1].toLowerCase();
    return VIDEO.has(ext) ? 'direct_video' : AUDIO.has(ext) ? 'direct_audio' : null;
  }
  function mediaType(url, mime = '') { return manifestType(url,mime) || directType(url,mime); }
  function qualityKey(url) {
    const u = http(url);
    if (!u) return null;
    let height = null;
    for (const name of ['quality','height','resolution']) {
      const value = u.searchParams.get(name);
      if (/^(?:[1-9]\d{2,3})p?$/.test(value || '')) { height = Number(value.replace('p','')); u.searchParams.set(name,'{quality}'); }
    }
    const match = u.pathname.match(/([_.-])([1-9]\d{2,3})p(?=[_.-]|$)/i);
    if (match) { height = Number(match[2]); u.pathname = u.pathname.replace(match[0],match[1]+'{quality}'); }
    return height ? {key:key(u.href),height} : null;
  }
  function responseMetadata(d, mime, previous = {}) {
    const headers = Object.fromEntries((d.responseHeaders || []).map(h=>[String(h.name).toLowerCase(),String(h.value || '')]));
    const range = /^bytes\s+(\d+)-(\d+)\/(\d+|\*)$/i.exec(headers['content-range'] || '');
    const positive = v => /^\d+$/.test(v || '') && Number.isSafeInteger(Number(v)) && Number(v)>0 ? Number(v) : null;
    const size = range ? positive(range[3]) : d.statusCode === 206 ? null : positive(headers['content-length']);
    let filename;
    const disposition = headers['content-disposition'] || '';
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    try { filename = encoded ? decodeURIComponent(encoded[1]) : /filename\s*=\s*"?([^";]+)/i.exec(disposition)?.[1]; } catch {}
    filename = filename?.split(/[\\/]/).pop().trim().slice(0,255);
    const format = http(d.url)?.pathname.match(/\.([a-z0-9]+)$/i)?.[1]
      || ({'video/quicktime':'mov','audio/mpeg':'mp3','audio/mp4':'m4a','video/x-matroska':'mkv'})[mime]
      || mime.split('/')[1]?.replace(/^x-/,'');
    return {...previous, ...(size ? {size} : {}), ...(filename ? {filename} : {}),
      ...(format && /^[a-z0-9-]{1,20}$/i.test(format) ? {format:format.toUpperCase()} : {}),
      ...(range ? {content_range:headers['content-range'].slice(0,120)} : {}),
      status_code:d.statusCode, ...(qualityKey(d.url) ? {height:qualityKey(d.url).height} : {})};
  }
  function smallTechnical(url, metadata) {
    const size = metadata.size, path = http(url)?.pathname || '';
    return size && (size < 8192 || (size < 131072 && /(?:^|[/_.-])(?:sprite|favicon|spinner|loader|loading|avatar|icon|preview|hover|teaser)(?=[/_.-]|$)/i.test(path)));
  }
  function key(url) {
    const u = http(url);
    if (!u) return '';
    const stable = [...u.searchParams].filter(([k]) => !VOLATILE.has(k.toLowerCase()));
    stable.sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    return JSON.stringify([u.origin, u.pathname, stable]);
  }
  function rank(c) {
    if (c.type === 'dash') return 3; // An MPD normally describes all adaptations.
    if (c.type.startsWith('direct_')) return c.type==='direct_audio' ? -1 : 0;
    if (c.hls?.kind==='master') return 4;
    if (['audio','subtitles'].includes(c.hls?.kind)) return -1;
    const path = http(c.url)?.pathname || '';
    return /(?:^|\/)master[^/]*\.m3u8$/i.test(path) ? 3 : /(?:^|\/)index\.m3u8$/i.test(path) ? 2 : 1;
  }
  class Store {
    constructor(now = Date.now) { this.now = now; this.tabs = new Map(); this.requests = new Map(); }
    clear(tabId) {
      this.tabs.delete(tabId);
      for (const [id, r] of this.requests) if (r.tabId === tabId) this.requests.delete(id);
    }
    navigate(tabId, url) {
      if (!Number.isInteger(tabId) || tabId < 0) return;
      const old = this.tabs.get(tabId);
      if (old?.page !== url) this.tabs.set(tabId, {page: url, candidates: new Map()});
    }
    before(d) {
      if (d.type === 'main_frame') this.navigate(d.tabId, d.url);
    }
    context(tabId,page,hasBlob) {
      if (!http(page) || !Number.isInteger(tabId) || tabId<0) return;
      this.navigate(tabId,page); this.tabs.get(tabId).hasBlob=Boolean(hasBlob);
    }
    headers(d) {
      if (d.tabId < 0 || d.method !== 'GET') return;
      const requestContext=KittyRequestContext.capture(d.url,d.requestHeaders);
      const headers = KittyRequestContext.legacy(requestContext || KittyRequestContext.snapshot(d.requestHeaders));
      for (const [id,r] of this.requests) if (this.now()-r.at > 60000) this.requests.delete(id);
      if (this.requests.size >= 256) this.requests.delete(this.requests.keys().next().value);
      const range = (d.requestHeaders || []).find(h=>String(h.name).toLowerCase()==='range')?.value;
      this.requests.set(d.requestId, {tabId:d.tabId, documentUrl:d.documentUrl, headers, requestContext, range:typeof range==='string'?range.slice(0,120):null, at:this.now(), navigationPage:this.tabs.get(d.tabId)?.page || null, page:this.tabs.get(d.tabId)?.page || d.documentUrl || d.originUrl});
    }
    response(d, pageOverride) {
      if (d.tabId < 0 || d.method !== 'GET' || !((d.statusCode >= 200 && d.statusCode < 300) || d.statusCode === 304)) return null;
      const mime = String((d.responseHeaders || []).find(h => String(h.name).toLowerCase() === 'content-type')?.value || '').split(';')[0].trim().toLowerCase();
      const type = mediaType(d.url, mime);
      if (!type) return null;
      const request = this.requests.get(d.requestId);
      if (request?.navigationPage && this.tabs.get(d.tabId)?.page && request.navigationPage !== this.tabs.get(d.tabId).page) return null;
      const page = this.tabs.get(d.tabId)?.page || pageOverride || request?.page || d.documentUrl || d.originUrl || (d.type === 'main_frame' ? d.url : null);
      if (!http(page)) return null;
      if (!this.tabs.has(d.tabId)) this.navigate(d.tabId, page);
      const tab = this.tabs.get(d.tabId);
      const direct = type.startsWith('direct_'), quality = direct ? qualityKey(d.url) : null;
      const candidateKey = type + ':' + (quality?.key || key(d.url)), old = tab.candidates.get(candidateKey);
      const previousMetadata = old?.variants?.find(v=>key(v.url)===key(d.url))?.metadata
        || (old && key(old.url)===key(d.url) ? old.metadata : undefined);
      const metadata = direct ? responseMetadata(d,mime,previousMetadata) : undefined;
      if (direct && (smallTechnical(d.url,metadata) || ['image','font','stylesheet','script'].includes(d.type))) return null;
      const candidate = {id:old?.id || crypto.randomUUID(), type, url:d.url,
        page_url:page, tab_id:d.tabId, frame_id:d.frameId ?? 0,
        frame_ids:[...new Set([...(old?.frame_ids || []),d.frameId ?? 0])], document_url:d.documentUrl || request?.documentUrl || page,
        timestamp:this.now()/1000, content_type:mime,
        headers:request?.headers || old?.headers || {},
        ...(request?.requestContext ? {requestContext:request.requestContext} : {}), hostname:http(d.url).hostname, title:type.toUpperCase()+' stream',
        ...(direct ? {metadata:{...metadata,...(request?.range ? {request_range:request.range} : {})}} : {}),
        ...(old?.hls ? {hls:{...old.hls,...(old.hls.kind==='master' ? {masterUrl:d.url} : {})},hlsDuplicateLogged:old.hlsDuplicateLogged} : {})};
      if (direct && quality) {
        const variants = [...(old?.variants || (old ? [{...old,variants:undefined}] : []))]
          .filter(v=>key(v.url)!==key(d.url) && this.now()-v.timestamp*1000<=TTL);
        variants.push({...candidate}); variants.sort((a,b)=>(b.metadata?.height||0)-(a.metadata?.height||0));
        candidate.variants = variants.slice(0,4);
        Object.assign(candidate,{url:variants[0].url,headers:variants[0].headers,requestContext:variants[0].requestContext,metadata:variants[0].metadata});
      }
      // The newest signed URL wins, but the complete original string is retained.
      tab.candidates.set(candidateKey, candidate);
      const visible=this.list(d.tabId);
      if (visible.length > 20 || tab.candidates.size > 128) {
        const pool=visible.length>20 ? new Set(visible.map(c=>c.id)) : null;
        const victim = [...tab.candidates].filter(([,c])=>!pool || pool.has(c.id))
          .sort((a,b) => rank(a[1])-rank(b[1]) || a[1].timestamp-b[1].timestamp)[0];
        if(victim)tab.candidates.delete(victim[0]);
      }
      return candidate;
    }
    manifest(candidate, text) {
      const tab=this.tabs.get(candidate?.tab_id);
      // A late body must not resurrect a closed tab, previous navigation or an
      // older signed response that was replaced while it was still loading.
      const current=tab && [...tab.candidates.values()].find(c=>c.id===candidate.id);
      if (!current || current.url!==candidate.url || current.page_url!==candidate.page_url || current.type!=='hls') return null;
      const parsed=globalThis.KittyHlsParser?.parse(text,current.url);
      if(!parsed)return null; // Keep the raw, downloadable candidate.
      const old=current.hls;
      current.hls={...parsed,parsedKind:parsed.kind, masterUrl:parsed.kind==='master' ? current.url : null,
        originalMasterUrl:parsed.kind==='master' ? old?.originalMasterUrl || current.url : null,
        pageUrl:current.page_url,tabId:current.tab_id,timestamp:current.timestamp};
      const semantic=h=>h && JSON.stringify({kind:h.parsedKind || h.kind,protected:h.protected,
        variants:h.variants.map(v=>({...v,url:key(v.url)})),
        audioTracks:h.audioTracks.map(v=>({...v,url:v.url ? key(v.url) : null})),
        subtitles:h.subtitles.map(v=>({...v,url:v.url ? key(v.url) : null}))});
      const changed=semantic(old)!==semantic(current.hls);
      return {changed,kind:parsed.kind,duplicate:!changed,candidate:current};
    }
    list(tabId) {
      const tab = this.tabs.get(tabId);
      if (!tab) return [];
      for (const [k,c] of tab.candidates) if (this.now()-c.timestamp*1000 > TTL) tab.candidates.delete(k);
      const all=[...tab.candidates.values()], masters=all.filter(c=>c.hls?.kind==='master');
      const children=new Map();
      const references=c=>[...c.hls.variants,...c.hls.audioTracks,...c.hls.subtitles];
      const pointsBack=(child,master,seen=new Set())=>{
        if(seen.has(child.id))return false;
        seen.add(child.id);
        return references(child).some(ref=>ref.url && (key(ref.url)===key(master.url)
          || masters.some(next=>key(next.url)===key(ref.url) && pointsBack(next,master,seen))));
      };
      for(const master of masters) {
        for(const [role,refs] of [['video',master.hls.variants],['audio',master.hls.audioTracks],['subtitles',master.hls.subtitles]])
          for(const ref of refs) {
            const child=all.find(c=>c.type==='hls' && c.id!==master.id && ref.url && key(c.url)===key(ref.url));
            // Do not let malformed cyclic master references hide both sources.
            if(child && !(child.hls?.kind==='master' && pointsBack(child,master))) {
              const parents=children.get(child.id) || [];
              parents.push({id:master.id,role,ref});children.set(child.id,parents);
            }
          }
      }
      for(const c of all) {
        if(c.type!=='hls')continue;
        const parents=children.get(c.id) || [];
        c.hlsParents=parents.map(p=>p.id);
        if(parents.length && c.hls && c.hls.kind!=='master') {
          const roles=new Set(parents.map(p=>p.role));
          if(roles.size===1)c.hls.kind=parents[0].role;
          c.hls.height=Math.max(0,...parents.map(p=>p.ref.height || 0));
          c.hls.videoOnly=parents[0].role==='video' && Boolean(parents[0].ref.audio)
            && Boolean(parents[0].ref.codecs) && !/(?:mp4a|ac-3|ec-3|opus)/i.test(parents[0].ref.codecs);
        }
        c.hlsProtected=Boolean(c.hls?.protected || (c.hls?.kind==='master' && all.some(child=>children.get(child.id)?.some(p=>p.id===c.id) && child.hls?.protected)));
      }
      return all.filter(c=>!children.has(c.id)).sort((a,b) => rank(b)-rank(a) || b.timestamp-a.timestamp);
    }
    summary(c) {
      if(c.type!=='hls')return undefined;
      const h=c.hls;
      return {kind:h?.kind || 'unknown',max_height:h?.maxResolution || h?.height || 0,
        quality_count:h ? new Set(h.variants.map(v=>v.height ? `${v.width}x${v.height}` : key(v.url))).size : 0,
        audio_tracks:h?.audioTracks.length || 0,subtitles:h?.subtitles.length || 0,
        video_only:Boolean(h?.videoOnly),audio_only:h?.kind==='audio',protected:Boolean(c.hlsProtected)};
    }
    complete(d) { this.requests.delete(d.requestId); }
  }
  globalThis.KittyMedia = Object.freeze({Store, manifestType, isManifest, mediaType, directType, technical, qualityKey, key, rank});
  globalThis.KittyHls = globalThis.KittyMedia; // Compatibility with the first HLS implementation.
})();
