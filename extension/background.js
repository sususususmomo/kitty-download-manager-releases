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
let statusGeneration = 0;
let statusPromiseGeneration = 0;

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
  return Boolean(browser.runtime.getURL && sender?.url === browser.runtime.getURL("popup.html"));
}
async function currentDocumentSender(message,sender) {
  if(!Number.isInteger(sender?.tab?.id))return null;
  const tab=await browser.tabs.get(sender.tab.id);
  const frameId=sender.frameId||0;
  const pageUrl=httpUrl(message.pageUrl);
  if(!pageUrl || pageUrl===sender.url){
    if(frameId===0&&sender.url!==tab.url)return null;
    return {...sender,tab};
  }
  // Firefox's sender.url can stay at the initial document URL after
  // pushState. Challenge this exact live document before accepting its URL.
  if(!message.documentToken || (frameId===0&&pageUrl!==tab.url))return null;
  const context=await browser.tabs.sendMessage(tab.id,{type:'kitty-document-context'},
    sender.documentId?{documentId:sender.documentId}:{frameId});
  if(context?.pageUrl!==pageUrl || context?.documentToken!==message.documentToken)return null;
  return {...sender,tab,url:pageUrl,initialUrl:sender.url};
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
  const selected=candidates.find(c=>c.id===payload.preferred_source_id);
  const planned = [...(selected?[selected]:[]),...diverse,...preferred.filter(c=>!diverse.includes(c))].filter((c,i,all)=>all.indexOf(c)===i).slice(0,3);
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
  downloadTrace(message,'compatibility');
  let comp=await hlsCompatibility();
  if(comp?.code==='native_host_unavailable')return {ok:false,...comp};
  if(comp?.compatible&&!KittyShared.supportsMediaItems(comp)){compatibilityCache=null;comp=await ensureCompatibility();}
  if(!KittyShared.supportsMediaItems(comp))return {ok:false,error:'Les médias de la page nécessitent Kitty Backend v8.39 ou plus récent.'};
  if(message.track_selection&&Object.keys(message.track_selection).length&&!KittyShared.supportsMediaTracks(comp))return {ok:false,error:'Les pistes nécessitent Kitty Backend v8.42 ou plus récent.'};
  downloadTrace(message,'media_selection',{itemId:message.itemId});
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
  const selected=network.find(c=>c.id===message.preferred_source_id);
  if(selected){network.splice(network.indexOf(selected),1);network.unshift(selected);}
  const diverse=network.filter((c,i)=>network.findIndex(v=>v.sourceType===c.sourceType)===i);
  // Include the original (often unknown height) as well as transcodes. The
  // backend resolves these bounded, item-owned candidates before planning.
  const sources=[...diverse,...network.filter(c=>!diverse.includes(c))].slice(0,12);
  const upgrade=requestContextUpgrade(comp,sources);if(upgrade)return upgrade;
  const requestedMode=message.mode||'1080';
  const mode=message.shared&&item.mediaKind==='audio'&&['720','1080','best'].includes(requestedMode)?'audio':requestedMode;
  const payload={action:'download',url:item.extractionUrl,mode,force:Boolean(message.force),automatic:true,
    media_item:{id:item.id,page_url:item.pageUrl,title:item.title,title_source:item.titleSource,thumbnail:item.thumbnail,media_kind:item.mediaKind,
      explicit_sources:item.explicitSources,prefer_extractor:item.preferExtractor},
    media_fallbacks:sources.map(c=>({...mediaPayload(c),media_item_id:item.id})),track_selection:message.track_selection};
  if(message.shared){
    payload.track_policy='prefer_available';
    if(sources.some(c=>c.id===message.preferred_source_id))payload.preferred_source_id=message.preferred_source_id;
    return dispatchSharedDownload(payload,message);
  }
  const result=await nativeMessage(payload);
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
  return saved?.imageOnlyMode ? "image" : ['720','1080','best','audio','mp3'].includes(saved?.selectedMode) ? saved.selectedMode : "1080";
}


// Both entry points resolve preferences and targets here. Storage is owned by
// the background, so closing the popup cannot interrupt a pending change.
let downloadOperation = Promise.resolve();
const pendingDownloads=new Map();
let settingsRevision=0,downloadTraceCounter=0;
const downloadEvents=[];
const downloadJobTraces=new Map();
browser.storage.onChanged?.addListener((changes,area)=>{
  if(area==='local' && ['selectedMode','imageOnlyMode','playlistMode'].some(key=>key in changes))settingsRevision++;
});
function diagnosticText(value) {
  return String(value ?? '').replace(/https?:\/\/[^\s<>"']+/gi,raw=>{
    try {const u=new URL(raw);return `${u.origin}/[path-redacted]`;}catch{return '[url-redacted]';}
  }).replace(/(?:Bearer\s+\S+|(?:token|cookie|authorization|signature|password)\s*[:=]\s*[^\s,;]+)/gi,'[secret-redacted]').slice(0,2000);
}
function diagnosticUrl(value) {
  try {const u=new URL(value);return {origin:u.origin,path:'[redacted]',queryKeys:[...new Set(u.searchParams.keys())]};}catch{return null;}
}
function downloadTrace(message,stage,data={}) {
  if(!message?._trace)return;
  message._trace.stage=stage;
  const event={time:new Date().toISOString(),requestId:message._trace.id,entry:message._trace.entry,tabId:message._trace.tabId,stage,...data};
  for(const key of ['error','error_hint','error_detail'])if(event[key])event[key]=diagnosticText(event[key]);
  downloadEvents.push(event);if(downloadEvents.length>200)downloadEvents.shift();
  console.debug('Kitty download',event);
}
function sharedStartDownload(message,sender) {
  const tabId=isKittyUi(sender)?message.tabId:sender?.tab?.id;
  if(!Number.isInteger(tabId)||(!isKittyUi(sender)&&sender?.frameId!==0))
    return Promise.resolve({ok:false,code:'unauthorized_download',error:'Requête Kitty non autorisée.',stage:'received'});
  const key=JSON.stringify([tabId,sender?.documentId||message.documentToken||sender?.url||'',message.pageUrl||'',message.forceToken||null,settingsRevision]);
  if(pendingDownloads.has(key))return pendingDownloads.get(key);
  const request={...message,_trace:{id:`download-${Date.now().toString(36)}-${++downloadTraceCounter}`,entry:isKittyUi(sender)?'popup':'pill',tabId,stage:'received'}};
  downloadTrace(request,'received',{url:diagnosticUrl(sender?.tab?.url||sender?.url),messageType:message.type});
  const result=serialDownloadOperation(async()=>{
    try {
      const response=await addDownload(request,sender);
      const stage=response?.stage || (response?.ok?'accepted':request._trace.stage);
      downloadTrace(request,stage,{ok:Boolean(response?.ok),jobId:KittyShared.downloadJobId(response),code:response?.code,
        error:response?.error,error_hint:response?.error_hint,error_detail:response?.error_detail});
      const jobId=KittyShared.downloadJobId(response);
      if(jobId){downloadJobTraces.set(jobId,{message:request,signature:''});if(downloadJobTraces.size>100)downloadJobTraces.delete(downloadJobTraces.keys().next().value);}
      return {...response,stage,requestId:request._trace.id};
    }catch(error){
      const stage=request._trace.stage;
      downloadTrace(request,stage,{ok:false,error:error?.message||String(error),exception:error?.name||'Error'});
      return {ok:false,code:stage==='native_request'?'native_host_unavailable':'download_start_failed',
        error:diagnosticText(error?.message||String(error)),stage,requestId:request._trace.id};
    }
  });
  pendingDownloads.set(key,result);
  result.finally(()=>{if(pendingDownloads.get(key)===result)pendingDownloads.delete(key);});
  return result;
}
function serialDownloadOperation(operation) {
  const result = downloadOperation.then(operation);
  downloadOperation = result.catch(() => {});
  return result;
}
function cleanTrackPreferences(raw) {
  const result = {};
  if (!raw || typeof raw !== 'object') return result;
  for (const key of ['audioLanguage','audioTrackId'])
    if(typeof raw[key]==='string' && raw[key].length<=200 && !/[\x00-\x1f\x7f]/.test(raw[key]))result[key]=raw[key];
  for (const key of ['subtitleLanguages','subtitleTrackIds'])
    if(Array.isArray(raw[key]))result[key]=[...new Set(raw[key].filter(v=>typeof v==='string'&&v.length>0&&v.length<=200&&!/[\x00-\x1f\x7f]/.test(v)))].slice(0,20);
  if(typeof raw.preferOriginal==='boolean')result.preferOriginal=raw.preferOriginal;
  return result;
}
async function downloadSettings(tabId, change) {
  const tab=await browser.tabs.get(tabId);
  const saved=await browser.storage.local.get(['kittyTrackPreferences','kittyDownloadTargets']);
  const targets={...(saved?.kittyDownloadTargets||{})};
  const scoped=targets[tabId]?.pageUrl===tab.url ? targets[tabId] : {pageUrl:tab.url,tracks:{}};
  let tracks=cleanTrackPreferences(saved?.kittyTrackPreferences);
  delete tracks.audioTrackId;delete tracks.subtitleTrackIds;
  if(change) {
    if(Object.hasOwn(change,'itemId'))scoped.itemId=typeof change.itemId==='string'?change.itemId:null;
    if(Object.hasOwn(change,'collectionUrl'))scoped.collectionUrl=httpUrl(change.collectionUrl);
    if(Object.hasOwn(change,'candidateId'))scoped.candidateId=typeof change.candidateId==='string'?change.candidateId:null;
    if(change.track_selection && typeof change.itemId==='string') {
      const preference=cleanTrackPreferences(change.track_selection);
      scoped.tracks={...scoped.tracks,[change.itemId]:preference};
      // Languages are portable; opaque IDs remain tied to this item and page.
      tracks={...preference};delete tracks.audioTrackId;delete tracks.subtitleTrackIds;
      const item=(await itemsForTab(tabId)).find(i=>i.id===change.itemId);
      const audio=item?.audioTracks?.find(t=>t.id===preference.audioTrackId);
      if(audio?.language)tracks.audioLanguage=audio.language;
      const languages=(preference.subtitleTrackIds||[]).map(id=>item?.subtitleTracks?.find(t=>t.id===id)?.language).filter(Boolean);
      if(languages.length)tracks.subtitleLanguages=[...new Set([...(tracks.subtitleLanguages||[]),...languages])];
    }
    targets[tabId]=scoped;
    const bounded=Object.fromEntries(Object.entries(targets).slice(-100));
    await browser.storage.local.set({kittyTrackPreferences:tracks,kittyDownloadTargets:bounded});
  }
  return {ok:true,pageUrl:tab.url,itemId:scoped.itemId||null,candidateId:scoped.candidateId||null,
    trackPreferences:tracks,trackSelections:scoped.tracks||{},collectionUrl:scoped.collectionUrl||null};
}
function sharedRequestKey(payload) {
  // Use the stable logical identity and effective options. Never include
  // captured credentials, signed network URLs or transient probe metadata.
  const identity=payload.media_item ? [payload.media_item.page_url,payload.media_item.id] : [payload.url];
  return JSON.stringify([identity,payload.mode,payload.track_selection||{},
    payload.track_policy||'strict',payload.preferred_source_id||null]);
}

async function dispatchSharedDownload(payload, message) {
  downloadTrace(message,'compatibility');
  if(payload.track_policy==='prefer_available') {
    let comp=await ensureCompatibility();
    if(comp?.code==='native_host_unavailable')return {ok:false,...comp};
    if(!KittyShared.supportsAdaptiveTracks(comp)){compatibilityCache=null;comp=await ensureCompatibility();}
    if(!KittyShared.supportsAdaptiveTracks(comp)) {
      if(Object.keys(payload.track_selection||{}).length || payload.preferred_source_id)
        return {ok:false,code:'adaptive_tracks_backend_update_required',error:'Ces préférences nécessitent Kitty Backend v8.49 ou plus récent. Lance la mise à jour du backend.'};
      delete payload.track_policy;
    }
  }
  const requestKey=sharedRequestKey(payload);
  if(message._trace?.pageUrl && (await browser.tabs.get(message._trace.tabId)).url!==message._trace.pageUrl)
    return {ok:false,code:'stale_document',error:'La page a changé pendant la préparation du téléchargement.'};
  downloadTrace(message,'native_request',{action:payload.action,fields:Object.keys(payload).sort(),mode:payload.mode,
    url:diagnosticUrl(payload.url),sourceCount:payload.media_fallbacks?.length||0,preferredSourceId:payload.preferred_source_id||null,
    tracks:cleanTrackPreferences(payload.track_selection),destination:'backend:get_settings/output_dir',automatic:Boolean(payload.automatic)});
  const result=await nativeMessage({...payload,force:message.forceToken===requestKey});
  downloadTrace(message,'native_response',{ok:Boolean(result?.ok),jobId:KittyShared.downloadJobId(result),code:result?.code,
    error:result?.error,error_hint:result?.error_hint,error_detail:result?.error_detail});
  invalidateStatus();
  return {...result,requestKey,selectedMode:payload.mode};
}
async function addDownload(message,sender) {
  downloadTrace(message,'tab');
  const tabId=isKittyUi(sender)?message.tabId:sender?.tab?.id;
  if(!Number.isInteger(tabId) || (!isKittyUi(sender) && sender.frameId!==0))
    return {ok:false,error:'Requête Kitty non autorisée.'};
  const tab=await browser.tabs.get(tabId);
  message._trace.pageUrl=tab.url;
  downloadTrace(message,'tab',{url:diagnosticUrl(tab.url),frameId:sender?.frameId??null});
  if(!isKittyUi(sender)){
    let current;
    try{current=await currentDocumentSender(message,sender);}catch(error){downloadTrace(message,'tab',{error:error?.message||String(error)});}
    if(!current)return {ok:false,code:'stale_document',error:'Le document ciblé a changé. Recharge la page puis réessaie.'};
    downloadTrace(message,'tab',{sameDocumentNavigation:current.url!==sender.url,documentId:sender.documentId||null,url:diagnosticUrl(current.url)});
  }
  downloadTrace(message,'settings');
  const settings=await downloadSettings(tabId);
  let mode=await savedDownloadMode();
  const saved=await browser.storage.local.get(['playlistMode','selectedMode','imageOnlyMode']);
  downloadTrace(message,'settings',{mode,itemId:settings.itemId,candidateId:settings.candidateId,tracks:settings.trackPreferences,
    defaults:[...(!['720','1080','best','audio','mp3'].includes(saved?.selectedMode)&&!saved?.imageOnlyMode?['mode:1080']:[]),
      ...(!settings.candidateId?['source:automatic']:[]),...(!Object.keys(settings.trackPreferences).length?['tracks:automatic']:[])],destination:'backend:get_settings/output_dir'});
  if(mode!=='image' && saved?.playlistMode && settings.collectionUrl)
    return dispatchSharedDownload({action:'download_playlist',url:settings.collectionUrl,mode},message);
  if(mode!=='image') {
    downloadTrace(message,'rescan');
    try {
      const response=await browser.tabs.sendMessage?.(tabId,{type:'kitty-media-rescan'});
      if(response?.ok===false)downloadTrace(message,'rescan',{error:response.error||'Snapshot not acknowledged'});
    }catch(error){downloadTrace(message,'rescan',{error:error?.message||String(error)});}
    let items=await itemsForTab(tabId);
    let item=items.find(i=>i.id===settings.itemId);
    if(!item && /(^|\.)tiktok\.com$/i.test(new URL(tab.url).hostname)) {
      downloadTrace(message,'media_selection',{selection:'visible_tiktok'});
      try {
        const response=await browser.tabs.sendMessage(tabId,{type:'kitty-media-target'},{frameId:0});
        items=await itemsForTab(tabId);
        item=items.find(i=>i.contexts.some(c=>c.frameId===0&&c.dom.domId===response?.target?.domId));
      }catch(error){downloadTrace(message,'media_selection',{error:error?.message||String(error)});}
      // A feed with several preloaded players needs an explicit active target.
      if(!item&&items.length>1)return {ok:false,code:'media_not_detected',error:'Média non détecté sur cette page. Place le média à télécharger au centre de l’écran.'};
    }
    item ||= items.find(i=>i.downloadable) || items[0];
    const track_selection=item && Object.hasOwn(settings.trackSelections,item.id)
      ? settings.trackSelections[item.id] : settings.trackPreferences;
    if(item) {
      if(item.mediaKind==='audio'&&['720','1080','best'].includes(mode))mode='audio';
      return downloadItem({tabId,itemId:item.id,mode,track_selection,_trace:message._trace,
        preferred_source_id:settings.candidateId,shared:true,forceToken:message.forceToken});
    }
  }
  let resolved;
  downloadTrace(message,'resolve_url');
  try {resolved=await browser.tabs.sendMessage?.(tabId,{type:'kitty-resolve-media-url'});}catch(error){downloadTrace(message,'resolve_url',{error:error?.message||String(error)});}
  if(resolved?.error)return {ok:false,code:'media_not_detected',error:resolved.error};
  const url=httpUrl(resolved?.url)||httpUrl(tab.url);
  if(!url)return {ok:false,code:'media_not_detected',error:'URL HTTP/HTTPS requise.'};
  const catalogue=mode==='image'?[]:await hlsForTab(tabId);
  const selected=catalogue.find(c=>c.id===settings.candidateId);
  if(['720','1080','best'].includes(mode) && (selected?.type==='direct_audio' ||
      catalogue.length && catalogue.every(c=>c.type==='direct_audio'||c.hls?.audio_only)))mode='audio';
  let payload=await withHlsFallbacks({action:'download',url,mode,
    ...(selected?{preferred_source_id:selected.id}:{})},tabId);
  if(mode!=='image') {
    if(!payload.media_fallbacks?.some(c=>c.id===payload.preferred_source_id))delete payload.preferred_source_id;
    payload.track_selection=settings.trackPreferences;
    payload.track_policy='prefer_available';
  }
  return dispatchSharedDownload(payload,message);
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
    .catch(error => ({ compatible: false, code:'native_host_unavailable',
      error:diagnosticText(error?.message||String(error)), message:diagnosticText(error?.message||String(error)) }))
    .finally(() => { compatibilityPromise = null; });
  return compatibilityPromise;
}

async function nativeMessage(payload) {
  const action = String(payload?.action || "");
  if (!SAFE_NATIVE_ACTIONS.has(action)) {
    const comp = await ensureCompatibility();
    if (!comp?.compatible) {
      if(comp?.code==='native_host_unavailable')return {ok:false,...comp};
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
  if (statusPromise && statusPromiseGeneration === statusGeneration) return statusPromise;

  const generation=statusGeneration;
  statusPromiseGeneration=generation;
  const pending = nativeMessage({ action: "status" })
    .then(result => {
      for(const job of [result?.state?.active,...(result?.state?.queue||[]),...(result?.state?.history||[])].filter(Boolean)){
        const trace=downloadJobTraces.get(job.id);
        if(!trace)continue;
        const signature=JSON.stringify([job.status,job.metadata_status,Math.floor(KittyShared.jobPercent(job)||0),job.error,job.error_detail]);
        if(signature===trace.signature)continue;
        trace.signature=signature;
        downloadTrace(trace.message,'job_status',{jobId:job.id,status:job.status,metadataStatus:job.metadata_status,
          progress:KittyShared.jobPercent(job),code:job.error_code,error:job.error,error_hint:job.error_hint,error_detail:job.error_detail});
      }
      if(generation===statusGeneration){cachedStatus = result;cachedAt = Date.now();}
      return result;
    })
    .finally(() => {
      if(statusPromise===pending)statusPromise = null;
    });

  statusPromise=pending;
  return pending;
}

function invalidateStatus() {
  statusGeneration++;
  cachedStatus = null;
  cachedAt = 0;
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (!message || typeof message !== "object") return;

  if(message.type==='kitty-media-dom') {
    // Preserve the synchronous path for unchanged, already scoped snapshots.
    const update=current=>{
      const accepted=Boolean(current&&mediaItems?.update(current,message.items));
      if(accepted)notifyHls(current.tab.id);
      return {ok:accepted,...(!accepted?{error:'Snapshot média refusé : document ou onglet périmé.'}:{})};
    };
    if(!message.pageUrl||message.pageUrl===sender.url)return Promise.resolve(update(sender));
    return currentDocumentSender(message,sender).then(update,error=>({ok:false,error:diagnosticText(error.message)}));
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
      for(const itemId of new Set(message.itemIds))results.push({itemId,...await downloadItem({...message,itemId,shared:true,track_selection:message.trackSelections?.[itemId]})});
      return {ok:true,results,added:results.filter(r=>r.ok).length};
    })();
  }

  if (message.type === 'kitty-media-context' && Number.isInteger(sender?.tab?.id) && typeof message.hasBlob==='boolean') {
    return currentDocumentSender(message,sender).then(current=>{
      if(!current)return {ok:false,error:'Document média périmé.'};
      hlsStore?.context(current.tab.id,current.tab.url,message.hasBlob);
      notifyHls(current.tab.id);return {ok:true};
    },error=>({ok:false,error:diagnosticText(error.message)}));
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

  if(message.type==='kitty-download-settings') {
    if(!isKittyUi(sender))return Promise.resolve({ok:false,error:'Requête Kitty non autorisée.'});
    if(message.change)settingsRevision++;
    return serialDownloadOperation(()=>downloadSettings(message.tabId,message.change));
  }
  if(message.type==='kitty-add-download' || message.type==='kitty-pill-download') {
    return sharedStartDownload(message,sender);
  }
  if(message.type==='kitty-download-diagnostics') {
    return Promise.resolve(isKittyUi(sender)?{ok:true,events:downloadEvents.slice()}:{ok:false,error:'Requête Kitty non autorisée.'});
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
