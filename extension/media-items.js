/* Logical media above the unchanged network catalogue. Never merge by CDN alone. */
(() => {
  const http=value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password ? value : null;}catch{return null;}};
  const clean=value=>String(value||'').replace(/\s+/g,' ').trim().slice(0,1000);
  const key=value=>globalThis.KittyMedia.key(value);
  const urls=c=>[c.url,...(c.variants||[]).map(v=>v.url),...(c.hls?.variants||[]).map(v=>v.url),...(c.hls?.audioTracks||[]).map(v=>v.url),
    ...(c.type==='ytdlp'?(c.formats||[]).filter(v=>v.vcodec!=='none').map(v=>v.url):[])].filter(http);
  const identityUrls=c=>[c.url,...(c.variants||[]).map(v=>v.url),...(c.hls?.variants||[]).map(v=>v.url),
    ...(c.type==='ytdlp'?(c.formats||[]).filter(v=>v.vcodec!=='none').map(v=>v.url):[])].filter(http);
  const hash=value=>{let a=2166136261,b=5381;for(const c of value){a=Math.imul(a^c.charCodeAt(0),16777619);b=Math.imul(b,33)^c.charCodeAt(0);}return (a>>>0).toString(36)+(b>>>0).toString(36);};
  const sourceType=c=>c.type?.startsWith('direct_')?'direct':c.type;
  function wikimediaFile(value) {
    if(!http(value))return null;
    const u=new URL(value);let repository,name,match;
    if(['upload.wikimedia.org','thumb.wikimedia.org'].includes(u.hostname)) {
      match=u.pathname.match(/^\/wikipedia\/([^/]+)\/(?:thumb\/|transcoded\/)?[a-f0-9]\/([a-f0-9]{2})\/([^/]+)/i);
      if(match){repository=match[1];name=match[3];}
    } else if(u.hostname==='commons.wikimedia.org'||/^[\w-]+\.wikipedia\.org$/.test(u.hostname)) {
      match=u.pathname.match(/^\/wiki\/(?:File|Image):(.+)$/i);
      if(match){repository=u.hostname==='commons.wikimedia.org'?'commons':u.hostname.split('.')[0];name=match[1];}
    }
    if(!name)return null;
    try{name=decodeURIComponent(name).replace(/ /g,'_').normalize('NFC');}catch{return null;}
    return JSON.stringify([repository,name]);
  }
  const fileKeys=dom=>{
    const resource=wikimediaFile(dom.resourceUrl),name=resource?JSON.parse(resource)[1]:null;
    return [...new Set([dom.thumbnail,...dom.sources.map(s=>s.url),dom.resourceUrl].map(wikimediaFile)
      .filter(k=>k&&(!name||JSON.parse(k)[1]===name)))];
  };
  function fileExtractionUrl(dom) {
    const keys=fileKeys(dom).map(k=>JSON.parse(k));
    const resource=wikimediaFile(dom.resourceUrl);
    const name=resource?JSON.parse(resource)[1]:null;
    // Wikipedia's resource link can point to its duplicate-player File page.
    // A Commons poster/source identifies the actual repository for THIS file.
    const commons=keys.find(([repo,file])=>repo==='commons'&&(!name||file===name));
    return commons?'https://commons.wikimedia.org/wiki/File:'+encodeURIComponent(commons[1]):dom.resourceUrl&&resource?dom.resourceUrl:null;
  }
  function filename(value) {try{return decodeURIComponent(new URL(value).pathname.split('/').pop()).replace(/\.[^.]+$/,'').slice(0,1000);}catch{return '';}}
  const overlap=(a,b)=>a.some(v=>b.includes(v));
  const sourceKeys=d=>d.sources.map(s=>key(s.url));
  const families=values=>values.map(u=>globalThis.KittyMedia.qualityKey(u)?.key).filter(Boolean);
  const positive=n=>Number.isFinite(n)&&n>0?n:null;
  const closeDuration=(a,b)=>Math.abs(a-b)<=Math.max(.5,Math.min(a,b)*.02);
  const normalizedTitle=t=>clean(t).normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  const meaningfulTitle=t=>t.length>=6&&!/^(?:video|audio|media|média|hls|dash|direct)(?: stream)?$/.test(t);
  function providerPage(value) {
    if(!http(value))return null;
    const u=new URL(value),host=u.hostname.toLowerCase();
    if(host==='youtu.be'||host==='youtube.com'||host.endsWith('.youtube.com'))
      return globalThis.KittyMediaResolver?._canonicalizers.youtube(value)||null;
    if((host==='soundcloud.com'||host==='www.soundcloud.com')&&/^\/[^/]+\/[^/]+\/?$/.test(u.pathname)
      &&!/^\/(?:discover|search|charts|you|settings|stations)\//.test(u.pathname)
      &&!/^\/[^/]+\/(?:sets|tracks|albums|reposts|likes|popular-tracks|followers|following)\/?$/.test(u.pathname))return value;
    return null;
  }
  const strongIdentity=d=>d.embedUrl || fileExtractionUrl(d) || d.resourceUrl || null;
  const domCue=d=>({strong:strongIdentity(d),files:fileKeys(d),keys:sourceKeys(d),families:families(d.sources.map(s=>s.url)),title:normalizedTitle(d.title)});
  const candidateKey=c=>c.type+':'+(http(c.url)?key(c.url):String(c.id||''));
  function scope(c,tabId,page,context) {
    if(c.entries!=null||['playlist','multi_video'].includes(c._type))return 'candidate_is_collection';
    if(c.tab_id!==undefined&&c.tab_id!==tabId)return 'wrong_tab';
    if(c.page_url&&c.page_url!==page)return 'wrong_page';
    if(c.frame_id!==context.frameId&&!(c.frame_ids||[]).includes(context.frameId))return 'wrong_frame';
    if(c.document_url&&c.document_url!==context.frameUrl)return 'wrong_document';
    return null;
  }
  function domProof(a,b,context,relationships,cue=domCue) {
    if(a.mediaKind!==b.mediaKind)return {reason:'media_kind_conflict'};
    const ac=cue(a),bc=cue(b),sa=ac.strong,sb=bc.strong;
    if(sa&&sb&&sa!==sb)return {reason:'strong_identity_conflict'};
    if(a.embedUrl&&a.embedUrl===b.embedUrl)return {score:100,reason:'embed_identity'};
    if(sa&&sa===sb)return {score:100,reason:'resource_identity'};
    if(overlap(ac.files,bc.files))return {score:100,reason:'wikimedia_file'};
    const aa=ac.keys,bb=bc.keys;
    if(overlap(aa,bb)) {
      if(aa.some(u=>!bb.includes(u))&&bb.some(u=>!aa.includes(u)))return {reason:'mixed_source_sets'};
      return {score:100,reason:'shared_source'};
    }
    if(overlap(ac.families,bc.families))return {score:95,reason:'quality_family'};
    const links=relationships.get?.(context.frameId);
    if(links&&aa.some(u=>bb.some(v=>overlap(links.get(u)||[],links.get(v)||[]))))return {score:95,reason:'declared_source_relationship'};
    // Container, equal title/duration/resolution and timing alone cannot prove
    // that two real players show the same video (e.g. two cuts in one figure).
    return {reason:a.containerId&&a.containerId===b.containerId?'container_without_identity':'no_identity_proof'};
  }
  class Store {
    constructor({log=(event,data)=>console.debug('[Kitty MediaItem]',event,data)}={}){this.tabs=new Map();this.metadata=new Map();this.log=log;}
    clear(tabId){this.tabs.delete(tabId);for(const id of this.metadata.keys())if(id.startsWith(`item:${tabId}:`))this.metadata.delete(id);}
    enrich(id,data){const previous=this.metadata.get(id)||{};
      const next={...previous,title:clean(data.title)||previous.title,thumbnail:http(data.thumbnail)||previous.thumbnail,duration:data.duration||previous.duration};
      for(const kind of ['videoTracks','audioTracks','subtitleTracks'])if(Array.isArray(data[kind]))next[kind]=data[kind];
      this.metadata.set(id,next);}
    update(sender,items) {
      const tabId=sender?.tab?.id,page=sender?.tab?.url,frameUrl=sender?.url,frameId=sender?.frameId||0;
      if(!Number.isInteger(tabId)||tabId<0||!http(page)||!http(frameUrl)||!Array.isArray(items))return false;
      if(frameId===0&&frameUrl!==page)return false;
      let tab=this.tabs.get(tabId);
      if(!tab||tab.page!==page){tab={page,frames:new Map(),nodes:new Map(),identities:new Map(),decisions:new Map()};this.tabs.set(tabId,tab);}
      const safe=items.slice(0,100).filter(i=>i&&typeof i.domId==='string'&&i.domId.length<100).map(i=>({
        domId:i.domId,title:clean(i.title),titleSource:clean(i.titleSource),thumbnail:http(i.thumbnail),
        mediaKind:i.mediaKind==='audio'?'audio':'video',duration:Number.isFinite(i.duration)&&i.duration>0?i.duration:null,
        height:Number.isFinite(i.height)?i.height:null,width:Number.isFinite(i.width)?i.width:null,
        embedUrl:http(i.embedUrl),resourceUrl:http(i.resourceUrl),blob:Boolean(i.blob),timestamp:Date.now()/1000,
        containerId:typeof i.containerId==='string'&&i.containerId.length<100?i.containerId:null,
        sources:(Array.isArray(i.sources)?i.sources:[]).slice(0,12).filter(s=>http(s?.url)).map(s=>({url:s.url,contentType:clean(s.contentType).slice(0,100)}))}));
      // Keep declarations when Wikimedia replaces an original node by its
      // source-less placeholder. A changed per-file URL never inherits them.
      const previous=tab.frames.get(frameId);
      for(const dom of safe) {
        const old=previous?.items.find(i=>i.domId===dom.domId || strongIdentity(dom)&&strongIdentity(i)===strongIdentity(dom));
        if(old&&dom.blob===old.blob&&dom.duration===old.duration&&dom.height===old.height&&(!strongIdentity(dom)||strongIdentity(dom)===strongIdentity(old))
          &&(!old.sources.length||!dom.sources.length||domProof(old,dom,{frameId,frameUrl},[]).score))dom.timestamp=old.timestamp;
      }
      for(const dom of safe)if(!dom.sources.length&&dom.resourceUrl) {
        const old=previous?.items.find(i=>i.resourceUrl===dom.resourceUrl);
        if(old){dom.sources=old.sources;dom.duration ||= old.duration;dom.height ||= old.height;dom.width ||= old.width;}
      }
      tab.frames.set(frameId,{frameUrl,items:safe});return true;
    }
    list(tabId,page,catalogue=[]) {
      const tab=this.tabs.get(tabId);if(!tab||tab.page!==page)return [];
      const logical=[],decisions=new Map(),relationships=new Map(),domCues=new WeakMap(),candidateCues=new WeakMap(),anchors=new Map();
      const cue=d=>{if(!domCues.has(d))domCues.set(d,domCue(d));return domCues.get(d);};
      const candidateCue=c=>{
        if(!candidateCues.has(c)){const resource=identityUrls(c);candidateCues.set(c,{resource,keys:resource.map(key),files:resource.map(wikimediaFile).filter(Boolean),families:families(resource),
          title:normalizedTitle(c.metadata?.title||(c.type==='ytdlp'||c.titleSource==='metadata'?c.title:''))});}
        return candidateCues.get(c);
      };
      // Index explicit aliases once; don't rescan the entire catalogue for
      // every pair of DOM players in a large gallery.
      for(const [frameId,frame] of tab.frames) {
        const links=new Map();relationships.set(frameId,links);
        for(const c of catalogue)if(!scope(c,tabId,page,{frameId,frameUrl:frame.frameUrl}))
          for(const url of candidateCue(c).keys){const groups=links.get(url)||[];groups.push(candidateKey(c));links.set(url,groups);}
      }
      const decide=(kind,subject,target,action,reason,signals=[])=>{
        // Only opaque IDs and reasons: never titles, URLs, tokens or headers.
        const id=kind+':'+subject+':'+target;
        decisions.set(id,{kind,subject,target,action,reason,signals});
      };
      for(const [frameId,frame] of tab.frames)for(const dom of frame.items) {
        const context={frameId,frameUrl:frame.frameUrl,dom},strong=cue(dom).strong;
        const identity=strong || [...cue(dom).keys].sort().join('|');
        let item=null;
        for(const other of logical) {
          let proof={reason:'wrong_frame'};
          for(const old of other.contexts) {
            if(old.frameId!==frameId||old.frameUrl!==frame.frameUrl) {
              if(dom.embedUrl&&old.dom.embedUrl===dom.embedUrl&&dom.mediaKind===old.dom.mediaKind)proof={score:100,reason:'embed_identity'};
              continue;
            }
            const match=domProof(old.dom,dom,context,relationships,cue);
            if(!proof.score||match.score>proof.score)proof=match;
          }
          decide('dom',hash(frameId+':'+dom.domId),other.id,proof.score?'merge':'reject',proof.reason);
          if(proof.score){item=other;break;}
        }
        const node=frameId+':'+dom.domId,previous=tab.nodes.get(node);
        const storageKey=dom.mediaKind+':'+(dom.embedUrl?'embed:':frameId+':')+identity;
        const consistent=previous&&(!strong||!previous.strong||previous.strong===strong)
          &&(!previous.dom.sources.length||!dom.sources.length||domProof(previous.dom,dom,context,relationships,cue).score);
        const id=item?.id || (consistent&&previous.id) || (identity&&tab.identities.get(storageKey)) || `item:${tabId}:${hash(page+':'+node+':'+(strong||identity))}`;
        tab.nodes.set(node,{id,strong,dom});if(identity)tab.identities.set(storageKey,id);
        if(item){item.contexts.push(context);if(!item.title&&dom.title){item.title=dom.title;item.titleSource=dom.titleSource;}if(!item.thumbnail)item.thumbnail=dom.thumbnail;continue;}
        item={id,identity,title:dom.title,thumbnail:dom.thumbnail,titleSource:dom.titleSource,
          tabId,frameId,pageUrl:page,mediaKind:dom.mediaKind,duration:dom.duration,embedUrl:dom.embedUrl,
          contexts:[context],candidates:[]};logical.push(item);
      }
      const proofFor=(item,c)=>{
        let best={score:0,reason:'wrong_frame',signals:[]},matchedContext=false;
        for(const context of item.contexts) {
          const invalid=scope(c,tabId,page,context);
          if(invalid){if(!matchedContext&&!best.score)best={score:0,reason:invalid,signals:[]};continue;}
          matchedContext=true;
          const d=context.dom,data=candidateCue(c),resource=data.resource,related=data.keys;
          const attached=anchors.get(item.id)?.get(context.frameId)||[];
          let proof={score:0,reason:'no_identity_proof',signals:[]};
          const knownFiles=cue(d).files,candidateFiles=data.files;
          if(knownFiles.length&&candidateFiles.length&&!overlap(knownFiles,candidateFiles))proof.reason='different_wikimedia_file';
          else if(d.embedUrl&&c.type==='ytdlp'&&key(c.url)===key(d.embedUrl))proof={score:100,reason:'embed_identity',signals:['embed']};
          else if(d.resourceUrl&&c.type==='ytdlp'&&related.includes(key(cue(d).strong)))proof={score:100,reason:'resource_identity',signals:['resource']};
          else if(overlap(cue(d).keys,related))proof={score:100,reason:'linked_url',signals:['declared_url']};
          else if(overlap(attached,related))proof={score:95,reason:'linked_candidate_url',signals:['declared_relationship']};
          else if(overlap(knownFiles,candidateFiles))proof={score:100,reason:'wikimedia_file',signals:['repository','original_filename']};
          else if(overlap(cue(d).families,data.families))proof={score:95,reason:'quality_family',signals:['quality_url_family']};
          else {
            const duration=positive(c.metadata?.duration)||positive(c.duration),domDuration=positive(d.duration)||positive(this.metadata.get(item.id)?.duration);
            const near=Number.isFinite(c.timestamp)&&Math.abs(c.timestamp-d.timestamp)<=30&&Math.abs(Date.now()/1000-c.timestamp)<=30;
            const height=positive(c.metadata?.height)||positive(c.hls?.maxResolution)||positive(c.maxHeight);
            const resolution=Boolean(d.height&&height===d.height);
            const title=data.title;
            const ownTitle=cue(d).title||normalizedTitle(this.metadata.get(item.id)?.title);
            const titleMatch=meaningfulTitle(title)&&title===ownTitle;
            const container=Boolean(d.containerId&&c.container_id===d.containerId);
            const durationMatch=Boolean(duration&&domDuration&&closeDuration(duration,domDuration));
            const signals=[durationMatch&&'duration',resolution&&'resolution',titleMatch&&'title',near&&'time',container&&'container'].filter(Boolean);
            if(duration&&domDuration&&!durationMatch)proof={score:0,reason:'duration_conflict',signals};
            else if(durationMatch&&(titleMatch&&(resolution||near||container)||resolution&&near))proof={score:70+(titleMatch?20:0)+(container?5:0),reason:'metadata_agreement',signals};
            else if(d.blob&&!d.sources.length&&['hls','dash'].includes(c.type)&&!['audio','subtitles'].includes(c.hls?.kind)&&near) {
              const peers=logical.filter(i=>i.contexts.some(v=>v.frameId===context.frameId));
              const manifests=catalogue.filter(v=>['hls','dash'].includes(v.type)&&!['audio','subtitles'].includes(v.hls?.kind)&&!scope(v,tabId,page,context)
                && Number.isFinite(v.timestamp)&&Math.abs(v.timestamp-d.timestamp)<=30&&Math.abs(Date.now()/1000-v.timestamp)<=30);
              const unique=manifests.every(v=>overlap(candidateCue(v).keys,related));
              proof=peers.length===1&&unique?{score:65,reason:'unique_blob_manifest',signals:['single_player','single_manifest_group','time']}:
                {score:0,reason:'ambiguous_blob_sources',signals};
            }else proof={score:0,reason:'insufficient_evidence',signals};
          }
          if(proof.score>best.score||!best.score)best=proof;
        }
        return best;
      };
      const append=(item,c)=>{
        const frames=anchors.get(item.id)||new Map();anchors.set(item.id,frames);
        for(const context of item.contexts)if(!scope(c,tabId,page,context))frames.set(context.frameId,[...new Set([...(frames.get(context.frameId)||[]),...candidateCue(c).keys])]);
        const fingerprint=candidateKey(c),old=item.candidates.findIndex(v=>candidateKey(v)===fingerprint);
        if(old<0){item.candidates.push({...c,sourceType:sourceType(c)});return true;}
        const previous=item.candidates[old];
        if((c.timestamp||0)>(previous.timestamp||0)||urls(c).length>urls(previous).length)item.candidates[old]={...c,sourceType:sourceType(c)};
        decide('candidate',hash(fingerprint),item.id,'merge','duplicate_candidate');return false;
      };
      // Relations may be discovered after their child response. Repeat only
      // while new anchors become available; never infer aliases from a CDN.
      let pending=[...catalogue];
      for(let pass=0;pending.length&&pass<=catalogue.length;pass++) {
        const remaining=[];let progress=false;
        for(const c of pending) {
          const diagnosticId=hash(candidateKey(c));
          const ranked=logical.map(item=>({item,proof:proofFor(item,c)})).sort((a,b)=>b.proof.score-a.proof.score);
          const first=ranked[0],ambiguous=first?.proof.score>=60&&ranked[1]&&first.proof.score-ranked[1].proof.score<15;
          if(!first)decide('candidate',diagnosticId,'none','reject','no_dom_item');
          const accepted=first?.proof.score>=60&&!ambiguous;
          for(const r of ranked)decide('candidate',diagnosticId,r.item.id,accepted&&r===first?'merge':'reject',
            accepted&&r!==first&&r.proof.score>=60?'owned_by_other_item':ambiguous&&r.proof.score>=60?'ambiguous_match':r.proof.reason,r.proof.signals);
          if(accepted)progress=append(first.item,c)||progress;else remaining.push(c);
        }
        pending=remaining;if(!progress)break;
      }
      for(const item of logical) {
        for(const context of item.contexts)for(const s of context.dom.sources) {
          const type=globalThis.KittyMedia.mediaType(s.url,s.contentType);
          if(!type||item.candidates.some(c=>urls(c).some(u=>key(u)===key(s.url))))continue;
          item.candidates.push({id:'dom:'+hash(key(s.url)),type,sourceType:type.startsWith('direct_')?'direct':type,url:s.url,
            page_url:page,tab_id:tabId,frame_id:context.frameId,document_url:context.frameUrl,timestamp:context.dom.timestamp,
            content_type:s.contentType,headers:{Referer:context.frameUrl},hostname:new URL(s.url).hostname,metadata:{...(globalThis.KittyMedia.qualityKey(s.url)?.height ? {height:globalThis.KittyMedia.qualityKey(s.url).height} : {})},title:item.title||filename(s.url)});
        }
        if(item.embedUrl&&!item.candidates.some(c=>c.type==='ytdlp'))item.candidates.unshift({id:'embed:'+hash(item.embedUrl),type:'ytdlp',sourceType:'ytdlp',url:item.embedUrl});
        // The URL of a known single-media page belongs to its sole main-frame
        // player. Its extractor knows titles and formats that raw CDN URLs lack.
        // Generic pages and galleries keep each item's own direct/File URL.
        const provider=item.embedUrl || (logical.length===1&&item.contexts.some(c=>c.frameId===0)?providerPage(page):null);
        item.preferExtractor=Boolean(provider);
        const resolved=this.metadata.get(item.id);
        if(resolved?.title&&(!item.title||item.preferExtractor)){item.title=resolved.title;item.titleSource="metadata";}
        if(!item.thumbnail)item.thumbnail=resolved?.thumbnail||null;
        if(!item.duration)item.duration=resolved?.duration||null;
        const metadata=item.candidates.find(c=>c.metadata?.title);
        if(!item.title){item.title=clean(metadata?.metadata?.title)||filename(item.candidates.find(c=>c.url)?.url)||'Média';item.titleSource=metadata?'metadata':'filename';}
        if(!item.thumbnail)item.thumbnail=http(metadata?.metadata?.thumbnail);
        item.candidates=item.candidates.map(c=>({...c,title:item.title,maxHeight:c.metadata?.height||c.hls?.maxResolution||null,
          hasVideo:c.type==='direct_audio'?false:c.type==='direct_video'?true:null,hasAudio:c.type==='direct_audio'?true:null,
          container:c.metadata?.format||null,confidence:c.id?.startsWith('dom:')?0.7:1}));
        const scopedResource=item.contexts.map(c=>fileExtractionUrl(c.dom)).find(Boolean);
        const native=item.candidates.find(c=>c.type!=='ytdlp'&&!c.hlsProtected&&c.url);
        item.extractionUrl=provider || native?.url || scopedResource || (logical.length===1?page:null);
        // yt-dlp participates for the item's own URL, never the whole gallery.
        if(item.extractionUrl&&!item.candidates.some(c=>c.sourceType==='ytdlp'))item.candidates.unshift({id:'extractor:'+hash(item.extractionUrl),type:'ytdlp',sourceType:'ytdlp',url:item.extractionUrl,title:item.title});
        item.downloadable=Boolean(item.extractionUrl);
        for(const kind of ['videoTracks','audioTracks','subtitleTracks'])item[kind]=(resolved?.[kind]||[]).filter(t=>t.sourceId==='item-extractor'||item.candidates.some(c=>c.id===t.sourceId));
        item.selectable=true;
        item.explicitSources=item.contexts.some(({dom})=>dom.sources.some(s=>globalThis.KittyMedia.mediaType(s.url,s.contentType))
          || fileKeys(dom).some(k=>item.candidates.some(c=>c.type!=='ytdlp'&&urls(c).some(u=>wikimediaFile(u)===k))));
      }
      for(const [id,decision] of decisions) {
        const signature=JSON.stringify(decision);
        if(tab.decisions.get(id)!==signature)this.log(decision.action,{tabId,...decision});
        decisions.set(id,signature);
      }
      tab.decisions=decisions;
      return logical;
    }
  }
  globalThis.KittyMediaItems=Object.freeze({Store,sourceType});
})();
