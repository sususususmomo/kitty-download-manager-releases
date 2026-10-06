"""Common track metadata and selection over existing extractor output.

No media/manifest downloader here. Public tracks contain opaque source IDs,
never addresses, request headers or credentials.
"""
from platform_support import replace_file
from copy import deepcopy
import hashlib
import json
import math
import re
from urllib.parse import urljoin
from hls import identity
from metadata_guard import MetadataError

KINDS = ('videoTracks', 'audioTracks', 'subtitleTracks')


def text(value, limit=160):
    return ' '.join(str(value or '').split())[:limit] or None


def number(value):
    return value if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def flag(value):
    return value if isinstance(value, bool) else None


def track_id(source, kind, key):
    return 'track:' + hashlib.sha256(json.dumps([source, kind, key], sort_keys=True).encode()).hexdigest()[:24]


def source_id(source):
    return (source or {}).get('id') or (source or {}).get('identity') or 'item-extractor'


def validate_selection(raw):
    if raw is None:
        return {}
    fields = {'audioTrackId', 'audioLanguage', 'subtitleTrackIds', 'subtitleLanguages', 'preferOriginal'}
    if not isinstance(raw, dict) or set(raw) - fields:
        raise ValueError('Sélection de pistes invalide.')
    clean = {}
    for key, value in raw.items():
        if key == 'preferOriginal':
            if not isinstance(value, bool):
                raise ValueError('Sélection de pistes invalide.')
        elif key.endswith('Ids') or key == 'subtitleLanguages':
            if not isinstance(value, list) or len(value) > 20 or any(
                    not isinstance(v, str) or not 1 <= len(v) <= 200 or re.search(r'[\x00-\x1f\x7f]', v) for v in value):
                raise ValueError('Sélection de pistes invalide.')
            value = list(dict.fromkeys(value))
        elif not isinstance(value, str) or not 1 <= len(value) <= 200 or re.search(r'[\x00-\x1f\x7f]', value):
            raise ValueError('Sélection de pistes invalide.')
        clean[key] = value
    return clean


def language_matches(actual, requested):
    # Exact locale first; a base language can match its regional renditions.
    return bool(actual and requested and (actual.casefold() == requested.casefold()
                or '-' not in requested and actual.split('-')[0].casefold() == requested.casefold()))


def catalogue(info, candidate_id, source_type):
    result = {k: [] for k in KINDS}
    audio = {}
    for fmt in info.get('formats') or [info]:
        if not isinstance(fmt, dict) or fmt.get('has_drm') or not fmt.get('url'):
            continue
        fid = str(fmt.get('format_id') or 'direct')
        meta = fmt.get('_kitty_track') or {}
        lang = text(fmt.get('language'))
        label = text(meta.get('label') or fmt.get('format_note'))
        if label:
            label = text(re.sub(r',\s*(?:low|medium|high|\d+k(?:bps)?)$', '', label, flags=re.I))
        if label and re.fullmatch(r'(?:DASH audio|low|medium|high|\d+k)', label, re.I):
            label = None
        original = flag(meta.get('original', fmt.get('is_original')))
        if original is None and label and re.search(r'\boriginal\b', label, re.I):
            original = True  # Explicit extractor/manifest label, never guessed language.
        common = dict(sourceId=candidate_id, sourceType=source_type, language=lang,
                      label=label, default=flag(meta.get('default', fmt.get('is_default'))), original=original)
        video = fmt.get('vcodec') != 'none' and (fmt.get('vcodec') or fmt.get('height') or source_type == 'direct_video')
        has_audio = fmt.get('acodec') not in (None, '', 'none') or fmt.get('vcodec') == 'none'
        if video:
            result['videoTracks'].append(dict(common, id=track_id(candidate_id, 'video', fid),
                formatIds=[fid], codec=text(fmt.get('vcodec')), bitrate=number(fmt.get('vbr') or fmt.get('tbr')),
                width=number(fmt.get('width')), height=number(fmt.get('height')), fps=number(fmt.get('fps')),
                muxed=bool(has_audio), container=text(fmt.get('ext'))))
        if has_audio:
            streams = fmt.get('_kitty_audio_streams') or [{}]
            for stream in streams:
                values = dict(common)
                if stream:
                    values.update(language=text(stream.get('language')), label=text(stream.get('label')),
                                  default=flag(stream.get('default')), original=flag(stream.get('original')))
                key = (values['language'], values['label'], values['original'], text(meta.get('role')), stream.get('audioIndex'))
                track = audio.setdefault(key, dict(values, id=track_id(candidate_id, 'audio', key),
                    formatIds=[], codec=None, bitrate=None, native=False, muxed=False, representations=[],
                    audioIndex=stream.get('audioIndex'), embedded=bool(stream), streamCount=len(streams), role=text(meta.get('role'))))
                track['formatIds'].append(fid)
                native = fmt.get('vcodec') == 'none'
                track['native'] |= native
                track['muxed'] |= not native
                track['representations'].append(dict(formatId=fid, codec=text(stream.get('codec') or fmt.get('acodec')),
                    bitrate=number(stream.get('bitrate') or fmt.get('abr') or (fmt.get('tbr') if native else None)),
                    container=text(fmt.get('ext')), native=native))
        for stream in fmt.get('_kitty_subtitle_streams') or []:
            result['subtitleTracks'].append(dict(id=track_id(candidate_id, 'subtitle', ['embedded', fid, stream['index']]),
                sourceId=candidate_id, sourceType=source_type, language=text(stream.get('language')),
                label=text(stream.get('label')), codec=text(stream.get('codec')), bitrate=number(stream.get('bitrate')),
                default=flag(stream.get('default')), original=flag(stream.get('original')), automatic=False,
                embedded=True, streamIndex=stream['index'], formatIds=[fid], formats=[]))
    for track in audio.values():
        codecs = {r['codec'] for r in track['representations'] if r['codec']}
        track['codec'] = next(iter(codecs)) if len(codecs) == 1 else None
        track['bitrate'] = max((r['bitrate'] or 0 for r in track['representations']), default=0) or None
        result['audioTracks'].append(track)
    for automatic, key in ((False, 'subtitles'), (True, 'automatic_captions')):
        for lang, entries in (info.get(key) or {}).items():
            usable = [e for e in entries if isinstance(e, dict) and (e.get('url') or e.get('data')) and not e.get('has_drm')]
            if not usable:
                continue
            meta = usable[0].get('_kitty_track') or {}
            result['subtitleTracks'].append(dict(id=track_id(candidate_id, 'subtitle', [lang, automatic]),
                sourceId=candidate_id, sourceType=source_type, language=text(lang),
                label=text(meta.get('label') or usable[0].get('name')), codec=None, bitrate=None,
                default=flag(meta.get('default')), original=flag(meta.get('original')),
                automatic=automatic, formats=list(dict.fromkeys(text(e.get('ext')) for e in usable if e.get('ext')))))
    return result


def choose_tracks(tracks, selection):
    selection = validate_selection(selection)
    audio = tracks['audioTracks']
    if selection.get('audioTrackId'):
        audio = [t for t in audio if t['id'] == selection['audioTrackId']]
    if selection.get('audioLanguage'):
        audio = [t for t in audio if language_matches(t['language'], selection['audioLanguage'])]
    if not audio and (selection.get('audioTrackId') or selection.get('audioLanguage')):
        raise MetadataError('track_unavailable', 'La piste audio demandée est indisponible pour ce média.')
    selected_audio = max(audio, key=lambda t: (t['native'],
        t['original'] is True if selection.get('preferOriginal', True) else False,
        t['default'] is True, t['bitrate'] or 0), default=None)
    subtitles = []
    for tid in selection.get('subtitleTrackIds', []):
        found = next((t for t in tracks['subtitleTracks'] if t['id'] == tid), None)
        if not found:
            raise MetadataError('track_unavailable', 'Le sous-titre demandé est indisponible pour ce média.')
        subtitles.append(found)
    for lang in selection.get('subtitleLanguages', []):
        found = [t for t in tracks['subtitleTracks'] if language_matches(t['language'], lang)]
        if not found:
            raise MetadataError('track_unavailable', 'Le sous-titre demandé est indisponible pour ce média.')
        subtitles.append(min(found, key=lambda t: t['automatic']))
    subtitles = list({t['id']: t for t in subtitles}.values())
    if len({t['language'] for t in subtitles}) != len(subtitles):
        raise MetadataError('track_unavailable', 'Choisis une seule piste de sous-titres par langue.')
    return selected_audio, subtitles


def available_selection(tracks, selection):
    """Adapt preferences without changing the saved request or strict API.

    One unavailable subtitle must not remove another available language. Opaque
    IDs never migrate to a different source; languages can match locales.
    """
    clean = validate_selection(selection)
    audio = tracks['audioTracks']
    if clean.get('audioTrackId') and not any(t['id'] == clean['audioTrackId'] for t in audio):
        clean.pop('audioTrackId')
    if clean.get('audioLanguage') and not any(language_matches(t['language'], clean['audioLanguage']) for t in audio):
        clean.pop('audioLanguage')
    for key, attribute in (('subtitleTrackIds', 'id'), ('subtitleLanguages', 'language')):
        if key in clean:
            clean[key] = [value for value in clean[key] if any(
                language_matches(t[attribute], value) if attribute == 'language' else t[attribute] == value
                for t in tracks['subtitleTracks'])]
            if not clean[key]:
                clean.pop(key)
    return clean


def compose_info(candidate, cohort, selection, mode, adapt=False):
    """Choose only among sources already scoped to this item by the resolver.

    An explicit audio choice may be a separate candidate. Its native formats
    and context stay attached to that source; no page/global format lookup.
    """
    selection = validate_selection(selection)
    catalogues = [(c, catalogue(c.info, source_id(c.source), c.sourceType)) for c in cohort]
    tracks = {kind: [t for _, catalogue_ in catalogues for t in catalogue_[kind]] for kind in KINDS}
    if adapt:
        selection = available_selection(tracks, selection)
    explicit_audio = bool(selection.get('audioTrackId') or selection.get('audioLanguage'))
    if explicit_audio:
        audio, subtitles = choose_tracks(tracks, selection)
        if audio and not audio['native'] and not selection.get('audioTrackId'):
            # A language can exist in several muxed quality variants. Keep the
            # current video's rendition rather than borrowing another file.
            local_tracks = catalogue(candidate.info, source_id(candidate.source), candidate.sourceType)
            if any(language_matches(t['language'], selection.get('audioLanguage')) for t in local_tracks['audioTracks']):
                audio, _ = choose_tracks(local_tracks, {k:v for k,v in selection.items() if not k.startswith('subtitle')})
    else:
        audio, _ = choose_tracks(catalogue(candidate.info, source_id(candidate.source), candidate.sourceType), {})
        if not audio:
            audio, _ = choose_tracks({**tracks, 'audioTracks':[t for t in tracks['audioTracks'] if t['native']]}, {})
        _, subtitles = choose_tracks(tracks, {k: v for k, v in selection.items() if k.startswith('subtitle')})
    result = deepcopy(candidate.info)
    # extract_info(download=False) may already have a global selection. A
    # single audio choice has no requested_formats key to overwrite that old
    # video+audio pair; retaining it would pin the wrong streams in our plan.
    for key in ('requested_formats', 'requested_downloads', 'requested_subtitles'):
        result.pop(key, None)
    auxiliary = []
    primary_audio = catalogue(candidate.info, source_id(candidate.source), candidate.sourceType)['audioTracks']
    if audio and (explicit_audio or mode in ('audio', 'mp3') or selection.get('preferOriginal') or len(primary_audio) != 1):
        provider = next(c for c, cat in catalogues if any(t['id'] == audio['id'] for t in cat['audioTracks']))
        formats = [deepcopy(f) for f in provider.info.get('formats') or [provider.info]
                   if str(f.get('format_id') or 'direct') in audio['formatIds']]
        native = [f for f in formats if f.get('vcodec') == 'none']
        if provider is not candidate:
            if not native:
                raise MetadataError('track_unavailable', 'Cette source ne fournit pas de piste audio séparée.')
            auxiliary.append(provider.source) if provider.source else None
            # Format IDs are local to each extractor. Qualify borrowed IDs.
            translated = {}
            for f in native:
                old = str(f.get('format_id') or 'direct')
                f['format_id'] = source_id(provider.source) + ':' + old
                translated[old] = f['format_id']
            tracks = deepcopy(tracks)
            for t in tracks['audioTracks']:
                if t['id'] == audio['id']:
                    t['formatIds'] = [translated.get(fid, fid) for fid in t['formatIds']]
                    audio = t
        if mode in ('audio', 'mp3'):
            result['formats'] = native or formats
        elif native:
            video = [f for f in result.get('formats') or [result] if f.get('vcodec') != 'none']
            # A muxed source can still provide the best video. Declare the
            # requested video stream so yt-dlp's existing FFmpegMerger omits
            # that file's old audio rather than adding a second language.
            for fmt in video:
                if fmt.get('acodec') not in (None, 'none'):
                    fmt.pop('language', None)  # This was the muxed audio's language.
                fmt['acodec'] = 'none'
            result['formats'] = video + native
        else:
            result['formats'] = formats
        if audio.get('embedded'):
            for fmt in result['formats']:
                if str(fmt.get('format_id') or 'direct') in audio['formatIds']:
                    # FFmpegMetadata consumes the selected format's language;
                    # retain the chosen embedded stream, not the first stream.
                    fmt['language'] = audio['language']
                    fmt['acodec'] = audio['codec'] or fmt.get('acodec')
        result['language'] = audio['language']
    selected_subs = {}
    for track in subtitles:
        if selection.get('subtitleLanguages') and track['id'] not in selection.get('subtitleTrackIds', []):
            local_subs = catalogue(candidate.info, source_id(candidate.source), candidate.sourceType)['subtitleTracks']
            same = [t for t in local_subs if t['language'] == track['language'] and not t['automatic']]
            if same:
                replacement = same[0]
                subtitles[subtitles.index(track)] = replacement
                track = replacement
        provider = next(c for c, cat in catalogues if any(t['id'] == track['id'] for t in cat['subtitleTracks']))
        if track.get('embedded'):
            if provider is not candidate:
                raise MetadataError('track_unavailable', 'Le sous-titre intégré appartient à un autre conteneur.')
            result['formats'] = [f for f in result.get('formats') or [result] if str(f.get('format_id') or 'direct') in track['formatIds']]
            continue
        key = 'automatic_captions' if track['automatic'] else 'subtitles'
        selected_subs[track['language']] = deepcopy(provider.info[key][track['language']])
        if provider is not candidate and provider.source and provider.source not in auxiliary:
            auxiliary.append(provider.source)
    result['subtitles'] = selected_subs
    result['automatic_captions'] = {}
    return result, tracks, audio, subtitles, auxiliary


def embedded_postprocessor(ydl, plan, mode, runner):
    """Local stream-copy selection, after the existing native downloader."""
    from yt_dlp.postprocessor import PostProcessor
    import os
    from pathlib import Path
    import shutil
    import subprocess
    class SelectedStreamsPP(PostProcessor):
        def run(self, info):
            src = Path(info['filepath'])
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise MetadataError('ffmpeg_missing', 'ffmpeg est requis pour sélectionner les pistes intégrées.')
            def execute(args):
                process = runner([ffmpeg, '-y', '-v', 'error', '-i', str(src), *args],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
                if process.returncode:
                    raise MetadataError('postprocess_failed', 'Impossible de sélectionner les pistes intégrées.')
            # Extract captions before removing them from the selected media.
            for track in plan.embeddedSubtitles:
                codec = track.get('codec')
                ext = {'ass':'ass', 'ssa':'ass', 'subrip':'srt', 'mov_text':'srt', 'webvtt':'vtt', 'hdmv_pgs_subtitle':'sup'}.get(codec, 'mks')
                lang = re.sub(r'[^\w-]', '_', track.get('language') or 'und')
                dst = src.with_name(src.stem + '.' + lang + '.' + ext)
                args = ['-map', f"0:{track['streamIndex']}"]
                if ext in ('sup','mks'):
                    args += ['-c:s', 'copy']
                if ext == 'mks':
                    args += ['-f', 'matroska']
                execute([*args, str(dst)])
            if plan.embeddedAudioIndex is not None:
                temp = src.with_name(src.stem + '.track-temp' + src.suffix)
                maps = ['-map', '0:v?'] if mode not in ('audio','mp3') else []
                try:
                    execute([*maps, '-map', f'0:a:{plan.embeddedAudioIndex}', '-map_metadata', '0', '-c', 'copy', str(temp)])
                    replace_file(temp, src)
                finally:
                    temp.unlink(missing_ok=True)
            return [], info
    return SelectedStreamsPP(ydl)


def auxiliary_contexts(plan):
    """Reuse RequestContext for borrowed formats and their own fragment paths."""
    from request_context import from_source, origin
    contexts = []
    for source in plan.auxiliarySources:
        context = from_source(source)
        contexts.append(context.wire())
        prefix = source_id(source) + ':'
        formats = [f for f in plan.preparedInfo.get('formats', []) if str(f.get('format_id', '')).startswith(prefix)]
        for f in formats:
            urls = [f.get('url')]
            base = f.get('fragment_base_url') or f.get('url') or source['url']
            urls.extend(urljoin(base, fragment.get('url') or fragment.get('path') or '') for fragment in f.get('fragments', []))
            for url in urls:
                if url and origin(url) == origin(context.source_url):
                    contexts.append({**context.wire(), 'source_url': url})
    return contexts


def annotate_manifest(info, data, url, kind):
    """Recover flags/labels discarded by extractors, without parsing media."""
    if kind == 'hls':
        from yt_dlp.utils import parse_m3u8_attributes, parse_codecs
        metadata = {}
        lines = data.decode('utf-8-sig', 'replace').splitlines()
        audio_codecs = {}
        for line in lines:
            if line.startswith('#EXT-X-STREAM-INF:'):
                a = parse_m3u8_attributes(line.split(':', 1)[1])
                codec = parse_codecs(a.get('CODECS') or '').get('acodec')
                if a.get('AUDIO') and codec and codec != 'none':
                    audio_codecs.setdefault(a['AUDIO'], set()).add(codec)
        for line in lines:
            if not line.startswith('#EXT-X-MEDIA:'):
                continue
            a = parse_m3u8_attributes(line.split(':', 1)[1])
            if not a.get('URI'):
                continue
            metadata[identity(urljoin(url, a['URI']), '')] = dict(label=a.get('NAME'), group=a.get('GROUP-ID'),
                type=a.get('TYPE'), default=True if a.get('DEFAULT') == 'YES' else False if a.get('DEFAULT') == 'NO' else None)
        for fmt in info.get('formats', []) + [e for entries in (info.get('subtitles') or {}).values() for e in entries]:
            if fmt.get('url') and identity(fmt['url'], '') in metadata:
                fmt['_kitty_track'] = metadata[identity(fmt['url'], '')]
                codecs = audio_codecs.get(fmt['_kitty_track']['group'], set())
                if fmt['_kitty_track']['type'] == 'AUDIO' and not fmt.get('acodec') and len(codecs) == 1:
                    fmt['acodec'] = next(iter(codecs))
    elif kind == 'dash':
        import xml.etree.ElementTree as ET
        root = ET.fromstring(data)
        local = lambda n: n.tag.rsplit('}', 1)[-1]
        for adaptation in (n for n in root.iter() if local(n) == 'AdaptationSet'):
            for rep in (n for n in adaptation if local(n) == 'Representation'):
                roles = [n.get('value') for parent in (adaptation, rep) for n in parent if local(n) == 'Role']
                label = next((n.text for parent in (rep, adaptation) for n in parent if local(n) == 'Label'), None)
                for fmt in info.get('formats', []):
                    fid = str(fmt.get('format_id') or '')
                    if rep.get('id') and (fid == rep.get('id') or fid.endswith('-' + rep.get('id'))):
                        fmt['_kitty_track'] = dict(label=label, role=','.join(filter(None, roles)) or None,
                            group=adaptation.get('id'), default=True if 'main' in roles else None,
                            original=True if 'original' in roles else False if 'dub' in roles else None)
                # Caption labels/roles are attached only with an exact native
                # extractor URL match, never by language alone.
                base = next((n.text for n in rep if local(n) == 'BaseURL'), None)
                if base:
                    target = urljoin(url, base)
                    for entries in (info.get('subtitles') or {}).values():
                        for entry in entries:
                            if entry.get('url') and identity(entry['url'], '') == identity(target, ''):
                                entry['_kitty_track'] = dict(label=label, default=True if 'main' in roles else None,
                                    original=True if 'original' in roles else None)
