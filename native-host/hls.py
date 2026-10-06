"""Validated network sources; all media bytes remain owned by yt-dlp's downloader."""
from __future__ import annotations
import hashlib
import math
import re
import time
from urllib.parse import parse_qsl, urlsplit

HLS_TYPES = frozenset(('application/vnd.apple.mpegurl', 'application/x-mpegurl',
                       'application/mpegurl', 'audio/mpegurl', 'audio/x-mpegurl'))
VOLATILE_QUERY = frozenset(('token', 'access_token', 'auth', 'signature', 'sig', 'expires',
                            'expiry', 'exp', 'policy', 'key-pair-id', 'hdnea', 'hdnts',
                            'x-amz-signature', 'x-amz-date', 'x-amz-expires', 'x-amz-credential',
                            'x-amz-security-token'))
DASH_TYPES = frozenset(('application/dash+xml',))
MAX_MANIFEST = 2 * 1024 * 1024

class HlsError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def http_url(value):
    if not isinstance(value, str) or not value or len(value) > 16384 or re.search(r'[\x00-\x20\x7f]', value):
        raise ValueError('URL média invalide.')
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        parts.port
    except ValueError:
        raise ValueError('URL média invalide.') from None
    return value  # Do not reconstruct signed URLs.


def identity(url, page_url):
    parsed = urlsplit(url)
    stable = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
              if k.casefold() not in VOLATILE_QUERY]
    value = repr((page_url, parsed.scheme, parsed.netloc, parsed.path, sorted(stable)))
    return hashlib.sha256(value.encode()).hexdigest()


def validate_source(raw, _variants=True):
    if not isinstance(raw, dict) or raw.get('type') not in ('hls', 'dash', 'direct_video', 'direct_audio'):
        raise ValueError('Candidat média invalide.')
    kind = raw['type']
    label = kind.upper()
    url = http_url(raw.get('url'))
    page = http_url(raw.get('page_url'))
    parts = urlsplit(url)
    mime = str(raw.get('content_type') or '').split(';')[0].strip().lower()
    direct = kind.startswith('direct_')
    if len(mime)>100 or re.search(r'[\x00-\x1f\x7f]',mime):
        raise ValueError('Content-Type média invalide.')
    if direct:
        from direct_media import media_type, source_identity, validate_metadata, quality_key
        if media_type(url,mime)!=kind:
            raise ValueError('Aucun signal de média direct valide.')
    elif re.search(r'\.(?:ts|m4s|mp4|m4a|cmfv|cmfa)(?:$)', parts.path, re.I):
        raise ValueError('Un fragment ne peut pas être téléchargé comme manifest média.')
    if not direct and ('.mpd' if kind == 'dash' else '.m3u8') not in url.lower() and mime not in (DASH_TYPES if kind == 'dash' else HLS_TYPES):
        raise ValueError('Aucun signal de manifest média.')
    tab_id, timestamp = raw.get('tab_id'), raw.get('timestamp')
    if isinstance(tab_id, bool) or not isinstance(tab_id, int) or tab_id < 0:
        raise ValueError('Onglet source média invalide.')
    if isinstance(timestamp, bool) or not isinstance(timestamp, (float, int)) or not math.isfinite(timestamp) or timestamp < 0 or timestamp > time.time() + 60:
        raise ValueError('Date du candidat média invalide.')
    from request_context import RequestContext
    context = RequestContext.validate(raw.get('request_context'), url, raw.get('headers'))
    headers = context.legacy_headers()
    title = raw.get('title') or label + ' stream'
    if not isinstance(title, str) or len(title) > 1000:
        raise ValueError('Titre média invalide.')
    source = dict(type=kind, url=url, page_url=page, tab_id=tab_id, timestamp=timestamp,
                content_type=mime, headers=headers, request_context=context.wire(), title=title,
                hostname=parts.hostname, identity=source_identity(url,page,kind) if direct else identity(url, page) if kind == 'hls' else 'dash_' + identity(url, page))
    for name in ('id', 'media_item_id'):
        if name in raw:
            value = raw[name]
            if not isinstance(value, str) or not 1 <= len(value) <= 200 or re.search(r'[\x00-\x1f\x7f]', value):
                raise ValueError('Identité du candidat média invalide.')
            source[name] = value
    if kind == 'hls' and raw.get('manifest_kind') in ('master', 'video', 'audio', 'subtitles', 'unknown'):
        source['manifest_kind'] = raw['manifest_kind']
    if direct:
        source['metadata']=validate_metadata(raw.get('metadata'))
    if 'variants' in raw:
        values=raw['variants']
        if not _variants or not direct or not isinstance(values,list) or not 1<=len(values)<=4 or not quality_key(url):
            raise ValueError('Qualités de média direct invalides.')
        variants=[validate_source(item,False) for item in values]
        if any(v['type']!=kind or v['page_url']!=page or quality_key(v['url'])!=quality_key(url) for v in variants):
            raise ValueError('Les qualités ne correspondent pas au même média.')
        source['variants']=variants
    return source


def validate_fallbacks(raw, limit=3):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError('Liste de fallback média invalide.')
    return [validate_source(item) for item in raw]


class QuietHlsLogger:
    # yt-dlp may otherwise print complete signed URLs on stderr.
    def debug(self, *_args, **_kwargs): pass
    def warning(self, *_args, **_kwargs): pass
    def error(self, *_args, **_kwargs): pass


def apply_options(opts, source):
    from request_context import options
    options(opts, source)
    opts.update(logger=QuietHlsLogger(),
                allow_unplayable_formats=False, skip_unavailable_fragments=False,
                hls_prefer_native=True)
    return opts


def error_info(error, kind='hls'):
    from errors import classify_backend_error
    text = str(error).casefold()
    code = getattr(error, 'code', None)
    if not code:
        if any(s in text for s in ('drm', 'sample-aes', 'widevine', 'fairplay', 'playready')):
            code = 'drm_protected'
        elif 'expired' in text or 'http error 410' in text or '410 gone' in text:
            code = 'hls_expired'
        elif any(s in text for s in ('403', '401', 'forbidden', 'unauthorized')):
            code = 'hls_access_denied'
        elif any(s in text for s in ('no formats', 'no video formats', 'requested format', 'aucun format')):
            code = 'hls_no_formats'
        else:
            normal = classify_backend_error(error)
            if normal['code'] in ('disk_full', 'ffmpeg_missing', 'ffprobe_missing', 'permission_denied', 'no_audio', 'no_video', 'image_unavailable', 'postprocess_failed'):
                normal['detail'] = normal['message']
                return normal
            code = 'hls_unavailable'
    if kind == 'dash' and code.startswith('hls_'):
        code = 'dash_' + code[4:]
    if kind == 'dash' and code == 'drm_protected':
        code = 'dash_drm'
    if kind.startswith('direct_') and code.startswith('hls_'):
        code = 'direct_' + code[4:]
    if kind.startswith('direct_') and code == 'drm_protected':
        code = 'direct_drm'
    info = classify_backend_error('', code_hint=code)
    info['detail'] = info['message']  # No token, cookie, URL or raw server error.
    return info


def extract_manifest(ydl, raw_source, check_control=lambda: None):
    """Bounded manifest/DRM check, then the normal yt-dlp generic extractor."""
    from yt_dlp.networking import Request
    source = validate_source(raw_source)
    kind = source['type']
    check_control()
    try:
        with ydl.urlopen(Request(source['url'], headers=source['headers'])) as response:
            data = response.read(MAX_MANIFEST + 1)
    except Exception as exc:
        check_control()  # Preserve cancellation even while the manifest request is blocked.
        info = error_info(exc, kind)
        raise HlsError(info['code'], info['message']) from None
    check_control()
    if len(data) > MAX_MANIFEST:
        raise HlsError(kind+'_unavailable', 'Manifest trop volumineux')
    if kind == 'dash':
        import xml.etree.ElementTree as ET
        class SafeMpdTree(ET.TreeBuilder):
            def doctype(self, *_args):
                raise HlsError('dash_unavailable', 'Flux DASH indisponible')
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise HlsError('dash_unavailable', 'Flux DASH indisponible')
        try:
            root = ET.fromstring(data, parser=ET.XMLParser(target=SafeMpdTree()))
        except ET.ParseError:
            raise HlsError('dash_unavailable', 'Flux DASH indisponible') from None
        local = lambda tag: tag.rsplit('}', 1)[-1]
        if local(root.tag) != 'MPD':
            raise HlsError('dash_unavailable', 'Flux DASH indisponible')
        if any(local(node.tag) == 'ContentProtection' for node in root.iter()):
            raise HlsError('dash_drm', 'Flux DASH protégé / DRM')
        if not any(local(node.tag) == 'Representation' for node in root.iter()):
            raise HlsError('dash_no_formats', 'Aucun format DASH utilisable')
    else:
        if len(data) > MAX_MANIFEST or not data.lstrip(b'\xef\xbb\xbf\r\n\t ').startswith(b'#EXTM3U'):
            raise HlsError('hls_unavailable', 'Flux HLS indisponible')
        manifest = data.decode('utf-8-sig', errors='replace')
        for line in manifest.splitlines():
            if not line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')):
                continue
            method = re.search(r'(?:[:,])METHOD=([^,]+)', line)
            key_format = re.search(r'(?:[:,])KEYFORMAT="([^"]+)"', line)
            if (method and method.group(1) not in ('NONE', 'AES-128')) or (key_format and key_format.group(1) != 'identity'):
                raise HlsError('drm_protected', 'Contenu protégé par DRM')
        if not any(tag in manifest for tag in ('#EXTINF:', '#EXT-X-STREAM-INF:', '#EXT-X-MEDIA:')):
            raise HlsError('hls_no_formats', 'Aucun format HLS utilisable')
    info = ydl.extract_info(source['url'], download=False, force_generic_extractor=True)
    if not isinstance(info, dict):
        raise HlsError(kind+'_no_formats', 'Aucun format '+kind.upper()+' utilisable')
    formats = info.get('formats') or []
    usable = [f for f in formats if isinstance(f, dict) and not f.get('has_drm') and (str(f.get('protocol', '')).startswith('m3u8') if kind == 'hls' else f.get('protocol') in ('http_dash_segments', 'dash'))]
    if info.get('has_drm') or (formats and not usable and any(f.get('has_drm') for f in formats if isinstance(f, dict))):
        raise HlsError('dash_drm' if kind == 'dash' else 'drm_protected', 'Flux DASH protégé / DRM' if kind == 'dash' else 'Contenu protégé par DRM')
    if not usable:
        raise HlsError(kind+'_no_formats', 'Aucun format '+kind.upper()+' utilisable')
    info.update(title=source['title'], id=source['identity'][:16], formats=usable,
                webpage_url=source['page_url'])
    from media_tracks import annotate_manifest
    annotate_manifest(info, data, source['url'], kind)
    return info


def extract_job(ydl, job, check_control=lambda: None, on_fallback=lambda source: None):
    source = job.get('media_source')
    if source:
        return extract_source(ydl, source, check_control), source
    check_control()
    try:
        return ydl.extract_info(job['url'], download=False), None
    except Exception as original:
        from errors import classify_backend_error
        # Auth/DRM/geo/access errors never trigger an automatic alternate path.
        blocked = any(marker in str(original).casefold() for marker in ('drm', 'widevine', 'fairplay', 'playready'))
        eligible = not blocked and classify_backend_error(original)['code'] in ('unsupported_url', 'extraction_failed', 'no_video', 'format_unavailable')
        if not eligible or not (job.get('media_fallbacks') or job.get('hls_fallbacks')):
            raise
        original_error=original
    last_error = None
    for source in (job.get('media_fallbacks') or job.get('hls_fallbacks')):
        if (source['type']=='direct_audio' and job.get('mode') in ('720','1080','best')) or (source['type'].startswith('direct_') and job.get('mode')=='image'):
            continue
        check_control()
        on_fallback(source)
        try:
            from request_context import youtube_dl
            with youtube_dl(apply_options(dict(ydl.params), source)) as fallback_ydl:
                return extract_source(fallback_ydl, source, check_control), source
        except Exception as exc:
            if isinstance(exc, HlsError) and exc.code in ('drm_protected', 'dash_drm', 'direct_drm'):
                raise
            # Do not swallow cancellation / process stop exceptions.
            if not isinstance(exc, (HlsError,)) and exc.__class__.__name__ in ('DownloadCancelled', 'DownloadPaused', 'ExternalWorkerStop'):
                raise
            last_error = exc
    raise last_error or original_error


def network_resource_ids(info,page):
    """Hashes only: remember an exact observed resource without storing its URL."""
    urls=[f.get('url') for f in (info.get('formats') or []) if isinstance(f,dict)]
    if info.get('url'):urls.append(info['url'])
    result=[]
    for url in urls[:64]:
        try:
            value=identity(http_url(url),http_url(page))
            if value not in result:result.append(value)
        except ValueError:pass
    return result


def extract_source(ydl,raw,check_control=lambda:None):
    source=validate_source(raw)
    if source['type'].startswith('direct_'):
        from direct_media import extract_direct
        return extract_direct(ydl,source,check_control)
    return extract_manifest(ydl,source,check_control)

# Backward-compatible name for the first HLS integration.
extract_hls = extract_manifest
