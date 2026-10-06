const HOST = "com.kitty.download_manager";
const FRONTEND_VERSION = browser.runtime.getManifest().version;
const NATIVE_PROTOCOL_VERSION = globalThis.KittyShared?.NATIVE_PROTOCOL_VERSION || 1;
const NATIVE_CLIENT = Object.freeze({ version: FRONTEND_VERSION, protocol: NATIVE_PROTOCOL_VERSION });
const SAFE_NATIVE_ACTIONS = new Set(["status", "get_settings", "compatibility", "diagnostics", "check_updates", "youtube_auth_status", "open_logs"]);
let compatibilityCache = null;
let compatibilityPromise = null;

let cachedStatus = null;
let cachedAt = 0;
let statusPromise = null;

const CONTEXT_MENU_ID = "kitty-download-with-kitty";
const CONTEXT_MENU_CONTEXTS = Object.freeze([
  "page", "frame", "selection", "link", "editable", "image", "video", "audio"
]);

const hlsStore = globalThis.KittyMedia ? new KittyMedia.Store() : null;
const mediaItems = globalThis.KittyMediaItems ? new KittyMediaItems.Store() : null;
const hlsReader = globalThis.KittyHlsResponse ? new KittyHlsResponse.Reader(browser.webRequest) : null;
function mediaPayload(c) {
  // Relationships stay inside the catalogue. Native Messaging needs just the
  // chosen complete URL/context, never a large tree of signed child URLs.
  const {hls,hlsParents,hlsProtected,hlsDuplicateLogged,requestContext,...source}=c;
  const context=requestContext || KittyRequestContext.capture(c.url,Object.entries(c.headers||{}).map(([name,value])=>({name,value})));
  return {...source, ...(context ? {request_context:context} : {}),
    ...(source.variants ? {variants:source.variants.map(mediaPayload)} : {}), ...(hls?.kind ? {manifest_kind:hls.kind} : {})};
}
function requiresRequestContext(c) {
  return KittyRequestContext.requiresBackend(c.requestContext)||c.variants?.some(requiresRequestContext);
}
function requestContextUpgrade(comp,sources) {
  return !KittyShared.supportsRequestContext(comp)&&sources.some(requiresRequestContext)
    ? {ok:false,code:'request_context_backend_update_required',error:'Cette source nécessite Kitty Backend v8.40 ou plus récent pour transmettre son contexte réseau.'} : null;
}
function notifyHls(tabId) {
  browser.runtime.sendMessage({type:"kitty-hls-changed", tabId}).catch(() => {});
}
if (hlsStore && browser.webRequest) {
  const filter = {urls:["http://*/*", "https://*/*"]};
  browser.webRequest.onBeforeRequest.addListener(d => {
    if(d.type==='main_frame')hlsReader?.clear(d.tabId);
    hlsStore.before(d);
  }, filter);
  browser.webRequest.onBeforeSendHeaders.addListener(d => hlsStore.headers(d), filter, ["requestHeaders"]);
  browser.webRequest.onHeadersReceived.addListener(d => {
    const mime = (d.responseHeaders || []).find(h => h.name.toLowerCase() === "content-type")?.value || "";
    if (d.tabId < 0 || !KittyMedia.mediaType(d.url, mime)) return;
    // Attach the tee synchronously, before awaiting tabs.get. No additional
    // HTTP request: we inspect the player's original authenticated response.
    const body=KittyMedia.manifestType(d.url,mime)==='hls' ? hlsReader?.read(d) : null;
    const ready=(async()=>{
      // After installing on an already open page, documentUrl can refer to an iframe.
      let page;
      if (!hlsStore.tabs.has(d.tabId)) {
        try { page = (await browser.tabs.get(d.tabId)).url; } catch { return; }
      }
      const previous = new Map(hlsStore.list(d.tabId).map(c => [c.id,c.variants?.length || 1]));
      const candidate = hlsStore.response(d, page);
      if (candidate && hlsStore.list(d.tabId).some(c=>c.id===candidate.id)) {
        if (!previous.has(candidate.id)) console.debug("Kitty media: source détectée", {type:candidate.type, tabId:d.tabId, count:hlsStore.list(d.tabId).length});
        if (!previous.has(candidate.id) || previous.get(candidate.id)!==(candidate.variants?.length || 1)) notifyHls(d.tabId);
      }
      return candidate;
    })();
    if(body)body.then(async text=>{
      const candidate=await ready;
      const before=new Set(hlsStore.list(d.tabId).map(c=>c.id));
      const result=text!==null ? hlsStore.manifest(candidate,text) : null;
      if(!result)return;
      const after=hlsStore.list(d.tabId);
      const source=result.candidate;
      if(result.changed) {
        console.debug('Kitty HLS: manifest classifié',{tabId:d.tabId,kind:source.hls.kind});
        if(result.kind==='master')console.debug('Kitty HLS: groupe construit',{tabId:d.tabId,qualities:hlsStore.summary(source).quality_count,audio:source.hls.audioTracks.length,subtitles:source.hls.subtitles.length});
        else if(source.hlsParents?.length)console.debug('Kitty HLS: enfant attaché au master',{tabId:d.tabId,kind:source.hls.kind});
      } else if(!source.hlsDuplicateLogged) {
        source.hlsDuplicateLogged=true;
        console.debug('Kitty HLS: duplicate ignoré',{tabId:d.tabId,kind:source.hls.kind});
      }
      const attached=[...before].filter(id=>!after.some(c=>c.id===id));
      if(attached.length)console.debug('Kitty HLS: enfants attachés au master',{tabId:d.tabId,count:attached.length});
      if(result.changed || attached.length)notifyHls(d.tabId);
    }).catch(()=>{});
    // Firefox requires a synchronous blocking event to attach the filter
    // before the channel passes this phase. Return immediately, without a
    // BlockingResponse or a promise: neither headers nor delivery are changed.
  }, filter, ["responseHeaders", "blocking"]);
  browser.webRequest.onCompleted.addListener(d => hlsStore.complete(d), filter);
  browser.webRequest.onErrorOccurred.addListener(d => {hlsReader?.error(d.requestId);hlsStore.complete(d);}, filter);
  browser.tabs.onRemoved.addListener(id => { hlsReader?.clear(id);hlsStore.clear(id); mediaItems?.clear(id); notifyHls(id); });
  browser.tabs.onUpdated.addListener((id, change) => {
    if (change.url) { hlsReader?.clear(id);hlsStore.navigate(id, change.url); mediaItems?.clear(id); notifyHls(id); }
  });
}
function isKittyUi(sender) {
  return sender?.url === browser.runtime.getURL("popup.html");
}
async function hlsForTab(tabId) {
  if (!hlsStore || !Number.isInteger(tabId)) return [];
  try {
    const tab = await browser.tabs.get(tabId);
    if (!/^https?:\/\//i.test(tab.url || "")) return [];
    hlsStore.navigate(tabId, tab.url);
    return hlsStore.list(tabId).map(c => ({...c, title:String(tab.title || c.type.toUpperCase()+" stream").slice(0,1000)}));
  } catch { hlsStore.clear(tabId); return []; }
}
async function hlsCompatibility() {
  let comp = await ensureCompatibility();
  if (comp?.compatible && !KittyShared.supportsAutomatic(comp)) {
    // A backend upgrade should work even if the background cached the older version.
    compatibilityCache = null;
    comp = await ensureCompatibility();
  }
  return comp;
}
async function withHlsFallbacks(payload, tabId) {
  const comp = await hlsCompatibility();
  if (payload.mode !== 'image' && KittyShared.supportsAutomatic(comp)) payload = {...payload,automatic:true};
  const candidates = (await hlsForTab(tabId)).filter(c=>
    (!requiresRequestContext(c)||KittyShared.supportsRequestContext(comp)) && !c.hlsProtected
    && !(c.type==='direct_audio' && ['720','1080','best'].includes(payload.mode || '1080'))
    && !(c.type.startsWith('direct_') && payload.mode==='image'));
  // A right-click on an external link must never download this tab's unrelated player.
  const samePage = candidates.find(c => c.page_url === payload.url || (
    KittyMediaResolver.canonicalizeKnownMediaUrl(c.page_url)
    && KittyMediaResolver.canonicalizeKnownMediaUrl(c.page_url) === KittyMediaResolver.canonicalizeKnownMediaUrl(payload.url)));
  if (!samePage) {
    if (payload.automatic && candidates.length) console.debug('[Kitty media] catalogue candidates rejected: unrelated_page');
    return payload;
  }
  // The page resolver may shorten a Reddit/social permalink. Keep the observed
  // page context; the backend already canonicalizes the classic extraction URL.
  // Never equate arbitrary same-host links or a feed with a different post.
  payload = {...payload,url:samePage.page_url};
  // Include each source family before additional players of the same family.
  // Audio requests prefer a native direct audio resource over a direct video.
  const preferred = ['audio','mp3'].includes(payload.mode)
    ? [...candidates.filter(c=>c.type==='direct_audio'), ...candidates.filter(c=>c.type!=='direct_audio')] : candidates;
  const family = c => c.type.startsWith('direct_') ? 'direct' : c.type;
  const diverse = preferred.filter((c,i)=>preferred.findIndex(v=>family(v)===family(c))===i);
  const planned = [...diverse, ...preferred.filter(c=>!diverse.includes(c))].slice(0,3);
  if (payload.automatic) {
    console.debug('[Kitty media] catalogue candidates accepted:', planned.map(c=>c.type).join(','));
    return {...payload,media_fallbacks:planned.map(mediaPayload)};
  }
  if (KittyShared.supportsDirect(comp)) return {...payload, media_fallbacks:candidates.slice(0,3).map(mediaPayload)};
  if (KittyShared.supportsDash(comp)) {
    const manifests=candidates.filter(c=>!c.type.startsWith('direct_')).slice(0,3);
    return manifests.length ? {...payload,media_fallbacks:manifests.map(mediaPayload)} : payload;
  }
  const hls = candidates.filter(c => c.type === 'hls');
  return KittyShared.supportsHls(comp) && hls.length ? {...payload, hls_fallbacks:hls.slice(0,3).map(mediaPayload)} : payload;
}
async function chosenHls(message) {
  const candidates = await hlsForTab(message.tabId);
  const source = candidates.find(c => c.id === message.candidateId);
  if (!source) return {ok:false, code:"hls_candidate_missing", error:"Flux réseau introuvable. Recharge la page et relance la lecture."};
  if(source.type==='hls' && source.hlsProtected)return {ok:false,code:'drm_protected',error:'Flux HLS protégé / DRM'};
  const comp = await hlsCompatibility();
  if (!(source.type.startsWith('direct_') ? KittyShared.supportsDirect(comp) : source.type === 'dash' ? KittyShared.supportsDash(comp) : KittyShared.supportsHls(comp)))
    return {ok:false, code:source.type+'_backend_update_required', error:source.type === 'dash'
      ? "Le mode DASH nécessite Kitty Backend v8.34 ou plus récent."
      : source.type.startsWith('direct_') ? "Les médias directs nécessitent Kitty Backend v8.35 ou plus récent."
      : "Le mode HLS nécessite Kitty Backend v8.33 ou plus récent."};
  const upgrade=requestContextUpgrade(comp,[source]);if(upgrade)return upgrade;
  const probe = ["kitty-probe-hls", "kitty-probe-media"].includes(message.type);
  const result = await nativeMessage({action:probe ? (KittyShared.supportsDash(comp) ? "media_probe" : "hls_probe") : "download",
    url:source.url, media_source:mediaPayload(source), mode:message.mode || "1080", force:Boolean(message.force)});
  if (!probe) invalidateStatus();
  return result;
}

async function itemsForTab(tabId) {
  const catalogue=await hlsForTab(tabId);
  try {
    const tab=await browser.tabs.get(tabId);
    if(mediaItems&&!mediaItems.tabs.has(tabId))try{await browser.tabs.sendMessage?.(tabId,{type:'kitty-media-rescan'});}catch{}
    return mediaItems?.list(tabId,tab.url,catalogue) || [];
  }catch{return [];}
}
function publicItem(item) {
  const {contexts,identity,embedUrl,extractionUrl,candidates,...safe}=item;
  return {...safe,candidates:candidates.map(c=>({id:c.id,sourceType:c.sourceType,type:c.type,
    maxHeight:c.metadata?.height || c.hls?.maxResolution || null}))};
}
async function downloadItem(message) {
  let comp=await hlsCompatibility();
  if(comp?.compatible&&!KittyShared.supportsMediaItems(comp)){compatibilityCache=null;comp=await ensureCompatibility();}
  if(!KittyShared.supportsMediaItems(comp))return {ok:false,error:'Les médias de la page nécessitent Kitty Backend v8.39 ou plus récent.'};
  if(message.track_selection&&Object.keys(message.track_selection).length&&!KittyShared.supportsMediaTracks(comp))return {ok:false,error:'Les pistes nécessitent Kitty Backend v8.42 ou plus récent.'};
  let items=await itemsForTab(message.tabId),item=items.find(i=>i.id===message.itemId);
  // An unresolved DOM item can be selected before a player initializes. Take
  // a fresh, acknowledged frame snapshot before deciding it has no safe URL.
  if(item&&(!item.downloadable||!item.candidates.some(c=>c.type!=='ytdlp'&&!c.hlsProtected))){
    await Promise.allSettled([...new Set(item.contexts.map(c=>c.frameId))].map(frameId=>
      browser.tabs.sendMessage?.(message.tabId,{type:'kitty-media-rescan'},{frameId})));
    items=await itemsForTab(message.tabId);item=items.find(i=>i.id===message.itemId);
  }
  if(!item?.downloadable)return {ok:false,error:'Aucune source HTTP exploitable pour ce média.'};
  const network=item.candidates.filter(c=>c.type!=='ytdlp'&&!c.hlsProtected)
    .sort((a,b)=>(b.maxHeight||0)-(a.maxHeight||0));
  const diverse=network.filter((c,i)=>network.findIndex(v=>v.sourceType===c.sourceType)===i);
  // Include the original (often unknown height) as well as transcodes. The
  // backend resolves these bounded, item-owned candidates before planning.
  const sources=[...diverse,...network.filter(c=>!diverse.includes(c))].slice(0,12);
  const upgrade=requestContextUpgrade(comp,sources);if(upgrade)return upgrade;
  const result=await nativeMessage({action:'download',url:item.extractionUrl,mode:message.mode||'1080',force:Boolean(message.force),automatic:true,
    media_item:{id:item.id,page_url:item.pageUrl,title:item.title,title_source:item.titleSource,thumbnail:item.thumbnail,media_kind:item.mediaKind,
      explicit_sources:item.explicitSources,prefer_extractor:item.preferExtractor},
    media_fallbacks:sources.map(c=>({...mediaPayload(c),media_item_id:item.id})),track_selection:message.track_selection});
  invalidateStatus();return result;
}

function httpUrl(value) {
  const raw = typeof value === "string" ? value.trim() : "";
  return /^https?:\/\//i.test(raw) ? raw : null;
}

function knownMediaPage(url) {
  if (!url) return false;
  try {
    const key = globalThis.KittyShared?.sourceInfo?.(url)?.key;
    return Boolean(key && key !== "web");
  } catch {
    return false;
  }
}

function resolveContextDownloadUrl(info, tab) {
  const linkUrl = httpUrl(info?.linkUrl);
  const srcUrl = httpUrl(info?.srcUrl);
  const frameUrl = httpUrl(info?.frameUrl);
  const pageUrl = httpUrl(info?.pageUrl) || httpUrl(tab?.url);

  // Un clic droit sur un lien doit viser ce lien : pratique depuis un feed ou une page de résultats.
  if (linkUrl) return linkUrl;

  const mediaType = String(info?.mediaType || "").toLowerCase();
  if (mediaType === "video" || mediaType === "audio") {
    // Sur YouTube/TikTok/etc., l'URL du lecteur est souvent blob:/CDN/temporaire :
    // on laisse yt-dlp travailler à partir de la vraie page.
    if (knownMediaPage(frameUrl)) return frameUrl;
    if (knownMediaPage(pageUrl)) return pageUrl;
    // Sur une page générique, une vraie URL HTTP du média reste utile.
    if (srcUrl) return srcUrl;
  }

  // Images, sélection, champ éditable, zone vide, iframe… => page visitée.
  return frameUrl || pageUrl || srcUrl;
}

function contextMenuTitle(language) {
  return language === "en" ? "Download with Kitty" : "Télécharger avec Kitty";
}

async function refreshKittyContextMenu() {
  if (!browser.menus?.create) return;
  const saved = await browser.storage.local.get("uiLanguage");
  try { await browser.menus.remove(CONTEXT_MENU_ID); } catch {}
  browser.menus.create({
    id: CONTEXT_MENU_ID,
    title: contextMenuTitle(saved?.uiLanguage),
    contexts: [...CONTEXT_MENU_CONTEXTS]
  });
}

async function downloadFromContextMenu(info, tab) {
  const url = resolveContextDownloadUrl(info, tab);
  if (!url) return { ok: false, error: "URL HTTP/HTTPS requise." };

  const mode = await savedDownloadMode();
  const result = await nativeMessage(await withHlsFallbacks({
    action: "download",
    url,
    mode,
    force: false
  }, tab?.id));

  invalidateStatus();
  return { ...result, selectedMode: mode, url };
}

async function savedDownloadMode() {
  const saved = await browser.storage.local.get(["selectedMode", "imageOnlyMode"]);
  return saved?.imageOnlyMode ? "image" : saved?.selectedMode || "1080";
}


async function rawNativeMessage(payload) {
  const result=await browser.runtime.sendNativeMessage(HOST, { ...payload, client: NATIVE_CLIENT });
  if(result?.state?.active || (payload.action==='download' && result?.ok)) armSourceRefresh();
  if(payload.action==='status') void serviceSourceRefresh(result?.state?.active);
  return result;
}

let sourceRefreshTimer=null;
let servicingSourceRefresh=false;
function armSourceRefresh() {
  if(sourceRefreshTimer)return;
  sourceRefreshTimer=setTimeout(async()=>{
    sourceRefreshTimer=null;
    try {
      const result=await getStatusCached(true);
      if(result?.state?.active)armSourceRefresh();
    }catch{}
  },2000);
}
// Reconnect to an existing worker after an extension/background restart.
armSourceRefresh();
async function serviceSourceRefresh(job) {
  const request=job?.source_refresh_request;
  if(!request || servicingSourceRefresh)return;
  servicingSourceRefresh=true;
  try {
    let source;
    if(request.media_item_id){
      const item=(await itemsForTab(request.tab_id)).find(i=>i.id===request.media_item_id);
      source=item?.candidates.find(c=>c.id===request.candidate_id && c.type!=='ytdlp');
    }else{
      source=(await hlsForTab(request.tab_id)).find(c=>c.id===request.candidate_id);
    }
    if(!source)return;
    await nativeMessage({action:'refresh_source',job_id:job.id,nonce:request.nonce,
      media_source:{...mediaPayload(source), ...(request.media_item_id ? {media_item_id:request.media_item_id} : {})}});
  }catch{}finally{servicingSourceRefresh=false;}
}

async function ensureCompatibility() {
  if (compatibilityCache?.compatible) return compatibilityCache;
  if (compatibilityPromise) return compatibilityPromise;
  compatibilityPromise = rawNativeMessage({ action: "compatibility" })
    .then(result => {
      const comp = result?.compatibility;
      if (result?.ok && comp?.compatible) compatibilityCache = comp;
      return comp || { compatible: false, message: "Backend Kitty ancien ou incompatible." };
    })
    .catch(() => ({ compatible: false, message: "Backend Kitty ancien ou incompatible." }))
    .finally(() => { compatibilityPromise = null; });
  return compatibilityPromise;
}

async function nativeMessage(payload) {
  const action = String(payload?.action || "");
  if (!SAFE_NATIVE_ACTIONS.has(action)) {
    const comp = await ensureCompatibility();
    if (!comp?.compatible) {
      return {
        ok: false,
        code: "incompatible_frontend_backend",
        error: "Kitty doit être mise à jour",
        error_hint: comp?.message || "Lance l’updater puis recharge l’extension."
      };
    }
    const featureError = KittyShared.downloadModeError(payload?.mode, comp);
    if (featureError) return featureError;
  }
  return rawNativeMessage(payload);
}

async function getStatusCached(force = false) {
  const now = Date.now();
  const active = Boolean(cachedStatus?.state?.active);
  const ttl = active ? 450 : 1800;

  if (!force && cachedStatus && now - cachedAt < ttl) return cachedStatus;
  if (statusPromise) return statusPromise;

  statusPromise = nativeMessage({ action: "status" })
    .then(result => {
      cachedStatus = result;
      cachedAt = Date.now();
      return result;
    })
    .finally(() => {
      statusPromise = null;
    });

  return statusPromise;
}

function invalidateStatus() {
  cachedStatus = null;
  cachedAt = 0;
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (!message || typeof message !== "object") return;

  if(message.type==='kitty-media-dom') {
    if(mediaItems?.update(sender,message.items))notifyHls(sender.tab.id);
    return;
  }
  if(['kitty-media-items','kitty-probe-item','kitty-download-item','kitty-download-items'].includes(message.type)) {
    if(!isKittyUi(sender))return Promise.resolve({ok:false,error:'Requête Kitty non autorisée.'});
    if(message.type==='kitty-media-items')return itemsForTab(message.tabId).then(items=>({ok:true,items:items.map(publicItem)}));
    if(message.type==='kitty-probe-item')return (async()=>{
      const item=(await itemsForTab(message.tabId)).find(i=>i.id===message.itemId);
      if(!item?.extractionUrl)return {ok:false};
      const sources=item.candidates.filter(c=>c.type!=='ytdlp'&&!c.hlsProtected).slice(0,12);
      const source=sources[0],comp=await hlsCompatibility();
      const result=KittyShared.supportsMediaTracks(comp) ? await nativeMessage({action:'media_item_probe',url:item.extractionUrl,
        media_item:{id:item.id,page_url:item.pageUrl,prefer_extractor:item.preferExtractor},media_sources:sources.map(c=>({...mediaPayload(c),media_item_id:item.id}))})
        : source ? await nativeMessage({action:'media_probe',media_source:mediaPayload(source)})
        : await nativeMessage({action:'media_item_probe',url:item.extractionUrl,media_item:{id:item.id,page_url:item.pageUrl}});
      if(result?.ok)mediaItems.enrich(item.id,result);
      return result;
    })();
    if(message.type==='kitty-download-item')return downloadItem(message);
    return (async()=>{
      if(!Array.isArray(message.itemIds)||message.itemIds.length>100)return {ok:false,error:'Sélection invalide.'};
      const results=[];
      for(const itemId of new Set(message.itemIds))results.push({itemId,...await downloadItem({...message,itemId,track_selection:message.trackSelections?.[itemId]})});
      return {ok:true,results,added:results.filter(r=>r.ok).length};
    })();
  }

  if (message.type === 'kitty-media-context' && Number.isInteger(sender?.tab?.id) && typeof message.hasBlob==='boolean') {
    hlsStore?.context(sender.tab.id,sender.tab.url,message.hasBlob);
    notifyHls(sender.tab.id);
    return;
  }

  if (["kitty-media-list", "kitty-download-media", "kitty-probe-media", "kitty-hls-list", "kitty-download-hls", "kitty-probe-hls", "kitty-download-page"].includes(message.type)) {
    if (!isKittyUi(sender)) return Promise.resolve({ok:false, error:"Requête Kitty non autorisée."});
    if (["kitty-media-list", "kitty-hls-list"].includes(message.type)) return Promise.all([hlsForTab(message.tabId),hlsCompatibility()]).then(([candidates,comp]) => ({ok:true,
      automatic_available:KittyShared.supportsAutomatic(comp),
      blob_unavailable:Boolean(hlsStore?.tabs.get(message.tabId)?.hasBlob && !candidates.length),
      candidates:candidates.map(c => ({id:c.id,type:c.type,title:c.title,content_type:c.content_type,hostname:c.hostname,
        ...(c.metadata ? {metadata:{size:c.metadata.size,format:c.metadata.format,height:c.metadata.height}} : {}),
        ...(c.type==='hls' ? {hls:hlsStore.summary(c)} : {}),format_count:c.variants?.length || 1}))}));
    if (message.type === "kitty-download-page") return (async () => {
      if (!httpUrl(message.url)) return {ok:false, error:"URL HTTP/HTTPS requise."};
      const result = await nativeMessage(await withHlsFallbacks({action:"download", url:message.url,
        mode:message.mode || "1080", force:Boolean(message.force)}, message.tabId));
      invalidateStatus();
      return result;
    })();
    return chosenHls(message);
  }

  if (message.type === "kitty-pill-download") {
    return (async () => {
      const url = message.url;
      if (!url || !/^https?:\/\//i.test(url)) {
        return { ok: false, error: "URL HTTP/HTTPS requise." };
      }

      const mode = await savedDownloadMode();
      const result = await nativeMessage(await withHlsFallbacks({
        action: "download",
        url,
        mode,
        force: Boolean(message.force)
      }, sender?.tab?.id));

      invalidateStatus();
      return { ...result, selectedMode: mode };
    })();
  }


  if (message.type === "kitty-get-output-dir") {
    return (async () => {
      const result = await nativeMessage({ action: "get_settings" });
      const outputDir = result?.settings?.output_dir || result?.output_dir || null;
      if (result?.ok && outputDir) {
        try { await browser.storage.local.set({ kittyOutputDir: outputDir }); } catch {}
      }
      return result;
    })();
  }

  if (message.type === "kitty-choose-output-dir") {
    return (async () => {
      // Le sélecteur natif prend le focus et Firefox peut fermer la popup.
      // Le background possède donc toute l'opération jusqu'à la persistance
      // du nouveau chemin côté Native Messaging host.
      const result = await nativeMessage({ action: "choose_output_dir" });
      const outputDir = result?.output_dir || result?.settings?.output_dir || null;

      if (result?.ok && !result?.cancelled && outputDir) {
        try { await browser.storage.local.set({ kittyOutputDir: outputDir }); } catch {}
      }

      return result;
    })();
  }

  if (message.type === "kitty-youtube-auth-start") {
    return nativeMessage({ action: "youtube_auth_start" });
  }

  if (message.type === "kitty-download-playlist") {
    return (async () => {
      const url = message.url;
      const mode = message.mode || "1080";

      if (!url || !/^https?:\/\//i.test(url)) {
        return { ok: false, error: "URL HTTP/HTTPS requise." };
      }

      const result = await nativeMessage({
        action: "download_playlist",
        url,
        mode
      });

      invalidateStatus();
      return result;
    })();
  }

  if (message.type === "kitty-pill-status") {
    return getStatusCached(Boolean(message.force));
  }
});

if (browser.menus?.onClicked?.addListener) {
  browser.menus.onClicked.addListener((info, tab) => {
    if (info?.menuItemId !== CONTEXT_MENU_ID) return;
    return downloadFromContextMenu(info, tab).catch(() => undefined);
  });

  refreshKittyContextMenu().catch(() => undefined);
}

if (browser.storage?.onChanged?.addListener) {
  browser.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "local" && changes?.uiLanguage && browser.menus?.create) {
      refreshKittyContextMenu().catch(() => undefined);
    }
  });
}
