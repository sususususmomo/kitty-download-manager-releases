"""Supervise metadata in a disposable process, with a real wall-clock limit.

No queue mutation in the child. The worker keeps its controls and download
pipeline; slow HTTP, yt-dlp retries and JS/FFmpeg children cannot hold it forever.
"""
from __future__ import annotations
from request_context import youtube_dl
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

WORKER_METADATA_TIMEOUT = 120
PROBE_TIMEOUT = 30
FFPROBE_TIMEOUT = 15
FFMPEG_TIMEOUT = 600


class MetadataError(RuntimeError):
    def __init__(self, code, message, detail=None):
        self.code = code
        self.detail = detail or message
        super().__init__(message)


def stop_process(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        if process.poll() is not None:
            process.wait(timeout=3)
            return
        try:
            from platform_support import run_hidden
            taskkill = str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe')
            run_hidden([taskkill, '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
    process.wait(timeout=3)


def _json_options(options):
    # Callbacks and the logger live in the parent; never serialize executable
    # objects. The child uses its own quiet logger and no progress hooks.
    clean = {}
    for key, value in options.items():
        if key in ('logger', 'progress_hooks', 'postprocessor_hooks', 'match_filter'):
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        clean[key] = value
    return clean


def extract_metadata(options, job, check_control=lambda: None,
                     on_fallback=lambda source: None, timeout=WORKER_METADATA_TIMEOUT):
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Invalid metadata timeout')
    check_control()
    with tempfile.TemporaryDirectory(prefix='kitty-metadata-') as temp:
        request, result = Path(temp) / 'request.json', Path(temp) / 'result.json'
        request.write_text(json.dumps({'options': _json_options(options), 'job': job}), encoding='utf-8')
        os.chmod(request, 0o600)
        spawn = {'start_new_session': True} if os.name == 'posix' else {'creationflags': subprocess.CREATE_NO_WINDOW}
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(request), str(result)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **spawn)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                check_control()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MetadataError('metadata_timeout', 'Analyse des métadonnées trop longue')
                try:
                    process.wait(timeout=min(.1, remaining))
                except subprocess.TimeoutExpired:
                    pass
            check_control()
            if not result.is_file() or result.stat().st_size > 32 * 1024 * 1024:
                raise MetadataError('metadata_failed', 'Métadonnées indisponibles')
            payload = json.loads(result.read_text(encoding='utf-8'))
            if not payload.get('ok'):
                error = payload.get('error') or {}
                raise MetadataError(error.get('code', 'metadata_failed'), error.get('message', 'Métadonnées indisponibles'), error.get('detail'))
            source = payload.get('source')
            if source and not job.get('media_source'):
                on_fallback(source)
            return payload['info'], source
        finally:
            # Also clears detached JS children after successful extraction.
            stop_process(process)


def install_ffmpeg_timeouts():
    """Limit yt-dlp's own local FFmpeg/ffprobe operations, not media download duration."""
    from yt_dlp.postprocessor import ffmpeg
    import yt_dlp.utils
    from yt_dlp.utils import _utils
    if getattr(ffmpeg.Popen, '_kitty_bounded', False):
        return
    original = ffmpeg.Popen
    class BoundedPopen(original):
        _kitty_bounded = True
        @classmethod
        def run(cls, command, *args, **kwargs):
            executable = Path(str(command[0])).name.lower()
            kwargs.setdefault('timeout', FFPROBE_TIMEOUT if 'probe' in executable else FFMPEG_TIMEOUT)
            try:
                return super().run(command, *args, **kwargs)
            except subprocess.TimeoutExpired:
                raise MetadataError('processing_timeout', 'Traitement FFmpeg trop long') from None
    # Scope the adapter to the postprocessor module; downloader Popen is unchanged.
    ffmpeg.Popen = BoundedPopen
    class VersionPopen(original):
        @classmethod
        def run(cls, command, *args, **kwargs):
            name = Path(str(command[0])).name.lower()
            if name in ('ffmpeg', 'ffmpeg.exe', 'ffprobe', 'ffprobe.exe', 'avconv', 'avprobe'):
                kwargs.setdefault('timeout', FFPROBE_TIMEOUT)
            return super().run(command, *args, **kwargs)
    # Version detection uses the utility module, outside the FFmpeg class.
    _utils.Popen = VersionPopen
    yt_dlp.utils.Popen = VersionPopen


def _child(request, result):
    from platform_support import configure_worker_job
    from hls import QuietHlsLogger, extract_job, error_info
    from errors import classify_backend_error, redact_error_detail
    payload = json.loads(Path(request).read_text(encoding='utf-8'))
    job, options = payload['job'], payload['options']
    options['logger'] = QuietHlsLogger()
    options['socket_timeout'] = min(float(options.get('socket_timeout') or 10), 10)
    source_kind = (job.get('media_source') or {}).get('type')
    def on_fallback(source):
        nonlocal source_kind
        source_kind = source['type']
    try:
        configure_worker_job()
        install_ffmpeg_timeouts()
        with youtube_dl(options) as ydl:
            info, source = extract_job(ydl, job, on_fallback=on_fallback)
            # Materialize lazy playlist metadata within the supervised budget.
            info = ydl.sanitize_info(info, remove_private_keys=False)
        answer = {'ok': True, 'info': info, 'source': source}
    except Exception as exc:
        error = error_info(exc, source_kind) if source_kind else classify_backend_error(exc, code_hint=getattr(exc, 'code', None))
        answer = {'ok': False, 'error': {'code': error['code'], 'message': error['message'],
                                       'detail': redact_error_detail(error.get('detail') or str(exc))}}
    Path(result).write_text(json.dumps(answer), encoding='utf-8')
    os.chmod(result, 0o600)


if __name__ == '__main__':
    _child(*sys.argv[1:])
