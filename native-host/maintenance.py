#!/usr/bin/env python3
"""Safe updater / uninstaller for Kitty Download Manager."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent
if str(NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(NATIVE_DIR))

from app_paths import (
    APP_NAME,
    APP_SLUG,
    cache_dir,
    config_dir,
    install_dir,
    native_manifest_path,
)
from compatibility import NATIVE_PROTOCOL_VERSION, app_series
from queue_store import mutate_state, queue_lock

CACHE_DIR = cache_dir()
CONFIG_DIR = config_dir()
INSTALL_DIR = install_dir()
QUEUE_FILE = CACHE_DIR / "queue.json"
LOCK_FILE = CACHE_DIR / "queue.lock"
BACKUP_ROOT = CACHE_DIR / "update-backups"
BIN_DIR = Path.home() / ".local" / "bin"
UPDATE_BIN = BIN_DIR / "kitty-update"
UNINSTALL_BIN = BIN_DIR / "kitty-uninstall"

BACKEND_FILES = (
    "host.py",
    "worker.py",
    "metadata.py",
    "errors.py",
    "app_paths.py",
    "migrate.py",
    "compatibility.py",
    "maintenance.py",
    "runtime_storage.py",
    "queue_store.py",
    "platform_support.py",
)


def _read_json(path: Path, default=None):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return default


def _atomic_json(path: Path, data: dict, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _process_alive(pid) -> bool:
    try:
        pid = int(pid)
        if pid <= 1:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _proc_cmdline(pid) -> str:
    try:
        raw = (Path("/proc") / str(int(pid)) / "cmdline").read_bytes()
        return raw.replace(b"\0", b" ").decode("utf-8", "replace")
    except Exception:
        return ""


def _safe_worker_pid(pid, kind: str) -> bool:
    if not _process_alive(pid):
        return False
    cmd = _proc_cmdline(pid)
    if not cmd:
        # Kitty is Linux-first. If /proc cannot verify identity, never risk
        # signalling an unrelated process.
        return False
    needle = "worker.py" if kind == "worker" else "metadata.py"
    return needle in cmd and APP_SLUG in cmd


def _backup_state(reason: str) -> Path | None:
    if not QUEUE_FILE.is_file():
        return None
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = BACKUP_ROOT / f"queue-{reason}-{stamp}-{os.getpid()}.json"
    try:
        with queue_lock(LOCK_FILE):
            shutil.copy2(QUEUE_FILE, target)
            os.chmod(target, 0o600)
        return target
    except Exception:
        return None


def _freeze_queue_and_collect_pids() -> dict:
    result = {"was_paused": False, "worker_pid": None, "metadata_pids": []}

    def freeze(state):
        result["was_paused"] = bool(state.get("queue_paused", False))
        state["queue_paused"] = True

        active = state.get("active")
        if isinstance(active, dict):
            result["worker_pid"] = active.get("worker_pid")

        seen = set()
        for job in list(state.get("queue") or []) + ([active] if isinstance(active, dict) else []):
            if not isinstance(job, dict):
                continue
            pid = job.get("metadata_pid")
            try:
                pid = int(pid)
            except Exception:
                continue
            if pid > 1 and pid not in seen:
                seen.add(pid)
                result["metadata_pids"].append(pid)

    # Strict mode: maintenance must never overwrite corrupt/future queue data.
    mutate_state(QUEUE_FILE, LOCK_FILE, freeze)

    return result


def _signal_and_wait(pid, kind: str, timeout=8.0) -> bool:
    if not pid:
        return True
    if not _process_alive(pid):
        return True
    if not _safe_worker_pid(pid, kind):
        raise RuntimeError(
            f"Refus d’arrêter PID {pid}: identité du processus {kind} non vérifiée."
        )

    os.kill(int(pid), signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.08)
    return not _process_alive(pid)


def prepare_maintenance(reason: str) -> dict:
    _backup_state(reason)
    frozen = _freeze_queue_and_collect_pids()

    worker_pid = frozen.get("worker_pid")
    if worker_pid and not _signal_and_wait(worker_pid, "worker", timeout=10.0):
        raise RuntimeError(
            "Le worker actif ne s’est pas arrêté dans le délai. Mise à jour annulée; file laissée en pause."
        )

    for pid in frozen.get("metadata_pids", []):
        try:
            _signal_and_wait(pid, "metadata", timeout=3.0)
        except RuntimeError:
            # Metadata helpers are non-destructive. Do not block a whole update
            # if a stale PID cannot be verified; host repair restarts probes.
            pass

    return frozen


def _version_from_host(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
        match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        return match.group(1) if match else None
    except Exception:
        return None


def _version_key(value: str | None):
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(p) for p in parts[:4]) if parts else ()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_release_info(source: Path) -> dict:
    source = source.resolve()
    manifest = _read_json(source / "extension" / "manifest.json")
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.json de la release introuvable/invalide.")

    version = str(manifest.get("version") or "").strip()
    if not re.fullmatch(r"[1-9]\d{0,8}\.\d{1,9}", version):
        raise RuntimeError(f"Version Firefox invalide dans la release: {version!r}")

    host_version = _version_from_host(source / "native-host" / "host.py")
    if host_version != version:
        raise RuntimeError(
            f"Release incohérente: frontend {version}, backend {host_version or '?'}."
        )

    compat = _load_module(
        source / "native-host" / "compatibility.py",
        f"kitty_release_compat_{os.getpid()}_{time.time_ns()}",
    )
    backend_protocol = int(getattr(compat, "NATIVE_PROTOCOL_VERSION", -1))

    shared = (source / "extension" / "shared.js").read_text(encoding="utf-8")
    match = re.search(r"const\s+NATIVE_PROTOCOL_VERSION\s*=\s*(\d+)\s*;", shared)
    if not match:
        raise RuntimeError("Protocole frontend absent de shared.js.")
    frontend_protocol = int(match.group(1))
    if frontend_protocol != backend_protocol:
        raise RuntimeError(
            f"Release incohérente: protocole frontend {frontend_protocol} / backend {backend_protocol}."
        )

    if app_series(version) != getattr(compat, "APP_SERIES", None):
        raise RuntimeError("Série frontend/backend incohérente dans la release.")

    for filename in BACKEND_FILES:
        if not (source / "native-host" / filename).is_file():
            raise RuntimeError(f"Fichier backend manquant dans la release: {filename}")

    return {
        "source": source,
        "version": version,
        "protocol": backend_protocol,
    }


def _validate_backend_dir(path: Path, home: Path):
    for filename in BACKEND_FILES:
        file_path = path / filename
        compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-B", "-c", "import host, compatibility, maintenance"],
        cwd=path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Validation backend échouée: {proc.stderr.strip()[:500]}")


def _native_call(host_path: Path, message: dict, timeout=15) -> dict:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    framed = struct.pack("<I", len(payload)) + payload
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-B", str(host_path)],
        input=framed,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0 or len(proc.stdout) < 4:
        raise RuntimeError(
            f"Native Host invalide (code {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace')[:500]}"
        )
    size = struct.unpack("<I", proc.stdout[:4])[0]
    body = proc.stdout[4:4 + size]
    if len(body) != size:
        raise RuntimeError("Réponse Native Messaging tronquée pendant validation.")
    return json.loads(body.decode("utf-8"))


def _write_native_manifest(source: Path, host_path: Path):
    src = source / "native-host" / "manifest.json"
    data = _read_json(src)
    if not isinstance(data, dict):
        raise RuntimeError("Manifest Native Messaging invalide dans la release.")
    data["path"] = str(host_path)
    _atomic_json(native_manifest_path(), data, mode=0o600)


def _install_cli_links():
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = INSTALL_DIR / "maintenance.py"
    for link in (UPDATE_BIN, UNINSTALL_BIN):
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)
        except Exception:
            # Symlinks are convenience only; package-local scripts remain usable.
            pass


def _dependency_check_from_source(source: Path, client: dict) -> dict | None:
    try:
        # Import source host under an isolated name; it only performs network
        # access when check_dependency_updates is called explicitly here.
        old_path = list(sys.path)
        sys.path.insert(0, str(source / "native-host"))
        spec = importlib.util.spec_from_file_location(
            f"kitty_update_host_{os.getpid()}_{time.time_ns()}",
            source / "native-host" / "host.py",
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.check_dependency_updates(client=client, save_cache=True)
    except Exception as exc:
        print(f"⚠ Vérification des dépendances indisponible: {exc}")
        return None
    finally:
        try:
            sys.path[:] = old_path
        except Exception:
            pass


def _print_update_report(report: dict | None):
    if not isinstance(report, dict):
        return
    print()
    print("Dépendances:")
    items = report.get("items") or []
    updates = [item for item in items if item.get("update_available")]
    if not updates:
        print("  ✓ aucune mise à jour détectée avec les sources disponibles")
    else:
        for item in updates:
            marker = "⚠" if item.get("potential_incompatibility") else "↑"
            current = item.get("current") or "?"
            available = item.get("available") or "?"
            print(f"  {marker} {item.get('label') or item.get('id')}: {current} → {available}")
            if item.get("potential_incompatibility"):
                print(f"    {item.get('reason') or 'compatibilité à vérifier'}")
    source_note = report.get("source_note")
    if source_note:
        print(f"  Source: {source_note}")


def update(source: Path, allow_downgrade=False, skip_network=False) -> int:
    info = _source_release_info(source)
    source = info["source"]
    version = info["version"]
    protocol = info["protocol"]
    client = {"version": version, "protocol": protocol}

    installed_version = _version_from_host(INSTALL_DIR / "host.py")
    if not installed_version:
        print("Aucune installation V8 détectée. Utilise ./install.sh pour une installation fraîche.")
        return 2

    if _version_key(version) < _version_key(installed_version) and not allow_downgrade:
        print(f"Refus du downgrade {installed_version} → {version}. Utilise --allow-downgrade si c’est volontaire.")
        return 2

    print()
    print(f"{APP_NAME} — updater")
    print(f"Backend installé : {installed_version}")
    print(f"Release cible     : {version}")
    print(f"Protocole         : frontend/backend v{protocol} ✓")

    if not skip_network:
        report = _dependency_check_from_source(source, client)
        _print_update_report(report)

    print()
    print("Préparation sûre de la file…")
    frozen = prepare_maintenance("pre-update")
    print("  ✓ file mise en pause")
    if frozen.get("worker_pid"):
        print("  ✓ worker actif arrêté et réinséré par la logique d’arrêt sûr")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    backend_backup = BACKUP_ROOT / f"backend-v{installed_version}-{stamp}"
    if INSTALL_DIR.is_dir():
        shutil.copytree(INSTALL_DIR, backend_backup)

    nm_backup = None
    nm_path = native_manifest_path()
    if nm_path.is_file():
        nm_backup = BACKUP_ROOT / f"native-manifest-{stamp}.json"
        shutil.copy2(nm_path, nm_backup)

    parent = INSTALL_DIR.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / f".{APP_SLUG}.new-{os.getpid()}"
    rollback = parent / f".{APP_SLUG}.rollback-{os.getpid()}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(rollback, ignore_errors=True)
    stage.mkdir(mode=0o700)

    for filename in BACKEND_FILES:
        shutil.copy2(source / "native-host" / filename, stage / filename)
    for filename in ("host.py", "worker.py", "metadata.py", "migrate.py", "compatibility.py", "maintenance.py", "runtime_storage.py"):
        os.chmod(stage / filename, 0o755)
    for filename in ("errors.py", "app_paths.py", "queue_store.py"):
        os.chmod(stage / filename, 0o644)

    _validate_backend_dir(stage, Path.home())

    try:
        if INSTALL_DIR.exists():
            os.rename(INSTALL_DIR, rollback)
        os.rename(stage, INSTALL_DIR)
        _write_native_manifest(source, INSTALL_DIR / "host.py")
        _install_cli_links()

        response = _native_call(
            INSTALL_DIR / "host.py",
            {"action": "compatibility", "client": client},
        )
        comp = response.get("compatibility") if isinstance(response, dict) else None
        if not response.get("ok") or not isinstance(comp, dict) or not comp.get("compatible"):
            raise RuntimeError(f"Validation frontend/backend échouée: {response}")

        shutil.rmtree(rollback, ignore_errors=True)
    except Exception:
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)
        if rollback.exists():
            os.rename(rollback, INSTALL_DIR)
        if nm_backup and nm_backup.is_file():
            shutil.copy2(nm_backup, nm_path)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    # Restore the queue's previous pause policy. If it was running, resume via
    # the newly validated backend so interrupted active work continues safely.
    if not frozen.get("was_paused"):
        try:
            _native_call(
                INSTALL_DIR / "host.py",
                {"action": "resume_queue", "client": client},
            )
            print("  ✓ file reprise automatiquement")
        except Exception as exc:
            print(f"  ⚠ file laissée en pause; reprise manuelle recommandée: {exc}")

    print()
    print(f"✓ Backend Kitty {installed_version} → {version} mis à jour")
    print("✓ configuration, historique, file et cookies conservés")
    print("✓ sauvegarde backend créée dans ~/.cache/kitty-download-manager/update-backups")
    print("→ Recharge l’extension Firefox pour aligner le frontend sur cette release.")
    return 0


def check(network=True) -> int:
    if not (INSTALL_DIR / "host.py").is_file():
        print("Backend Kitty non installé.")
        return 2

    installed_version = _version_from_host(INSTALL_DIR / "host.py") or "?"
    compat_path = INSTALL_DIR / "compatibility.py"
    protocol = 0
    if compat_path.is_file():
        try:
            module = _load_module(compat_path, f"kitty_installed_compat_{os.getpid()}_{time.time_ns()}")
            protocol = int(getattr(module, "NATIVE_PROTOCOL_VERSION", 0))
        except Exception:
            protocol = 0

    client = {"version": installed_version, "protocol": protocol}
    print(f"{APP_NAME} — vérification")
    print(f"Backend : {installed_version}")
    print(f"Protocole natif : {protocol or 'ancien/inconnu'}")

    try:
        response = _native_call(
            INSTALL_DIR / "host.py",
            {"action": "compatibility", "client": client},
        )
        comp = response.get("compatibility") or {}
        print(f"Compatibilité backend : {'OK' if comp.get('compatible') else 'À mettre à jour'}")
    except Exception as exc:
        print(f"Compatibilité backend : ancien/inconnu ({exc})")

    if network:
        try:
            response = _native_call(
                INSTALL_DIR / "host.py",
                {"action": "check_updates", "client": client},
                timeout=30,
            )
            _print_update_report(response.get("updates") if isinstance(response, dict) else None)
        except Exception as exc:
            print(f"⚠ Vérification réseau des dépendances impossible: {exc}")
    return 0


def _remove_cli_links():
    target = INSTALL_DIR / "maintenance.py"
    for link in (UPDATE_BIN, UNINSTALL_BIN):
        try:
            if link.is_symlink() and link.resolve(strict=False) == target.resolve(strict=False):
                link.unlink()
        except Exception:
            pass


def uninstall(purge=False, yes=False) -> int:
    print()
    print(f"{APP_NAME} — désinstallation")
    if purge and not yes:
        if not sys.stdin.isatty():
            print("--purge nécessite --yes hors terminal interactif.")
            return 2
        answer = input("PURGE supprime config, cache et cookies Kitty. Tape PURGE pour confirmer : ").strip()
        if answer != "PURGE":
            print("Purge annulée.")
            return 1

    if INSTALL_DIR.exists() or QUEUE_FILE.exists():
        print("Préparation sûre de la file…")
        prepare_maintenance("pre-uninstall")
        print("  ✓ workers arrêtés / file gelée")

    nm = native_manifest_path()
    try:
        if nm.is_file() or nm.is_symlink():
            nm.unlink()
    except Exception as exc:
        raise RuntimeError(f"Impossible de supprimer le manifest Native Messaging: {exc}")

    _remove_cli_links()
    shutil.rmtree(INSTALL_DIR, ignore_errors=False) if INSTALL_DIR.exists() else None

    if purge:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        print("✓ backend, config, cache, logs et cookies Kitty supprimés")
    else:
        print("✓ backend et Native Messaging supprimés")
        print("✓ config, file/cache et cookies conservés pour une éventuelle réinstallation")

    print("✓ aucun dossier de téléchargements ni média terminé n’a été supprimé")
    print("→ Firefox : retire l’extension temporaire dans about:debugging si elle est encore chargée.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kitty-maintenance")
    sub = parser.add_subparsers(dest="command", required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--source", type=Path, required=True)
    p_update.add_argument("--allow-downgrade", action="store_true")
    p_update.add_argument("--skip-network", action="store_true")

    p_check = sub.add_parser("check")
    p_check.add_argument("--no-network", action="store_true")

    p_uninstall = sub.add_parser("uninstall")
    p_uninstall.add_argument("--purge", action="store_true")
    p_uninstall.add_argument("--yes", action="store_true")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    invoked = Path(sys.argv[0]).name

    # Convenience symlinks installed in ~/.local/bin.
    if invoked == "kitty-update":
        if argv and not argv[0].startswith("-"):
            source = Path(argv.pop(0))
            return update(
                source,
                allow_downgrade="--allow-downgrade" in argv,
                skip_network="--skip-network" in argv,
            )
        return check(network="--no-network" not in argv)

    if invoked == "kitty-uninstall":
        return uninstall(purge="--purge" in argv, yes="--yes" in argv)

    args = _parser().parse_args(argv)
    if args.command == "update":
        return update(args.source, args.allow_downgrade, args.skip_network)
    if args.command == "check":
        return check(network=not args.no_network)
    if args.command == "uninstall":
        return uninstall(args.purge, args.yes)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nOpération interrompue.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        raise SystemExit(1)
