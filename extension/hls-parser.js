/* Bounded HLS catalogue metadata, not a segment downloader. */
(() => {
  const MAX_TEXT = 2 * 1024 * 1024, MAX_RENDITIONS = 128;
  function attributes(line) {
    const result = {};
    // Commas inside quoted CODECS/NAME values belong to the value.
    for (const match of line.matchAll(/(?:^|,)\s*([A-Z0-9-]+)=("[^"]*"|[^,]*)/g))
      result[match[1]] = match[2].replace(/^"|"$/g, '').trim().slice(0,4096);
    return result;
  }
  function uri(value, base) {
    if (!value || value.includes('{$')) return null; // Unresolved EXT-X-DEFINE.
    try {
      const u = new URL(value, base);
      return /^https?:$/.test(u.protocol) && !u.username && !u.password
        && u.href.length<=16384 && !/[\x00-\x20\x7f]/.test(u.href) ? u.href : null;
    } catch { return null; }
  }
  const number = value => Number.isFinite(Number(value)) && Number(value)>0 ? Number(value) : undefined;
  function rendition(a, url) {
    const resolution = /^(\d+)x(\d+)$/i.exec(a.RESOLUTION || '');
    return {url, ...(resolution ? {width:Number(resolution[1]),height:Number(resolution[2])} : {}),
      bandwidth:number(a.BANDWIDTH), averageBandwidth:number(a['AVERAGE-BANDWIDTH']), frameRate:number(a['FRAME-RATE']),
      codecs:a.CODECS, audio:a.AUDIO, subtitles:a.SUBTITLES,
      groupId:a['GROUP-ID'], name:a.NAME, language:a.LANGUAGE,
      default:a.DEFAULT==='YES', autoselect:a.AUTOSELECT==='YES'};
  }
  function parse(text, url) {
    if (typeof text!=='string' || text.length>MAX_TEXT || !/^\uFEFF?\s*#EXTM3U(?:\s|$)/.test(text)) return null;
    const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/).map(s=>s.trim());
    const variants=[], audioTracks=[], subtitles=[], segments=[];
    let pending=null, master=false, isMedia=false, protectedStream=false, videoOnly=false;
    for (const line of lines) {
      if (line.startsWith('#EXT-X-STREAM-INF:')) {master=true;pending=attributes(line.slice(18));}
      else if (line.startsWith('#EXT-X-MEDIA:')) {
        master=true;
        const a=attributes(line.slice(13)), resolved=uri(a.URI,url);
        const target=a.TYPE==='AUDIO' ? audioTracks : a.TYPE==='SUBTITLES' ? subtitles : null;
        if (target && target.length<MAX_RENDITIONS) target.push(rendition(a,resolved));
      } else if (/^#EXTINF:|^#EXT-X-MAP:/.test(line)) isMedia=true;
      else if(line==='#EXT-X-I-FRAMES-ONLY')videoOnly=true;
      else if (/^#EXT-X-(?:SESSION-)?KEY:/.test(line)) {
        const a=attributes(line.slice(line.indexOf(':')+1));
        if (/^SAMPLE-AES/.test(a.METHOD || '') || (a.KEYFORMAT && a.KEYFORMAT!=='identity')) protectedStream=true;
      } else if (line && !line.startsWith('#')) {
        if (pending) {const resolved=uri(line,url);if(resolved && variants.length<MAX_RENDITIONS)variants.push(rendition(pending,resolved));pending=null;}
        else if(segments.length<16)segments.push(line);
      }
    }
    // Audio elementary segments are positive evidence. TS and fMP4 may contain
    // video, audio or both: their extension alone cannot establish video-only.
    const audioOnly=isMedia && segments.length>0 && segments.every(s=>/\.(?:aac|mp3|ac3|ec3)(?:[?#]|$)/i.test(s));
    const textOnly=isMedia && segments.length>0 && segments.every(s=>/\.(?:vtt|webvtt|ttml)(?:[?#]|$)/i.test(s));
    const codecs=[...new Set(variants.flatMap(v=>(v.codecs || '').split(',')).map(s=>s.trim()).filter(Boolean))];
    const heights=variants.map(v=>v.height || 0);
    return {kind:master ? 'master' : videoOnly ? 'video' : audioOnly ? 'audio' : textOnly ? 'subtitles' : 'unknown',
      isMedia, audioOnly, videoOnly, protected:protectedStream, variants, audioTracks, subtitles,
      maxResolution:Math.max(0,...heights), codecs};
  }
  globalThis.KittyHlsParser=Object.freeze({parse,attributes,MAX_TEXT});
})();
