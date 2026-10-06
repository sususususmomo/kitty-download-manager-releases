#!/usr/bin/env python3
"""Optional public metadata smoke check, isolated from the user's queue.

The parent enforces a wall-clock budget over the entire yt-dlp extraction,
including retries, slow responses and JavaScript children. No media is saved.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def stop_probe(process):
    # This process/group was created by this QA runner, never by Kitty's queue.
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait(timeout=3)


def bounded_command(command, seconds=60, payload=None):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Le timeout doit être positif et fini.')
    started = time.monotonic()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        options = {'start_new_session': True} if os.name == 'posix' else {}
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output,
                              stderr=errors, **options) as process:
            try:
                process.communicate(json.dumps(payload or {}).encode(), timeout=seconds)
            except subprocess.TimeoutExpired:
                stop_probe(process)
                return {'ok': False, 'status': 'timeout', 'timeout_seconds': seconds,
                        'elapsed_seconds': round(time.monotonic() - started, 2)}
            except BaseException:
                stop_probe(process)
                raise
            output.seek(0)
            try:
                report = json.loads(output.read(65536))
                if not isinstance(report, dict) or not isinstance(report.get('ok'), bool):
                    raise ValueError('Invalid report')
            except (ValueError, UnicodeDecodeError):
                report = {'ok': False, 'status': 'invalid_result',
                          'returncode': process.returncode}
            if process.returncode and report.get('ok'):
                report = {'ok': False, 'status': 'process_error',
                          'returncode': process.returncode}
            report['elapsed_seconds'] = round(time.monotonic() - started, 2)
            return report


def check_metadata(url, seconds=60, *, system_ca=False):
    return bounded_command([sys.executable, str(Path(__file__).resolve()), '--child'],
                           seconds, {'url': url, 'system_ca': bool(system_ca)})


def child():
    sys.path.insert(0, str(ROOT / 'native-host'))
    import hls
    import worker
    import yt_dlp
    from errors import classify_backend_error
    payload = json.load(sys.stdin)
    url = hls.http_url(payload.get('url'))
    try:
        # Existing page extraction and quality options; only the QA network
        # retries are shortened. The API does not load user's CLI config files.
        with tempfile.TemporaryDirectory(prefix='kitty-public-metadata-') as temp:
            options = worker.build_opts('best', lambda _: None, Path(temp))
            options.update(writethumbnail=False, skip_download=True, socket_timeout=8,
                           retries=0, extractor_retries=0, cachedir=False,
                           logger=hls.QuietHlsLogger())
            if payload.get('system_ca'):
                # Some CI proxies have a CA installed in the system store,
                # rather than certifi. TLS verification remains enabled.
                options['compat_opts'] = {'no-certifi'}
            with yt_dlp.YoutubeDL(options) as ydl:
                info, source = hls.extract_job(ydl, {'url': url})
            worker.validate_extracted_info(info, 'best')
            report = {'ok': True, 'status': 'ready', 'title': info.get('title'),
                      'extractor': info.get('extractor_key'),
                      'format_count': len(info.get('formats') or []),
                      'hls_fallback_used': bool(source), 'downloaded_media': False,
                      'system_ca': bool(payload.get('system_ca')),
                      'yt_dlp_version': yt_dlp.version.__version__}
    except Exception as error:
        text = str(error).lower()
        category = ('tls_certificate' if 'certificate_verify_failed' in text
                    or 'certificate verify failed' in text else
                    classify_backend_error(error)['code'])
        # No signed URLs, response bodies or headers in the persisted report.
        report = {'ok': False, 'status': 'error', 'error_code': category,
                  'downloaded_media': False}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('url', nargs='?', default='https://www.youtube.com/watch?v=aqz-KE-bpKQ')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--system-ca', action='store_true',
                        help='Use trusted system certificates for this QA probe only; TLS remains verified.')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.child:
        return child()
    report = check_metadata(args.url, args.timeout, system_ca=args.system_ca)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0 if report['ok'] else 124 if report['status'] == 'timeout' else 1


if __name__ == '__main__':
    raise SystemExit(main())
