"""Direct-resource metadata, using yt-dlp's existing HTTP download pipeline."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import parse_qsl, unquote, urlsplit

VIDEO = frozenset(('mp4','webm','m4v','mov','mkv'))
AUDIO = frozenset(('mp3','m4a','ogg','opus','wav','flac','aac'))


def technical(url):
    path = urlsplit(url).path
    return bool(re.search(r'\.(?:ts|m4s|cmfv|cmfa)$',path,re.I)
                or re.search(r'(?:^|[/_.-])init(?:ialization)?(?:[-_.][\w.-]+)?\.(?:mp4|m4a|webm)$',path,re.I)
                or re.search(r'(?:^|/)(?:chunk|segment|seg|fragment|frag)[-_]?(?:stream\d+[-_])?\d+[._-]',path,re.I))


def media_type(url, mime):
    from hls import HLS_TYPES, DASH_TYPES
    if technical(url) or mime in HLS_TYPES | DASH_TYPES:
        return None
    if mime.startswith('video/') and mime != 'video/mp2t':
        return 'direct_video'
    if mime.startswith('audio/'):
        return 'direct_audio'
    if mime and mime not in ('application/octet-stream','binary/octet-stream'):
        return None
    ext = Path(urlsplit(url).path).suffix[1:].lower()
    return 'direct_video' if ext in VIDEO else 'direct_audio' if ext in AUDIO else None


def quality_key(url):
    from hls import VOLATILE_QUERY
    u = urlsplit(url)
    height = None
    query = []
    for name,value in parse_qsl(u.query,keep_blank_values=True):
        if name in ('height','resolution','quality') and re.fullmatch(r'[1-9]\d{2,3}p?',value):
            height = int(value.removesuffix('p'));value = '{quality}'
        if name.casefold() not in VOLATILE_QUERY:
            query.append((name,value))
    def replace(match):
        nonlocal height
        height = int(match[2]);return match[1]+'{quality}'
    path = re.sub(r'([_.-])([1-9]\d{2,3})p(?=[_.-]|$)',replace,u.path,count=1,flags=re.I)
    return (u.scheme,u.netloc,path,tuple(sorted(query))) if height else None


def source_identity(url,page,kind):
    from hls import identity
    group = quality_key(url)
    return kind+'_'+(hashlib.sha256(repr((page,group)).encode()).hexdigest() if group else identity(url,page))


def validate_metadata(raw):
    if raw is None:
        return {}
    fields = {'size','height','format','filename','content_range','request_range','status_code'}
    if not isinstance(raw,dict) or set(raw)-fields:
        raise ValueError('Métadonnées de média direct invalides.')
    clean = {}
    for name,value in raw.items():
        if name in ('size','height','status_code'):
            limit = 20000 if name=='height' else 599 if name=='status_code' else 10**15
            if isinstance(value,bool) or not isinstance(value,int) or not 0<value<=limit:
                raise ValueError('Métadonnées de média direct invalides.')
        elif not isinstance(value,str) or len(value)>(255 if name=='filename' else 120) or re.search(r'[\x00-\x1f\x7f]',value):
            raise ValueError('Métadonnées de média direct invalides.')
        if name=='format' and not re.fullmatch(r'[A-Za-z0-9-]{1,20}',value):
            raise ValueError('Format de média direct invalide.')
        clean[name] = value
    return clean


def protected_mp4(data):
    """Recognize protected sample entries in a bounded MP4 metadata prefix.

    This only reads box sizes/types; no keys or sample decryption. Late moov
    boxes beyond the prefix may remain unclassified by this optional check.
    """
    import struct
    containers={b'moov',b'trak',b'mdia',b'minf',b'stbl'}
    def walk(start,end,depth=0):
        if depth>8:return False
        while start+8<=end:
            size,kind=struct.unpack_from('>I4s',data,start);header=8
            if size==1:
                if start+16>end:return False
                size=struct.unpack_from('>Q',data,start+8)[0];header=16
            if size==0:size=end-start
            if size<header:return False
            if kind in (b'encv',b'enca',b'pssh'):return True
            limit=min(end,start+size)
            if kind in containers and walk(start+header,limit,depth+1):return True
            if kind==b'stsd' and start+header+8<=limit and walk(start+header+8,limit,depth+1):return True
            start+=size
        return False
    return walk(0,len(data))


def _probe(url,headers):
    """Optional, bounded remote ffprobe. Never log its URL, arguments or stderr."""
    from hls import HlsError
    from metadata_guard import FFPROBE_TIMEOUT
    from platform_support import run_hidden
    executable = shutil.which('ffprobe')
    if not executable:
        return {}
    command = [executable,'-v','error','-rw_timeout','8000000',
               '-protocol_whitelist','http,https,tcp,tls','-probesize','1048576','-analyzeduration','2000000']
    if urlsplit(url).scheme=='https':
        command += ['-tls_verify','1']
    if headers:
        command += ['-headers',''.join(name+': '+value+'\r\n' for name,value in headers.items())]
    command += ['-show_format','-show_streams','-of','json',url]
    try:
        result = run_hidden(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,timeout=FFPROBE_TIMEOUT)
        if any(marker in result.stderr.lower() for marker in (b'encrypted',b'encryption',b'widevine',b'playready')):
            raise HlsError('direct_drm','Média direct protégé / DRM')
        if result.returncode or len(result.stdout)>2*1024*1024:
            return {}
        data = json.loads(result.stdout)
    except (OSError,subprocess.TimeoutExpired,ValueError):
        return {} # Keep a usable raw source if optional details fail.
    streams = data.get('streams') or []
    if any(str(s.get('codec_tag_string','')).lower() in ('encv','enca') for s in streams):
        raise HlsError('direct_drm','Média direct protégé / DRM')
    video = next((s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')),None)
    audio = next((s for s in streams if s.get('codec_type')=='audio'),None)
    answer = {}
    audio_streams = [s for s in streams if s.get('codec_type') == 'audio']
    subtitle_streams = [s for s in streams if s.get('codec_type') == 'subtitle']
    def stream_metadata(stream, index):
        tags, disposition = stream.get('tags', {}), stream.get('disposition', {})
        try:
            bitrate = float(stream.get('bit_rate') or 0) / 1000 or None
        except (ValueError, TypeError):
            bitrate = None
        return dict(index=stream.get('index'), audioIndex=index, language=tags.get('language'),
                    label=tags.get('title'), codec=stream.get('codec_name'), bitrate=bitrate,
                    default=bool(disposition.get('default')), original=True if disposition.get('original') else None)
    if len(audio_streams) > 1:
        answer['_kitty_audio_streams'] = [stream_metadata(s, i) for i, s in enumerate(audio_streams)]
    if subtitle_streams:
        answer['_kitty_subtitle_streams'] = [stream_metadata(s, i) for i, s in enumerate(subtitle_streams)]
    if video:
        answer.update(vcodec=video.get('codec_name'),width=video.get('width'),height=video.get('height'))
    elif audio:
        answer['vcodec'] = 'none'
    if audio:
        answer['acodec'] = audio.get('codec_name')
        answer['language'] = audio.get('tags', {}).get('language')
        answer['audio_channels'] = audio.get('channels')
        try:
            answer['abr'] = float(audio.get('bit_rate') or 0) / 1000 or None
        except (ValueError, TypeError):
            pass
        answer['is_default'] = bool(audio.get('disposition', {}).get('default'))
    elif video:
        answer['acodec'] = 'none'
    for key,target,divisor in (('duration','duration',1),('bit_rate','tbr',1000)):
        try:
            value = float(data.get('format',{}).get(key))/divisor
            if 0<value<10**12:
                answer[target] = value
        except (ValueError,TypeError):
            pass
    return answer


def _one(ydl,source,check_control):
    from hls import HlsError, HLS_TYPES, DASH_TYPES
    from yt_dlp.networking import Request
    from yt_dlp.utils import determine_ext, mimetype2ext
    check_control()
    # Read at most 8 KiB and close. GET works on servers which reject HEAD.
    # No browser Range header is replayed: this must be a whole-file resource.
    with ydl.urlopen(Request(source['url'],headers=source['headers'])) as response:
        headers = response.headers
        sample = response.read(8192)
    mime = str(headers.get('Content-Type') or source['content_type']).split(';')[0].strip().lower()
    if mime in HLS_TYPES | DASH_TYPES or media_type(source['url'],mime) is None:
        raise HlsError('direct_unavailable','Média direct indisponible')
    stripped=sample.lstrip(b'\xef\xbb\xbf\r\n\t ')
    if stripped.startswith(b'#EXTM3U') or (stripped.startswith(b'<') and re.search(br'<(?:\w+:)?MPD(?:\s|>)',stripped)):
        raise HlsError('direct_unavailable','Média direct indisponible')
    if protected_mp4(sample):
        raise HlsError('direct_drm','Média direct protégé / DRM')
    content_range = re.fullmatch(r'bytes\s+(\d+)-(\d+)/(\d+|\*)',headers.get('Content-Range',''),re.I)
    if content_range and (int(content_range[1])!=0 or content_range[3]=='*' or int(content_range[2])+1!=int(content_range[3])):
        raise HlsError('direct_partial','La source fournit seulement un fragment média')
    check_control()
    try:
        info = ydl.extract_info(source['url'],download=False,force_generic_extractor=True)
    except Exception as exc:
        # A verified direct MIME can still be usable when generic extraction
        # lacks an extension. Access/DRM/network errors keep their normal error.
        from errors import classify_backend_error
        if classify_backend_error(exc)['code'] not in ('unsupported_url','extraction_failed','format_unavailable'):
            raise
        info = {}
    if not isinstance(info,dict) or info.get('has_drm'):
        raise HlsError('direct_drm' if isinstance(info,dict) and info.get('has_drm') else 'direct_unavailable','Média direct indisponible')
    if info.get('entries') is not None:
        raise HlsError('direct_unavailable','Média direct indisponible')
    formats = info.get('formats') or [info]
    if not any(item.get('protocol') in (None,'http','https') for item in formats):
        raise HlsError('direct_no_formats','Aucun format direct utilisable')
    from request_context import from_source
    # Remote ffprobe follows redirects outside yt-dlp's scoped transport. Never
    # pass credentials/custom tokens to that optional subprocess.
    details = {} if from_source(source).sensitive else _probe(source['url'],source['headers'])
    check_control()
    ext = mimetype2ext(mime) or determine_ext(source['url'],None)
    if ext not in VIDEO | AUDIO:
        ext = {'direct_video':'mp4','direct_audio':'m4a'}[source['type']]
    usable = []
    for item in formats:
        if item.get('has_drm'):
            raise HlsError('direct_drm','Média direct protégé / DRM')
        if item.get('protocol') not in (None,'http','https'):
            continue
        fmt = {key:item[key] for key in ('url','ext','width','height','vcodec','acodec','tbr','filesize','filesize_approx','format_id') if key in item}
        fmt.update(url=source['url'],protocol=urlsplit(source['url']).scheme,ext=ext,http_headers=source['headers'])
        fmt.update({key:value for key,value in details.items() if key!='duration'})
        if source['type']=='direct_audio':
            fmt['vcodec']='none'
        if 'height' not in fmt and source.get('metadata',{}).get('height'):
            fmt['height']=source['metadata']['height']
        try:
            length = int(headers.get('Content-Length'))
            if length>0:fmt['filesize']=length
        except (ValueError,TypeError):
            if source.get('metadata',{}).get('size'):fmt['filesize']=source['metadata']['size']
        usable.append(fmt)
    if not usable:
        raise HlsError('direct_no_formats','Aucun format direct utilisable')
    # Title remains owned by the page context; filenames are only a fallback.
    name = source.get('metadata',{}).get('filename')
    if not name:
        disposition=headers.get('Content-Disposition','')
        encoded=re.search(r"filename\*=UTF-8''([^;]+)",disposition,re.I)
        match = re.search(r'filename\s*=\s*"?([^";]+)',disposition,re.I)
        name = unquote(encoded[1]) if encoded else match[1] if match else unquote(urlsplit(source['url']).path.rsplit('/',1)[-1])
    title = source['title']
    if title in ('DIRECT_VIDEO stream','DIRECT_AUDIO stream'):
        title = re.split(r'[\\/]',name or '')[-1].rsplit('.',1)[0] or 'Media'
    return info,usable,details.get('duration'),title


def extract_direct(ydl,source,check_control=lambda:None):
    from hls import HlsError, apply_options, error_info
    formats=[];base={};title=source['title'];duration=None;errors=[];initialized=False
    variants=source.get('variants') or [source]
    for index,variant in enumerate(variants):
        try:
            from request_context import youtube_dl
            with youtube_dl(apply_options(dict(ydl.params),variant)) as direct_ydl:
                info,items,seconds,name=_one(direct_ydl,variant,check_control)
        except Exception as exc:
            if exc.__class__.__name__ in ('DownloadCancelled','DownloadPaused','ExternalWorkerStop'):
                raise
            error=error_info(exc,source['type'])
            if error['code']=='direct_drm':raise HlsError(error['code'],error['message']) from None
            errors.append(HlsError(error['code'],error['message']));continue
        if not initialized:
            base=info;duration=seconds;initialized=True
            if title in ('DIRECT_VIDEO stream','DIRECT_AUDIO stream'):title=name
        # A measured mismatch invalidates merging variants into one format list.
        if seconds and duration and abs(seconds-duration)>max(3,duration*.1):
            continue
        for item in items:
            item['format_id']='direct-'+str(index)+'-'+str(len(formats));formats.append(item)
    if not formats:
        raise errors[-1] if errors else HlsError('direct_no_formats','Aucun format direct utilisable')
    base.update(title=title,id=source['identity'][:24],webpage_url=source['page_url'],formats=formats)
    if duration:base['duration']=duration
    return base
