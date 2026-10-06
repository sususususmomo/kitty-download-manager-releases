"""Refresh transport URLs, never restart a job or its native downloader.

The original fragment iterator and yt-dlp's .ytdl ledger remain authoritative.
New manifests provide addresses only after a strict VOD identity comparison.
Unknown identity stops with a resolution request and leaves partial data intact.
"""
from copy import deepcopy
import hashlib
import io
import json
import re
import threading
from urllib.parse import urljoin

from hls import HlsError, MAX_MANIFEST, identity
from queue_store import atomic_json


def resource(url):
    return identity(url, '')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def reject():
    raise HlsError('source_identity_unconfirmed',
                   'Identité de la source non confirmée. Fichier partiel conservé ; nouvelle résolution nécessaire.')


def hls_snapshot(text, base):
    """Canonical validation only; extraction and transfers still belong to yt-dlp."""
    from yt_dlp.utils import parse_m3u8_attributes
    if '#EXT-X-ENDLIST' not in text or '#EXT-X-STREAM-INF' in text:
        reject()  # Never remap a sliding window, master or a live stream by index.
    rows, urls = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')):
            if parse_m3u8_attributes(line.split(':', 1)[1]).get('METHOD') != 'NONE':
                reject()  # A rotated key cannot be inferred from its filename.
        if not line.startswith('#'):
            url = urljoin(base, line)
            urls.append(url)
            rows.append(resource(url))
        elif 'URI="' in line:
            def replace(match):
                url = urljoin(base, match[1])
                urls.append(url)
                return 'URI="' + resource(url) + '"'
            rows.append(re.sub(r'URI="([^"]+)"', replace, line))
        else:
            rows.append(line)
    if not urls:
        reject()
    return digest(rows), urls


def dash_snapshot(data, base):
    import xml.etree.ElementTree as ET
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        reject()
    root = ET.fromstring(data)
    local = lambda node: node.tag.rsplit('}', 1)[-1]
    if root.get('type', 'static') != 'static' or any(local(n) == 'ContentProtection' for n in root.iter()):
        reject()
    def canonical(node, parent):
        # Include periods, representations, codec, timescale, start number,
        # SegmentTimeline, byte ranges, initialization and every template.
        base_node = next((n for n in node if local(n) == 'BaseURL'), None)
        here = urljoin(parent, (base_node.text or '').strip()) if base_node is not None else parent
        attrs = {k: resource(urljoin(here, v)) if k in ('media', 'initialization', 'sourceURL') else v
                 for k, v in node.attrib.items()}
        text = (node.text or '').strip()
        if local(node) == 'BaseURL':
            text = resource(urljoin(parent, text))
        return [node.tag, attrs, text, [canonical(n, here if n is not base_node else parent) for n in node]]
    return digest(canonical(root, base))


def formats(info):
    if info.get('entries') is not None:
        return [f for entry in info['entries'] or [] if isinstance(entry, dict) for f in formats(entry)]
    return info.get('formats') or [info]


def fragment_urls(fmt):
    fragments = fmt.get('fragments')
    if not isinstance(fragments, list):
        reject()
    return [urljoin(fmt.get('fragment_base_url') or fmt.get('url', ''), f.get('url') or f.get('path', ''))
            for f in fragments]


def segment_queries(urls, fmt, info):
    from urllib.parse import parse_qs
    from yt_dlp.utils import update_url_query
    query = fmt.get('extra_param_to_segment_url') or info.get('extra_param_to_segment_url')
    return [update_url_query(u, parse_qs(query)) for u in urls] if query else urls


def refreshed_metadata(source, info, options, job, check=lambda: None,
                       browser_source=lambda *_: None):
    """Use the existing resolver, then bind only the original resource URLs."""
    from hls import apply_options, validate_source
    from metadata_guard import extract_metadata
    from request_context import RequestContext, header_name
    fresh_source = browser_source(source) if source else None
    page_info = None
    if not fresh_source:
        page = (source or {}).get('page_url') or job.get('source_page_url') or job['url']
        probe = dict(options, format=None, skip_download=True, writethumbnail=False,
                     postprocessors=[], progress_hooks=[], retries=0, extractor_retries=0)
        probe.pop('kitty_source_refresh', None)
        try:
            page_info, _ = extract_metadata(probe, dict(job, url=page, media_source=None,
                media_fallbacks=[], hls_fallbacks=[]), check, timeout=15)
        except Exception:
            check()
            reject()
        if source:
            matches = [f for f in formats(page_info)
                       if f.get('url') and resource(f.get('manifest_url') or f['url']) == resource(source['url'])]
            if not matches:
                reject()
            url = matches[0].get('manifest_url') or matches[0]['url']
            old_context = RequestContext.validate(source.get('request_context'), source['url'], source.get('headers'))
            headers = dict(old_context.headers)
            if old_context.for_url(url):
                headers.update({header_name(k): v for k, v in matches[0].get('http_headers', {}).items() if header_name(k)})
            raw = dict(source, url=url, request_context=RequestContext(url, headers, old_context.cookies).wire())
            raw.pop('variants', None)
            fresh_source = validate_source(raw)
        elif page_info.get('id') != info.get('id'):
            reject()
    if not source:
        return page_info, None
    if source['type'] in ('hls', 'dash'):
        probe = dict(options, format=None, skip_download=True, writethumbnail=False,
                     postprocessors=[], progress_hooks=[], retries=0, extractor_retries=0)
        probe.pop('kitty_source_refresh', None)
        return extract_metadata(apply_options(probe, fresh_source),
                                dict(job, media_source=fresh_source), check, timeout=15)
    # Direct metadata/probing must not re-download the already acquired prefix.
    fresh = deepcopy(info)
    variants = [fresh_source] + fresh_source.get('variants', [])
    for fmt in formats(fresh):
        matches = [v for v in variants if resource(v['url']) == resource(fmt.get('url', ''))]
        if not matches:
            continue
        fmt['url'] = matches[0]['url']
        fmt['http_headers'] = matches[0]['headers']
    return fresh, fresh_source


class SourceRefresh:
    def __init__(self, info, source, resolve, publish=lambda *_: None,
                 check=lambda: None, log=lambda *_: None, checkpoint=None):
        self.info, self.source = deepcopy(info), deepcopy(source)
        self.resolve, self.publish, self.check, self.log = resolve, publish, check, log
        self.checkpoint = checkpoint
        self.ledger = {'direct': {}, 'hls': {}, 'dash': {}, 'segments': {}}
        if checkpoint and checkpoint.is_file():
            try:
                self.ledger = json.loads(checkpoint.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                reject()
        self.mapping, self.playlists = {}, {}
        self.addresses, self.segment_keys = {}, set()
        self.format_headers = {}
        self.resumed_direct = set(self.ledger['direct'])
        self.resumed_hls = set(self.ledger['hls'])
        self.resumed_segments = set(self.ledger.get('segments', {}))
        self.refreshed_direct = set()
        self.generations = 0
        self.lock = threading.RLock()
        self.dash_checked = False
        self._register_dash(self.info)
        for fmt in formats(self.info):
            text = fmt.get('hls_media_playlist_data')
            if not text or not fmt.get('url'):
                continue
            key = resource(fmt['url'])
            try:
                stamp, urls = hls_snapshot(text, fmt['url'])
            except HlsError:
                stamp, urls = None, []
            previous = self.ledger['hls'].get(key)
            if (previous and previous != stamp) or (key in self.resumed_hls and not stamp):
                reject()
            self.playlists[key] = (text, fmt['url'])
            self.ledger['hls'][key] = stamp
            self.segment_keys.update(resource(u) for u in urls)
        self.save()

    def save(self):
        if self.checkpoint:
            atomic_json(self.checkpoint, self.ledger)

    def _register_dash(self, info):
        for fmt in formats(info):
            if fmt.get('protocol') != 'http_dash_segments':
                continue
            key = str(fmt.get('format_id'))
            urls = fragment_urls(fmt)
            self.segment_keys.update(resource(u) for u in urls)
            stamp = digest([[(resource(u), f.get('duration')) for u, f in zip(urls, fmt['fragments'])],
                            fmt.get('vcodec'), fmt.get('acodec'), fmt.get('width'), fmt.get('height')])
            previous = self.ledger['dash'].get(key)
            if previous and previous != stamp:
                reject()
            self.ledger['dash'][key] = stamp
        self.save()

    def _ensure_dash(self, info, send):
        from yt_dlp.networking import Request
        checked = set()
        for fmt in formats(info):
            if fmt.get('protocol') != 'http_dash_segments':
                continue
            url = fmt.get('manifest_url')
            if not url:
                reject()
            key = resource(url)
            if key in checked:
                continue
            checked.add(key)
            with send(Request(url, headers=fmt.get('http_headers', {}))) as response:
                data = response.read(MAX_MANIFEST + 1)
                if len(data) > MAX_MANIFEST:
                    reject()
                stamp = dash_snapshot(data, response.url)
            previous = self.ledger.setdefault('dash_manifests', {}).get(key)
            if previous and previous != stamp:
                self.log('source refresh reject: DASH manifest/timeline changed')
                reject()
            self.ledger['dash_manifests'][key] = stamp
        self.save()

    def direct(self, url):
        return next((f for f in formats(self.info) if f.get('protocol', 'https') in ('http', 'https')
                     and f.get('url') and resource(f['url']) == resource(url)), None)

    def is_segment(self, url):
        return resource(url) in self.segment_keys

    def _verify_segments(self, addresses, send, keys=None):
        from yt_dlp.networking import Request
        for key in keys if keys is not None else self.ledger.get('segments', {}):
            previous = self.ledger['segments'][key]
            if not previous[0] or key not in addresses:
                self.log('source refresh reject: segment byte identity unavailable')
                reject()
            with send(Request(addresses[key], method='HEAD')) as probe:
                if self.validator(probe) != previous:
                    self.log('source refresh reject: segment validator changed')
                    reject()

    @staticmethod
    def validator(response):
        etag = response.headers.get('ETag', '')
        total = response.headers.get('Content-Length', '')
        match = re.fullmatch(r'bytes \d+-\d+/(\d+)', response.headers.get('Content-Range', ''))
        if match:
            total = match[1]
        # Weak validators and dates alone cannot prove byte identity.
        return [etag if etag.startswith('"') and etag.endswith('"') else '',
                int(total) if str(total).isdigit() else None]

    def _record(self, request, response, send):
        from yt_dlp.networking import Response
        if self.is_segment(request.url):
            key = resource(request.url)
            current = self.validator(response)
            previous = self.ledger.setdefault('segments', {}).get(key)
            if previous and previous != current:
                response.close()
                reject()
            self.ledger['segments'][key] = current
            self.save()
        if self.direct(request.url):
            key = resource(request.url)
            current = self.validator(response)
            previous = self.ledger['direct'].get(key)
            range_header = request.headers.get('Range', '')
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header)
            if match and int(match[1]) > 0 and (key in self.resumed_direct or key in self.refreshed_direct):
                returned = re.match(r'bytes (\d+)-\d+/', response.headers.get('Content-Range', ''))
                if (not previous or not previous[0] or previous != current or response.status != 206
                        or not returned or int(returned[1]) != int(match[1])):
                    response.close()
                    self.log('source refresh reject: direct identity/range unconfirmed')
                    reject()
            elif previous and previous != current:
                response.close()
                reject()
            self.ledger['direct'][key] = current
            self.save()
        if any(str(f.get('protocol', '')).startswith('m3u8') and f.get('url')
               and resource(f['url']) == resource(request.url) for f in formats(self.info)):
            # Preserve the exact playlist that created the downloader's iterator.
            data = response.read(MAX_MANIFEST + 1)
            if len(data) > MAX_MANIFEST:
                response.close()
                reject()
            text = data.decode('utf-8', 'replace')
            key = resource(request.url)
            try:
                stamp, urls = hls_snapshot(text, response.url)
                self.segment_keys.update(resource(u) for u in urls)
            except HlsError:
                stamp = None  # Ordinary live/encrypted download unchanged; no safe refresh.
            previous = self.ledger['hls'].get(key)
            if (previous and previous != stamp) or (key in self.resumed_hls and not stamp):
                response.close()
                reject()
            self.ledger['hls'][key] = stamp
            self.playlists[key] = (text, response.url)
            self.save()
            if self.resumed_segments and stamp:
                addresses = {resource(u): u for u in urls}
                relevant = self.resumed_segments & set(addresses)
                self._verify_segments(addresses, send, relevant)
                self.resumed_segments -= relevant
            replacement = Response(io.BytesIO(data), response.url, response.headers, response.status)
            response.close()
            return replacement
        return response

    def _refresh(self, send, set_context):
        self.check()
        if self.generations >= 3:
            reject()
        self.generations += 1
        self.log('source refresh requested: candidate/context only; native progress retained')
        try:
            fresh, source = self.resolve(self.source, self.info)
        except (ValueError, HlsError):
            self.check()
            reject()
        if not isinstance(fresh, dict):
            reject()
        old_formats, new_formats = formats(self.info), formats(fresh)
        updates = {}
        # No best-source selection here: pin exactly the original representation.
        for old in old_formats:
            url = old.get('url')
            if not url:
                continue
            matches = [f for f in new_formats if f.get('url') and resource(f['url']) == resource(url)
                       and f.get('protocol', 'https') == old.get('protocol', 'https')
                       and (old.get('protocol') != 'http_dash_segments' or f.get('format_id') == old.get('format_id'))]
            if len(matches) != 1:
                continue
            new = matches[0]
            if any(old.get(k) is not None and new.get(k) is not None and old[k] != new[k]
                   for k in ('height', 'width', 'vcodec', 'acodec', 'duration')):
                reject()
            updates[url] = new['url']
            self.format_headers[url] = deepcopy(new.get('http_headers', {}))
        if not updates:
            reject()
        if source and self.source:
            if (source['type'] != self.source['type'] or resource(source['url']) != resource(self.source['url'])
                    or any(source.get(k) != self.source.get(k) for k in ('page_url', 'tab_id', 'media_item_id'))):
                reject()
        set_context(source)
        from yt_dlp.networking import Request
        for key, (text, base) in self.playlists.items():
            old_fmt = next(f for f in old_formats if f.get('url') and resource(f['url']) == key)
            fresh_url = updates.get(old_fmt['url'])
            if not fresh_url:
                reject()
            new_fmt = next(f for f in new_formats if f.get('url') == fresh_url)
            if new_fmt.get('hls_media_playlist_data'):
                new_stamp, new_urls = hls_snapshot(new_fmt['hls_media_playlist_data'], fresh_url)
            else:
                with send(Request(fresh_url, headers=(source or {}).get('headers', {}))) as response:
                    data = response.read(MAX_MANIFEST + 1)
                    if len(data) > MAX_MANIFEST:
                        reject()
                    new_stamp, new_urls = hls_snapshot(data.decode('utf-8', 'replace'), response.url)
            old_stamp, old_urls = hls_snapshot(text, base)
            if new_stamp != old_stamp or len(new_urls) != len(old_urls):
                self.log('source refresh reject: HLS timeline/resource changed')
                reject()
            updates.update(zip(old_urls, new_urls))
            updates.update(zip(segment_queries(old_urls, old_fmt, self.info), segment_queries(new_urls, new_fmt, fresh)))
        self._ensure_dash(fresh, send)
        self._register_dash(fresh)
        for old in old_formats:
            if old.get('protocol') != 'http_dash_segments':
                continue
            matches = [f for f in new_formats if f.get('format_id') == old.get('format_id')]
            if len(matches) != 1:
                reject()
            before, after = fragment_urls(old), fragment_urls(matches[0])
            if len(before) != len(after) or [resource(u) for u in before] != [resource(u) for u in after]:
                reject()
            updates.update(zip(before, after))
            updates.update(zip(segment_queries(before, old, self.info), segment_queries(after, matches[0], fresh)))
        # HEAD validates the already acquired bytes without transferring them
        # again. Timeline/path agreement alone cannot detect a replaced asset.
        addresses = {resource(old): new for old, new in updates.items()}
        self._verify_segments(addresses, send)
        # Resolve chains so the unchanged native iterator can still request gen 0.
        self.mapping = {old: updates.get(new, new) for old, new in self.mapping.items()}
        self.mapping.update(updates)
        self.addresses = {}
        for old, new in self.mapping.items():
            key = resource(old)
            if key in self.addresses and self.addresses[key] != new:
                self.addresses[key] = None  # An ambiguous URL must never be guessed.
            else:
                self.addresses[key] = new
        self.refreshed_direct.update(resource(u) for u in updates if self.direct(u))
        self.source = deepcopy(source)
        # Keep the original info/fragment timeline, only addresses/context evolve.
        self.publish(source, self.generations)
        self.log('source refresh accepted: pinned representation; validated ledger retained')

    def open(self, request, send, set_context):
        try:
            return self._open(request, send, set_context)
        except HlsError:
            raise
        except Exception:
            self.check()
            # Preserve partial data if renewed credentials/URLs fail too.
            if self.generations:
                reject()
            raise

    def _open(self, request, send, set_context):
        from yt_dlp.networking import Request
        from yt_dlp.networking.exceptions import HTTPError
        request = Request(request) if isinstance(request, str) else request.copy()
        with self.lock:
            self.check()
            if not self.dash_checked:
                self._ensure_dash(self.info, send)
                self.dash_checked = True
                addresses = {resource(u): u for fmt in formats(self.info) if fmt.get('protocol') == 'http_dash_segments'
                             for u in segment_queries(fragment_urls(fmt), fmt, self.info)}
                for text, base in self.playlists.values():
                    try:
                        addresses.update({resource(u): u for u in hls_snapshot(text, base)[1]})
                    except HlsError:
                        pass
                relevant = self.resumed_segments & set(addresses)
                self._verify_segments(addresses, send, relevant)
                self.resumed_segments -= relevant
            original_url = request.url
            request.url = self.mapping.get(original_url) or self.addresses.get(resource(original_url)) or original_url
            try:
                response = send(request)
            except HTTPError as error:
                known = self.direct(original_url) or self.is_segment(original_url) or any(
                    f.get('url') and resource(f['url']) == resource(original_url) for f in formats(self.info))
                if error.status not in (401, 403, 410) or not known:
                    raise
                error.response.close()
                self._refresh(send, set_context)
                fresh_url = self.mapping.get(original_url) or self.addresses.get(resource(original_url))
                if not fresh_url:
                    reject()
                request.url = fresh_url
                fresh_headers = self.format_headers.get(original_url)
                if fresh_headers is not None:
                    for key in list(request.headers):
                        if key.lower() not in ('range', 'if-range', 'accept-encoding'):
                            del request.headers[key]
                    request.headers.update(fresh_headers)
                if self.direct(original_url):
                    previous = self.ledger['direct'].get(resource(original_url))
                    if previous and previous[0]:
                        # Confirm before issuing the resumed GET, not after append.
                        headers = {k: v for k, v in request.headers.items() if k.lower() not in ('range', 'if-range')}
                        with send(Request(fresh_url, headers=headers, method='HEAD')) as probe:
                            if self.validator(probe) != previous:
                                self.log('source refresh reject: direct validator changed')
                                reject()
                        request.headers['If-Range'] = previous[0]
                    elif request.headers.get('Range'):
                        reject()
                response = send(request)
            try:
                return self._record(request, response, send)
            except BaseException:
                response.close()
                raise
