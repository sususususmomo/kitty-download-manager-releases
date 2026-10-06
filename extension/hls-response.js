/* Tee only manifest responses already loaded by Firefox. Every byte is passed
 * through immediately; errors, limits and timeout disconnect the observer. */
(() => {
  class Reader {
    constructor(api, {timeout=10000,maxBytes=2*1024*1024,maxActive=16}={}) {
      this.api=api;this.timeout=timeout;this.maxBytes=maxBytes;this.maxActive=maxActive;this.active=new Map();
      this.stats={opened:0,completed:0,failed:0,denied:0,timedOut:0,oversize:0,invalidRequest:0};
    }
    read(d) {
      if (!this.api?.filterResponseData || d.method!=='GET' || d.tabId<0
        || d.statusCode<200 || d.statusCode>=300 || this.active.has(d.requestId) || this.active.size>=this.maxActive) return null;
      let filter;
      try {filter=this.api.filterResponseData(d.requestId);} catch {this.stats.denied++;return null;}
      this.stats.opened++;
      return new Promise(resolve=>{
        let size=0,text='',done=false;
        const decoder=new TextDecoder('utf-8');
        const finish=(success=false)=>{
          if(done)return;done=true;clearTimeout(timer);this.active.delete(d.requestId);
          this.stats[success ? 'completed' : 'failed']++;
          try {success ? filter.close() : filter.disconnect();} catch {try{filter.disconnect();}catch{}}
          resolve(success ? text+decoder.decode() : null);text='';
        };
        const timer=setTimeout(()=>{this.stats.timedOut++;finish();},this.timeout);
        this.active.set(d.requestId,{tabId:d.tabId,finish});
        filter.ondata=e=>{
          if(done)return;
          // Never hold the player's data while parsing or waiting for Kitty.
          try {filter.write(e.data);size+=e.data.byteLength;
            if(size>this.maxBytes){this.stats.oversize++;finish();return;}
            text+=decoder.decode(e.data,{stream:true});
          } catch {finish();}
        };
        filter.onstop=()=>finish(true);
        filter.onerror=()=>{if(filter.error==='Invalid request ID')this.stats.invalidRequest++;finish();};
      });
    }
    clear(tabId) {for(const r of [...this.active.values()])if(r.tabId===tabId)r.finish();}
    error(id) {this.active.get(id)?.finish();}
  }
  globalThis.KittyHlsResponse=Object.freeze({Reader});
})();
