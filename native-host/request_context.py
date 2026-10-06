"""One validated, origin-scoped context for every observed network candidate.

Only headers seen on that candidate are replayed. Credentials stay out of global
yt-dlp headers, diagnostics and subprocess arguments. Redirects are rechecked.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from urllib.parse import urlsplit
from urllib.request import BaseHandler

LEGACY = {'referer': 'Referer', 'origin': 'Origin', 'user-agent': 'User-Agent'}
NAMES = dict(LEGACY, accept='Accept', **{'accept-language':'Accept-Language', 'authorization':'Authorization'})


def header_name(value):
    lower = str(value).lower()
    return NAMES.get(lower) or (lower if re.fullmatch(r'x-[a-z0-9-]{1,60}', lower)
                               and not re.match(r'x-(?:forwarded|real-ip|proxy)', lower) else None)


def origin(url):
    try:
        p = urlsplit(url)
        return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)
    except (TypeError, ValueError):
        raise ValueError('Origine du contexte invalide.') from None


@dataclass(frozen=True)
class RequestContext:
    source_url: str = field(repr=False)
    headers: dict = field(repr=False)
    cookies: str | None = field(default=None, repr=False)

    @classmethod
    def validate(cls, raw, url, legacy=None):
        from hls import http_url
        if raw is not None and legacy is not None:
            cls.validate(None,url,legacy)
        if raw is None:
            supplied = legacy or {}
            if not isinstance(supplied, dict) or len(supplied)>3 or any(str(n).lower() not in LEGACY for n in supplied):
                raise ValueError('Headers média invalides.')
            raw = {'version':1, 'source_url':url, 'headers':supplied}
        if not isinstance(raw,dict) or set(raw)-{'version','source_url','headers','cookies'} or type(raw.get('version')) is not int or raw['version']!=1:
            raise ValueError('RequestContext invalide.')
        if http_url(raw.get('source_url'))!=url:
            raise ValueError('RequestContext lié à une autre source.')
        supplied=raw.get('headers',{})
        if not isinstance(supplied,dict) or len(supplied)>32:
            raise ValueError('Headers du contexte invalides.')
        headers={}
        for key,value in supplied.items():
            name=header_name(key)
            if not name or not isinstance(value,str) or len(value)>8192 or re.search(r'[\x00-\x1f\x7f]',value):
                raise ValueError('Header du contexte non autorisé ou invalide.')
            if name in ('Referer','Origin') and not (name=='Origin' and value=='null'):
                http_url(value)
            if name in headers:
                raise ValueError('Header du contexte dupliqué.')
            headers[name]=value
        cookies=raw.get('cookies')
        if cookies is not None and (not isinstance(cookies,str) or len(cookies)>8192 or re.search(r'[\x00-\x1f\x7f]',cookies)):
            raise ValueError('Session du contexte invalide.')
        return cls(url,headers,cookies or None)

    def wire(self):
        return {'version':1,'source_url':self.source_url,'headers':dict(self.headers),
                **({'cookies':self.cookies} if self.cookies else {})}

    def legacy_headers(self):
        return {n:v for n,v in self.headers.items() if n.lower() in LEGACY}

    def for_url(self,url):
        if origin(url)!=origin(self.source_url):
            return {}
        return dict(self.headers, **({'Cookie':self.cookies} if self.cookies else {}))

    def summary(self):
        return {'version':1,'header_names':sorted(self.headers),'has_session':bool(self.cookies)}

    @property
    def sensitive(self):
        return bool(self.cookies or any(n.lower() not in LEGACY for n in self.headers))


def from_source(source):
    return RequestContext.validate(source.get('request_context'),source['url'],source.get('headers'))


def options(opts,source):
    context=from_source(source)
    opts.update(kitty_request_context=context.wire(),http_headers=context.legacy_headers(),
                debug_printtraffic=False,verbose=False)
    opts['kitty_variant_contexts']=[from_source(v).wire() for v in source.get('variants',[])]
    return opts


def youtube_dl(opts):
    """Keep yt-dlp's extraction/downloaders; scope its existing urllib transport."""
    import yt_dlp
    raw=opts.get('kitty_request_context')
    refresh=opts.get('kitty_source_refresh')
    if not raw and not refresh:
        return yt_dlp.YoutubeDL(opts)
    context=RequestContext.validate(raw,raw.get('source_url')) if raw else None
    contexts=([context] if context else [])+[RequestContext.validate(c,c.get('source_url')) for c in opts.get('kitty_variant_contexts',[])]
    controlled_names={n.lower() for c in contexts for n in c.headers}|{'cookie','authorization'}
    from yt_dlp.networking._urllib import UrllibRH

    class ContextCookieSanitizer(BaseHandler):
        handler_order=400  # Remove stale format snapshots before CookieProcessor.
        def http_request(self,req):
            if contexts:
                for bag in (req.headers,req.unredirected_hdrs):
                    for name in list(bag):
                        if name.lower()=='cookie':
                            del bag[name]
            return req
        https_request=http_request

    class ContextProcessor(BaseHandler):
        handler_order=900  # After CookieProcessor, including redirect requests.
        def http_request(self,req):
            if not contexts:
                return req
            # Remove inherited values first, then restore only for this origin.
            controlled=controlled_names
            existing_cookie=req.get_header('Cookie')
            current=next((c for c in contexts if c.source_url==req.full_url),None)
            if current is None:
                same_origin = [c for c in contexts if origin(c.source_url)==origin(req.full_url)]
                # Alternate tracks can use distinct sessions on one CDN. The
                # selected rendition directory is a stronger route than the
                # master origin; direct files still match their exact URL.
                def specificity(c):
                    directory = urlsplit(c.source_url).path.rsplit('/', 1)[0] + '/'
                    return len(directory) if urlsplit(req.full_url).path.startswith(directory) else 0
                current = max(same_origin, key=specificity, default=context)
            for bag in (req.headers,req.unredirected_hdrs):
                for name in list(bag):
                    if name.lower() in controlled:
                        del bag[name]
            values=current.for_url(req.full_url)
            if values and existing_cookie and current is context:
                values['Cookie']=existing_cookie
            for name,value in values.items():
                req.add_unredirected_header(name,value)
            return req
        https_request=http_request

    class ContextRH(UrllibRH):
        def _create_instance(self,*args,**kwargs):
            opener=super()._create_instance(*args,**kwargs)
            opener.add_handler(ContextCookieSanitizer())
            opener.add_handler(ContextProcessor())
            return opener

    class ContextYoutubeDL(yt_dlp.YoutubeDL):
        def build_request_director(self,handlers,preferences=None):
            # One policy for initial requests, redirects, playlists and fragments.
            return super().build_request_director([ContextRH] if raw else handlers,preferences=[] if raw else preferences)

        def urlopen(self,req):
            if not refresh:
                return super().urlopen(req)
            def update(source):
                nonlocal context,contexts
                if source:
                    context=from_source(source)
                    contexts=[context]+[from_source(v) for v in source.get('variants',[])]
                    controlled_names.update(n.lower() for c in contexts for n in c.headers)
                    # Replace this origin's old session without clearing other
                    # extractor/authentication domains in the shared jar.
                    host=urlsplit(context.source_url).hostname
                    for cookie in list(self.cookiejar):
                        domain=cookie.domain.lstrip('.')
                        if domain==host or domain==host+'.local' or host.endswith('.'+domain):
                            self.cookiejar.clear(cookie.domain,cookie.path,cookie.name)
            return refresh.open(req,super().urlopen,update)

    ydl=ContextYoutubeDL(opts)
    from http.cookies import SimpleCookie
    from http.cookiejar import Cookie
    for c in contexts[:1]:
        if not c.cookies:
            continue
        parsed=SimpleCookie()
        try:
            parsed.load(c.cookies)
        except Exception:
            raise ValueError('Session du contexte invalide.') from None
        for morsel in parsed.values():
            host=urlsplit(c.source_url).hostname
            domain=host if '.' in host else host+'.local'
            ydl.cookiejar.set_cookie(Cookie(0,morsel.key,morsel.value,None,False,domain,
                False,False,'/',True,urlsplit(c.source_url).scheme=='https',None,True,None,None,{},False))
    return ydl


def public_state(value):
    """Do not send private RequestContext/session to popup/status/diagnostics."""
    if isinstance(value,list):
        return [public_state(v) for v in value]
    if isinstance(value,dict):
        return {k:public_state(v) for k,v in value.items() if k not in ('request_context','kitty_request_context','kitty_variant_contexts')}
    return value
