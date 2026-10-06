"""Validated display/context for an already scoped Automatic request."""
import json
import os
import re
from urllib.parse import urlsplit, urlunsplit, parse_qs
from hls import http_url

FATAL_PAGE_CODES = {'drm_protected', 'video_private', 'login_required', 'geo_restricted',
                    'age_restricted', 'content_deleted', 'youtube_session_expired', 'youtube_auth_required'}


def trace_item(log, event, data):
    """Temporary opt-in diagnostics; never log signed query strings/headers."""
    if os.environ.get('KITTY_TRACE_MEDIA_ITEMS') == '1':
        log('mediaItem trace ' + event + ': ' + json.dumps(data, ensure_ascii=False))


def trace_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def validate_item(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError('Média logique invalide.')
    item_id = raw.get('id')
    if not isinstance(item_id, str) or not 1 <= len(item_id) <= 200:
        raise ValueError('Identité du média invalide.')
    title = raw.get('title') or ''
    if not isinstance(title, str) or len(title) > 1000:
        raise ValueError('Titre du média invalide.')
    title = ' '.join(title.split())
    thumbnail = raw.get('thumbnail')
    if thumbnail is not None:
        thumbnail = http_url(thumbnail)
    return dict(id=item_id, page_url=http_url(raw.get('page_url')), title=title,
                title_source=str(raw.get('title_source') or '')[:40], thumbnail=thumbnail,
                media_kind='audio' if raw.get('media_kind') == 'audio' else 'video',
                explicit_sources=raw.get('explicit_sources') is True,
                prefer_extractor=raw.get('prefer_extractor') is True,
                videoTracks=[], audioTracks=[], subtitleTracks=[])


def provider_media_page(url):
    """Only unambiguous single-media URLs, never profiles/feeds/galleries."""
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    if host == 'youtu.be':
        return bool(re.fullmatch(r'/[\w-]{6,}/?', parts.path))
    if host == 'youtube.com' or host.endswith('.youtube.com'):
        return (parts.path == '/watch' and bool(re.fullmatch(r'[\w-]{6,}', parse_qs(parts.query).get('v', [''])[0])) or
                bool(re.fullmatch(r'/(?:shorts|live|embed)/[\w-]{6,}/?', parts.path)))
    if host in ('soundcloud.com', 'www.soundcloud.com'):
        segments = parts.path.strip('/').split('/')
        return (len(segments) == 2 and all(segments) and segments[0] not in
                ('discover', 'search', 'charts', 'you', 'settings', 'stations') and segments[1] not in
                ('sets', 'tracks', 'albums', 'reposts', 'likes', 'popular-tracks', 'followers', 'following'))
    return False


def prefers_extractor(item, url):
    return bool(item and (item.get('prefer_extractor') or provider_media_page(url)))


def apply_item_metadata(info, item):
    if not item or not isinstance(info, dict):
        return
    # DOM caption/label wins; an inferred filename must not replace extractor metadata.
    if (item.get('title') and item.get('title_source') not in ('filename', '')
            and not (item.get('prefer_extractor') and info.get('title'))):
        info['title'] = item['title']
    if item.get('thumbnail'):
        info['thumbnail'] = item['thumbnail']
        info['thumbnails'] = [{'url': item['thumbnail'], 'id': 'dom-poster'}]
