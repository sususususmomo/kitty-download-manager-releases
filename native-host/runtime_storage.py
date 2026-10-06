#!/usr/bin/env python3
"""Runtime storage helpers: bounded logs and safe size accounting.

This module deliberately knows nothing about download destinations.  Every
operation is confined to Kitty's private cache directory.
"""
from __future__ import annotations
from platform_support import replace_file

from platform_support import acquire_file_lock, release_file_lock
import os
import time
from pathlib import Path

from app_paths import cache_dir

CACHE_DIR = cache_dir()
LOG_FILE = CACHE_DIR / "worker.log"
LOG_LOCK_FILE = CACHE_DIR / "worker.log.lock"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_ARCHIVE_COUNT = 4


def _cache_root_is_safe() -> bool:
    try:
        return not CACHE_DIR.is_symlink()
    except Exception:
        return False


def safe_file_size(path: Path) -> int:
    """Return a regular file's size without following symlinks."""
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            return 0
        return int(path.stat().st_size)
    except Exception:
        return 0


def safe_tree_stats(path: Path) -> dict:
    """Count bytes/files under *path* without following symlinks."""
    root = Path(path)
    result = {"bytes": 0, "files": 0}
    try:
        if root.is_symlink():
            return result
        if root.is_file():
            return {"bytes": safe_file_size(root), "files": 1}
        if not root.is_dir():
            return result
    except Exception:
        return result

    try:
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            base_path = Path(base)
            safe_dirs = []
            for name in dirs:
                candidate = base_path / name
                try:
                    if not candidate.is_symlink():
                        safe_dirs.append(name)
                except Exception:
                    pass
            dirs[:] = safe_dirs

            for name in files:
                candidate = base_path / name
                size = safe_file_size(candidate)
                if size or (candidate.exists() and not candidate.is_symlink()):
                    result["files"] += 1
                    result["bytes"] += size
    except Exception:
        pass
    return result


def rotated_log_paths() -> list[Path]:
    return [LOG_FILE.with_name(f"{LOG_FILE.name}.{index}") for index in range(1, LOG_ARCHIVE_COUNT + 1)]


def all_log_paths() -> list[Path]:
    return [LOG_FILE, *rotated_log_paths()]


def log_stats() -> dict:
    current = safe_file_size(LOG_FILE)
    archives = []
    for path in rotated_log_paths():
        size = safe_file_size(path)
        if size or (path.exists() and not path.is_symlink()):
            archives.append({"name": path.name, "bytes": size})
    return {
        "current_bytes": current,
        "archive_bytes": sum(item["bytes"] for item in archives),
        "total_bytes": current + sum(item["bytes"] for item in archives),
        "archive_count": len(archives),
        "max_file_bytes": LOG_MAX_BYTES,
        "max_archives": LOG_ARCHIVE_COUNT,
    }


def _rotate_locked(incoming_bytes: int = 0) -> bool:
    try:
        if LOG_FILE.is_symlink():
            return False
        current = safe_file_size(LOG_FILE)
        if current <= 0 or current + max(0, int(incoming_bytes)) <= LOG_MAX_BYTES:
            return False

        oldest = LOG_FILE.with_name(f"{LOG_FILE.name}.{LOG_ARCHIVE_COUNT}")
        try:
            if oldest.exists() or oldest.is_symlink():
                oldest.unlink()
        except Exception:
            pass

        for index in range(LOG_ARCHIVE_COUNT - 1, 0, -1):
            src = LOG_FILE.with_name(f"{LOG_FILE.name}.{index}")
            dst = LOG_FILE.with_name(f"{LOG_FILE.name}.{index + 1}")
            try:
                if src.is_symlink():
                    src.unlink()
                elif src.is_file():
                    replace_file(src, dst)
            except Exception:
                pass

        if LOG_FILE.is_file() and not LOG_FILE.is_symlink():
            replace_file(LOG_FILE, LOG_FILE.with_name(f"{LOG_FILE.name}.1"))
        return True
    except Exception:
        return False


def append_log(message, *, prefix: str = "") -> None:
    """Append one line while keeping worker.log bounded and race-safe."""
    try:
        if not _cache_root_is_safe():
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(CACHE_DIR, 0o700)
        except Exception:
            pass

        body = f"{prefix} {message}".strip() if prefix else str(message)
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {body}\n"
        encoded_len = len(line.encode("utf-8", "replace"))

        with LOG_LOCK_FILE.open("a+", encoding="utf-8") as lock:
            acquire_file_lock(lock)
            try:
                _rotate_locked(encoded_len)
                if LOG_FILE.is_symlink():
                    return
                with LOG_FILE.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                try:
                    os.chmod(LOG_FILE, 0o600)
                except Exception:
                    pass
            finally:
                release_file_lock(lock)
    except Exception:
        # Logging must never break a download.
        pass


def purge_rotated_logs() -> dict:
    """Delete archived logs only. The current worker.log is always retained."""
    removed = 0
    freed = 0
    try:
        if not _cache_root_is_safe():
            return {"removed": 0, "freed_bytes": 0}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_LOCK_FILE.open("a+", encoding="utf-8") as lock:
            acquire_file_lock(lock)
            try:
                for path in rotated_log_paths():
                    try:
                        if path.is_symlink():
                            path.unlink()
                            removed += 1
                            continue
                        if not path.is_file():
                            continue
                        size = safe_file_size(path)
                        path.unlink()
                        removed += 1
                        freed += size
                    except Exception:
                        pass
            finally:
                release_file_lock(lock)
    except Exception:
        pass
    return {"removed": removed, "freed_bytes": freed}
