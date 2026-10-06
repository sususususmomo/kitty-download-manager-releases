"""Bounded parallel metadata discovery and source selection, never media transfer.

Each resolver owns a supervised subprocess. Formats from one source are never
combined with formats from another video, player, tab or manifest.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from copy import deepcopy
from request_context import youtube_dl
import errno
import math
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

from errors import classify_backend_error
from hls import validate_source, apply_options, network_resource_ids
from metadata_guard import extract_metadata, MetadataError
from media_item import trace_item, trace_url, prefers_extractor, FATAL_PAGE_CODES
from media_tracks import catalogue, source_id, validate_selection, compose_info

PAGE_TIMEOUT = 30
NETWORK_TIMEOUT = 20
READY_GRACE = 5


@dataclass(frozen=True)
class DownloadRequest:
    mode: str
    maxHeight: int | None
    preferredContainer: str | None
    audioRequired: bool
    preferOriginalCodec: bool
    allowTranscode: bool

    @classmethod
    def from_mode(cls, mode):
        if mode not in ('1080', '720', 'best', 'audio', 'mp3'):
            raise ValueError('Mode automatique invalide.')
        return cls('audio' if mode in ('audio', 'mp3') else 'video',
                   int(mode) if mode in ('1080', '720') else None,
                   'mp3' if mode == 'mp3' else None if mode == 'audio' else 'mp4',
                   mode in ('audio', 'mp3'), mode != 'mp3', mode == 'mp3')


@dataclass
class MediaCandidate:
    sourceType: str
    url: str
    pageUrl: str
    tabId: int | None
    title: str
    maxHeight: int | None
    resolutions: list
    hasVideo: bool | None
    hasAudio: bool | None
    videoCodec: str | None
    audioCodec: str | None
    container: str | None
    bitrate: float | None
    fps: float | None
    estimatedSize: float | None
    isMaster: bool
    isPartial: bool
    requiresMerge: bool
    requiresTranscode: bool
    confidence: float
    timestamp: float
    expiryTime: float | None
    completeness: float
    nativeAudio: bool
    info: dict = field(repr=False)
    source: dict | None = field(repr=False)
    score: float = 0
    requestContext: dict | None = field(default=None, repr=False)
    videoTracks: list = field(default_factory=list)
    audioTracks: list = field(default_factory=list)
    subtitleTracks: list = field(default_factory=list)

    def __post_init__(self):
        if self.source:
            self.requestContext = self.source.get("request_context")
        for kind, tracks in catalogue(self.info, source_id(self.source), self.sourceType).items():
            setattr(self, kind, tracks)

    @property
    def expiryKnown(self):
        return self.expiryTime is not None


@dataclass(frozen=True)
class DownloadPlan:
    mediaItemId: str
    candidateId: str
    sourceType: str
    sourceUrl: str
    downloadUrls: tuple
    selectionPolicy: str
    formatSelector: str
    selection: dict = field(repr=False)
    videoTrackIds: tuple = ()
    audioTrackId: str | None = None
    audioLanguage: str | None = None
    subtitleTrackIds: tuple = ()
    subtitleLanguages: tuple = ()
    preparedInfo: dict = field(default_factory=dict, repr=False)
    auxiliarySources: tuple = field(default=(), repr=False)
    embeddedAudioIndex: int | None = None
    embeddedSubtitles: tuple = field(default=(), repr=False)

    def select_formats(self, _context):
        # yt-dlp's callable selector consumes the already selected formats.
        # It cannot reinterpret a global mode or borrow another item's URL.
        yield deepcopy(self.selection)

    def summary(self):
        return {name: getattr(self, name) for name in ('mediaItemId', 'candidateId',
                'sourceType', 'sourceUrl', 'downloadUrls', 'selectionPolicy', 'formatSelector',
                'videoTrackIds', 'audioTrackId', 'audioLanguage', 'subtitleTrackIds', 'subtitleLanguages', 'embeddedAudioIndex')}


def build_item_plan(candidate, job, options, cohort=None):
    """Use yt-dlp's existing selector, metadata only, then bind its choice."""
    owned = (getattr(candidate, '_track_cohort', None) or cohort or [candidate]) if job.get('media_item') else [candidate]
    info, tracks, audio, subtitles, auxiliary = compose_info(candidate, owned,
        validate_selection(job.get('track_selection')), job['mode'])
    policy = options['format']
    if job.get('media_item') and job['mode'] in ('720', '1080', 'best'):
        cap = '' if job['mode'] == 'best' else '[height<=?' + job['mode'] + ']'
        # Silent Wikimedia videos are valid. Prefer the best video, optionally
        # merged with its own audio, rather than a lower muxed transcode.
        policy = 'bv*' + cap + '+ba/bv*' + cap
    opts = dict(options, format=policy, skip_download=True, writethumbnail=False,
                postprocessors=[], progress_hooks=[], writesubtitles=bool(subtitles),
                subtitleslangs=[t['language'] for t in subtitles], writeautomaticsub=False)
    with youtube_dl(opts) as ydl:
        chosen = ydl.process_ie_result(info, download=False)
    parts = chosen.get('requested_formats') or [chosen]
    urls = tuple(f['url'] for f in parts if f.get('url'))
    if not urls:
        raise MetadataError('format_unavailable', 'Aucune URL pour le média sélectionné.')
    ids = '+'.join(str(f['format_id']) for f in parts)
    selection = {k: v for k, v in chosen.items() if k not in ('formats', 'entries', 'requested_downloads')}
    selected_ids = {str(f.get('format_id')) for f in parts}
    video_ids = tuple(t['id'] for t in tracks['videoTracks'] if selected_ids.intersection(t['formatIds']))
    actual_audio = audio if audio and selected_ids.intersection(audio['formatIds']) else next((t for t in tracks['audioTracks'] if selected_ids.intersection(t['formatIds'])), None)
    if len(parts) > 1 and any(t.get('embedded') for t in subtitles):
        raise MetadataError('track_unavailable', 'Le sous-titre intégré nécessite le téléchargement de son conteneur.')
    return DownloadPlan((job.get('media_item') or {}).get('id', ''), (candidate.source or {}).get('id') or
                        (candidate.source or {}).get('identity') or 'item-extractor',
                        candidate.sourceType, candidate.url, urls, policy, ids, selection,
                        video_ids, (actual_audio or audio or {}).get('id'), (actual_audio or audio or {}).get('language'),
                        tuple(t['id'] for t in subtitles), tuple(t['language'] or 'und' for t in subtitles), info, tuple(auxiliary),
                        (actual_audio or {}).get('audioIndex'), tuple(t for t in subtitles if t.get('embedded')))


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def _presence(formats, codec):
    if codec == 'acodec' and any(f.get('vcodec') == 'none' and f.get('acodec') != 'none' for f in formats):
        return True
    values = [f.get(codec) for f in formats]
    if any(v not in (None, 'none', '') for v in values):
        return True
    return False if values and all(v == 'none' for v in values) else None


def candidate_from_info(info, source, job, request):
    if not isinstance(info, dict) or info.get('entries') is not None or info.get('_type') in ('playlist', 'multi_video'):
        raise MetadataError('format_unavailable', 'Une collection nécessite le mode Playlist.')
    formats = [f for f in (info.get('formats') or [info]) if isinstance(f, dict) and not f.get('has_drm')]
    if info.get('has_drm') or not formats or not any(f.get('url') or f.get('manifest_url') for f in formats):
        raise MetadataError('drm_protected' if info.get('has_drm') else 'format_unavailable', 'Aucun format compatible.')
    video = [f for f in formats if f.get('vcodec') != 'none' and
             (request.maxHeight is None or not number(f.get('height')) or f['height'] <= request.maxHeight)]
    audio = [f for f in formats if f.get('acodec') not in (None, '', 'none') or f.get('vcodec') == 'none' and f.get('acodec') != 'none']
    native = [f for f in audio if f.get('vcodec') == 'none']
    heights = sorted({int(f['height']) for f in video if number(f.get('height'))})
    best_video = max(video, key=lambda f: (number(f.get('height')) or 0, number(f.get('tbr')) or 0), default={})
    effective = native + video if request.mode == 'video' else formats
    compatible_audio = [f for f in effective if f.get('acodec') not in (None, '', 'none')]
    best_audio = max(native or compatible_audio, key=lambda f: number(f.get('abr') or f.get('tbr')) or 0, default={})
    selected = best_audio if request.mode == 'audio' else best_video
    source_type = source['type'] if source else 'ytdlp'
    expiry = None
    try:
        query = parse_qs(urlsplit(source['url'] if source else job['url']).query)
        # Only explicit epoch expiry is known; arbitrary CDN tokens aren't decoded.
        for name in ('expires', 'expiry', 'exp'):
            value = float(query.get(name, ['0'])[0])
            if 1e9 < value < 1e11:
                expiry = value
                break
    except (ValueError, TypeError):
        pass
    has_video = _presence(video, 'vcodec') if video else False
    has_audio = _presence(effective, 'acodec')
    manifest_kind = (source or {}).get('manifest_kind')
    partial = source_type == 'hls' and (manifest_kind not in (None, 'master') or
                                      (manifest_kind is None and not any(f.get('height') for f in formats)))
    completeness = sum(v is not None for v in (has_video, has_audio, selected.get('ext'), selected.get('vcodec'), selected.get('acodec'), number(selected.get('height')))) / 6
    return MediaCandidate(source_type, source['url'] if source else job['url'],
                          source['page_url'] if source else job.get('source_page_url') or job['url'], source.get('tab_id') if source else None,
                          str(info.get('title') or ''), max(heights, default=None), heights,
                          has_video, has_audio, best_video.get('vcodec'), best_audio.get('acodec'), selected.get('ext'),
                          number(selected.get('tbr')), number(best_video.get('fps')),
                          number(selected.get('filesize') or selected.get('filesize_approx')),
                          source_type == 'dash' or (source_type == 'hls' and not partial), partial,
                          bool(best_video and best_video.get('acodec') == 'none' and native),
                          request.preferredContainer == 'mp3' and best_audio.get('acodec') not in ('mp3', 'mp3float'),
                          1.0, source.get('timestamp', time.time()) if source else time.time(), expiry,
                          completeness, bool(native), info, source)


def rejection_reason(candidate, request, now=None):
    now = time.time() if now is None else now
    if candidate.expiryTime is not None and candidate.expiryTime <= now:
        return 'source_expired'
    if request.mode == 'video' and candidate.hasVideo is False:
        return 'no_video_format_under_requested_cap'
    if request.audioRequired and candidate.hasAudio is False:
        return 'audio_required_but_absent'
    if candidate.requiresTranscode and not request.allowTranscode:
        return 'transcode_not_allowed'
    return None


def scoreCandidate(candidate, request, now=None):
    """Quality/audio suitability dominates small metadata and site-extractor bonuses."""
    now = time.time() if now is None else now
    if rejection_reason(candidate, request, now):
        return -math.inf
    score = 60 + 4 * candidate.completeness + 2 * candidate.confidence
    if request.mode == 'video':
        height = candidate.maxHeight or 0
        # 720 -> 1080 is worth 30 points, dwarfing every tie-breaker together.
        score += (90 * min(height / request.maxHeight, 1) if request.maxHeight
                  else 90 * math.log2(1 + height / 720))
        if not height:
            score -= 15
    else:
        if candidate.nativeAudio:
            score += {'direct_audio': 70, 'direct_video': 65, 'hls': 60, 'dash': 60, 'ytdlp': 50}.get(candidate.sourceType, 50)
        elif candidate.hasAudio:
            score += 10  # Lossless extraction from an existing video container.
    if candidate.requiresTranscode:
        score -= 30
    if request.audioRequired:
        score += 12 if candidate.hasAudio else -25
    elif candidate.hasAudio:
        score += 12  # Prefer sound without rejecting legitimate silent videos.
    if candidate.container == request.preferredContainer:
        score += 2
    if request.preferredContainer == 'mp4':
        # Small compatibility bonus for common MP4 codecs. Others can remain
        # usable through the existing remux pipeline; this is not a DRM bypass.
        if str(candidate.videoCodec or '').lower().startswith(('avc', 'h264', 'hev', 'hvc', 'h265', 'av01', 'av1', 'mpeg4')):
            score += 1
        if str(candidate.audioCodec or '').lower().startswith(('aac', 'mp4a', 'mp3', 'alac', 'ac3', 'eac3')):
            score += 1
    if candidate.isMaster or candidate.sourceType == 'ytdlp':
        score += 1
    if candidate.isPartial:
        score -= 4
    if candidate.expiryTime is not None and candidate.expiryTime - now < 60:
        score -= 25
    return round(score, 3)


def resolve_candidates(options, job, check_control=lambda: None, log=lambda _: None,
                       extractor=extract_metadata, page_timeout=PAGE_TIMEOUT,
                       network_timeout=NETWORK_TIMEOUT, ready_grace=READY_GRACE):
    """At most four simultaneous metadata probes; each item owns its sources."""
    request = DownloadRequest.from_mode(job['mode'])
    track_selection = validate_selection(job.get('track_selection'))
    page = job['url']
    observed_page = job.get('source_page_url') or page
    item = job.get('media_item')
    prefer_page = prefers_extractor(item, page)
    sources = []
    seen = set()
    for raw in job.get('media_fallbacks') or job.get('hls_fallbacks') or []:
        source = validate_source(raw)
        if item and source.get('media_item_id', item['id']) != item['id']:
            log('candidate rejected: ' + source['type'] + '; reason=unrelated_media_item')
            continue
        # Right-click links and stale tab snapshots must not use unrelated players.
        if source['page_url'] != observed_page or source['identity'] in seen:
            log('candidate rejected: ' + source['type'] + '; reason=' + ('unrelated_page' if source['page_url'] != observed_page else 'duplicate'))
            continue
        log('candidate accepted by resolver: ' + source['type'])
        seen.add(source['identity'])
        sources.append(source)
        if len(sources) == (12 if item else 3):
            break
    # A selected item's attached sources supersede page extraction. Unresolved
    # items use only their own File/embed URL; ordinary page jobs stay unchanged.
    if not item or not sources or prefer_page:
        sources.insert(0, None)
    if item:
        trace_item(log, 'selected', {'id': item['id'], 'title': item.get('title')})
        trace_item(log, 'candidates', [{'id': s.get('id') or s['identity'], 'type': s['type'],
                   'quality': (s.get('metadata') or {}).get('height'), 'url': trace_url(s['url'])}
                   if s else {'id': 'item-extractor', 'type': 'ytdlp', 'url': trace_url(page)} for s in sources])
    stopped = threading.Event()
    results, failures, probed_candidates = [], [], []
    incompatible = 0
    fatal_page_error = None
    def control():
        if stopped.is_set():
            raise MetadataError('probe_stopped', 'Analyse terminée.')
    def probe(source):
        opts = dict(options, skip_download=True, writethumbnail=False, format=None,
                    ignore_no_formats_error=True, retries=0, extractor_retries=0, fragment_retries=0,
                    socket_timeout=8)
        probe_job = {'url': source['url'] if source else page, 'mode': job['mode']}
        if source:
            probe_job['media_source'] = source
            apply_options(opts, source)
        info, _ = extractor(opts, probe_job, check_control=control,
                            timeout=network_timeout if source else page_timeout)
        return candidate_from_info(info, source, job, request)
    check_control()
    with ThreadPoolExecutor(max_workers=min(4, len(sources)), thread_name_prefix='kitty-probe') as pool:
        pending = {pool.submit(probe, s): s['type'] if s else 'ytdlp' for s in sources}
        deadline = time.monotonic() + max(page_timeout, network_timeout)
        ready_deadline = None
        try:
            for kind in pending.values():
                log('candidate discovered: ' + kind)
            while pending:
                check_control()
                if time.monotonic() >= min(deadline, ready_deadline or deadline):
                    for kind in pending.values():
                        log('resolver timeout: ' + kind)
                    break
                done, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                for future in done:
                    kind = pending.pop(future)
                    try:
                        candidate = future.result()
                        probed_candidates.append(candidate)
                        candidate.score = scoreCandidate(candidate, request)
                        log(f'resolver completed: {kind}; candidate score: {candidate.score}')
                        if math.isfinite(candidate.score):
                            results.append(candidate)
                            matches = request.mode == 'audio' and candidate.nativeAudio or request.mode == 'video' and request.maxHeight and (candidate.maxHeight or 0) >= request.maxHeight
                            if matches and ready_deadline is None and not track_selection and not prefer_page:
                                ready_deadline = time.monotonic() + ready_grace
                        else:
                            incompatible += 1
                            log('candidate rejected: ' + kind + '; reason=' + rejection_reason(candidate, request))
                    except Exception as exc:
                        if prefer_page and kind == 'ytdlp' and classify_backend_error(exc, code_hint=getattr(exc, 'code', None))['code'] in FATAL_PAGE_CODES:
                            fatal_page_error = exc
                        failures.append(exc)
                        log('resolver timeout: ' + kind if getattr(exc, 'code', None) == 'metadata_timeout' else 'resolver failed: ' + kind + '; reason=' + classify_backend_error(exc, code_hint=getattr(exc, 'code', None))['code'])
        finally:
            stopped.set()
    if fatal_page_error:
        raise fatal_page_error
    if not results:
        failure = (MetadataError('format_unavailable', 'Aucune source ne correspond au format demandé.') if incompatible
                   else failures[-1] if failures else MetadataError('metadata_timeout', 'Analyse des sources trop longue.'))
        raise failure
    if track_selection:
        eligible = []
        for candidate in probed_candidates:
            try:
                owned = probed_candidates if item else [candidate]
                prepared, *_ = compose_info(candidate, owned, track_selection, job['mode'])
                effective = candidate_from_info(prepared, candidate.source, job, request)
                candidate.score = scoreCandidate(effective, request)
                if math.isfinite(candidate.score):
                    candidate._track_cohort = owned
                    eligible.append(candidate)
            except MetadataError:
                log('candidate rejected: ' + candidate.sourceType + '; reason=track_unavailable')
        if not eligible:
            raise MetadataError('track_unavailable', 'La piste demandée est indisponible pour ce média.')
        results = eligible
    elif item:
        for candidate in results:
            candidate._track_cohort = probed_candidates
    page_candidate = next((c for c in results if c.sourceType == 'ytdlp'), None)
    if page_candidate and not (job.get("media_item") or {}).get("explicit_sources"):
        page_resources = set(network_resource_ids(page_candidate.info, observed_page))
        matching = [c for c in results if c.sourceType != 'ytdlp'
                    and page_resources.intersection(network_resource_ids(c.info, observed_page))]
        if matching:
            # A positive shared-resource relationship identifies the page's
            # player. Don't let a separate ad/preview win just by its resolution.
            # Without such evidence keep the network fallback, rather than
            # guessing that a recognized site makes every network source redundant.
            results = [page_candidate, *matching]
            log('candidate cohort: shared page resources')
    if prefer_page and page_candidate:
        # Unproven CDN renditions remain fallback candidates. They cannot add
        # an ad's audio/subtitles to a successful site's extraction plan.
        for candidate in results:
            candidate._track_cohort = [candidate]
    # yt-dlp preference is strictly a tie-breaker, not part of the quality score.
    results.sort(key=lambda c: ((prefer_page and c.sourceType == 'ytdlp',) if prefer_page else ())
                 + ((c.maxHeight or 0,) if item and request.mode == 'video' else ())
                 + (c.score, c.sourceType == 'ytdlp'), reverse=True)
    log('selected candidate: ' + results[0].sourceType)
    return results


def can_runtime_fallback(error, downloaded, media_finished, elapsed):
    if getattr(error, 'code', None) == 'source_identity_unconfirmed':
        return downloaded == 0 and not media_finished
    if downloaded > 65536 or media_finished or elapsed > 10:
        return False
    if error.__class__.__name__ in ('DownloadCancelled', 'DownloadPaused', 'WorkerShutdown'):
        return False
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EACCES, errno.EPERM, errno.ENOENT, errno.EIO, errno.EROFS):
        return False
    code = classify_backend_error(error, code_hint=getattr(error, 'code', None))['code']
    if code == 'backend_error' and re.search(r'HTTP Error (?:401|403|404|410)\b', str(error), re.I):
        return True
    return code in {'unsupported_url', 'extraction_failed', 'format_unavailable', 'network_interrupted',
                    'access_denied', 'content_deleted', 'hls_expired', 'hls_access_denied', 'hls_unavailable', 'hls_no_formats',
                    'dash_expired', 'dash_access_denied', 'dash_unavailable', 'dash_no_formats',
                    'direct_expired', 'direct_access_denied', 'direct_unavailable', 'direct_no_formats'}
