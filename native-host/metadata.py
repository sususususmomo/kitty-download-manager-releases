#!/usr/bin/env python3
import os
import shutil
import signal
import sys
import time
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent
if str(NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(NATIVE_DIR))

from app_paths import cache_dir, config_dir
from platform_support import WINDOWS, configure_worker_job, metadata_deadline
from errors import classify_backend_error
from runtime_storage import append_log
from queue_store import STATE_VERSION, QueueStateError, mutate_state, update_job

CACHE_DIR = cache_dir()
QUEUE_FILE = CACHE_DIR / "queue.json"
LOCK_FILE = CACHE_DIR / "queue.lock"
CONFIG_DIR = config_dir()
YOUTUBE_COOKIE_FILE = CONFIG_DIR / "youtube-auth" / "cookies.txt"
AUTH_JOB_DIR = CACHE_DIR / "auth-jobs"

def log(message):
    append_log(message, prefix="META")

def mutate_job(job_id, **kwargs):
    try:
        return mutate_state(QUEUE_FILE, LOCK_FILE,
                            lambda data: update_job(data, job_id, kwargs))
    except QueueStateError:
        return False


def _prepare_cookie_copy(job_id, use_auth):
    if not use_auth or YOUTUBE_COOKIE_FILE.is_symlink() or not YOUTUBE_COOKIE_FILE.is_file():
        return None

    AUTH_JOB_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(AUTH_JOB_DIR, 0o700)
    except Exception:
        pass

    target = AUTH_JOB_DIR / f"{job_id}.metadata.cookies.txt"
    target.unlink(missing_ok=True)
    with open(YOUTUBE_COOKIE_FILE, "rb") as src, open(target, "xb") as dst:
        os.chmod(target, 0o600)
        shutil.copyfileobj(src, dst, length=1024 * 64)
    return target


def _cleanup_cookie_copy(path):
    if not path:
        return
    try:
        path = Path(path)
        if AUTH_JOB_DIR.resolve(strict=False) in path.resolve(strict=False).parents:
            path.unlink(missing_ok=True)
    except Exception:
        pass


class MetadataTimeout(Exception):
    pass


def _metadata_alarm_handler(signum, frame):
    raise MetadataTimeout("Le probe métadonnées a dépassé 30 secondes.")


def main():
    if len(sys.argv) not in (3, 4):
        return 2

    job_id, url = sys.argv[1], sys.argv[2]
    use_auth = len(sys.argv) == 4 and sys.argv[3] == "1"
    cookiefile = _prepare_cookie_copy(job_id, use_auth)
    deadline = None

    try:
        configure_worker_job()
        if WINDOWS:
            signal.signal(signal.SIGINT, _metadata_alarm_handler)
            deadline = metadata_deadline(30)
        import yt_dlp

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "ignore_no_formats_error": True,
            "socket_timeout": 10,
            "retries": 1,
            "extractor_retries": 1,
            "fragment_retries": 1,
        }
        if cookiefile:
            opts["cookiefile"] = str(cookiefile)

        mutate_job(
            job_id,
            metadata_status="fetching",
            metadata_error=None,
            metadata_pid=os.getpid(),
            metadata_started_at=time.time(),
        )
        log(f"début id={job_id}")

        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _metadata_alarm_handler)
            signal.alarm(30)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        title = ""
        if isinstance(info, dict):
            title = info.get("title") or ""

        if title:
            mutate_job(job_id, title=title, metadata_status="ready", metadata_error=None, metadata_pid=None)
            log(f"title={title!r}")
        else:
            mutate_job(job_id, metadata_status="unavailable", metadata_error="Titre non fourni par l’extracteur.", metadata_pid=None)
            log("aucun titre")
        return 0

    except Exception as exc:
        raw_error = str(exc).strip() or exc.__class__.__name__
        error_info = classify_backend_error(
            raw_error,
            context="metadata",
            youtube_auth=use_auth,
        )
        mutate_job(
            job_id,
            metadata_status="error",
            metadata_error=error_info["message"],
            metadata_error_code=error_info["code"],
            metadata_error_hint=error_info["hint"],
            metadata_error_detail=error_info["detail"],
            metadata_pid=None,
        )
        log(
            f"erreur id={job_id} code={error_info['code']} "
            f"detail={raw_error!r}"
        )
        return 1

    finally:
        if deadline is not None:
            deadline.set()
        if hasattr(signal, "SIGALRM"):
            try:
                signal.alarm(0)
            except Exception:
                pass
        _cleanup_cookie_copy(cookiefile)

if __name__ == "__main__":
    raise SystemExit(main())
