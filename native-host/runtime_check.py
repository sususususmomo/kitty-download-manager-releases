"""Offline checks of the Python packages actually used by Kitty's downloads."""
from __future__ import annotations
import argparse
import base64
import csv
import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import sys

MODULES = ('ssl', 'yt_dlp', 'yt_dlp.postprocessor', 'yt_dlp.postprocessor.ffmpeg',
           'yt_dlp.postprocessor.embedthumbnail', 'yt_dlp.extractor.youtube',
           'yt_dlp.networking', 'mutagen')


def check_ytdlp_files(packages=None):
    """Check installed Python files against pip's wheel RECORD, without network."""
    return check_distribution_files('yt-dlp', 'yt_dlp', packages, python_only=True)


def check_distribution_files(distribution, package, packages=None, *, python_only=False):
    dist = importlib.metadata.distribution(distribution)
    # Distribution.files filters missing files on some Python versions. Read
    # RECORD directly so a deleted subpackage cannot disappear from the check.
    record = dist.read_text('RECORD') or ''
    entries = [row for row in csv.reader(io.StringIO(record))
               if len(row) == 3 and row[0].startswith(package + '/')
               and (not python_only or row[0].endswith('.py'))]
    if not entries:
        return {'ok': False, 'checked': 0, 'issues': [distribution + ': inventaire des fichiers absent']}
    issues = []
    package_root = Path(dist.locate_file(package)).resolve()
    for entry, recorded_hash, _size in entries:
        path = Path(dist.locate_file(entry)).resolve()
        if not path.is_relative_to(package_root):
            issues.append(f'{entry}: fichier hors du paquet {distribution}')
            continue
        if packages is not None and not path.is_relative_to(Path(packages).resolve()):
            issues.append(f'{entry}: fichier hors des paquets prives')
            continue
        if not path.is_file():
            issues.append(f'{entry}: fichier manquant')
            continue
        if recorded_hash:
            algorithm, expected = recorded_hash.split('=', 1)
            digest = hashlib.new(algorithm, path.read_bytes()).digest()
            value = base64.urlsafe_b64encode(digest).decode().rstrip('=')
            if value != expected:
                issues.append(f'{entry}: empreinte incorrecte')
    return {'ok': not issues, 'checked': len(entries), 'issue_count': len(issues), 'issues': issues[:12]}


def check_psutil_api(module, *, smoke=False):
    functions = ('process_iter', 'Process', 'pid_exists', 'wait_procs', 'NoSuchProcess', 'AccessDenied', 'TimeoutExpired')
    missing = [name for name in functions if not callable(getattr(module, name, None))]
    process = getattr(module, 'Process', None)
    methods = ('is_running', 'status', 'cmdline', 'exe', 'children', 'create_time', 'terminate', 'kill', 'wait')
    missing.extend('Process.' + name for name in methods if not callable(getattr(process, name, None)))
    if missing:
        raise RuntimeError('psutil: API absente : ' + ', '.join(missing))
    if smoke:
        # Exercise the native extension without touching other processes.
        pid = os.getpid()
        if sys.platform.startswith('linux'):
            # Containers can expose a host-mounted /proc while Python runs in
            # a PID namespace. Use the PID visible to psutil's /proc reader.
            try:
                pid = int(Path('/proc/self').resolve().name)
            except (OSError, ValueError):
                pass
        proc = module.Process(pid)
        namespace_mismatch = pid != os.getpid()
        # pid_exists/is_running use OS PID syscalls, whereas other Linux
        # getters read /proc. Those identifiers differ in a host-mounted proc.
        if not namespace_mismatch and (not module.pid_exists(proc.pid) or not proc.is_running()):
            raise RuntimeError('psutil: suivi du processus Python indisponible')
        if not isinstance(proc.cmdline(), list):
            raise RuntimeError('psutil: suivi du processus Python indisponible')
        proc.create_time()
        proc.status()
        proc.exe()
        proc.children(recursive=True)
        module.wait_procs([], timeout=0)
        iterator = iter(module.process_iter(['name', 'cmdline']))
        try:
            try:
                next(iterator, None)
            except module.NoSuchProcess:
                # A different process may exit during enumeration.
                pass
        finally:
            if hasattr(iterator, 'close'):
                iterator.close()
        return {'native_calls': True, 'liveness_checked': not namespace_mismatch,
                'linux_pid_namespace_mismatch': namespace_mismatch}


def check_runtime(packages=None):
    private = Path(packages).resolve() if packages is not None else None
    names = MODULES + (('psutil', 'yt_dlp_ejs') if private is not None or sys.platform in ('win32', 'darwin') else ())
    items, issues = [], []
    for name in names:
        item = {'name': name, 'ok': False, 'path': None}
        try:
            spec = importlib.util.find_spec(name)
            item['path'] = spec.origin if spec else None
            module = importlib.import_module(name)
            if private is not None and name != 'ssl':
                if not getattr(module, '__file__', None) or not Path(module.__file__).resolve().is_relative_to(private):
                    raise RuntimeError(f'{name}: charge hors des paquets prives')
            if name == 'psutil':
                item['process_smoke'] = check_psutil_api(module, smoke=True)
            item['ok'] = True
        except Exception as exc:
            item['error'] = f'{type(exc).__name__}: {exc}'
            issues.append(item['error'])
        items.append(item)
    integrity = None
    process_integrity = None
    try:
        integrity = check_ytdlp_files(private)
        issues.extend(integrity['issues'])
    except Exception as exc:
        issues.append(f'Inventaire yt-dlp: {type(exc).__name__}: {exc}')
    if 'psutil' in names:
        try:
            process_integrity = check_distribution_files('psutil', 'psutil', private)
            issues.extend(process_integrity['issues'])
        except Exception as exc:
            issues.append(f'Inventaire psutil: {type(exc).__name__}: {exc}')
    if not issues:
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.postprocessor import get_postprocessor
            with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True}) as ydl:
                # The same factories used by the real worker, without media I/O.
                for key in ('FFmpegMerger', 'FFmpegMetadata', 'EmbedThumbnail'):
                    if not callable(get_postprocessor(key)):
                        raise RuntimeError(f'Postprocessor indisponible: {key}')
                if not callable(ydl.extract_info):
                    raise RuntimeError('API de telechargement yt-dlp indisponible')
        except Exception as exc:
            issues.append(f'{type(exc).__name__}: {exc}')
    report = {'ok': not issues, 'python': sys.executable, 'modules': items, 'integrity': integrity, 'process_integrity': process_integrity,
              'issues': list(dict.fromkeys(issues))[:20]}
    if issues:
        report['error'] = 'Dependances Python invalides; reinstalle le backend Kitty. ' + '; '.join(report['issues'][:3])
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--packages', type=Path)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    result = check_runtime(args.packages)
    if args.quiet:
        print('Paquets Python verifies.' if result['ok'] else result['error'])
    else:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
