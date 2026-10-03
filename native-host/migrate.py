#!/usr/bin/env python3
"""
One-time V8 migration from the pre-release firefox-ytdlp layout to
Kitty Download Manager.

The migration is deliberately conservative:
- PREPARE only copies state/config into the new layout; legacy data remains.
- FINALIZE runs only after the V8 backend has been installed and self-tested.
- a live legacy download aborts the migration;
- symlinks are never followed for sensitive migration inputs;
- the old default download directory is renamed only during FINALIZE and only
  when the target does not already exist;
- legacy backend/config/cache and the legacy Native Messaging manifest are
  removed only after the new state validates.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app_paths import (
    APP_NAME,
    NATIVE_HOST_NAME,
    cache_dir,
    config_dir,
    default_output_dir,
    install_dir,
    legacy_cache_dir,
    legacy_config_dir,
    legacy_default_output_dir,
    legacy_install_dir,
    legacy_native_manifest_path,
    migration_file,
    native_manifest_path,
)

STATE_VERSION = 2
MIGRATION_VERSION = 8


class MigrationError(RuntimeError):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _safe_json(path: Path):
    try:
        if path.is_symlink():
            raise MigrationError(f"Refus du lien symbolique: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except FileNotFoundError:
        return None


def _write_json_atomic(path: Path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _copy_file_atomic(src: Path, dst: Path, mode=None):
    if src.is_symlink():
        raise MigrationError(f"Refus du lien symbolique: {src}")
    if not src.is_file():
        return False
    if dst.exists() and dst.is_symlink():
        raise MigrationError(f"Refus du lien symbolique destination: {dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".migrate-{os.getpid()}")
    try:
        shutil.copy2(src, tmp, follow_symlinks=False)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    return True


def _copy_tree_no_links(src: Path, dst: Path, *, file_mode=None):
    if not src.exists():
        return 0
    if src.is_symlink() or not src.is_dir():
        raise MigrationError(f"Dossier legacy non sûr: {src}")

    copied = 0
    for root, dirs, files in os.walk(src, topdown=True, followlinks=False):
        root_path = Path(root)

        safe_dirs = []
        for name in dirs:
            child = root_path / name
            if child.is_symlink():
                continue
            safe_dirs.append(name)
        dirs[:] = safe_dirs

        rel = root_path.relative_to(src)
        target_root = dst / rel
        target_root.mkdir(parents=True, exist_ok=True)

        for name in files:
            child = root_path / name
            if child.is_symlink():
                continue
            target = target_root / name
            if _copy_file_atomic(child, target, mode=file_mode):
                copied += 1
    return copied


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _pid_cmdline(pid):
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        return [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
    except Exception:
        return []


def _legacy_worker_live():
    queue = legacy_cache_dir() / "queue.json"
    data = _safe_json(queue)
    if not isinstance(data, dict):
        return False, None

    active = data.get("active")
    if not isinstance(active, dict):
        return False, None

    pid = active.get("worker_pid")
    if not pid or not _pid_alive(pid):
        return False, None

    cmdline = _pid_cmdline(pid)
    legacy_worker = str((legacy_install_dir() / "worker.py").resolve(strict=False))

    # On Linux we require the actual legacy worker path to avoid PID reuse.
    if cmdline:
        for arg in cmdline:
            try:
                if str(Path(arg).resolve(strict=False)) == legacy_worker:
                    return True, int(pid)
            except Exception:
                continue
        return False, None

    # Conservative fallback on non-/proc systems.
    return True, int(pid)


def _pending_auth_process_live():
    pending = legacy_cache_dir() / "youtube-auth-pending.json"
    data = _safe_json(pending)
    if not isinstance(data, dict):
        return False, None

    profile = data.get("profile_dir") or data.get("profile")
    if not profile:
        return False, None
    needle = str(profile)

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return False, None

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except Exception:
            continue
        if needle.encode("utf-8", "ignore") in raw:
            return True, int(entry.name)
    return False, None


def _validate_queue(path: Path):
    if not path.exists():
        return
    data = _safe_json(path)
    if not isinstance(data, dict):
        raise MigrationError("queue.json migré n'est pas un objet JSON.")
    version = data.get("state_version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        raise MigrationError("state_version de queue.json invalide.")
    if version > STATE_VERSION:
        raise MigrationError(
            f"queue.json v{version} est plus récent que le schéma supporté v{STATE_VERSION}."
        )
    if not isinstance(data.get("queue", []), list):
        raise MigrationError("queue.json: queue invalide.")
    if not isinstance(data.get("history", []), list):
        raise MigrationError("queue.json: history invalide.")


def _validate_settings(path: Path):
    if not path.exists():
        return {}
    data = _safe_json(path)
    if not isinstance(data, dict):
        raise MigrationError("settings.json migré n'est pas un objet JSON.")
    return data


def _validate_cookie(path: Path):
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file():
        raise MigrationError("Snapshot YouTube migré non sûr.")
    if path.stat().st_size <= 0:
        raise MigrationError("Snapshot YouTube migré vide.")
    os.chmod(path, 0o600)


def _read_marker():
    path = migration_file()
    data = _safe_json(path)
    return data if isinstance(data, dict) else {}


def _write_marker(**updates):
    marker = _read_marker()
    marker.update({
        "migration_version": MIGRATION_VERSION,
        "app": APP_NAME,
        **updates,
    })
    _write_json_atomic(migration_file(), marker, mode=0o600)
    return marker


def _legacy_present():
    return any(
        p.exists()
        for p in (
            legacy_install_dir(),
            legacy_config_dir(),
            legacy_cache_dir(),
            legacy_native_manifest_path(),
            legacy_default_output_dir(),
        )
    )


def prepare():
    existing = _read_marker()
    if existing.get("status") == "completed":
        # Reinstall/update of V8+: never erase the historical migration result.
        return existing

    live, pid = _legacy_worker_live()
    if live:
        raise MigrationError(
            f"Un téléchargement V7 est encore actif (PID {pid}). "
            "Attends sa fin ou annule-le avant d'installer V8."
        )

    auth_live, auth_pid = _pending_auth_process_live()
    if auth_live:
        raise MigrationError(
            f"La fenêtre Firefox de session YouTube V7 est encore ouverte (PID {auth_pid}). "
            "Ferme-la puis rouvre les réglages V7 avant de relancer l'installation."
        )

    new_config = config_dir()
    new_cache = cache_dir()
    new_config.mkdir(parents=True, exist_ok=True)
    new_cache.mkdir(parents=True, exist_ok=True)
    os.chmod(new_config, 0o700)
    os.chmod(new_cache, 0o700)

    legacy_found = _legacy_present()
    copied = []

    old_config = legacy_config_dir()
    if old_config.is_dir() and not old_config.is_symlink():
        settings_src = old_config / "settings.json"
        if _copy_file_atomic(settings_src, new_config / "settings.json", mode=0o600):
            copied.append("settings")

        auth_src = old_config / "youtube-auth"
        if auth_src.is_dir() and not auth_src.is_symlink():
            count = _copy_tree_no_links(auth_src, new_config / "youtube-auth")
            cookie = new_config / "youtube-auth" / "cookies.txt"
            if cookie.exists():
                os.chmod(cookie, 0o600)
            meta = new_config / "youtube-auth" / "metadata.json"
            if meta.exists():
                os.chmod(meta, 0o600)
            if count:
                copied.append("youtube_auth")

    old_cache = legacy_cache_dir()
    if old_cache.is_dir() and not old_cache.is_symlink():
        for filename, label in (
            ("queue.json", "queue_history"),
            ("worker.log", "worker_log"),
        ):
            if _copy_file_atomic(old_cache / filename, new_cache / filename, mode=0o600):
                copied.append(label)

        backups_src = old_cache / "state-backups"
        if backups_src.is_dir() and not backups_src.is_symlink():
            count = _copy_tree_no_links(backups_src, new_cache / "state-backups", file_mode=0o600)
            if count:
                copied.append("state_backups")

    _validate_settings(new_config / "settings.json")
    _validate_queue(new_cache / "queue.json")
    _validate_cookie(new_config / "youtube-auth" / "cookies.txt")

    stale_pending_discarded = (legacy_cache_dir() / "youtube-auth-pending.json").exists()

    marker = _write_marker(
        status="prepared",
        prepared_at=_now(),
        legacy_found=legacy_found,
        copied=sorted(set(copied)),
        stale_pending_discarded=bool(stale_pending_discarded),
        legacy_removed=False,
        output_migration="pending",
    )
    return marker


def _rewrite_prefix(value: str, old_prefix: Path, new_prefix: Path):
    if not isinstance(value, str):
        return value
    old = str(old_prefix)
    new = str(new_prefix)
    if value == old:
        return new
    if value.startswith(old + os.sep):
        return new + value[len(old):]
    return value


def _rewrite_paths_recursive(value, old_prefix: Path, new_prefix: Path):
    if isinstance(value, dict):
        return {
            key: _rewrite_paths_recursive(item, old_prefix, new_prefix)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_paths_recursive(item, old_prefix, new_prefix) for item in value]
    if isinstance(value, str):
        return _rewrite_prefix(value, old_prefix, new_prefix)
    return value


def _migrate_default_output():
    old_output = legacy_default_output_dir()
    new_output = default_output_dir()
    settings_path = config_dir() / "settings.json"
    settings = _validate_settings(settings_path)

    configured = settings.get("output_dir")
    configured_path = None
    if isinstance(configured, str) and configured.strip():
        configured_path = Path(configured).expanduser()

    uses_legacy_default = (
        configured_path is None
        or configured_path == old_output
    )

    if not uses_legacy_default:
        # Custom destination is user data, not an app identity path.
        # Remove only the old default folder when it is empty; never touch
        # media that may still live there.
        try:
            if old_output.is_dir() and not old_output.is_symlink() and not any(old_output.iterdir()):
                old_output.rmdir()
        except Exception:
            pass
        new_output.mkdir(parents=True, exist_ok=True)
        return "custom_destination_preserved"

    moved = False
    conflict = False

    if old_output.exists():
        if old_output.is_symlink() or not old_output.is_dir():
            raise MigrationError(f"Ancien dossier de téléchargement non sûr: {old_output}")

        if not new_output.exists():
            try:
                os.replace(old_output, new_output)
                moved = True
            except OSError:
                # Never copy a potentially huge media library behind the user's
                # back. Preserve the legacy folder as a custom destination.
                conflict = True
        else:
            try:
                old_nonempty = any(old_output.iterdir())
            except Exception:
                old_nonempty = True

            if old_nonempty:
                conflict = True
            else:
                old_output.rmdir()

    if conflict:
        settings["output_dir"] = str(old_output)
        _write_json_atomic(settings_path, settings, mode=0o600)
        return "legacy_destination_preserved_due_to_conflict"

    new_output.mkdir(parents=True, exist_ok=True)
    settings["output_dir"] = str(new_output)
    _write_json_atomic(settings_path, settings, mode=0o600)

    queue_path = cache_dir() / "queue.json"
    if queue_path.exists():
        queue = _safe_json(queue_path)
        if isinstance(queue, dict):
            queue = _rewrite_paths_recursive(queue, old_output, new_output)
            _write_json_atomic(queue_path, queue, mode=0o600)
            _validate_queue(queue_path)

    return "legacy_default_renamed" if moved else "new_default_selected"


def _safe_remove_tree(path: Path, allowed_parent: Path):
    if not path.exists():
        return False
    if path.is_symlink():
        raise MigrationError(f"Refus de supprimer un lien symbolique: {path}")

    resolved = path.resolve(strict=False)
    parent = allowed_parent.resolve(strict=False)
    if resolved.parent != parent:
        raise MigrationError(f"Chemin legacy inattendu, suppression refusée: {path}")

    shutil.rmtree(path)
    return True


def finalize():
    marker = _read_marker()
    if marker.get("status") == "completed":
        return marker

    # Validate installed V8 backend before touching legacy data.
    required = [
        install_dir() / "host.py",
        install_dir() / "worker.py",
        install_dir() / "metadata.py",
        install_dir() / "errors.py",
        install_dir() / "app_paths.py",
        install_dir() / "migrate.py",
        native_manifest_path(),
    ]
    missing = [str(p) for p in required if not p.is_file() or p.is_symlink()]
    if missing:
        raise MigrationError(f"Installation V8 incomplète: {missing}")

    _validate_settings(config_dir() / "settings.json")
    _validate_queue(cache_dir() / "queue.json")
    _validate_cookie(config_dir() / "youtube-auth" / "cookies.txt")

    output_migration = _migrate_default_output()

    # Validate again after path rewrite/move.
    _validate_settings(config_dir() / "settings.json")
    _validate_queue(cache_dir() / "queue.json")
    _validate_cookie(config_dir() / "youtube-auth" / "cookies.txt")

    removed = []

    legacy_manifest = legacy_native_manifest_path()
    if legacy_manifest.exists():
        if legacy_manifest.is_symlink():
            raise MigrationError(f"Manifest legacy symlink refusé: {legacy_manifest}")
        legacy_manifest.unlink()
        removed.append("native_manifest")

    if _safe_remove_tree(legacy_install_dir(), Path.home() / ".local" / "lib"):
        removed.append("install")
    if _safe_remove_tree(legacy_config_dir(), Path.home() / ".config"):
        removed.append("config")
    if _safe_remove_tree(legacy_cache_dir(), Path.home() / ".cache"):
        removed.append("cache")

    marker = _write_marker(
        status="completed",
        completed_at=_now(),
        legacy_removed=True,
        removed=removed,
        output_migration=output_migration,
    )
    return marker


def status():
    marker = _read_marker()
    if not marker:
        return {
            "migration_version": MIGRATION_VERSION,
            "app": APP_NAME,
            "status": "not_started",
            "legacy_found": _legacy_present(),
        }
    return marker


def main(argv):
    action = argv[1] if len(argv) > 1 else "status"
    try:
        if action == "prepare":
            result = prepare()
        elif action == "finalize":
            result = finalize()
        elif action == "status":
            result = status()
        else:
            raise MigrationError(f"Action migration inconnue: {action}")

        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "type": exc.__class__.__name__,
        }, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
