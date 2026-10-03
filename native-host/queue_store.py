"""Shared queue persistence for host, worker, metadata and maintenance.

Callers pass paths explicitly: this module has no cached HOME or app state.
Normal reads and no-op transactions never replace queue.json. Migration and
corruption recovery are explicit host-only exceptions to read-only access.
"""
from __future__ import annotations

import copy
from platform_support import acquire_file_lock, release_file_lock
import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

STATE_VERSION = 2
HISTORY_LIMIT = 50
MAX_STATE_BACKUPS = 8


class QueueStateError(RuntimeError):
    pass


class FutureStateVersion(QueueStateError):
    pass


def default_state():
    return {"state_version": STATE_VERSION, "active": None, "queue": [],
            "history": [], "queue_paused": False}


def normalize_job(job, queued=False):
    if not isinstance(job, dict):
        return None
    clean = dict(job)
    if queued:
        if clean.get("status") == "paused_queue":
            clean["paused"] = True
        clean["status"] = "queued"
    for key in ("control_request", "paused_from_status", "pause_requested"):
        clean.pop(key, None)
    return clean


def migrate_state(data):
    if not isinstance(data, dict):
        raise QueueStateError("Le fichier d'état ne contient pas un objet JSON.")
    version = data.get("state_version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        version = 0
    if version > STATE_VERSION:
        raise FutureStateVersion(f"future_state_version:{version}")
    state = dict(data)
    queue = state.get("queue")
    history = state.get("history")
    state["active"] = normalize_job(state.get("active"))
    state["queue"] = [normalize_job(job, queued=True) for job in
                      (queue if isinstance(queue, list) else []) if isinstance(job, dict)]
    state["history"] = [dict(job) for job in
                        (history if isinstance(history, list) else [])
                        if isinstance(job, dict)][:HISTORY_LIMIT]
    state["queue_paused"] = bool(state.get("queue_paused", False))
    state["state_version"] = STATE_VERSION
    return state, state != data, version


@contextmanager
def queue_lock(lock_file):
    lock_file = Path(lock_file)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a+", encoding="utf-8") as lock:
        acquire_file_lock(lock)
        try:
            yield
        finally:
            release_file_lock(lock)


def atomic_json(path, data):
    """Publish complete UTF-8 JSON; unique temp file, private mode, cleanup.

    The original remains intact if serialization/write/replace fails, including
    a BaseException raised by a worker signal during a transaction.
    """
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def trim_backups(directory, limit=MAX_STATE_BACKUPS):
    backups = sorted((p for p in Path(directory).glob("queue-*.json")
                      if p.is_file() and not p.is_symlink()),
                     key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for old in backups[limit:]:
        old.unlink(missing_ok=True)


def backup_state_file(queue_file, directory, reason, version=None, move=False):
    path = Path(queue_file)
    if not path.exists():
        return None
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    version_part = f"-v{version}" if version is not None else ""
    target = directory / (f"queue-{reason}{version_part}-"
                          f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}.json")
    if move:
        os.replace(path, target)
    else:
        shutil.copy2(path, target)
    os.chmod(target, 0o600)
    # Failure to trim old backups must not invalidate a successful backup.
    try:
        trim_backups(directory)
    except OSError:
        pass
    return target


def load_state_locked(queue_file, *, recover=False, backup_dir=None):
    """Load under an already-held lock. Return state and a repair flag.

    Never treats read/permission errors as corruption. Future schemas always
    block access; the original file is never moved, reset or downgraded.
    """
    path = Path(queue_file)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default_state(), False
    reason = None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        if not recover:
            raise QueueStateError(f"État queue.json illisible: {exc}") from exc
        reason = "corrupt"
    else:
        try:
            state, changed, version = migrate_state(data)
        except FutureStateVersion:
            raise
        except QueueStateError:
            if not recover:
                raise
            reason = "invalid"
        else:
            if changed and recover:
                backup_state_file(path, backup_dir, "pre-migration", version)
            return state, changed
    # Fail closed if the original cannot be backed up. Do not erase evidence.
    backup_state_file(path, backup_dir, reason)
    return default_state(), True


def read_state(queue_file, lock_file, *, recover=False, backup_dir=None):
    with queue_lock(lock_file):
        state, repaired = load_state_locked(queue_file, recover=recover, backup_dir=backup_dir)
        if repaired and recover:
            atomic_json(queue_file, state)
        return copy.deepcopy(state)


def mutate_state(queue_file, lock_file, fn, *, recover=False, backup_dir=None):
    with queue_lock(lock_file):
        state, repaired = load_state_locked(queue_file, recover=recover, backup_dir=backup_dir)
        before = copy.deepcopy(state)
        result = fn(state)
        # Enforce the same schema/history limit on every writer, before publish.
        state, _, _ = migrate_state(state)
        if repaired or state != before:
            atomic_json(queue_file, state)
        return result


def claim_next_job(data):
    """Reserve one runnable job while holding the queue transaction lock."""
    if data.get("active") or data.get("queue_paused"):
        return None
    queue = normalize_queue_priority(data["queue"])
    data["queue"] = queue
    index = next((i for i, job in enumerate(queue) if not job.get("paused")), None)
    if index is None:
        return None
    job = queue.pop(index)
    now = time.time()
    job.update(status="starting", worker_pid=None, speed=None, eta=None,
               error=None, started_at=job.get("started_at") or now, updated_at=now)
    for key in ("error_code", "error_hint", "error_detail", "error_retryable"):
        job.pop(key, None)
    data["active"] = job
    return copy.deepcopy(job)


def update_job(data, job_id, changes, *, active_only=False):
    """A late writer may update only the job it owns, never its successor."""
    active = data.get("active")
    candidates = ([active] if isinstance(active, dict) else [])
    if not active_only:
        candidates += data["queue"]
    for job in candidates:
        if job.get("id") == job_id:
            job.update(changes)
            job["updated_at"] = time.time()
            return True
    return False


def release_failed_start(data, job_id):
    """A failed spawn returns its reservation to the queue, in a paused state."""
    job = data.get("active")
    if not isinstance(job, dict) or job.get("id") != job_id:
        return False
    if job.get("status") != "starting" or job.get("worker_pid"):
        return False
    job.update(status="queued", worker_pid=None, updated_at=time.time())
    data["active"] = None
    queue = normalize_queue_priority(data["queue"])
    insert_at_lane_head(queue, job)
    data["queue"] = queue
    data["queue_paused"] = True
    return True


def is_playlist_job(job):
    return (
        isinstance(job, dict)
        and bool(job.get("playlist_id") or job.get("collection_url"))
    )


def normalize_queue_priority(queue):
    """
    Partition stable :
      - téléchargements manuels/interactifs d'abord (FIFO)
      - jobs de playlist ensuite (FIFO)
    """
    if not isinstance(queue, list):
        return []

    interactive = []
    playlist = []

    for job in queue:
        if not isinstance(job, dict):
            continue
        if is_playlist_job(job):
            playlist.append(job)
        else:
            interactive.append(job)

    return interactive + playlist


def insert_interactive_job(queue, job):
    normalized = normalize_queue_priority(queue)
    first_playlist = next(
        (i for i, queued in enumerate(normalized) if is_playlist_job(queued)),
        len(normalized),
    )
    normalized.insert(first_playlist, job)
    return normalized


def append_playlist_job(queue, job):
    normalized = normalize_queue_priority(queue)
    normalized.append(job)
    return normalized


def insert_at_lane_head(queue, job):
    """Restore an interrupted/failed-start job before peers in its own lane."""
    queue[:] = normalize_queue_priority(queue)
    if is_playlist_job(job):
        index = next((i for i, queued in enumerate(queue) if is_playlist_job(queued)), len(queue))
    else:
        index = 0
    queue.insert(index, job)
