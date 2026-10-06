/* Small source selector; the existing Kitty quality/menu and queue remain shared. */
(() => {
  let activeTab = null, activePage = null, candidates = [], automatic = false, refreshGeneration = 0, probeGeneration = 0, translate = value => value, onSelect = () => {};
  const panel = () => document.getElementById('hlsPanel');
  const select = () => document.getElementById('hlsSource');
  const detail = () => document.getElementById('hlsDetail');
  function text(value) { detail().textContent = translate(value); }
  function label(c) {
    if(c?.type==='hls') {
      const h=c.hls;
      return 'HLS'+(h?.protected ? ' · '+translate('protégé / DRM') : '')
        +(h?.audio_only ? ' · '+translate('Audio uniquement') : h?.kind==='subtitles' ? ' · '+translate('Sous-titres')
          : h?.video_only ? ' · '+translate('Vidéo uniquement') : '')
        +(h?.max_height ? ' · '+h.max_height+'p'+(h.kind==='master' ? ' max' : '') : '')
        +(h?.quality_count>1 ? ' · '+h.quality_count+' '+translate('qualités') : '');
    }
    return c?.type?.startsWith('direct_')
    ? (c.metadata?.format ? c.metadata.format+' '+translate('direct') : translate(KittyShared.mediaLabel(c)))
    : (c?.type || 'hls').toUpperCase()+' stream';
  }
  function bytes(size) {
    if (!Number.isFinite(size) || size<=0) return '';
    return ' • '+(size<1048576 ? Math.ceil(size/1024)+' '+translate('Kio')
      : (size/1048576).toFixed(size<10485760?1:0)+' '+translate('Mo'));
  }
  function idle(result) { text(result?.blob_unavailable ? 'Lecteur blob : aucune ressource HTTP exploitable observée. Relance la lecture.' : automatic ? 'Sources détectées comparées automatiquement' : 'Flux réseau détecté · fallback disponible'); }
  async function refresh() {
    const turn = ++refreshGeneration;
    try {
      const [tab] = await browser.tabs.query({active:true,currentWindow:true});
      const result = tab ? await browser.runtime.sendMessage({type:'kitty-media-list',tabId:tab.id}) : null;
      if (turn !== refreshGeneration) return;
      const saved=await browser.runtime.sendMessage({type:'kitty-download-settings',tabId:tab.id});
      if(turn!==refreshGeneration)return;
      const previous = activeTab === tab?.id && activePage === tab?.url ? select().value : saved?.candidateId || ''; 
      activeTab = tab?.id ?? null;activePage=tab?.url||null;
      candidates = result?.ok ? result.candidates : [];
      automatic = Boolean(result?.automatic_available);
      select().replaceChildren();
      const page = document.createElement('option');page.value='';page.textContent=translate(result?.automatic_available ? 'Automatique · meilleure source' : 'Page active · yt-dlp en priorité');select().append(page);
      candidates.forEach((c,i) => {const o=document.createElement('option');o.value=c.id;
        o.textContent=label(c)+((c.type.startsWith('direct_') || c.type==='hls') && c.hostname ? ' • '+c.hostname : candidates.length>1 ? ' '+(i+1) : '')
          +(c.format_count>1 && c.type.startsWith('direct_') ? ' • '+c.format_count+' '+translate('qualités') : '');select().append(o);});
      select().value = candidates.some(c=>c.id===previous) ? previous : '';
      panel().hidden = !candidates.length && !result?.blob_unavailable;
      await globalThis.KittyItemsPopup?.refresh(tab?.id);
      if(previous && !select().value){++probeGeneration;onSelect(null);}
      if (!select().value) idle(result);
    } catch { if(turn===refreshGeneration){candidates=[];panel().hidden=true;} }
  }
  async function probe() {
    const candidateId=select().value, tabId=activeTab;
    const turn=++probeGeneration;
    if(!candidateId){onSelect(null);idle();return;}
    const candidate=candidates.find(c=>c.id===candidateId);
    onSelect(candidate);
    if(candidate?.hls?.protected){text('Flux HLS protégé / DRM');return;}
    text(candidate?.type.startsWith('direct_') ? 'Analyse du média…' : 'Analyse du manifest…');
    try {
      const r=await browser.runtime.sendMessage({type:'kitty-probe-media',candidateId,tabId});
      if(turn!==probeGeneration||activeTab!==tabId||select().value!==candidateId)return;
      detail().textContent=r?.ok ? (r.type?.startsWith('direct_') ? label({...candidate,metadata:{...candidate.metadata,format:r.format}}) : candidate?.hls?.kind==='master' ? 'HLS' : label(candidate))
        +(r.heights?.length ? ' • '+r.heights.slice(0,6).map(h=>h+'p').join(' / ') : '')
        +(r.separate_av ? ' • '+translate('vidéo + audio') : '')
        +(candidate?.hls?.subtitles ? ' • '+translate('Sous-titres') : '')+bytes(r.size)
        : translate(r?.error || 'Flux réseau indisponible');
    } catch {if(turn===probeGeneration&&activeTab===tabId)text('Flux réseau indisponible');}
  }
  function start(options={}) {
    translate=options.translate || translate;
    onSelect=options.onSelect || onSelect;
    if(!panel())return;
    select().addEventListener('change',()=>{
      browser.runtime.sendMessage({type:'kitty-download-settings',tabId:activeTab,change:{candidateId:select().value||null}}).catch(()=>{});
      probe();
    });
    browser.runtime.onMessage.addListener(m=>{if(m?.type==='kitty-hls-changed' && (activeTab===null || m.tabId===activeTab))refresh();});
    browser.tabs.onActivated?.addListener(refresh);
    browser.tabs.onUpdated?.addListener((id,c)=>{if(id===activeTab&&c.url)refresh();});
    refresh();
  }
  globalThis.KittyMediaPopup=Object.freeze({start,
    hasCandidates:tabId=>activeTab===tabId&&candidates.length>0,
    selection:tabId=>activeTab===tabId ? select()?.value || null : null});
  globalThis.KittyHlsPopup=globalThis.KittyMediaPopup;
})();
