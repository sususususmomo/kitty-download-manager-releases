/* Observed request context, private to the background; never a cookie-store scan. */
(() => {
  const names={'referer':'Referer','origin':'Origin','user-agent':'User-Agent','accept':'Accept','accept-language':'Accept-Language','authorization':'Authorization'};
  function headerName(name) {
    const lower=String(name).toLowerCase();
    return names[lower] || (/^x-[a-z0-9-]{1,60}$/.test(lower)&&!/^x-(?:forwarded|real-ip|proxy)/.test(lower) ? lower : null);
  }
  function snapshot(observed=[]) {
    const headers={};let cookies=null;
    for(const h of observed.slice(0,128)) {
      if(typeof h.value!=='string'||h.value.length>8192||/[\x00-\x1f\x7f]/.test(h.value))continue;
      if(String(h.name).toLowerCase()==='cookie'){cookies=/^[^=;\s]+=[^\r\n]*$/.test(h.value)?h.value:null;continue;}
      const name=headerName(h.name);if(name&&Object.keys(headers).length<32)headers[name]=h.value;
    }
    return {headers,...(cookies?{cookies}:{})};
  }
  function capture(url,observed=[]) {
    try {const u=new URL(url);if(!/^https?:$/.test(u.protocol)||u.username||u.password)return null;}catch{return null;}
    return {version:1,source_url:url,...snapshot(observed)};
  }
  const legacy=context=>Object.fromEntries(Object.entries(context?.headers||{}).filter(([name])=>['Referer','Origin','User-Agent'].includes(name)));
  const requiresBackend=context=>Boolean(context?.cookies||Object.keys(context?.headers||{}).some(n=>!['Referer','Origin','User-Agent'].includes(n)));
  globalThis.KittyRequestContext=Object.freeze({capture,snapshot,legacy,requiresBackend});
})();
