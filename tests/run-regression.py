#!/usr/bin/env python3
"""
Kitty Download Manager — banc de tests de régression hors-ligne.

Aucune dépendance Python externe : uniquement la stdlib.
Node.js est utilisé pour les tests du resolver si disponible.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
NATIVE = ROOT / "native-host"

PASS = 0
FAIL = 0
SKIP = 0
DETAILS = []


class SkipTest(Exception):
    pass


class TestFailure(AssertionError):
    pass


def check(condition, message="condition non satisfaite"):
    if not condition:
        raise TestFailure(message)


def equal(actual, expected, message="valeurs différentes"):
    if actual != expected:
        raise TestFailure(f"{message}: attendu={expected!r}, reçu={actual!r}")


def run_case(name, fn):
    global PASS, FAIL
    started = time.monotonic()
    try:
        fn()
    except SkipTest as exc:
        skip_case(name, str(exc))
    except Exception as exc:
        FAIL += 1
        elapsed = (time.monotonic() - started) * 1000
        print(f"✗ {name} ({elapsed:.0f} ms)")
        print(f"    {type(exc).__name__}: {exc}")
        DETAILS.append((name, traceback.format_exc()))
    else:
        PASS += 1
        elapsed = (time.monotonic() - started) * 1000
        print(f"✓ {name} ({elapsed:.0f} ms)")


def skip_case(name, reason):
    global SKIP
    SKIP += 1
    print(f"↷ {name} — {reason}")


def clean_subprocess_env(home=None):
    """Neutralise les hooks propres au sandbox ChatGPT dans les Python enfants."""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CUA_DD_"):
            env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    if home is not None:
        env["HOME"] = str(home)
    return env


def load_module(path: Path, name: str, home: Path):
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Impossible de charger {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def native_call(host_path: Path, home: Path, message: dict) -> dict:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    framed = struct.pack("<I", len(payload)) + payload
    env = clean_subprocess_env(home)

    proc = subprocess.run(
        [sys.executable, str(host_path)],
        input=framed,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=12,
        check=False,
    )
    check(proc.returncode == 0, f"host.py code={proc.returncode}, stderr={proc.stderr.decode('utf-8', 'replace')!r}")
    check(len(proc.stdout) >= 4, "réponse Native Messaging trop courte")
    size = struct.unpack("<I", proc.stdout[:4])[0]
    body = proc.stdout[4:4 + size]
    check(len(body) == size, "réponse Native Messaging tronquée")
    return json.loads(body.decode("utf-8"))


def test_required_files():
    required = [
        EXT / "manifest.json",
        EXT / "background.js",
        EXT / "popup.js",
        EXT / "content-pill.js",
        EXT / "media-resolver.js",
        NATIVE / "host.py",
        NATIVE / "worker.py",
        NATIVE / "metadata.py",
        NATIVE / "errors.py",
        NATIVE / "app_paths.py",
        NATIVE / "migrate.py",
        NATIVE / "compatibility.py",
        NATIVE / "maintenance.py",
        NATIVE / "runtime_storage.py",
        NATIVE / "queue_store.py",
        ROOT / "install.sh",
        ROOT / "update.sh",
        ROOT / "uninstall.sh",
        ROOT / "test.sh",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    check(not missing, f"fichiers manquants: {missing}")


def test_manifest_contract():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("version", "")
    check(re.fullmatch(r"[1-9]\d{0,8}\.\d{1,9}", version) is not None, f"version Firefox hors format X.N: {version!r}")
    equal(manifest.get("manifest_version"), 3, "manifest_version")
    equal(manifest.get("browser_specific_settings", {}).get("gecko", {}).get("id"), "kitty-download-manager@local", "Firefox ID")

    permissions = set(manifest.get("permissions", []))
    check({"activeTab", "nativeMessaging", "storage"}.issubset(permissions), "permissions essentielles absentes")

    scripts = manifest.get("content_scripts", [{}])[0].get("js", [])
    check("media-resolver.js" in scripts and "content-pill.js" in scripts, "resolver/pill absents du content script")
    check(scripts.index("media-resolver.js") < scripts.index("content-pill.js"), "resolver doit charger avant le pill")


def test_native_manifest_contract():
    native = json.loads((NATIVE / "manifest.json").read_text(encoding="utf-8"))
    equal(native.get("name"), "com.kitty.download_manager", "nom Native Messaging")
    check("kitty-download-manager@local" in native.get("allowed_extensions", []), "extension Firefox non autorisée")
    equal(native.get("type"), "stdio", "type Native Messaging")


def test_python_syntax():
    for path in [NATIVE / "host.py", NATIVE / "worker.py", NATIVE / "metadata.py", NATIVE / "errors.py", NATIVE / "app_paths.py", NATIVE / "migrate.py", NATIVE / "compatibility.py", NATIVE / "maintenance.py", NATIVE / "runtime_storage.py", NATIVE / "queue_store.py"]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_version_consistency():
    version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    host = (NATIVE / "host.py").read_text(encoding="utf-8")
    worker = (NATIVE / "worker.py").read_text(encoding="utf-8")
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    check(f'APP_VERSION = "{version}"' in host, "APP_VERSION différent du manifest")
    check(f"worker V{version} lancé" in worker, "label worker périmé")
    check(f"Kitty Download Manager V{version} installée." in installer, "label install.sh périmé")

    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    compatibility = (NATIVE / "compatibility.py").read_text(encoding="utf-8")
    proto_front = re.search(r"const\s+NATIVE_PROTOCOL_VERSION\s*=\s*(\d+)", shared)
    proto_back = re.search(r"NATIVE_PROTOCOL_VERSION\s*=\s*(\d+)", compatibility)
    check(proto_front is not None and proto_back is not None, "protocole frontend/backend absent")
    equal(proto_front.group(1), proto_back.group(1), "protocole frontend/backend différent")


def test_resolver_cost_guards():
    source = (EXT / "media-resolver.js").read_text(encoding="utf-8")
    code = re.sub(r"//.*?$", "", source, flags=re.MULTILINE)
    forbidden_patterns = {
        "fetch réseau": r"\bfetch\s*\(",
        "XMLHttpRequest": r"\bXMLHttpRequest\b",
        "MutationObserver actif": r"\bnew\s+MutationObserver\b",
        "polling setInterval": r"\bsetInterval\s*\(",
    }
    for label, pattern in forbidden_patterns.items():
        check(re.search(pattern, code) is None, f"resolver contient une opération coûteuse/permanente: {label}")
    for required in [
        "MAX_NEARBY_LINKS",
        "MAX_ANCESTOR_DEPTH",
        "MAX_JSONLD_SCRIPTS",
        "MAX_JSONLD_TOTAL_CHARS",
        "MAX_JSONLD_NODES",
        "CACHE_MS",
    ]:
        check(required in source, f"garde de coût absente: {required}")


def test_installer_sandbox():
    with tempfile.TemporaryDirectory(prefix="kitty-install-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        env = clean_subprocess_env(home)

        proc = subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            check=False,
        )
        check(proc.returncode == 0, f"install.sh a échoué:\n{proc.stdout}")

        version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
        check(f"V{version} installée." in proc.stdout, "install.sh affiche une ancienne version")

        install_dir = home / ".local" / "lib" / "kitty-download-manager"
        for filename in ["host.py", "worker.py", "metadata.py"]:
            path = install_dir / filename
            check(path.is_file(), f"{filename} non installé")
            check(os.access(path, os.X_OK), f"{filename} non exécutable")

        check((install_dir / "errors.py").is_file(), "errors.py non installé")
        check((install_dir / "app_paths.py").is_file(), "app_paths.py non installé")
        check((install_dir / "migrate.py").is_file(), "migrate.py non installé")
        check((install_dir / "compatibility.py").is_file(), "compatibility.py non installé")
        check((install_dir / "maintenance.py").is_file(), "maintenance.py non installé")
        check((home / ".local" / "bin" / "kitty-update").is_symlink(), "kitty-update non installé")
        check((home / ".local" / "bin" / "kitty-uninstall").is_symlink(), "kitty-uninstall non installé")
        check((home / ".config" / "kitty-download-manager" / "migration-v8.json").is_file(), "marker migration absent")

        nm = home / ".mozilla" / "native-messaging-hosts" / "com.kitty.download_manager.json"
        check(nm.is_file(), "manifest Native Messaging non installé")
        data = json.loads(nm.read_text(encoding="utf-8"))
        equal(Path(data["path"]), install_dir / "host.py", "chemin host installé")
        check((home / "Downloads" / "kitty-download-manager").is_dir(), "dossier par défaut non créé")



def test_v8_full_legacy_migration():
    with tempfile.TemporaryDirectory(prefix="kitty-v8-migrate-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)

        legacy_install = home / ".local" / "lib" / "firefox-ytdlp"
        legacy_config = home / ".config" / "firefox-ytdlp"
        legacy_cache = home / ".cache" / "firefox-ytdlp"
        legacy_nm = home / ".mozilla" / "native-messaging-hosts" / "com.example.ytdlp_downloader.json"
        legacy_downloads = home / "Downloads" / "videoytdlp"

        legacy_install.mkdir(parents=True)
        (legacy_install / "legacy-sentinel.txt").write_text("old backend", encoding="utf-8")

        auth = legacy_config / "youtube-auth"
        auth.mkdir(parents=True)
        old_cookie = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSAPISID\tsecret\n"
        (auth / "cookies.txt").write_text(old_cookie, encoding="utf-8")
        os.chmod(auth / "cookies.txt", 0o600)
        (auth / "metadata.json").write_text(
            json.dumps({"source": "kitty-isolated-firefox-profile"}),
            encoding="utf-8",
        )

        legacy_downloads.mkdir(parents=True)
        media = legacy_downloads / "Already Downloaded.opus"
        media.write_bytes(b"legacy-media")

        settings = {"output_dir": str(legacy_downloads), "youtube_auth_enabled": True}
        (legacy_config / "settings.json").write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        legacy_cache.mkdir(parents=True)
        queue = {
            "state_version": 2,
            "active": None,
            "queue": [{
                "id": "queued-1",
                "url": "https://example.com/media",
                "mode": "audio",
                "status": "queued",
                "output_dir": str(legacy_downloads),
                "output_stem": str(legacy_downloads / "Future Track"),
            }],
            "history": [{
                "id": "history-1",
                "url": "https://example.com/done",
                "mode": "audio",
                "status": "finished",
                "output_dir": str(legacy_downloads),
                "filepath": str(media),
            }],
            "queue_paused": True,
        }
        (legacy_cache / "queue.json").write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (legacy_cache / "worker.log").write_text("legacy log\n", encoding="utf-8")
        backups = legacy_cache / "state-backups"
        backups.mkdir()
        (backups / "queue-old.json").write_text(json.dumps(queue), encoding="utf-8")

        legacy_nm.parent.mkdir(parents=True)
        legacy_nm.write_text(
            json.dumps({
                "name": "com.example.ytdlp_downloader",
                "path": str(legacy_install / "host.py"),
                "type": "stdio",
                "allowed_extensions": ["ytdlp-downloader@local"],
            }),
            encoding="utf-8",
        )

        env = clean_subprocess_env(home)
        proc = subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=25,
            check=False,
        )
        check(proc.returncode == 0, f"migration V8 échouée:\n{proc.stdout}")

        new_install = home / ".local" / "lib" / "kitty-download-manager"
        new_config = home / ".config" / "kitty-download-manager"
        new_cache = home / ".cache" / "kitty-download-manager"
        new_downloads = home / "Downloads" / "kitty-download-manager"
        new_nm = home / ".mozilla" / "native-messaging-hosts" / "com.kitty.download_manager.json"

        check(new_install.is_dir(), "nouveau backend absent")
        check(new_config.is_dir(), "nouvelle config absente")
        check(new_cache.is_dir(), "nouveau cache absent")
        check(new_nm.is_file(), "nouveau manifest Native Messaging absent")

        check(not legacy_install.exists(), "ancien backend non supprimé")
        check(not legacy_config.exists(), "ancienne config non supprimée")
        check(not legacy_cache.exists(), "ancien cache non supprimé")
        check(not legacy_nm.exists(), "ancien manifest Native Messaging non supprimé")
        check(not legacy_downloads.exists(), "ancien dossier de téléchargement non renommé")

        check((new_downloads / media.name).read_bytes() == b"legacy-media", "média legacy non préservé")

        migrated_settings = json.loads((new_config / "settings.json").read_text(encoding="utf-8"))
        equal(migrated_settings["output_dir"], str(new_downloads), "destination legacy non réécrite")
        check(migrated_settings.get("youtube_auth_enabled") is True, "réglage auth YouTube perdu")

        migrated_queue = json.loads((new_cache / "queue.json").read_text(encoding="utf-8"))
        equal(migrated_queue["queue"][0]["output_dir"], str(new_downloads), "queue output_dir non migré")
        equal(migrated_queue["queue"][0]["output_stem"], str(new_downloads / "Future Track"), "queue output_stem non migré")
        equal(migrated_queue["history"][0]["filepath"], str(new_downloads / media.name), "historique filepath non migré")

        cookie = new_config / "youtube-auth" / "cookies.txt"
        equal(cookie.read_text(encoding="utf-8"), old_cookie, "snapshot YouTube perdu")
        equal(stat.S_IMODE(cookie.stat().st_mode), 0o600, "permissions cookie migré")

        check((new_cache / "worker.log").read_text(encoding="utf-8") == "legacy log\n", "log legacy perdu")
        check((new_cache / "state-backups" / "queue-old.json").is_file(), "backup état perdu")

        marker = json.loads((new_config / "migration-v8.json").read_text(encoding="utf-8"))
        equal(marker.get("status"), "completed", "migration non finalisée")
        check(marker.get("legacy_found") is True, "legacy non détecté")
        check(marker.get("legacy_removed") is True, "legacy non marqué supprimé")
        equal(marker.get("output_migration"), "legacy_default_renamed", "dossier Downloads non migré")

        # Une future réinstallation V8 ne doit pas effacer l'historique du marker.
        prepare_again = subprocess.run(
            [sys.executable, str(new_install / "migrate.py"), "prepare"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=8,
            check=False,
        )
        check(prepare_again.returncode == 0, f"prepare idempotent échoué: {prepare_again.stdout}")
        marker_again = json.loads((new_config / "migration-v8.json").read_text(encoding="utf-8"))
        check(marker_again.get("legacy_found") is True, "réinstallation V8 efface legacy_found")
        equal(marker_again.get("status"), "completed", "réinstallation V8 rétrograde marker")


def test_v8_preserves_custom_destination():
    with tempfile.TemporaryDirectory(prefix="kitty-v8-custom-dest-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)

        legacy_config = home / ".config" / "firefox-ytdlp"
        legacy_config.mkdir(parents=True)
        custom = home / "Music" / "My Collection"
        custom.mkdir(parents=True)
        (custom / "keep.opus").write_bytes(b"keep")

        (legacy_config / "settings.json").write_text(
            json.dumps({"output_dir": str(custom)}, ensure_ascii=False),
            encoding="utf-8",
        )

        env = clean_subprocess_env(home)
        proc = subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=25,
            check=False,
        )
        check(proc.returncode == 0, f"migration destination custom échouée:\n{proc.stdout}")

        settings = json.loads(
            (home / ".config" / "kitty-download-manager" / "settings.json").read_text(encoding="utf-8")
        )
        equal(settings.get("output_dir"), str(custom), "destination personnalisée modifiée")
        check((custom / "keep.opus").read_bytes() == b"keep", "fichier custom modifié")

        marker = json.loads(
            (home / ".config" / "kitty-download-manager" / "migration-v8.json").read_text(encoding="utf-8")
        )
        equal(marker.get("output_migration"), "custom_destination_preserved", "statut destination custom")


def test_v8_migration_refuses_live_legacy_worker():
    with tempfile.TemporaryDirectory(prefix="kitty-v8-live-worker-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)

        legacy_install = home / ".local" / "lib" / "firefox-ytdlp"
        legacy_cache = home / ".cache" / "firefox-ytdlp"
        legacy_install.mkdir(parents=True)
        legacy_cache.mkdir(parents=True)

        worker_script = legacy_install / "worker.py"
        worker_script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

        env = clean_subprocess_env(home)
        sleeper = subprocess.Popen(
            [sys.executable, str(worker_script)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            queue = {
                "state_version": 2,
                "active": {
                    "id": "live",
                    "status": "downloading",
                    "worker_pid": sleeper.pid,
                },
                "queue": [],
                "history": [],
                "queue_paused": False,
            }
            (legacy_cache / "queue.json").write_text(json.dumps(queue), encoding="utf-8")

            proc = subprocess.run(
                ["bash", str(ROOT / "install.sh")],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
                check=False,
            )
            check(proc.returncode != 0, "migration autorisée pendant un worker V7 actif")
            check("encore actif" in proc.stdout, "raison blocage worker actif absente")
            check(legacy_install.exists(), "legacy supprimé malgré blocage")
        finally:
            sleeper.terminate()
            try:
                sleeper.wait(timeout=3)
            except subprocess.TimeoutExpired:
                sleeper.kill()
                sleeper.wait(timeout=3)


def test_v8_runtime_identity_is_clean():
    runtime_files = [
        EXT / "manifest.json",
        EXT / "background.js",
        EXT / "popup.html",
        EXT / "popup.js",
        EXT / "content-pill.js",
        NATIVE / "manifest.json",
        NATIVE / "host.py",
        NATIVE / "worker.py",
        NATIVE / "metadata.py",
        NATIVE / "errors.py",
        ROOT / "install.sh",
    ]
    forbidden = (
        "Kitty Video Downloader",
        "com.example.ytdlp_downloader",
        "ytdlp-downloader@local",
        "kitty-video-downloader-pill-host",
        ".cache/firefox-ytdlp",
        ".config/firefox-ytdlp",
        ".local/lib/firefox-ytdlp",
        "Downloads/videoytdlp",
    )

    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            check(needle not in text, f"ancienne identité encore dans {path.name}: {needle}")

    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    equal(manifest.get("name"), "Kitty Download Manager", "nom public V8")
    equal(manifest.get("action", {}).get("default_title"), "Kitty Download Manager", "titre action V8")
    check("kitty-download-manager-pill-host" in (EXT / "content-pill.js").read_text(encoding="utf-8"), "ID pill V8 absent")


def test_native_protocol():
    with tempfile.TemporaryDirectory(prefix="kitty-protocol-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        env = clean_subprocess_env(home)
        subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=True,
        )

        installed_host = home / ".local" / "lib" / "kitty-download-manager" / "host.py"

        status = native_call(installed_host, home, {"action": "status"})
        check(status.get("ok") is True, "status Native Messaging")
        equal(status["state"]["state_version"], 2, "state_version")

        settings = native_call(installed_host, home, {"action": "get_settings"})
        check(settings.get("ok") is True, "get_settings")

        custom = home / "Videos" / "Kitty"
        changed = native_call(
            installed_host,
            home,
            {"action": "set_output_dir", "output_dir": str(custom)},
        )
        check(changed.get("ok") is True, "set_output_dir")
        equal(changed.get("output_dir"), str(custom), "destination sauvegardée")

        reread = native_call(installed_host, home, {"action": "get_settings"})
        equal(reread.get("settings", {}).get("output_dir"), str(custom), "destination persistée")

        diag = native_call(installed_host, home, {"action": "diagnostics"})
        check(diag.get("ok") is True, "diagnostics")
        version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
        equal(diag["diagnostics"]["kitty_version"], version, "version diagnostic")
        check(isinstance(diag.get("dependencies", {}).get("items"), list), "dépendances diagnostic Native Messaging")
        equal(diag.get("privacy", {}).get("network_used"), False, "diagnostic Native Messaging sans réseau")

        pause = native_call(installed_host, home, {"action": "pause_active"})
        check(pause.get("ok") is False, "pause active doit rester désactivée")
        equal(pause.get("error_code"), "active_pause_disabled", "code pause active")

        unknown = native_call(installed_host, home, {"action": "action-inconnue"})
        check(unknown.get("ok") is False, "action inconnue doit être refusée")
        equal(unknown.get("error_code"), "unsupported_action", "code action inconnue")

        reset = native_call(installed_host, home, {"action": "reset_kitty"})
        check(reset.get("ok") is True, "reset_kitty")


def test_host_url_canonicalization():
    with tempfile.TemporaryDirectory(prefix="kitty-host-url-") as tmp:
        home = Path(tmp)
        host = load_module(NATIVE / "host.py", f"kitty_host_urls_{os.getpid()}_{time.time_ns()}", home)

        cases = [
            (
                "https://www.tiktok.com/@andreea/video/7660560870455840021?is_from_webapp=1",
                "https://www.tiktok.com/@andreea/video/7660560870455840021",
            ),
            (
                "https://www.instagram.com/reels/ABC_123/?igshid=x",
                "https://www.instagram.com/reel/ABC_123/",
            ),
            (
                "https://twitter.com/alice/status/123456?s=20",
                "https://x.com/i/status/123456",
            ),
            (
                "https://www.reddit.com/r/videos/comments/abc123/title/",
                "https://www.reddit.com/comments/abc123",
            ),
            (
                "https://www.pinterest.fr/pin/a-pretty-pin--984881012265751603/?utm_source=x",
                "https://www.pinterest.com/pin/984881012265751603/",
            ),
            (
                "https://www.facebook.com/reel/123456789/?mibextid=x",
                "https://www.facebook.com/reel/123456789",
            ),
            (
                "https://www.youtube.com/watch?v=abcDEF12345&list=foo",
                "https://www.youtube.com/watch?v=abcDEF12345",
            ),
            (
                "https://youtu.be/abcDEF12345?si=x",
                "https://www.youtube.com/watch?v=abcDEF12345",
            ),
        ]
        for source, expected in cases:
            equal(host.normalize_download_url(source), expected, f"canonicalisation {source}")

        generic = "https://example.com/feed?x=1"
        equal(host.normalize_download_url(generic), generic, "URL générique ne doit pas être inventée")


def test_state_migration_recovery():
    with tempfile.TemporaryDirectory(prefix="kitty-state-") as tmp:
        home = Path(tmp)
        host = load_module(NATIVE / "host.py", f"kitty_host_state_{os.getpid()}_{time.time_ns()}", home)
        host.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Ancien état pré-versionné + état expérimental paused_queue.
        old = {
            "active": None,
            "queue": [{"id": "q1", "url": "https://example.com/a", "status": "paused_queue"}],
            "history": [{"id": f"h{i}", "status": "finished"} for i in range(60)],
        }
        host.QUEUE_FILE.write_text(json.dumps(old), encoding="utf-8")
        state = host.snapshot()
        equal(state["state_version"], host.STATE_VERSION, "migration state_version")
        check(state["queue"][0].get("paused") is True, "migration paused_queue")
        equal(len(state["history"]), 50, "historique tronqué")
        check(list(host.STATE_BACKUP_DIR.glob("queue-pre-migration-*.json")), "backup pré-migration absent")

        # Corruption JSON : doit être isolée et repartir proprement.
        host.QUEUE_FILE.write_text("{ ceci n'est pas du json", encoding="utf-8")
        state = host.snapshot()
        equal(state["active"], None, "recovery corruption active")
        equal(state["queue"], [], "recovery corruption queue")
        check(list(host.STATE_BACKUP_DIR.glob("queue-corrupt-*.json")), "backup corruption absent")

        # Version future : ne jamais essayer de la réinterpréter.
        host.QUEUE_FILE.write_text(
            json.dumps({"state_version": 999, "active": None, "queue": [], "history": []}),
            encoding="utf-8",
        )
        original = host.QUEUE_FILE.read_bytes()
        try:
            host.snapshot()
        except host.FutureStateVersion:
            pass
        else:
            raise TestFailure("Une version future doit bloquer la lecture")
        equal(host.QUEUE_FILE.read_bytes(), original, "version future modifiée")

        check(not host.QUEUE_FILE.with_suffix(".tmp").exists(), "fichier .tmp résiduel après écriture atomique")


def test_settings_and_safe_reset():
    with tempfile.TemporaryDirectory(prefix="kitty-reset-") as tmp:
        home = Path(tmp)
        host = load_module(NATIVE / "host.py", f"kitty_host_reset_{os.getpid()}_{time.time_ns()}", home)

        destination = home / "Media" / "Kitty"
        result = host.set_output_dir(str(destination))
        check(result.get("ok") is True, "set_output_dir avant reset")

        def seed(data):
            data["active"] = None
            data["queue"] = [{"id": "queued", "url": "https://example.com/x", "status": "queued"}]
            data["history"] = [{"id": "done", "url": "https://example.com/y", "status": "finished"}]

        host.with_state(seed)
        reset = host.reset_kitty_state()
        check(reset.get("ok") is True, "reset_kitty_state")
        state = reset["state"]
        equal(state["active"], None, "reset active")
        equal(state["queue"], [], "reset queue")
        equal(state["history"], [], "reset history")
        equal(host.get_output_dir(), destination, "reset doit conserver la destination")
        host.YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
        host.YOUTUBE_COOKIE_FILE.write_text("SAFE-AUTH", encoding="utf-8")
        reset2 = host.reset_kitty_state()
        check(reset2.get("ok") is True, "second reset")
        equal(host.YOUTUBE_COOKIE_FILE.read_text(encoding="utf-8"), "SAFE-AUTH", "reset a supprimé auth YouTube")
        check(list(host.STATE_BACKUP_DIR.glob("queue-manual-reset-*.json")), "backup manuel absent")


def test_queue_semantics_without_network():
    with tempfile.TemporaryDirectory(prefix="kitty-queue-") as tmp:
        home = Path(tmp)
        host = load_module(NATIVE / "host.py", f"kitty_host_queue_{os.getpid()}_{time.time_ns()}", home)

        # Le test ne lance jamais yt-dlp : on remplace uniquement les spawners.
        host.WORKER = NATIVE / "worker.py"
        host.META_WORKER = NATIVE / "metadata.py"
        spawned = []
        metadata = []
        next_pid = 41000

        def fake_spawn(job_id):
            nonlocal next_pid
            next_pid += 1
            spawned.append(job_id)
            return SimpleNamespace(pid=next_pid)

        host.spawn = fake_spawn
        host.spawn_metadata = lambda job: metadata.append(job["id"])
        host.time.sleep = lambda _seconds: None

        first = host.enqueue("https://www.youtube.com/watch?v=AAA111bbb22&list=x", "1080")
        check(first.get("ok") is True, "premier enqueue")
        state = first["state"]
        equal(state["active"]["url"], "https://www.youtube.com/watch?v=AAA111bbb22", "canonicalisation dans la queue")
        equal(len(spawned), 1, "worker actif simulé")

        second = host.enqueue("https://example.com/video/2", "audio")
        check(second.get("ok") is True, "second enqueue")
        equal(len(second["state"]["queue"]), 1, "second job en file")
        equal(len(metadata), 1, "metadata worker simulé pour job en file")

        duplicate = host.enqueue("https://example.com/video/2", "audio")
        equal(duplicate.get("code"), "already_queued", "détection doublon file")

        queued_id = second["job_id"]
        paused = host.toggle_queue_item_pause(queued_id)
        check(paused.get("ok") and paused.get("paused") is True, "pause job en file")
        resumed = host.toggle_queue_item_pause(queued_id)
        check(resumed.get("ok") and resumed.get("paused") is False, "reprise job en file")

        qpause = host.set_queue_paused(True)
        check(qpause.get("queue_paused") is True, "pause globale file")
        qresume = host.set_queue_paused(False)
        check(qresume.get("queue_paused") is False, "reprise globale file")

        # Détection déjà téléchargé dans même mode + destination.
        destination = host.get_output_dir()
        def seed_history(data):
            data.clear()
            data.update(host.default_state())
            data["history"] = [{
                "id": "old",
                "url": "https://example.com/already",
                "mode": "mp3",
                "status": "finished",
                "output_dir": str(destination),
                "filepath": str(destination / "Already.mp3"),
            }]
        host.with_state(seed_history)
        already = host.enqueue("https://example.com/already", "mp3")
        equal(already.get("code"), "already_downloaded", "détection historique")

        forced = host.enqueue("https://example.com/already", "mp3", force=True)
        check(forced.get("ok") is True, "retéléchargement forcé")


def test_worker_filename_and_cleanup_helpers():
    with tempfile.TemporaryDirectory(prefix="kitty-worker-") as tmp:
        home = Path(tmp)
        worker = load_module(NATIVE / "worker.py", f"kitty_worker_{os.getpid()}_{time.time_ns()}", home)
        out = home / "Downloads"
        out.mkdir(parents=True)

        (out / "Titre.opus").write_bytes(b"a")
        equal(worker.choose_unique_output_stem(out, "Titre"), "Titre (2)", "collision simple")
        (out / "Titre (2).webp").write_bytes(b"b")
        equal(worker.choose_unique_output_stem(out, "Titre"), "Titre (3)", "collision thumbnail")

        template = worker.output_template_for_stem(out, "100% Kitty")
        check("100%% Kitty.%(ext)s" in template, "échappement % du template")

        # Nettoyage annulation strictement limité au stem du job.
        target_part = out / "Song.webm.part"
        target_thumb = out / "Song.webp"
        protected = out / "Song (2).opus"
        for p in [target_part, target_thumb, protected]:
            p.write_bytes(b"x")

        removed = worker.cleanup_cancelled_files(
            set(),
            str(out / "Song"),
            time.time() - 1,
        )
        check(not target_part.exists(), "partiel non supprimé")
        check(not target_thumb.exists(), "thumbnail du job non supprimé")
        check(protected.exists(), "un autre stem a été supprimé")
        check(str(protected) not in removed, "un autre stem apparaît dans removed")

        equal(worker.preferred_audio_container("opus"), "opus", "conteneur opus")
        equal(worker.preferred_audio_container("vorbis"), "ogg", "conteneur vorbis")
        equal(worker.preferred_audio_container("aac"), "m4a", "conteneur aac")
        equal(worker.preferred_audio_container("flac"), "flac", "conteneur flac")
        equal(worker.preferred_audio_container("weirdcodec"), "mka", "fallback audio")


def _make_fake_firefox_cookie_db(profile, include_auth=True):
    profile.mkdir(parents=True, exist_ok=True)
    db = profile / "cookies.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA user_version=15")
        conn.execute(
            """
            CREATE TABLE moz_cookies (
                id INTEGER PRIMARY KEY,
                originAttributes TEXT NOT NULL DEFAULT '',
                name TEXT,
                value TEXT,
                host TEXT,
                path TEXT,
                expiry INTEGER,
                lastAccessed INTEGER DEFAULT 0,
                creationTime INTEGER DEFAULT 0,
                isSecure INTEGER DEFAULT 0,
                isHttpOnly INTEGER DEFAULT 0,
                inBrowserElement INTEGER DEFAULT 0,
                sameSite INTEGER DEFAULT 0,
                rawSameSite INTEGER DEFAULT 0,
                schemeMap INTEGER DEFAULT 0
            )
            """
        )
        rows = [
            ("PREF", "youtube-pref", ".youtube.com", "/", 1893456000, 1),
            ("VISITOR_INFO1_LIVE", "visitor", ".youtube.com", "/", 1893456000, 1),
            ("UNRELATED_SECRET", "do-not-export", ".example.com", "/", 1893456000, 1),
        ]
        if include_auth:
            rows.append(("SAPISID", "AUTH_SECRET_VALUE", ".youtube.com", "/", 1893456000, 1))
        conn.executemany(
            "INSERT INTO moz_cookies(name,value,host,path,expiry,isSecure) VALUES(?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_compact_pill_click_drag_contract():
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")
    check('const captureTarget = currentVariant === "classic" ? pill : downloadButton;' in pill, "capture compact incorrecte")
    check("captureTarget.setPointerCapture(event.pointerId)" in pill, "pointer capture robuste absente")
    check("captureTarget.releasePointerCapture(event.pointerId)" in pill, "pointer capture non libérée")
    check("Math.hypot(mx, my) < 5" in pill, "seuil clic/drag absent")
    check("suppressNextDownloadClick = true" in pill, "drag compact peut déclencher un clic")
    check('downloadButton.dataset.actionDisabled === "true"' in pill, "action-disabled absent")
    check('downloadButton.disabled = currentVariant === "classic" && visual.disabled;' in pill, "compact HTML-disabled")


def test_ascii_cat_has_readable_surface_contract():
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")
    start = pill.index('#pill[data-variant="cat"] #download {')
    end = pill.index('#pill[data-variant="cat"] #download:hover', start)
    block = pill[start:end]
    check("background: rgba(28,28,31,.94);" in block, "Chat ASCII encore transparent")
    check("border: 1px solid rgba(255,255,255,.13);" in block, "bordure Chat ASCII absente")
    check("box-shadow: 0 4px 14px rgba(0,0,0,.28);" in block, "contraste Chat ASCII insuffisant")
    for state in ("metadata", "queued", "paused", "downloading", "finished", "error"):
        check(f'#pill[data-variant="cat"][data-state="{state}"] #download' in pill, f"surface état Chat ASCII absente: {state}")


def test_pill_ui_in_real_browser():
    chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium_path:
        raise SkipTest("Chromium indisponible")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        raise SkipTest("Playwright indisponible")

    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")
    source = (EXT / "content-pill.js").read_text(encoding="utf-8")
    source = source.replace('attachShadow({ mode: "closed" })', 'attachShadow({ mode: "open" })', 1)

    bootstrap = r'''window.__kittyStyle = "cat";
window.__kittyDownloads = [];
window.__storageSets = [];
window.KittyShared = {
  COLORS: {blue:"#2A62BB",blueHover:"#3471D4",metadata:"#E6B85C",downloading:"#4AA3DF",success:"#63D98B",error:"#EF6D6D"},
  jobPhase: job => job?.status || "queued",
  jobPercent: () => 0,
  findJob: () => null,
  queuePosition: () => null,
  compactPosition: () => ""
};
window.KittyMediaResolver = {
  resolveMediaUrlForPage: () => ({ok:true,url:"https://example.com/video"}),
  comparableMediaUrl: value => String(value || "")
};
window.browser = {
  storage: {
    local: {
      get: async () => ({pillEnabled:true,pillScope:"all",pillStyle:window.__kittyStyle,uiLanguage:"fr",kittyPillPosition:null}),
      set: async value => { window.__storageSets.push(value); }
    },
    onChanged: { addListener: fn => { window.__storageListener = fn; } }
  },
  runtime: {
    sendMessage: async message => {
      if (message?.type === "kitty-pill-download") { window.__kittyDownloads.push(message); return {ok:true,job_id:"job-1"}; }
      if (message?.type === "kitty-pill-status") return {ok:true,state:{active:null,queue:[],history:[]}};
      return {ok:true};
    },
    onMessage: { addListener: () => {} }
  }
};'''

    def new_page(browser, style):
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.set_content("<!doctype html><html><body><video></video></body></html>")
        page.add_script_tag(content=bootstrap)
        page.add_script_tag(content=i18n)
        page.evaluate("style => { window.__kittyStyle = style; }", style)
        page.add_script_tag(content=source)
        page.wait_for_selector("#kitty-download-manager-pill-host", state="attached")
        page.wait_for_timeout(80)
        return page

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chromium_path, headless=True, args=["--no-sandbox", "--disable-gpu"])
        try:
            for style in ("minimal", "cat", "classic"):
                page = new_page(browser, style)
                button = page.locator("#kitty-download-manager-pill-host").locator("#download")
                button.click()
                page.wait_for_timeout(80)
                equal(page.evaluate("window.__kittyDownloads.length"), 1, f"clic pill {style} n'envoie pas de téléchargement")
                equal(page.evaluate("window.__kittyDownloads[0]?.type"), "kitty-pill-download", f"payload pill {style} incorrect")
                page.close()

            for style in ("minimal", "cat"):
                page = new_page(browser, style)
                button = page.locator("#kitty-download-manager-pill-host").locator("#download")
                box = button.bounding_box()
                check(box is not None, f"bouton pill {style} invisible")
                pill_box = page.locator("#kitty-download-manager-pill-host").locator("#pill")
                before = pill_box.bounding_box()
                check(before is not None, f"pill {style} sans géométrie")
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx - 45, cy + 28, steps=5)
                page.mouse.up()
                page.wait_for_timeout(80)
                equal(page.evaluate("window.__kittyDownloads.length"), 0, f"drag pill {style} déclenche un téléchargement")
                after = pill_box.bounding_box()
                check(after is not None, f"pill {style} perdue après drag")
                check(abs(after["x"]-before["x"])>10 or abs(after["y"]-before["y"])>10, f"pill {style} ne se déplace pas")
                page.close()

            page = new_page(browser, "cat")
            button = page.locator("#kitty-download-manager-pill-host").locator("#download")
            bg = button.evaluate("el => getComputedStyle(el).backgroundColor")
            check(bg not in ("transparent", "rgba(0, 0, 0, 0)"), "fond Chat ASCII transparent en navigateur")
            border = button.evaluate("el => getComputedStyle(el).borderTopWidth")
            check(border != "0px", "Chat ASCII sans bordure en navigateur")
            page.close()
        finally:
            browser.close()


def test_classic_preview_is_more_readable():
    html = (EXT / "popup.html").read_text(encoding="utf-8")

    start = html.index(".pillPreviewClassic {")
    end = html.index(".pillPreviewClassicCat", start)
    classic = html[start:end]
    check("height: 25px;" in classic, "mini pill Classique encore trop basse")
    check("max-width: 56px;" in classic, "mini pill Classique encore trop étroite")
    check("overflow: hidden;" in classic, "mini pill Classique non contenue")

    cat_start = html.index(".pillPreviewClassicCat")
    cat_end = html.index(".pillPreviewClassicDownload", cat_start)
    cat = html[cat_start:cat_end]
    check("font-size: 9px;" in cat, "chat aperçu Classique encore trop petit")

    button_start = html.index(".pillPreviewClassicDownload")
    button_end = html.index("}", button_start)
    button = html[button_start:button_end]
    check("width: 18px;" in button, "bouton bleu aperçu encore trop petit")
    check("height: 18px;" in button, "bouton bleu aperçu encore trop petit")
    check("font-size: 11px;" in button, "flèche aperçu encore trop petite")


def test_pill_style_preview_no_overlap_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check(
        "grid-template-columns: 56px minmax(0, 1fr) 12px;" in html,
        "largeur preview actuelle non bornée",
    )
    check(
        "grid-template-columns: 64px minmax(0, 1fr) 16px;" in html,
        "largeur preview menu non bornée",
    )
    check(
        ".pillStylePreview" in html and "overflow: hidden;" in html,
        "preview style non contenue",
    )

    classic_start = html.index(".pillPreviewClassic {")
    classic_end = html.index(".pillPreviewClassicCat", classic_start)
    classic_css = html[classic_start:classic_end]
    check("max-width: 56px;" in classic_css, "preview Classique non bornée")
    check("overflow: hidden;" in classic_css, "preview Classique peut encore déborder")

    # The preview is an icon; the actual readable label is the adjacent "Classique".
    static_start = html.index('data-pill-style="classic"')
    static_end = html.index("</button>", static_start)
    static_block = html[static_start:static_end]
    check("<span>Download</span>" not in static_block, "mot Download encore dans aperçu Classique")

    dynamic_start = popup.index("classic: {")
    dynamic_end = popup.index("  },", dynamic_start) + 4
    dynamic_block = popup[dynamic_start:dynamic_end]
    check("<span>Download</span>" not in dynamic_block, "aperçu dynamique Classique encore trop large")


def test_kitty_style_display_name_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check(
        '<span id="pillStyleCurrentLabel" class="pillStyleCurrentLabel">Kitty</span>' in html,
        "nom Kitty absent de la valeur sélectionnée",
    )
    check(
        '<span class="pillStyleOptionText">Kitty</span>' in html,
        "nom Kitty absent du menu",
    )
    check('label: "Kitty"' in popup, "nom Kitty absent des métadonnées UI")
    check('label: "Chat ASCII"' not in popup, "ancien nom Chat ASCII encore présent dans les métadonnées UI")


def test_pill_style_picker_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check('id="pillStylePicker"' in html, "picker style pill absent")
    check('id="pillStyleMenu"' in html, "menu style pill absent")

    for style in ("minimal", "cat", "classic"):
        check(f'data-pill-style="{style}"' in html, f"option style absente: {style}")

    check("pillPreviewMinimal" in html, "aperçu Minimal absent")
    check("pillPreviewCat" in html, "aperçu Chat ASCII absent")
    check("pillPreviewClassic" in html, "aperçu Classique absent")

    check("PILL_STYLE_META" in popup, "métadonnées styles absentes")
    check("selectPillStyle" in popup, "sélection style absente")
    check('browser.storage.local.set({ pillStyle: normalized })' in popup, "persistance pillStyle absente")
    check("pillStyleMenuOpen" in popup, "état menu style absent")


def test_pill_style_default_is_ascii_cat():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")
    html = (EXT / "popup.html").read_text(encoding="utf-8")

    check('return "cat";' in popup, "fallback popup non Chat ASCII")
    check('return PILL_VARIANTS.has(value) ? value : "cat";' in pill, "fallback content pill non Chat ASCII")
    check('let currentVariant = "cat";' in pill, "variant initial non Chat ASCII")
    check('data-pill-style="cat" role="option" aria-selected="true"' in html, "Chat ASCII non sélectionné initialement")
    check('>Kitty</span>' in html, "label Kitty absent")


def test_content_pill_three_variants_contract():
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")

    check('new Set(["minimal", "cat", "classic"])' in pill, "3 variantes non déclarées")
    check('pill.dataset.variant = currentVariant;' in pill, "variant non appliqué au DOM")
    check('currentVariant === "cat" ? "ᓚᘏᗢ" : visual.icon' in pill, "Chat ASCII non rendu comme contrôle unique")

    check('#pill[data-variant="minimal"] #download' in pill, "CSS Minimal absent")
    check('#pill[data-variant="cat"] #download' in pill, "CSS Chat ASCII absent")
    check('#pill[data-variant="minimal"] #status' in pill, "Minimal garde le texte")
    check('#pill[data-variant="cat"] #status' in pill, "Chat ASCII garde le texte")
    check('#pill[data-variant="minimal"] #close' in pill, "Minimal garde fermeture")
    check('#pill[data-variant="cat"] #close' in pill, "Chat ASCII garde fermeture")

    check("pill.append(mascot, statusText, downloadButton, closeButton);" in pill, "Classique régressé")


def test_pill_variants_keep_state_colors_and_live_switch():
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")

    for state in ("metadata", "queued", "paused", "downloading", "finished", "error"):
        check(
            f'#pill[data-variant="minimal"][data-state="{state}"] #download' in pill,
            f"couleur Minimal absente: {state}",
        )
        check(
            f'#pill[data-variant="cat"][data-state="{state}"] #download' in pill,
            f"couleur Chat ASCII absente: {state}",
        )

    check("if (changes.pillStyle && pill?.isConnected)" in pill, "switch live absent")
    check("applyVariant(changes.pillStyle.newValue)" in pill, "style live non appliqué")
    check('"pillEnabled", "pillScope", "pillStyle", "uiLanguage", "kittyPillPosition"' in pill, "pillStyle non lu")


def test_settings_color_accents_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check("settingsAccentGlyph destination" in html, "accent Destination absent")
    check("settingsAccentGlyph pill" in html, "accent Pill absent")
    check("settingsAccentGlyph diagnostic" in html, "accent Diagnostic absent")
    check("settingsAccentGlyph maintenance" in html, "accent Maintenance absent")

    check('id="cookiesHeaderMark"' in html, "indicateur Cookies absent")
    check("cookiesInactive" in html, "état Cookies inactif absent")
    check("cookiesActive" in html, "état Cookies actif absent")
    check('content: "!";' in html, "point d'exclamation jaune Cookies absent")
    check("background: var(--kitty-success);" in html, "point vert Cookies actif absent")

    check('id="dependenciesHeaderMark"' in html, "indicateur Dépendances absent")
    for cls in ("dependencyReady", "dependencyWarning", "dependencyError"):
        check(cls in html, f"couleur dépendances absente: {cls}")

    check("updateCookiesHeaderState" in popup, "sync Cookies header absente")
    check("updateDependenciesHeaderState" in popup, "sync Dépendances header absente")


def test_cookies_header_reflects_enabled_state_contract():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    start = popup.index("function renderYoutubeAuth")
    end = popup.index("\nasync function restoreYoutubeAuth", start)
    block = popup[start:end]

    check("updateCookiesHeaderState(" in block, "Cookies header non mis à jour")
    check("configured &&" in block, "Cookies actifs sans configuration possible")
    check("Boolean(auth?.enabled)" in block, "Cookies header ignore le toggle actif")
    check("!pending" in block, "Cookies marqués actifs pendant configuration")
    check('state !== "error"' in block, "Cookies marqués actifs en erreur")


def test_dependencies_header_tracks_diagnostics_contract():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    start = popup.index("function renderDiagnosticsHealth")
    end = popup.index("\nasync function restoreDiagnostics", start)
    block = popup[start:end]

    check("updateDependenciesHeaderState(overall)" in block, "header Dépendances non synchronisé")
    check('updateDependenciesHeaderState("error")' in popup, "erreur diagnostic non reflétée au header")


def test_collapsible_settings_groups_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    expected = ("cookies", "dependencies", "diagnostic", "maintenance")
    for name in expected:
        check(
            f'data-settings-section="{name}"' in html,
            f"section réglages non repliable: {name}",
        )

    check(
        '<span>Cookies</span>' in html,
        "YouTube n’a pas été renommé Cookies",
    )
    check(
        '<span>YouTube</span>' not in html,
        "ancien titre YouTube encore présent",
    )
    check(
        html.count('class="settingsGroupToggle"') >= 4,
        "boutons de dépliage réglages absents",
    )
    check(
        html.count('aria-expanded="false"') >= 4,
        "état ARIA initial des sections absent",
    )
    check(
        ".settingsCollapse.collapsed .settingsGroupBody" in html,
        "CSS masquage sections réglages absent",
    )
    check(
        ".settingsCollapse.collapsed .settingsGroupChevron" in html,
        "chevron réglages non animé",
    )

    check("settingsSectionDefaults" in popup, "defaults sections réglages absents")
    check("settingsSectionStates" in popup, "persistance sections réglages absente")
    check("restoreSettingsSectionStates" in popup, "restauration sections absente")
    check("setSettingsSectionOpen" in popup, "contrôle sections absent")
    check('toggle.closest(".settingsCollapse")' in popup, "clic header section absent")


def test_settings_sections_default_collapsed_and_persisted():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    start = popup.index("const settingsSectionDefaults")
    end = popup.index("async function setSettingsSectionOpen", start)
    block = popup[start:end]

    for key in ("cookies", "dependencies", "diagnostic", "maintenance"):
        check(f"{key}: false" in block, f"{key} n’est pas fermé par défaut")

    check(
        'browser.storage.local.get("settingsSectionStates")' in popup,
        "lecture état sections non persistée",
    )
    check(
        "browser.storage.local.set({ settingsSectionStates: states })" in popup,
        "écriture état sections non persistée",
    )
    check(
        'toggle.setAttribute("aria-expanded", open ? "true" : "false")' in popup,
        "aria-expanded non synchronisé",
    )


def test_source_capsule_dom_stability_contract():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check("function updateSourceHost" in popup, "helper capsule stable absent")
    check("host.dataset.sourceSignature === signature" in popup, "signature capsule absente")
    check("updateSourceHost(activeSourceEl, active.url, source)" in popup, "source active toujours recréée")
    check("updateSourceHost(activeSourceEl, last.url, source)" in popup, "dernier résultat toujours recréé")
    check("clearSourceHost(activeSourceEl)" in popup, "source active non nettoyée")

    start = popup.index("function renderActive")
    end = popup.index("\nfunction itemTitle", start)
    block = popup[start:end]
    check(
        "activeSourceEl.innerHTML = sourceButtonHtml" not in block,
        "renderActive remplace toujours le bouton à chaque poll",
    )


def test_history_dom_stability_contract():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check("let lastHistorySignature = null;" in popup, "signature historique absente")
    start = popup.index("function renderHistory")
    end = popup.index("\nfunction safeSourceUrl", start)
    block = popup[start:end]

    check("const signature = JSON.stringify" in block, "signature historique non calculée")
    check("if (signature === lastHistorySignature) return;" in block, "historique toujours rerendu")
    check("lastHistorySignature = signature;" in block, "signature historique non mémorisée")


def test_flat_source_capsule_contract():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    html = (EXT / "popup.html").read_text(encoding="utf-8")

    fn_start = popup.index("function sourceButtonHtml")
    fn_end = popup.index("\n}\n", fn_start) + 3
    block = popup[fn_start:fn_end]

    check('class="sourceBadge sourceLink' in block, "capsule source non cliquable")
    check('<span class="sourceGlyph"' in block, "icône absente de la capsule")
    check('<span class="sourceLabel">' in block, "label absent de la capsule")

    check("background: transparent;" in html, "fond propre à l’icône non supprimé")
    check("box-shadow: none;" in html, "ombre/fond interne icône restant")
    check('background: rgba(255,255,255,.025);' in html, "capsule légère absente")
    check("button.sourceBadge:hover" in html, "hover capsule entière absent")
    check('.sourceBadge[data-source="youtube"] .sourceGlyph' in html, "couleur plateforme non limitée à l’icône")

    check('class="activeSourceBadge sourceBadgeHost"' in html, "double capsule active encore présente")
    check('class="sourceBadge activeSourceBadge"' not in html, "ancien wrapper capsule encore présent")


def test_source_capsule_click_target_is_whole_badge():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check('data-open-source=' in popup, "capsule sans URL source")
    check('event.target.closest?.("[data-open-source]")' in popup, "clic capsule entier non délégué")
    check("updateSourceHost(activeSourceEl, active.url, source)" in popup, "actif n’utilise pas la capsule unique")
    check("sourceButtonHtml(job.url, source)" in popup, "queue n’utilise pas la capsule unique")
    check("updateSourceHost(activeSourceEl, last.url, source)" in popup, "dernier job n’utilise pas la capsule unique")


def test_source_icons_and_clickable_source_contract():
    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    html = (EXT / "popup.html").read_text(encoding="utf-8")

    check("function sourceIconSvg" in shared, "renderer SVG source absent")
    check("sourceIconSvg," in shared, "sourceIconSvg non exporté")
    check("function sourceButtonHtml" in popup, "bouton source absent")
    check('data-open-source=' in popup, "URL source absente du bouton")
    check("browser.tabs.create" in popup, "ouverture source onglet absente")
    check("safeSourceUrl" in popup, "validation URL source absente")
    check("button.sourceBadge:hover" in html, "hover source absent")
    check("cursor: pointer" in html, "source non visuellement cliquable")
    check("historySourceAction" in popup, "bouton source historique absent")

    # Legacy Unicode source glyphs must be gone from active/queue rendering.
    check("source.glyph" not in popup, "ancien glyph Unicode encore utilisé")


def test_source_info_known_sites_contract():
    node = shutil.which("node")
    if not node:
        raise SkipTest("Node indisponible")

    script = f"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync({json.dumps(str(EXT / "shared.js"))}, "utf8");
const ctx = {{ URL }};
vm.createContext(ctx);
vm.runInContext(src, ctx);

const cases = [
  ["https://www.youtube.com/watch?v=abc", "youtube", "YouTube"],
  ["https://soundcloud.com/a/b", "soundcloud", "SoundCloud"],
  ["https://www.tiktok.com/@a/video/1", "tiktok", "TikTok"],
  ["https://www.instagram.com/reel/x/", "instagram", "Instagram"],
  ["https://x.com/a/status/1", "x", "X"],
  ["https://vimeo.com/123", "vimeo", "Vimeo"],
  ["https://www.pinterest.fr/pin/123/", "pinterest", "Pinterest"],
  ["https://artist.bandcamp.com/track/x", "bandcamp", "Bandcamp"],
  ["https://example.com/media", "web", "Example"],
];

for (const [url, key, label] of cases) {{
  const got = ctx.KittyShared.sourceInfo(url);
  if (got.key !== key || got.label !== label) {{
    throw new Error(`${{url}} => ${{JSON.stringify(got)}}`);
  }}
}}

for (const key of ["youtube", "soundcloud", "tiktok", "instagram", "web"]) {{
  const svg = ctx.KittyShared.sourceIconSvg(key);
  if (!svg.includes("<svg")) throw new Error(`SVG absent: ${{key}}`);
}}
"""
    result = subprocess.run(
        [node, "-e", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    check(result.returncode == 0, f"sourceInfo/icons JS: {result.stderr}")


def test_external_worker_stop_freezes_and_requeues():
    with tempfile.TemporaryDirectory(prefix="kdm-worker-stop-") as tmp:
        home = Path(tmp)
        worker = load_module(
            NATIVE / "worker.py",
            f"kdm_worker_stop_{os.getpid()}_{time.time_ns()}",
            home,
        )

        def seed(data):
            data["active"] = {
                "id": "playlist-active",
                "url": "https://example.com/track-10",
                "mode": "audio",
                "status": "downloading",
                "worker_pid": 999999,
                "collection_url": "https://example.com/collection",
                "playlist_id": "collection-1",
                "playlist_position": 10,
                "playlist_total": 100,
                "output_stem": str(home / "Downloads" / "Track 10"),
            }
            data["queue"] = [
                {
                    "id": "manual-next",
                    "url": "https://example.com/manual",
                    "mode": "audio",
                    "status": "queued",
                },
                {
                    "id": "playlist-next",
                    "url": "https://example.com/track-11",
                    "mode": "audio",
                    "status": "queued",
                    "collection_url": "https://example.com/collection",
                    "playlist_id": "collection-1",
                    "playlist_position": 11,
                    "playlist_total": 100,
                },
            ]
            data["history"] = []
            data["queue_paused"] = False

        worker.locked_mutate(seed)
        result = worker.freeze_after_external_stop("playlist-active", 15)
        check(result["requeued"] is True, "job actif non remis en queue")

        state = worker.get_state()
        check(state["queue_paused"] is True, "file non gelée sur SIGTERM externe")
        check(state["active"] is None, "actif encore présent")
        equal(
            [job["id"] for job in state["queue"]],
            ["manual-next", "playlist-active", "playlist-next"],
            "job interrompu mal replacé dans sa lane",
        )
        equal(state["history"], [], "arrêt externe archivé comme annulé/erreur")
        restored = state["queue"][1]
        equal(restored["status"], "queued", "job interrompu non requeue")
        equal(restored["worker_pid"], None, "PID worker non nettoyé")
        equal(restored["interrupted_reason"], "external_signal", "raison interruption absente")
        equal(restored["interrupted_signal"], 15, "signal interruption absent")


def test_external_stop_manual_job_returns_to_manual_lane():
    with tempfile.TemporaryDirectory(prefix="kdm-worker-stop-manual-") as tmp:
        home = Path(tmp)
        worker = load_module(
            NATIVE / "worker.py",
            f"kdm_worker_stop_manual_{os.getpid()}_{time.time_ns()}",
            home,
        )

        def seed(data):
            data["active"] = {
                "id": "manual-active",
                "url": "https://example.com/a",
                "mode": "audio",
                "status": "downloading",
                "worker_pid": 123,
            }
            data["queue"] = [
                {
                    "id": "manual-next",
                    "url": "https://example.com/b",
                    "mode": "audio",
                    "status": "queued",
                },
                {
                    "id": "playlist-next",
                    "url": "https://example.com/c",
                    "mode": "audio",
                    "status": "queued",
                    "collection_url": "https://example.com/list",
                    "playlist_id": "x",
                },
            ]
            data["queue_paused"] = False

        worker.locked_mutate(seed)
        worker.freeze_after_external_stop("manual-active", 2)
        state = worker.get_state()
        equal(
            [job["id"] for job in state["queue"]],
            ["manual-active", "manual-next", "playlist-next"],
            "manuel interrompu n’est pas revenu en tête de lane",
        )


def test_signal_handler_distinguishes_cancel_from_external_stop():
    with tempfile.TemporaryDirectory(prefix="kdm-signal-contract-") as tmp:
        home = Path(tmp)
        worker = load_module(
            NATIVE / "worker.py",
            f"kdm_worker_signal_{os.getpid()}_{time.time_ns()}",
            home,
        )

        worker.current_job_id = "job-1"
        worker.CONTROL_DIR.mkdir(parents=True, exist_ok=True)

        try:
            worker.handle_signal(15, None)
            raise TestFailure("SIGTERM externe n’a pas levé WorkerShutdown")
        except worker.WorkerShutdown as exc:
            equal(exc.signum, 15, "signal externe perdu")

        worker.external_stop_requested = False
        worker.cancel_requested = False
        worker.control_path("job-1").write_text(
            json.dumps({"action": "cancel"}),
            encoding="utf-8",
        )

        try:
            worker.handle_signal(15, None)
            raise TestFailure("cancel contrôlé n’a pas levé DownloadCancelled")
        except worker.DownloadCancelled:
            pass

        check(worker.cancel_requested is True, "flag cancel contrôlé absent")


def test_host_cancel_marks_control_before_sigterm():
    with tempfile.TemporaryDirectory(prefix="kdm-host-cancel-control-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kdm_host_cancel_control_{os.getpid()}_{time.time_ns()}",
            home,
        )

        def seed(data):
            data["active"] = {
                "id": "active-1",
                "url": "https://example.com/a",
                "mode": "audio",
                "status": "downloading",
                "worker_pid": 424242,
            }
            data["queue"] = []
            data["history"] = []

        host.with_state(seed)

        calls = []
        original_alive = host.process_alive
        original_kill = host.os.kill
        try:
            host.process_alive = lambda pid: True

            def fake_kill(pid, sig):
                control = json.loads(
                    host.control_path("active-1").read_text(encoding="utf-8")
                )
                calls.append((pid, sig, control.get("action")))

            host.os.kill = fake_kill
            result = host.cancel_active()
        finally:
            host.process_alive = original_alive
            host.os.kill = original_kill

        check(result.get("ok") is True, "cancel_active doit réussir")
        equal(len(calls), 1, "SIGTERM non envoyé")
        equal(calls[0][2], "cancel", "marker cancel absent avant SIGTERM")


def test_external_stop_does_not_schedule_next():
    source = (NATIVE / "worker.py").read_text(encoding="utf-8")
    start = source.index("    except WorkerShutdown as stop:")
    end = source.index("    except DownloadCancelled:", start)
    block = source[start:end]
    check("freeze_after_external_stop" in block, "arrêt externe ne gèle pas la file")
    check("start_next_if_any()" not in block, "arrêt externe lance encore le suivant")
    check("cleanup_cancelled_files" not in block, "arrêt externe supprime encore les partiels")


def test_error_catalog_required_messages():
    errors = load_module(
        NATIVE / "errors.py",
        f"kitty_errors_{os.getpid()}_{time.time_ns()}",
        Path.home(),
    )

    cases = [
        ("ERROR: No audio formats found!", {}, "no_audio", "Aucun flux audio disponible"),
        ("HTTP Error 403: Forbidden; Sign in to confirm you're not a bot on YouTube", {"youtube_auth": True}, "youtube_session_expired", "Session YouTube expirée"),
        ("[Errno 28] No space left on device", {}, "disk_full", "Espace disque insuffisant"),
        ("ffmpeg not found. Please install ffmpeg", {}, "ffmpeg_missing", "ffmpeg introuvable"),
        ("ERROR: This video is private", {}, "video_private", "Vidéo privée"),
        ("ERROR: This video has been removed by the uploader", {}, "content_deleted", "Contenu supprimé"),
        ("Aucun média individuel accessible n’a été trouvé dans cette collection.", {}, "collection_empty", "Collection vide"),
        ("URLError: <urlopen error [Errno 104] Connection reset by peer>", {}, "network_interrupted", "Connexion interrompue"),
    ]

    for raw, kwargs, code, message in cases:
        info = errors.classify_backend_error(raw, **kwargs)
        equal(info["code"], code, f"code erreur pour {raw}")
        equal(info["message"], message, f"message erreur pour {raw}")
        check(bool(info["hint"]), f"hint absent pour {code}")
        equal(info["detail"], raw, f"détail technique perdu pour {code}")


def test_error_catalog_extended_backend_families():
    errors = load_module(
        NATIVE / "errors.py",
        f"kitty_errors_extended_{os.getpid()}_{time.time_ns()}",
        Path.home(),
    )

    cases = {
        "HTTP Error 429: Too Many Requests": "rate_limited",
        "This video is not available in your country": "geo_restricted",
        "This video is age-restricted": "age_restricted",
        "This video is DRM protected": "drm_protected",
        "Unsupported URL: https://example.invalid/x": "unsupported_url",
        "Requested format is not available": "format_unavailable",
        "ffprobe est requis pour détecter le codec audio.": "ffprobe_missing",
        "No module named 'yt_dlp'": "ytdlp_missing",
        "Permission denied: /root/secret": "permission_denied",
        "Le téléchargement n’a produit aucun fichier média valide.": "media_invalid",
        "Unable to extract uploader id": "extraction_failed",
    }

    for raw, expected in cases.items():
        info = errors.classify_backend_error(raw)
        equal(info["code"], expected, f"famille erreur {raw}")


def test_error_payload_keeps_flow_code_and_detail():
    errors = load_module(
        NATIVE / "errors.py",
        f"kitty_errors_payload_{os.getpid()}_{time.time_ns()}",
        Path.home(),
    )

    payload = errors.normalize_error_payload({
        "ok": False,
        "code": "already_downloaded",
        "error": "Ce média a déjà été téléchargé.",
    })
    equal(payload["code"], "already_downloaded", "flow code modifié")
    equal(payload["error_code"], "already_downloaded", "error_code absent")
    equal(payload["error"], "Déjà téléchargé", "message duplicate")
    check(bool(payload["error_hint"]), "hint duplicate absent")

    raw = "ERROR: [youtube] abc: HTTP Error 403: Forbidden; Sign in to confirm you're not a bot"
    payload = errors.normalize_error_payload(
        {"ok": False, "error": raw},
        youtube_auth=True,
    )
    equal(payload["error"], "Session YouTube expirée", "message brut exposé")
    equal(payload["error_detail"], raw, "détail technique non conservé")


def test_worker_terminal_error_contract():
    source = (NATIVE / "worker.py").read_text(encoding="utf-8")
    check("classify_backend_error(" in source, "worker ne classifie pas ses erreurs")
    check('active["error_code"] = info["code"]' in source, "error_code non persisté")
    check('active["error_detail"] = info["detail"]' in source, "détail technique non persisté")
    check('active["error_hint"] = info["hint"]' in source, "hint non persisté")


def test_error_ui_contract():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")
    html = (EXT / "popup.html").read_text(encoding="utf-8")

    check("backendErrorMessage" in popup, "helper UI erreurs absent")
    check('statusEl.textContent = last.error || "Erreur du backend";' in popup, "message personnalisé final absent")
    check("last.error_hint" in popup, "hint final absent")
    check('job.error || "Erreur du backend"' in popup, "raison historique absente")
    check("itemError" in html, "style erreur historique absent")
    check('setVisualState("error", located.job.error || "Erreur")' in pill, "pill n’affiche pas le message backend")


def test_frontend_backend_compatibility_contract():
    with tempfile.TemporaryDirectory(prefix="kitty-compat-") as tmp:
        home = Path(tmp)
        compatibility = load_module(
            NATIVE / "compatibility.py",
            f"kitty_compat_{os.getpid()}_{time.time_ns()}",
            home,
        )
        version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
        proto = compatibility.NATIVE_PROTOCOL_VERSION

        same = compatibility.client_report({"version": version, "protocol": proto}, version)
        check(same.get("compatible") is True, "frontend/backend identiques incompatibles")
        equal(same.get("status"), "compatible", "statut compatibilité identique")

        skew = compatibility.client_report({"version": "8.11", "protocol": proto}, version)
        check(skew.get("compatible") is True, "version skew même protocole doit rester compatible")
        equal(skew.get("status"), "version_skew", "statut version skew")

        bad = compatibility.client_report({"version": version, "protocol": proto + 1}, version)
        check(bad.get("compatible") is False, "mismatch protocole non bloqué")
        check(bad.get("update_required") is True, "mismatch protocole sans update_required")


def test_native_protocol_blocks_incompatible_mutations():
    with tempfile.TemporaryDirectory(prefix="kitty-native-compat-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        env = clean_subprocess_env(home)
        proc = subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=25,
            check=False,
        )
        check(proc.returncode == 0, f"install compat échoué:\n{proc.stdout}")
        host_path = home / ".local" / "lib" / "kitty-download-manager" / "host.py"
        version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]

        good = native_call(host_path, home, {
            "action": "compatibility",
            "client": {"version": version, "protocol": 1},
        })
        check(good.get("ok") is True and good.get("compatibility", {}).get("compatible") is True,
              "handshake compatible échoué")

        blocked = native_call(host_path, home, {
            "action": "pause_queue",
            "client": {"version": version, "protocol": 999},
        })
        check(blocked.get("ok") is False, "mutation incompatible non bloquée")
        equal(blocked.get("error_code"), "incompatible_frontend_backend", "code mismatch protocole")


def test_dependency_update_risk_report_without_network():
    with tempfile.TemporaryDirectory(prefix="kitty-update-report-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_updates_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.dependency_status = lambda: {
            "items": [
                {"id": "python", "label": "Python", "required": True, "ok": True, "version": "3.13.5"},
                {"id": "yt_dlp", "label": "yt-dlp", "required": True, "ok": True, "version": "2026.09.01"},
                {"id": "ffmpeg", "label": "ffmpeg", "required": True, "ok": True, "version": "ffmpeg version 7.1"},
                {"id": "ffprobe", "label": "ffprobe", "required": True, "ok": True, "version": "ffprobe version 7.1"},
                {"id": "mutagen", "label": "Mutagen", "required": False, "ok": True, "version": "1.47.0"},
            ],
            "required_ok": True,
            "required_missing": [],
            "optional_missing": [],
        }
        host._parse_package_manager_updates = lambda: ({
            "python": {"current": "3.13.5", "available": "3.14.0"},
            "yt-dlp": {"current": "2026.09.01", "available": "2026.10.01"},
            "ffmpeg": {"current": "7.1", "available": "8.0"},
        }, "mock", False, True)
        host._pypi_latest = lambda distribution, timeout=5: (None, None)

        report = host.check_dependency_updates(
            client={"version": host.APP_VERSION, "protocol": host.NATIVE_PROTOCOL_VERSION},
            save_cache=False,
        )
        check(report.get("updates_available") >= 3, "updates mock non détectées")
        check(report.get("risky_updates") >= 2, "Python/ffmpeg major-minor risk non signalé")
        by_id = {item["id"]: item for item in report["items"]}
        check(by_id["python"]["potential_incompatibility"] is True, "Python 3.14 non marqué review")
        check(by_id["ffmpeg"]["potential_incompatibility"] is True, "ffmpeg 8 non marqué review")
        check(by_id["yt_dlp"]["potential_incompatibility"] is False, "yt-dlp update abusivement bloquée")


def _i18n_translation_map():
    source = (EXT / "i18n.js").read_text(encoding="utf-8")
    match = re.search(
        r"const FR_EN = Object\.freeze\(\s*(\{.*?\})\s*\);\s*const EN_FR",
        source,
        re.S,
    )
    check(match is not None, "table FR_EN i18n introuvable")
    return json.loads(match.group(1))


def test_i18n_backend_error_catalog_is_complete():
    translations = _i18n_translation_map()
    tree = ast.parse((NATIVE / "errors.py").read_text(encoding="utf-8"))

    catalog = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "CATALOG" for target in node.targets):
            catalog = ast.literal_eval(node.value)
            break

    check(isinstance(catalog, dict) and catalog, "catalogue erreurs backend introuvable")
    missing = []
    for code, entry in catalog.items():
        message, hint = entry[0], entry[1]
        if message not in translations:
            missing.append(f"{code}: message={message!r}")
        if hint not in translations:
            missing.append(f"{code}: hint={hint!r}")

    check(not missing, "traductions erreurs backend manquantes: " + "; ".join(missing))


def test_i18n_static_popup_french_is_covered():
    from html.parser import HTMLParser

    translations = _i18n_translation_map()
    html = (EXT / "popup.html").read_text(encoding="utf-8")

    class Collector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []
            self.ignored_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag in {"style", "script"}:
                self.ignored_depth += 1
                return
            if self.ignored_depth:
                return
            for name, value in attrs:
                if name in {"title", "aria-label", "placeholder"} and value:
                    self.values.append(value.strip())

        def handle_endtag(self, tag):
            if tag in {"style", "script"} and self.ignored_depth:
                self.ignored_depth -= 1

        def handle_data(self, data):
            if self.ignored_depth:
                return
            value = data.strip()
            if value:
                self.values.append(value)

    parser = Collector()
    parser.feed(html)

    allowed = {"Français"}
    accented = re.compile(r"[éèêëàâäùûüôöîïçÉÈÊÀÂÙÛÔÎÏÇœ]")
    french_terms = re.compile(
        r"\b(réglages|choisir|supprimer|vérifier|ouvrir|dossier|téléchargement|"
        r"dépendances|diagnostic|maintenance|nettoyer|langue|historique|file)\b",
        re.I,
    )

    missing = sorted({
        value
        for value in parser.values
        if value not in allowed
        and (accented.search(value) or french_terms.search(value))
        and value not in translations
    })
    check(not missing, "texte statique français non couvert par i18n: " + " | ".join(missing))


def test_english_ui_has_no_french_residue_in_real_browser():
    chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium_path is None:
        raise SkipTest("Chromium indisponible")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SkipTest(f"Playwright requis pour audit i18n English: {exc}")

    html = (EXT / "popup.html").read_text(encoding="utf-8")
    html = re.sub(r'<script src="[^"]+"></script>', '', html)
    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    bootstrap = r'''window.__store = {uiLanguage:"en"};
window.browser = {
  runtime: {
    getManifest: () => ({version:"8.31"}),
    sendNativeMessage: async (host,payload) => {
      const action = payload?.action;
      if (action === "status") return {ok:true,state:{
        active:null,
        queue:[{
          id:"q1",status:"paused",paused:true,title:"User title",mode:"best",
          url:"https://youtube.com/watch?v=q1",metadata_status:"ready",
          output_dir:"/tmp/kitty"
        }],
        history:[{
          id:"h1",status:"error",title:"Failed item",mode:"audio",
          url:"https://youtube.com/watch?v=h1",
          error:"Connexion interrompue",
          error_hint:"Vérifie la connexion Internet puis relance le téléchargement.",
          output_dir:"/tmp/kitty"
        }],
        queue_paused:false
      }};
      if (action === "youtube_auth_status") return {ok:true,configured:false,enabled:false,state:"missing"};
      if (action === "compatibility") return {ok:true,compatibility:{
        compatible:true,frontend_version:"8.31",backend_version:"8.31",
        frontend_protocol:1,backend_protocol:1
      }};
      if (action === "diagnostics") return {
        ok:true,
        overall:"warning",
        dependencies:{
          items:[
            {id:"python",label:"Python",required:true,ok:true,version:"3.13"},
            {id:"yt_dlp",label:"yt-dlp",required:true,ok:true,version:"2026.10.01"},
            {id:"ffmpeg",label:"ffmpeg",required:true,ok:true,version:"7.1"},
            {id:"ffprobe",label:"ffprobe",required:true,ok:true,version:"7.1"},
            {id:"mutagen",label:"Mutagen",required:false,ok:false,version:null}
          ],
          required_missing:[],
          optional_missing:["mutagen"]
        },
        system:{
          destination:{writable:true,write_tested:true,free_bytes:5368709120},
          runtime_files:{ok:true},
          state_ok:true,
          migration:{status:"completed",legacy_found:false},
          cache:{
            total_bytes:8388608,
            logs_bytes:1048576,
            reclaimable_bytes:2097152,
            temporary_bytes:524288,
            update_backups_bytes:1048576,
            log_max_file_bytes:2097152,
            log_max_archives:4,
            orphan_partials:{count:2,bytes:12345}
          }
        },
        compatibility:{
          compatible:true,frontend_version:"8.31",backend_version:"8.31",
          frontend_protocol:1,backend_protocol:1
        },
        updates_cached:null
      };
      if (action === "clean_cache") return {
        ok:true,freed_bytes:2097152,downloads_touched:false,orphan_partials_deleted:0,
        cache:{
          total_bytes:6291456,logs_bytes:4096,reclaimable_bytes:0,
          temporary_bytes:0,update_backups_bytes:1048576,
          log_max_file_bytes:2097152,log_max_archives:4,
          orphan_partials:{count:2,bytes:12345}
        }
      };
      return {ok:true};
    },
    sendMessage: async message => (
      message?.type === "kitty-get-output-dir"
        ? {ok:true,settings:{output_dir:"/tmp/kitty"}}
        : {ok:true}
    )
  },
  storage: {local:{
    get: async keys => {
      if (typeof keys === "string") return {[keys]:window.__store[keys]};
      const out = {};
      const list = Array.isArray(keys) ? keys : Object.keys(keys || {});
      for (const key of list) if (key in window.__store) out[key] = window.__store[key];
      return out;
    },
    set: async value => Object.assign(window.__store, value)
  }},
  tabs:{
    query:async()=>[{id:1,url:"https://youtube.com/watch?v=current"}],
    sendMessage:async()=>({ok:false}),
    create:async()=>({})
  }
};'''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chromium_path,
            headless=True,
            args=["--no-sandbox","--disable-gpu"],
        )
        try:
            page = browser.new_page(viewport={"width":500,"height":1000})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.set_content(html)
            page.add_script_tag(content=bootstrap)
            page.add_script_tag(content=i18n)
            page.add_script_tag(content=shared)
            page.add_script_tag(content=popup)
            page.wait_for_timeout(250)

            page.locator("#openSettings").click()
            page.wait_for_timeout(150)

            equal(page.locator("#settingsView h2").inner_text(), "Settings", "English non restauré au démarrage")
            equal(page.locator("#cleanCache").inner_text(), "Clean cache", "cache maintenance non traduit")
            check("Dependencies" in page.locator("#settingsView").inner_text(), "dépendances non traduites")
            check("Diagnostics" in page.locator("#settingsView").inner_text(), "diagnostic non traduit")

            # Open the two sections whose body content is intentionally hidden by default.
            page.locator('[data-settings-section="diagnostic"] .settingsGroupToggle').click()
            page.locator('[data-settings-section="maintenance"] .settingsGroupToggle').click()
            page.wait_for_timeout(80)
            check("Local cache" in page.locator("#settingsView").inner_text(), "cache local non traduit")
            check("Orphan partials" in page.locator("#settingsView").inner_text(), "partiels orphelins non traduits")

            visible_settings = page.locator("#settingsView").evaluate(
                "el => { const clone=el.cloneNode(true); clone.querySelector('#uiLanguage')?.remove(); return clone.innerText; }"
            )
            forbidden = [
                "Réglages", "Choisir", "Nettoyer le cache", "Dépendances",
                "Vérifier les mises à jour", "Ouvrir les logs", "Réinitialiser Kitty",
                "Partiels orphelins", "Récupérable", "Chargement…",
            ]
            leaks = [token for token in forbidden if token in visible_settings]
            check(not leaks, "résidus français Settings English: " + ", ".join(leaks))

            page.locator("#cleanCache").click()
            page.wait_for_timeout(180)
            status = page.locator("#settingsStatus").inner_text()
            check(
                "Cache cleaned" in status or "Nothing to clean" in status,
                "statut nettoyage cache non traduit",
            )

            page.locator("#backToMain").click()
            page.locator("#queueToggle").click()
            page.locator("#historyToggle").click()
            page.wait_for_timeout(150)
            main_text = page.locator("#mainView").inner_text()
            check("Best quality" in main_text, "mode dynamique non traduit")
            check("Retry" in main_text, "action historique Retry non traduite")
            check("Connection interrupted" in main_text, "erreur backend historique non traduite")
            main_forbidden = ["Meilleure qualité", "Relancer", "Connexion interrompue", "En pause", "Historique"]
            leaks = [token for token in main_forbidden if token in main_text]
            check(not leaks, "résidus français vue principale English: " + ", ".join(leaks))

            equal(errors, [], "exception JS pendant audit English")
        finally:
            browser.close()


def test_i18n_display_layer_keeps_internal_contracts():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")
    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")

    check((EXT / "i18n.js").exists(), "couche i18n absente")
    check('<option value="fr">Français</option>' in html, "option Français absente")
    check('<option value="en">English</option>' in html, "option English absente")
    check('id="uiLanguage"' in html, "sélecteur de langue absent")
    check('browser.storage.local.set({ uiLanguage: language })' in popup, "langue non persistée")
    check('"uiLanguage"' in pill, "pill ne lit pas la langue UI")

    for internal in ('data-pill-style="minimal"', 'data-pill-style="cat"', 'data-pill-style="classic"'):
        check(internal in html, f"clé interne modifiée: {internal}")
    check('new Set(["minimal", "cat", "classic"])' in pill, "clés internes pill modifiées")
    check('type: "kitty-pill-download"' in pill, "message interne pill modifié")
    check('action: "download"' in popup, "action Native Messaging download modifiée")
    check('const NATIVE_PROTOCOL_VERSION = 1;' in (EXT / "shared.js").read_text(encoding="utf-8"), "protocole interne modifié")

    content_js = manifest["content_scripts"][0]["js"]
    check(content_js.index("i18n.js") < content_js.index("shared.js"), "i18n content script chargé trop tard")
    check('"Classique": "Classic"' in i18n, "traduction Classique absente")
    check('"Réglages": "Settings"' in i18n, "traduction Réglages absente")


def test_language_toggle_popup_in_real_browser():
    chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium_path is None:
        raise SkipTest("Chromium indisponible")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SkipTest(f"Playwright requis pour test i18n popup: {exc}")

    html = (EXT / "popup.html").read_text(encoding="utf-8")
    html = re.sub(r'<script src="[^"]+"></script>', '', html)
    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    bootstrap = r'''window.__store = {};
window.browser = {
  runtime: {
    getManifest: () => ({version:"8.31"}),
    sendNativeMessage: async (host,payload) => {
      const action = payload?.action;
      if (action === "status") return {ok:true,state:{active:null,queue:[],history:[],queue_paused:false}};
      if (action === "youtube_auth_status") return {ok:true,configured:false,enabled:false,state:"missing"};
      if (action === "compatibility") return {ok:true,compatibility:{compatible:true,frontend_version:"8.31",backend_version:"8.31",frontend_protocol:1,backend_protocol:1}};
      if (action === "diagnostics") return {ok:true,overall:"ready",dependencies:{items:[],required_missing:[],optional_missing:[]},system:{destination:{writable:true,write_tested:false,free_bytes:1000000},runtime_files:{ok:true},state_ok:true,migration:{status:"completed",legacy_found:false}},compatibility:{compatible:true,frontend_version:"8.31",backend_version:"8.31"},updates_cached:null};
      return {ok:true};
    },
    sendMessage: async message => message?.type === "kitty-get-output-dir" ? {ok:true,settings:{output_dir:"/tmp/kitty"}} : {ok:true}
  },
  storage: {local:{
    get: async keys => {
      if (typeof keys === "string") return {[keys]:window.__store[keys]};
      const out = {};
      for (const key of (Array.isArray(keys) ? keys : Object.keys(keys || {}))) if (key in window.__store) out[key] = window.__store[key];
      return out;
    },
    set: async value => Object.assign(window.__store, value)
  }},
  tabs: {query:async()=>[{id:1,url:"https://example.com/video"}],sendMessage:async()=>({ok:false}),create:async()=>({})}
};'''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chromium_path,
            headless=True,
            args=["--no-sandbox","--disable-gpu"],
        )
        try:
            page = browser.new_page(viewport={"width":500,"height":900})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.set_content(html)
            page.add_script_tag(content=bootstrap)
            page.add_script_tag(content=i18n)
            page.add_script_tag(content=shared)
            page.add_script_tag(content=popup)
            page.wait_for_timeout(160)

            page.locator("#openSettings").click()
            equal(page.locator("#settingsView h2").inner_text(), "Réglages", "français non conservé par défaut")

            page.locator("#uiLanguage").select_option("en")
            page.wait_for_timeout(100)
            equal(page.locator("#settingsView h2").inner_text(), "Settings", "Réglages non traduit")
            equal(page.locator("#chooseDestination").inner_text(), "Choose…", "bouton destination non traduit")
            equal(page.locator("#runDiagnostics").inner_text(), "Check Kitty now", "diagnostic non traduit")
            equal(page.evaluate("window.__store.uiLanguage"), "en", "langue anglaise non persistée")
            equal(page.locator("html").get_attribute("lang"), "en", "lang HTML non synchronisée")

            page.locator("#backToMain").click()
            equal(page.locator("#download").inner_text(), "Add download", "bouton download dynamique non traduit")

            page.locator("#openSettings").click()
            page.locator("#uiLanguage").select_option("fr")
            page.wait_for_timeout(100)
            equal(page.locator("#settingsView h2").inner_text(), "Réglages", "retour français impossible")
            equal(page.locator("#chooseDestination").inner_text(), "Choisir…", "bouton destination non restauré en français")
            equal(page.evaluate("window.__store.uiLanguage"), "fr", "retour français non persisté")
            equal(errors, [], "exception JS pendant changement de langue")
        finally:
            browser.close()


def test_language_toggle_pill_in_real_browser():
    chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium_path is None:
        raise SkipTest("Chromium indisponible")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SkipTest(f"Playwright requis pour test i18n pill: {exc}")

    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")
    source = (EXT / "content-pill.js").read_text(encoding="utf-8").replace('attachShadow({ mode: "closed" })', 'attachShadow({ mode: "open" })', 1)

    bootstrap = r'''window.__listener = null;
window.KittyShared = {
  COLORS:{blue:"#2A62BB",blueHover:"#3471D4",metadata:"#E6B85C",downloading:"#4AA3DF",success:"#63D98B",error:"#EF6D6D"},
  jobPhase:job=>job?.status||"queued",jobPercent:()=>0,findJob:()=>null,queuePosition:()=>null,compactPosition:()=>""
};
window.KittyMediaResolver = {resolveMediaUrlForPage:()=>({ok:true,url:"https://example.com/video"}),comparableMediaUrl:v=>String(v||"")};
window.browser = {
  storage:{local:{get:async()=>({pillEnabled:true,pillScope:"all",pillStyle:"classic",uiLanguage:"en",kittyPillPosition:null}),set:async()=>{}},onChanged:{addListener:fn=>window.__listener=fn}},
  runtime:{sendMessage:async m=>m?.type==="kitty-pill-status"?{ok:true,state:{active:null,queue:[],history:[]}}:{ok:true,job_id:"j"},onMessage:{addListener:()=>{}}}
};'''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chromium_path,
            headless=True,
            args=["--no-sandbox","--disable-gpu"],
        )
        try:
            page = browser.new_page(viewport={"width":900,"height":600})
            page.set_content("<!doctype html><html><body><video></video></body></html>")
            page.add_script_tag(content=bootstrap)
            page.add_script_tag(content=i18n)
            page.add_script_tag(content=source)
            page.wait_for_selector("#kitty-download-manager-pill-host", state="attached")
            button = page.locator("#kitty-download-manager-pill-host").locator("#download")
            equal(button.get_attribute("title"), "Download this page", "pill non anglaise au démarrage")

            page.evaluate("window.__listener({uiLanguage:{oldValue:'en',newValue:'fr'}}, 'local')")
            page.wait_for_timeout(100)
            equal(button.get_attribute("title"), "Télécharger cette page", "pill ne revient pas en français")
        finally:
            browser.close()


def test_popup_native_protocol_initialization_order():
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    destructure = popup.index("const {\n  NATIVE_PROTOCOL_VERSION,")
    client = popup.index("const NATIVE_CLIENT = Object.freeze")
    check(
        destructure < client,
        "NATIVE_PROTOCOL_VERSION utilisé avant son initialisation — popup gelée",
    )


def test_popup_startup_async_order():
    node = shutil.which("node")
    if not node:
        raise SkipTest("Node indisponible")
    result = subprocess.run([node, str(ROOT / "tests" / "test-popup-startup.js")],
                            capture_output=True, text=True, timeout=15)
    check(result.returncode == 0, result.stdout + result.stderr)


def test_popup_ui_smoke_in_real_browser():
    chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium_path is None:
        raise SkipTest("Chromium indisponible")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SkipTest(f"Playwright requis pour le smoke test popup: {exc}")

    html = (EXT / "popup.html").read_text(encoding="utf-8")
    html = re.sub(r'<script src="[^"]+"></script>', '', html)
    i18n = (EXT / "i18n.js").read_text(encoding="utf-8")
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    bootstrap = r'''window.browser = {
  runtime: {
    getManifest: () => ({version: "8.31"}),
    sendNativeMessage: async (host, payload) => {
      const action = payload?.action;
      if (action === "status") return {ok:true,state:{active:null,queue:[],history:[],queue_paused:false}};
      if (action === "youtube_auth_status") return {ok:true,configured:false,enabled:false,state:"missing"};
      if (action === "compatibility") return {ok:true,compatibility:{compatible:true,frontend_version:"8.31",backend_version:"8.31",frontend_protocol:1,backend_protocol:1}};
      if (action === "diagnostics") return {ok:true,overall:"ready",dependencies:{items:[],required_missing:[],optional_missing:[]},system:{destination:{writable:true,write_tested:false,free_bytes:1000000},runtime_files:{ok:true},state_ok:true,migration:{status:"completed",legacy_found:false}},compatibility:{compatible:true,frontend_version:"8.31",backend_version:"8.31"},updates_cached:null};
      return {ok:true};
    },
    sendMessage: async message => {
      if (message?.type === "kitty-get-output-dir") return {ok:true,settings:{output_dir:"/tmp/kitty-smoke"}};
      return {ok:true};
    }
  },
  storage: {local:{get:async()=>({}),set:async()=>{}}},
  tabs: {
    query: async () => [{id:1,url:"https://example.com/video"}],
    sendMessage: async () => ({ok:false}),
    create: async () => ({})
  }
};'''

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chromium_path,
            headless=True,
            args=["--no-sandbox", "--disable-gpu"],
        )
        try:
            page = browser.new_page(viewport={"width": 500, "height": 900})
            page_errors = []
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            page.set_content(html)
            page.add_script_tag(content=bootstrap)
            page.add_script_tag(content=i18n)
            page.add_script_tag(content=shared)
            page.add_script_tag(content=popup)
            page.wait_for_timeout(120)

            equal(page_errors, [], "exception JavaScript au démarrage du popup")

            page.locator("#modeButton").click()
            check(page.locator("#modeMenu").is_visible(), "menu format non cliquable après démarrage")
            page.locator("#modeButton").click()

            page.locator("#openSettings").click()
            check(
                not page.locator("#settingsView").evaluate("el => el.classList.contains('hidden')"),
                "bouton Réglages inactif",
            )
            check(
                page.locator("#mainView").evaluate("el => el.classList.contains('hidden')"),
                "vue principale non masquée",
            )

            cookies = page.locator('[data-settings-section="cookies"]')
            check(cookies.evaluate("el => el.classList.contains('collapsed')"), "Cookies non fermé initialement")
            cookies.locator(".settingsGroupToggle").click()
            check(
                not cookies.evaluate("el => el.classList.contains('collapsed')"),
                "section Cookies non dépliable",
            )

            page.locator("#pillStyleButton").click()
            check(page.locator("#pillStyleMenu").is_visible(), "menu Style du pill non cliquable")

            page.locator("#backToMain").click()
            check(
                not page.locator("#mainView").evaluate("el => el.classList.contains('hidden')"),
                "retour vers la vue principale inactif",
            )

            equal(page_errors, [], "exception JavaScript pendant l'interaction popup")
            page.close()
        finally:
            browser.close()


def test_update_diagnostic_ui_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    js = (EXT / "popup.js").read_text(encoding="utf-8")
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    background = (EXT / "background.js").read_text(encoding="utf-8")

    for element_id in ("diagnosticUpdateMark", "checkUpdates", "downloadKittyUpdate"):
        check(f'id="{element_id}"' in html, f"UI update absente: {element_id}")
    check("diagnosticUpdateMark.review" in html, "style update potentiellement incompatible absent")
    check("diagnosticUpdateMark.incompatible" in html, "style mismatch frontend/backend absent")
    check("renderDiagnosticUpdateMark" in js, "renderer icône update absent")
    check('nativeMessage({ action: "check_updates" })' in js, "bouton check_updates non branché")
    check('nativeMessage({ action: "download_kitty_update" })' in js, "bouton download update non branché")
    check("SHA-256" in js and "Télécharger la mise à jour" in html, "UI vérification SHA-256 absente")
    check("Vérifier les mises à jour" in html, "libellé check update absent")
    check("utilise le réseau uniquement quand tu le demandes" in html, "confidentialité réseau non explicitée")
    check("NATIVE_PROTOCOL_VERSION = 1" in shared, "protocole frontend absent")
    check("ensureNativeCompatibility" in js, "handshake popup absent")
    check("ensureCompatibility" in background, "handshake pill/background absent")


def test_context_menu_one_click_uses_saved_mode():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    check("menus" in manifest.get("permissions", []), "permission menus absente")

    background = (EXT / "background.js").read_text(encoding="utf-8")
    check('CONTEXT_MENU_ID = "kitty-download-with-kitty"' in background, "ID menu contextuel absent")
    check('"Télécharger avec Kitty"' in background and '"Download with Kitty"' in background, "libellé FR/EN absent")
    check("parentId" not in background, "le clic droit ne doit pas créer de sous-menu")
    check('browser.storage.local.get("selectedMode")' in background, "format sauvegardé non utilisé")

    node = shutil.which("node")
    if not node:
        skip("Node.js absent")
        return

    shared_path = (EXT / "shared.js").as_posix()
    background_path = (EXT / "background.js").as_posix()
    script = f"""
const fs = require('fs');
const vm = require('vm');
let clicked = null;
let created = null;
const sent = [];
global.browser = {{
  runtime: {{
    getManifest: () => ({{version:'8.31'}}),
    sendNativeMessage: async (_host, payload) => {{
      sent.push(payload);
      if (payload.action === 'compatibility') return {{ok:true, compatibility:{{compatible:true}}}};
      return {{ok:true, queued:true}};
    }},
    onMessage: {{ addListener: () => {{}} }}
  }},
  storage: {{
    local: {{
      get: async key => {{
        if (key === 'uiLanguage') return {{uiLanguage:'fr'}};
        if (key === 'selectedMode') return {{selectedMode:'mp3'}};
        return {{}};
      }},
      set: async () => {{}}
    }},
    onChanged: {{ addListener: () => {{}} }}
  }},
  menus: {{
    remove: async () => {{}},
    create: cfg => {{ created = cfg; return cfg.id; }},
    onClicked: {{ addListener: fn => {{ clicked = fn; }} }}
  }}
}};
vm.runInThisContext(fs.readFileSync({json.dumps(shared_path)}, 'utf8'), {{filename:'shared.js'}});
vm.runInThisContext(fs.readFileSync({json.dumps(background_path)}, 'utf8'), {{filename:'background.js'}});
(async () => {{
  await new Promise(r => setTimeout(r, 0));
  if (!created || created.id !== 'kitty-download-with-kitty') throw new Error('menu non créé');
  if (created.parentId) throw new Error('sous-menu inattendu');
  if (created.title !== 'Télécharger avec Kitty') throw new Error('titre FR incorrect: ' + created.title);
  if (!Array.isArray(created.contexts) || !created.contexts.includes('video') || !created.contexts.includes('link')) throw new Error('contextes incomplets');
  if (typeof clicked !== 'function') throw new Error('listener clic absent');

  await clicked({{menuItemId:'kitty-download-with-kitty', mediaType:'video', srcUrl:'blob:https://www.youtube.com/abc', pageUrl:'https://www.youtube.com/watch?v=abc'}}, {{url:'https://www.youtube.com/watch?v=abc'}});
  await new Promise(r => setTimeout(r, 0));
  let downloads = sent.filter(x => x.action === 'download');
  if (downloads.length !== 1) throw new Error('download YouTube non envoyé');
  if (downloads[0].url !== 'https://www.youtube.com/watch?v=abc') throw new Error('fallback page YouTube incorrect: ' + downloads[0].url);
  if (downloads[0].mode !== 'mp3') throw new Error('mode sauvegardé non repris: ' + downloads[0].mode);

  await clicked({{menuItemId:'kitty-download-with-kitty', linkUrl:'https://vimeo.com/123', pageUrl:'https://example.com/feed'}}, {{url:'https://example.com/feed'}});
  await new Promise(r => setTimeout(r, 0));
  downloads = sent.filter(x => x.action === 'download');
  if (downloads.length !== 2 || downloads[1].url !== 'https://vimeo.com/123') throw new Error('URL de lien non prioritaire');
}})().catch(err => {{ console.error(err.stack || err); process.exit(1); }});
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
    check(result.returncode == 0, f"clic droit Kitty invalide: {result.stderr or result.stdout}")


def test_github_release_check_and_sha256_download():
    with tempfile.TemporaryDirectory(prefix="kitty-release-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        host = load_module(NATIVE / "host.py", f"kitty_host_release_{os.getpid()}_{time.time_ns()}", home)

        asset_bytes = (b"KITTY-RELEASE-ZIP\n" * 257) + b"END"
        digest = hashlib.sha256(asset_bytes).hexdigest()
        release_payload = {
            "tag_name": "v8.31",
            "html_url": "https://github.com/sususususmomo/kitty-download-manager-releases/releases/tag/v8.31",
            "published_at": "2026-10-03T00:00:00Z",
            "assets": [{
                "name": "kitty-download-manager-v8.31.zip",
                "browser_download_url": "https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/v8.31/kitty-download-manager-v8.31.zip",
                "size": len(asset_bytes),
                "digest": f"sha256:{digest}",
            }],
        }
        release_json = json.dumps(release_payload).encode("utf-8")

        class FakeResponse:
            def __init__(self, payload):
                self.stream = io.BytesIO(payload)
            def read(self, size=-1):
                return self.stream.read(size)
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                self.stream.close()
                return False

        def fake_urlopen(request, timeout=None):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url == host.KITTY_RELEASE_API:
                return FakeResponse(release_json)
            if url == release_payload["assets"][0]["browser_download_url"]:
                return FakeResponse(asset_bytes)
            raise TestFailure(f"URL réseau inattendue dans le test release: {url}")

        host.urlopen = fake_urlopen
        report = host.check_kitty_release(save_cache=True)
        check(report.get("ok") is True, "check release GitHub simulé échoué")
        check(report.get("update_available") is True, "release v8.31 non détectée")
        equal(report.get("latest_version"), "8.31", "version release normalisée")
        equal(report.get("asset_sha256"), digest, "digest GitHub non lu")
        check(report.get("download_supported") is True, "download devrait être autorisé avec SHA-256")
        check(host.KITTY_RELEASE_CACHE_FILE.is_file(), "cache release absent")

        result = host.download_kitty_update()
        check(result.get("ok") is True, f"download release simulé échoué: {result}")
        check(result.get("verified") is True, "SHA-256 non marqué vérifié")
        equal(result.get("sha256"), digest, "SHA-256 téléchargé incorrect")
        target = home / "Downloads" / "kitty-download-manager-v8.31.zip"
        equal(target.read_bytes(), asset_bytes, "archive vérifiée non écrite dans Downloads")


def test_github_release_rejects_bad_sha256():
    with tempfile.TemporaryDirectory(prefix="kitty-release-badsha-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        host = load_module(NATIVE / "host.py", f"kitty_host_badsha_{os.getpid()}_{time.time_ns()}", home)

        asset_bytes = b"CORRUPTED-RELEASE"
        expected_digest = hashlib.sha256(b"EXPECTED-RELEASE").hexdigest()
        release_payload = {
            "tag_name": "v8.31",
            "html_url": "https://github.com/sususususmomo/kitty-download-manager-releases/releases/tag/v8.31",
            "published_at": "2026-10-03T00:00:00Z",
            "assets": [{
                "name": "kitty-download-manager-v8.31.zip",
                "browser_download_url": "https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/v8.31/kitty-download-manager-v8.31.zip",
                "size": len(asset_bytes),
                "digest": f"sha256:{expected_digest}",
            }],
        }
        release_json = json.dumps(release_payload).encode("utf-8")

        class FakeResponse:
            def __init__(self, payload):
                self.stream = io.BytesIO(payload)
            def read(self, size=-1):
                return self.stream.read(size)
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                self.stream.close()
                return False

        def fake_urlopen(request, timeout=None):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if url == host.KITTY_RELEASE_API:
                return FakeResponse(release_json)
            return FakeResponse(asset_bytes)

        host.urlopen = fake_urlopen
        result = host.download_kitty_update()
        check(result.get("ok") is False, "archive au mauvais SHA-256 acceptée")
        equal(result.get("code"), "kitty_update_integrity_failed", "code mauvais SHA-256")
        check(result.get("verified") is False, "mauvais SHA-256 marqué vérifié")
        check(not (home / "Downloads" / "kitty-download-manager-v8.31.zip").exists(), "archive corrompue conservée")



def test_safe_updater_preserves_user_state():
    with tempfile.TemporaryDirectory(prefix="kitty-updater-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        env = clean_subprocess_env(home)

        install = subprocess.run(
            ["bash", str(ROOT / "install.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        check(install.returncode == 0, f"install pré-update échoué:\n{install.stdout}")

        install_dir = home / ".local" / "lib" / "kitty-download-manager"
        host_path = install_dir / "host.py"
        host_path.write_text(
            host_path.read_text(encoding="utf-8").replace('APP_VERSION = "8.31"', 'APP_VERSION = "8.14"', 1),
            encoding="utf-8",
        )

        config = home / ".config" / "kitty-download-manager"
        settings = config / "settings.json"
        settings.write_text(json.dumps({"output_dir": "/tmp/kitty-custom"}), encoding="utf-8")
        auth = config / "youtube-auth"
        auth.mkdir(parents=True, exist_ok=True)
        (auth / "cookies.txt").write_text("COOKIE-SENTINEL", encoding="utf-8")

        queue = home / ".cache" / "kitty-download-manager" / "queue.json"
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_text(json.dumps({
            "state_version": 2,
            "active": None,
            "queue": [{"id": "keep-me", "status": "queued", "paused": True, "title": "Keep"}],
            "history": [{"id": "history-keep", "status": "finished"}],
            "queue_paused": True,
        }), encoding="utf-8")

        update = subprocess.run(
            ["bash", str(ROOT / "update.sh"), "--skip-network"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=35,
            check=False,
        )
        check(update.returncode == 0, f"update.sh échoué:\n{update.stdout}")
        check("8.14 → 8.31" in update.stdout, "résumé version updater absent")
        check('APP_VERSION = "8.31"' in host_path.read_text(encoding="utf-8"), "backend non remplacé")
        equal(json.loads(settings.read_text(encoding="utf-8"))["output_dir"], "/tmp/kitty-custom", "settings perdus")
        equal((auth / "cookies.txt").read_text(encoding="utf-8"), "COOKIE-SENTINEL", "cookies perdus")
        state = json.loads(queue.read_text(encoding="utf-8"))
        check(any(j.get("id") == "keep-me" for j in state.get("queue", [])), "queue perdue")
        check(any(j.get("id") == "history-keep" for j in state.get("history", [])), "history perdu")
        check((home / ".local" / "bin" / "kitty-update").is_symlink(), "kitty-update helper absent")
        backups = list((home / ".cache" / "kitty-download-manager" / "update-backups").glob("backend-v8.14-*"))
        check(backups, "backup backend avant update absent")


def test_uninstaller_safe_and_purge_preserve_media():
    # Safe uninstall keeps config/cache/auth.
    with tempfile.TemporaryDirectory(prefix="kitty-uninstall-safe-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        env = clean_subprocess_env(home)
        proc = subprocess.run(["bash", str(ROOT / "install.sh")], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        check(proc.returncode == 0, "install avant uninstall safe")
        media = home / "Downloads" / "kitty-download-manager" / "song.mp3"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"MEDIA")
        auth = home / ".config" / "kitty-download-manager" / "youtube-auth"
        auth.mkdir(parents=True, exist_ok=True)
        (auth / "cookies.txt").write_text("KEEP", encoding="utf-8")

        out = subprocess.run(["bash", str(ROOT / "uninstall.sh")], cwd=ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        check(out.returncode == 0, f"uninstall safe échoué:\n{out.stdout}")
        check(not (home / ".local" / "lib" / "kitty-download-manager").exists(), "backend non supprimé")
        check(not (home / ".mozilla" / "native-messaging-hosts" / "com.kitty.download_manager.json").exists(), "manifest NM non supprimé")
        check((home / ".config" / "kitty-download-manager").exists(), "config supprimée par uninstall safe")
        check((home / ".cache" / "kitty-download-manager").exists(), "cache supprimé par uninstall safe")
        equal(media.read_bytes(), b"MEDIA", "média supprimé par uninstall safe")

    # Purge removes Kitty private state but still never removes downloaded media.
    with tempfile.TemporaryDirectory(prefix="kitty-uninstall-purge-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        env = clean_subprocess_env(home)
        proc = subprocess.run(["bash", str(ROOT / "install.sh")], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        check(proc.returncode == 0, "install avant purge")
        media = home / "Downloads" / "kitty-download-manager" / "song.mp3"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"MEDIA")

        out = subprocess.run(["bash", str(ROOT / "uninstall.sh"), "--purge", "--yes"], cwd=ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        check(out.returncode == 0, f"purge échouée:\n{out.stdout}")
        check(not (home / ".config" / "kitty-download-manager").exists(), "config non purgée")
        check(not (home / ".cache" / "kitty-download-manager").exists(), "cache non purgé")
        equal(media.read_bytes(), b"MEDIA", "média supprimé par purge")


def test_log_rotation_is_bounded():
    with tempfile.TemporaryDirectory(prefix="kitty-log-rotation-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        env = clean_subprocess_env(home)
        env["PYTHONPATH"] = str(NATIVE)

        script = r"""
import json
import runtime_storage as rs
rs.LOG_MAX_BYTES = 320
rs.LOG_ARCHIVE_COUNT = 2
for i in range(30):
    rs.append_log("line-%02d %s" % (i, "x" * 90))
print(json.dumps(rs.log_stats()))
"""
        proc = subprocess.run(
            [sys.executable, "-B", "-c", script],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        check(proc.returncode == 0, f"rotation logs échouée: {proc.stderr}")
        stats = json.loads(proc.stdout.strip())
        check(stats["current_bytes"] <= 320, "worker.log dépasse la limite configurée")
        check(stats["archive_count"] <= 2, "trop d'archives de logs")
        check(stats["archive_count"] >= 1, "rotation de logs non déclenchée")

        cache = home / ".cache" / "kitty-download-manager"
        check((cache / "worker.log").is_file(), "log courant absent")
        check((cache / "worker.log.1").is_file(), "première archive de log absente")

    worker = (NATIVE / "worker.py").read_text(encoding="utf-8")
    metadata = (NATIVE / "metadata.py").read_text(encoding="utf-8")
    check("append_log(message)" in worker, "worker n'utilise pas le writer borné")
    check('append_log(message, prefix="META")' in metadata, "metadata n'utilise pas le writer borné")


def test_cache_cleanup_is_safe_and_reports_sizes():
    with tempfile.TemporaryDirectory(prefix="kitty-cache-clean-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir(parents=True)
        cache = home / ".cache" / "kitty-download-manager"
        config = home / ".config" / "kitty-download-manager"
        output = home / "Downloads" / "kitty-download-manager"
        cache.mkdir(parents=True)
        config.mkdir(parents=True)
        output.mkdir(parents=True)

        (config / "settings.json").write_text(
            json.dumps({"output_dir": str(output)}), encoding="utf-8"
        )
        auth = config / "youtube-auth"
        auth.mkdir(parents=True)
        cookie = auth / "cookies.txt"
        cookie.write_text("COOKIE-SENTINEL", encoding="utf-8")

        media = output / "finished.mp3"
        media.write_bytes(b"MEDIA-SENTINEL")
        partial = output / "orphan.webm.part"
        partial.write_bytes(b"PARTIAL-SENTINEL")
        old = time.time() - (3 * 24 * 60 * 60)
        os.utime(partial, (old, old))

        state = {
            "state_version": 2,
            "active": None,
            "queue": [],
            "history": [{"id": "done", "status": "finished", "output_dir": str(output)}],
            "queue_paused": True,
        }
        (cache / "queue.json").write_text(json.dumps(state), encoding="utf-8")

        auth_jobs = cache / "auth-jobs"
        auth_jobs.mkdir()
        stale_auth = auth_jobs / "old.cookies.txt"
        stale_auth.write_text("STALE", encoding="utf-8")

        playlist_auth = cache / "playlist-auth"
        playlist_auth.mkdir()
        stale_playlist = playlist_auth / "old.cookies.txt"
        stale_playlist.write_text("STALE", encoding="utf-8")
        stale_time = time.time() - 7200
        os.utime(stale_playlist, (stale_time, stale_time))

        sessions = cache / "youtube-auth-sessions"
        sessions.mkdir()
        stale_token = "a" * 32
        stale_session = sessions / stale_token
        stale_session.mkdir()
        (stale_session / ".kitty-youtube-auth-session").write_text(stale_token, encoding="utf-8")
        (stale_session / "junk").write_bytes(b"SESSION")

        pending_token = "b" * 32
        pending_session = sessions / pending_token
        pending_session.mkdir()
        (pending_session / ".kitty-youtube-auth-session").write_text(pending_token, encoding="utf-8")
        (pending_session / "keep").write_bytes(b"PENDING")
        (cache / "youtube-auth-pending.json").write_text(
            json.dumps({"token": pending_token, "pid": None, "created_at": time.time()}),
            encoding="utf-8",
        )

        backups = cache / "update-backups"
        backups.mkdir()
        for i in range(5):
            backend = backups / f"backend-v8.{10+i}-20260101-00000{i}"
            backend.mkdir()
            (backend / "host.py").write_bytes(b"x" * (50 + i))
            manifest = backups / f"native-manifest-20260101-00000{i}.json"
            manifest.write_bytes(b"{}")
            queue_backup = backups / f"queue-pre-update-20260101-00000{i}.json"
            queue_backup.write_bytes(b"{}")
            stamp = time.time() - (100 - i)
            os.utime(backend, (stamp, stamp))
            os.utime(manifest, (stamp, stamp))
            os.utime(queue_backup, (stamp, stamp))

        state_backups = cache / "state-backups"
        state_backups.mkdir()
        protected_state_backup = state_backups / "queue-test.json"
        protected_state_backup.write_bytes(b"STATE")

        current_log = cache / "worker.log"
        current_log.write_bytes(b"CURRENT-LOG")
        (cache / "worker.log.1").write_bytes(b"OLD-LOG-1")
        (cache / "worker.log.2").write_bytes(b"OLD-LOG-2")

        client = {"version": "8.31", "protocol": 1}
        before = native_call(NATIVE / "host.py", home, {"action": "diagnostics", "client": client})
        check(before.get("ok") is True, "diagnostic cache avant nettoyage échoué")
        cache_before = before.get("system", {}).get("cache", {})
        check(cache_before.get("logs_bytes", 0) >= len(b"CURRENT-LOG"), "taille logs non reportée")
        check(cache_before.get("total_bytes", 0) > 0, "taille cache totale absente")
        check(cache_before.get("orphan_partials", {}).get("count", 0) >= 1, "partiel orphelin non détecté")

        result = native_call(NATIVE / "host.py", home, {"action": "clean_cache", "client": client})
        check(result.get("ok") is True, "clean_cache échoué")
        check(result.get("downloads_touched") is False, "clean_cache prétend toucher les téléchargements")
        equal(result.get("orphan_partials_deleted"), 0, "clean_cache a supprimé des partiels")
        check(result.get("freed_bytes", 0) > 0, "aucun octet libéré")

        equal(media.read_bytes(), b"MEDIA-SENTINEL", "média terminé touché par clean_cache")
        equal(partial.read_bytes(), b"PARTIAL-SENTINEL", ".part touché par clean_cache")
        equal(cookie.read_text(encoding="utf-8"), "COOKIE-SENTINEL", "cookies persistants touchés")
        check((cache / "queue.json").is_file(), "queue supprimée par clean_cache")
        check(current_log.is_file(), "log courant supprimé")
        check(not (cache / "worker.log.1").exists(), "ancienne archive de log non nettoyée")
        check(not stale_auth.exists(), "snapshot auth job obsolète non nettoyé")
        check(not stale_playlist.exists(), "snapshot playlist obsolète non nettoyé")
        check(not stale_session.exists(), "session YouTube jetable obsolète non nettoyée")
        check(pending_session.exists(), "session YouTube en cours supprimée")
        check(protected_state_backup.exists(), "backup d'état supprimé")

        equal(len(list(backups.glob("backend-v*"))), 3, "rétention backups backend incorrecte")
        equal(len(list(backups.glob("native-manifest-*.json"))), 3, "rétention manifests update incorrecte")
        equal(len(list(backups.glob("queue-pre-*.json"))), 3, "rétention backups queue update incorrecte")

        after = result.get("cache", {})
        check(after.get("total_bytes", 0) < cache_before.get("total_bytes", 0), "taille cache non réduite")
        check(after.get("orphan_partials", {}).get("count", 0) >= 1, "partiel orphelin masqué après nettoyage")


def test_cache_maintenance_ui_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    host = (NATIVE / "host.py").read_text(encoding="utf-8")

    for element_id in ("cleanCache", "cacheMaintenanceSummary", "cacheMaintenanceHint"):
        check(f'id="{element_id}"' in html, f"UI cache absente: {element_id}")
    check("Nettoyer le cache" in html, "bouton Nettoyer le cache absent")
    check("fichiers .part ne sont jamais supprimés" in html, "garantie .part absente")
    check('nativeMessage({ action: "clean_cache" })' in popup, "clean_cache non branché au frontend")
    check("renderCacheHealth" in popup, "métriques cache non rendues")
    check("Partiels orphelins" in popup, "partiels orphelins absents du diagnostic")
    check('elif action == "clean_cache"' in host, "action backend clean_cache absente")
    check('"downloads_touched": False' in host, "invariant téléchargements intacts absent")
    check('"orphan_partials_deleted": 0' in host, "invariant partiels intacts absent")


def test_dependency_diagnostics_contract():
    with tempfile.TemporaryDirectory(prefix="kitty-deps-diag-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_deps_{os.getpid()}_{time.time_ns()}",
            home,
        )

        # Les fichiers installés attendus sont recréés dans HOME isolé.
        host.WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.WORKER.write_text("# worker", encoding="utf-8")
        host.META_WORKER.write_text("# metadata", encoding="utf-8")
        host.DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        result = host.diagnostics(deep=True)
        check(result.get("ok") is True, "diagnostic structuré")
        check(result.get("overall") in {"ready", "warning", "error"}, "overall diagnostic")

        deps = result.get("dependencies", {}).get("items", [])
        ids = {dep.get("id") for dep in deps}
        check({"python", "yt_dlp", "ffmpeg", "ffprobe", "mutagen"}.issubset(ids), f"dépendances absentes: {ids}")

        required = {
            dep.get("id"): dep.get("required")
            for dep in deps
        }
        check(required.get("python") is True, "Python doit être requis")
        check(required.get("yt_dlp") is True, "yt-dlp doit être requis")
        check(required.get("ffmpeg") is True, "ffmpeg doit être requis")
        check(required.get("ffprobe") is True, "ffprobe doit être requis")
        check(required.get("mutagen") is False, "Mutagen doit rester optionnel")

        destination = result.get("system", {}).get("destination", {})
        check(destination.get("write_tested") is True, "test d’écriture destination non exécuté")
        check(destination.get("writable") is True, "destination test isolé non écrivable")

        leftovers = list(host.DEFAULT_OUTPUT_DIR.glob(".kitty-diagnostic-*.tmp"))
        equal(leftovers, [], "fichier diagnostic temporaire non supprimé")

        privacy = result.get("privacy", {})
        equal(privacy.get("network_used"), False, "diagnostic ne doit pas utiliser le réseau")
        equal(privacy.get("includes_urls"), False, "diagnostic ne doit pas inclure URL")
        equal(privacy.get("includes_titles"), False, "diagnostic ne doit pas inclure titres")
        equal(privacy.get("includes_cookies"), False, "diagnostic ne doit pas inclure cookies")


def test_dependency_missing_required_changes_overall():
    with tempfile.TemporaryDirectory(prefix="kitty-deps-missing-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_deps_missing_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.WORKER.write_text("# worker", encoding="utf-8")
        host.META_WORKER.write_text("# metadata", encoding="utf-8")
        host.DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        original_probe = host._command_probe

        def fake_command_probe(name, args, required=True):
            if name == "ffmpeg":
                return {
                    "id": "ffmpeg",
                    "label": "ffmpeg",
                    "required": True,
                    "ok": False,
                    "version": None,
                    "path": None,
                    "error": "non installé",
                }
            return original_probe(name, args, required)

        host._command_probe = fake_command_probe
        result = host.diagnostics(deep=False)

        equal(result.get("overall"), "error", "ffmpeg absent doit rendre overall error")
        check("ffmpeg" in result["dependencies"]["required_missing"], "ffmpeg absent non signalé")


def test_diagnostic_ui_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    js = (EXT / "popup.js").read_text(encoding="utf-8")

    for element_id in (
        "dependencyState",
        "dependencyList",
        "refreshDiagnostics",
        "diagnosticFacts",
        "runDiagnostics",
        "openLogs",
        "copyDiagnostics",
    ):
        check(f'id="{element_id}"' in html, f"UI diagnostic absente: {element_id}")

    check("renderDiagnosticsHealth" in js, "renderer état dépendances absent")
    check('nativeMessage({ action: "diagnostics", deep: Boolean(deep) })' in js, "diagnostic deep/shallow absent")
    check("aucune URL/titre de téléchargement" in js, "garantie confidentialité diagnostic absente")
    check("destination_free" in js, "espace libre non copié")
    check("Mutagen" in js, "Mutagen absent du diagnostic copié")


def test_diagnostic_copy_has_no_job_content():
    js = (EXT / "popup.js").read_text(encoding="utf-8")

    # Le diagnostic copié ne doit jamais ajouter des champs job URL/title.
    fn_start = js.index("function diagnosticsToText")
    fn_end = js.index("\n\nasync function copyText", fn_start)
    body = js[fn_start:fn_end]

    forbidden = (
        "active.url",
        "active.title",
        "job.url",
        "job.title",
        "cookies.txt",
        "cookie_value",
    )
    for token in forbidden:
        check(token not in body, f"contenu sensible dans diagnostic copié: {token}")


def test_metadata_spawn_is_observable_and_failure_is_terminal():
    with tempfile.TemporaryDirectory(prefix="kitty-metadata-supervision-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_meta_supervision_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.META_WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.META_WORKER.write_text("# metadata worker", encoding="utf-8")

        job = {
            "id": "meta-job",
            "url": "https://example.com/media",
            "mode": "audio",
            "title": "",
            "status": "queued",
            "metadata_status": "pending",
        }

        host.with_state(lambda d: d["queue"].append(dict(job)))

        class FakeProc:
            pid = 456789

        original_popen = host.subprocess.Popen
        try:
            host.subprocess.Popen = lambda *args, **kwargs: FakeProc()
            pid = host.spawn_metadata(job)
            equal(pid, 456789, "PID metadata")

            state = host.snapshot()
            queued = state["queue"][0]
            equal(queued.get("metadata_status"), "fetching", "metadata_status après spawn")
            equal(queued.get("metadata_pid"), 456789, "metadata_pid")
            equal(queued.get("metadata_attempts"), 1, "metadata_attempts")

            job2 = {
                "id": "meta-job-2",
                "url": "https://example.com/media2",
                "mode": "audio",
                "title": "",
                "status": "queued",
                "metadata_status": "pending",
            }
            host.with_state(lambda d: d["queue"].append(dict(job2)))

            def failing_popen(*args, **kwargs):
                raise OSError("boom")

            host.subprocess.Popen = failing_popen
            result = host.spawn_metadata(job2)
            check(result is None, "spawn metadata en échec doit renvoyer None")
        finally:
            host.subprocess.Popen = original_popen

        state = host.snapshot()
        failed = next(j for j in state["queue"] if j["id"] == "meta-job-2")
        equal(failed.get("metadata_status"), "error", "échec spawn metadata non terminal")
        check("boom" in (failed.get("metadata_error") or ""), "raison erreur metadata absente")


def test_metadata_ui_has_error_fallback():
    js = (EXT / "popup.js").read_text(encoding="utf-8")
    check('["error", "unavailable"].includes(job.metadata_status)' in js, "fallback queue metadata absent")
    check("Titre indisponible" in js, "libellé metadata indisponible absent")
    check("metadata_error" in js, "erreur metadata non propagée UI")


def test_collection_rejects_artwork_assets():
    with tempfile.TemporaryDirectory(prefix="kitty-artwork-entry-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_artwork_{os.getpid()}_{time.time_ns()}",
            home,
        )

        image = host._collection_entry_media_url(
            {
                "_type": "url",
                "id": "artwork",
                "url": "https://i1.sndcdn.com/artworks-abc-large.jpg",
                "ie_key": "Soundcloud",
            },
            "https://soundcloud.com/example-artist/tracks",
        )
        check(image is None, "artwork SoundCloud transformé en job")

        png = host._collection_entry_media_url(
            {
                "_type": "url",
                "id": "cover",
                "webpage_url": "https://example.com/cover.png",
            },
            "https://example.com/album",
        )
        check(png is None, "image générique transformée en job")

        page = host._collection_entry_media_url(
            {
                "_type": "url",
                "id": "track",
                "url": "https://soundcloud.com/example-artist/real-track",
                "ie_key": "Soundcloud",
            },
            "https://soundcloud.com/example-artist/tracks",
        )
        equal(page, "https://soundcloud.com/example-artist/real-track", "page SoundCloud valide rejetée")


def test_worker_media_validation_rejects_image():
    import wave

    with tempfile.TemporaryDirectory(prefix="kitty-media-validate-") as tmp:
        home = Path(tmp)
        worker = load_module(
            NATIVE / "worker.py",
            f"kitty_worker_media_validate_{os.getpid()}_{time.time_ns()}",
            home,
        )

        image = home / "cover.jpg"
        image.write_bytes(b"\xff\xd8\xff\xe0" + b"not-media" * 20)
        ok, reason = worker.validate_media_file(image, "audio")
        check(ok is False, "jpg accepté comme audio")
        check("asset non média" in (reason or ""), "raison rejet jpg incorrecte")

        wav = home / "tone.wav"
        with wave.open(str(wav), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"\x00\x00" * 800)

        ok, reason = worker.validate_media_file(wav, "audio")
        check(ok is True, f"wav valide rejeté: {reason}")


def test_worker_final_media_selection_ignores_thumbnail():
    import wave

    with tempfile.TemporaryDirectory(prefix="kitty-final-media-") as tmp:
        home = Path(tmp)
        worker = load_module(
            NATIVE / "worker.py",
            f"kitty_worker_final_media_{os.getpid()}_{time.time_ns()}",
            home,
        )

        out = home / "Downloads"
        out.mkdir()

        jpg = out / "My Track.jpg"
        jpg.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

        wav = out / "My Track.wav"
        with wave.open(str(wav), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(8000)
            f.writeframes(b"\x00\x00" * 800)

        result = {
            "filepath": str(jpg),
            "requested_downloads": [{"filepath": str(wav)}],
        }

        selected = worker.select_final_media_path(
            result,
            str(jpg),
            out,
            "My Track",
            "audio",
        )
        equal(Path(selected), wav, "thumbnail choisie à la place de l’audio")


def test_manual_jobs_preempt_playlist_backlog_fifo():
    with tempfile.TemporaryDirectory(prefix="kitty-priority-queue-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_priority_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.WORKER.write_text("# worker", encoding="utf-8")

        now = time.time()
        active = {
            "id": "playlist-active",
            "url": "https://www.youtube.com/watch?v=PLAY0000001",
            "mode": "audio",
            "status": "downloading",
            "queued_at": now,
            "output_dir": str(home / "Downloads"),
            "playlist_id": "PL_BIG",
            "playlist_position": 13,
            "playlist_total": 837,
        }

        playlist_queue = [
            {
                "id": f"pl-{pos}",
                "url": f"https://www.youtube.com/watch?v=PL{pos:09d}",
                "mode": "audio",
                "title": f"Playlist {pos}",
                "status": "queued",
                "queued_at": now + pos,
                "output_dir": str(home / "Downloads"),
                "metadata_status": "ready",
                "playlist_id": "PL_BIG",
                "playlist_position": pos,
                "playlist_total": 837,
            }
            for pos in range(14, 838)
        ]

        def seed(data):
            data["active"] = dict(active)
            data["queue"] = list(playlist_queue)
            data["history"] = []
            data["queue_paused"] = False

        host.with_state(seed)
        host.spawn_metadata = lambda job: None

        first = host.enqueue(
            "https://www.youtube.com/watch?v=MANUAL00001",
            "audio",
        )
        check(first.get("ok") is True, f"premier manuel: {first}")

        second = host.enqueue(
            "https://www.youtube.com/watch?v=MANUAL00002",
            "audio",
        )
        check(second.get("ok") is True, f"second manuel: {second}")

        state = host.snapshot()
        equal(state["active"]["id"], "playlist-active", "job actif préempté")
        equal(state["queue"][0]["url"], "https://www.youtube.com/watch?v=MANUAL00001", "manuel 1 pas prochain")
        equal(state["queue"][1]["url"], "https://www.youtube.com/watch?v=MANUAL00002", "FIFO manuel cassé")
        check(state["queue"][2].get("playlist_id") == "PL_BIG", "playlist pas repoussée après manuels")


def test_priority_queue_respects_global_pause_and_existing_queue():
    with tempfile.TemporaryDirectory(prefix="kitty-priority-pause-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_priority_pause_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.WORKER.write_text("# worker", encoding="utf-8")
        host.spawn_metadata = lambda job: None
        spawned = []
        host.spawn_active_job = lambda job_id: spawned.append(job_id)

        now = time.time()

        def seed(data):
            data["active"] = None
            data["queue_paused"] = True
            data["queue"] = [{
                "id": "playlist-old",
                "url": "https://www.youtube.com/watch?v=PLAYOLD0001",
                "mode": "audio",
                "status": "queued",
                "queued_at": now,
                "output_dir": str(home / "Downloads"),
                "playlist_id": "PL_PAUSED",
                "playlist_position": 10,
                "playlist_total": 100,
            }]
            data["history"] = []

        host.with_state(seed)

        result = host.enqueue(
            "https://www.youtube.com/watch?v=MANUALPAUSE1",
            "audio",
        )
        check(result.get("ok") is True, "enqueue manuel pause")

        state = host.snapshot()
        check(state.get("active") is None, "ajout a contourné la pause globale")
        equal(len(spawned), 0, "worker lancé malgré pause globale")
        equal(state["queue"][0]["url"], "https://www.youtube.com/watch?v=MANUALPAUSE1", "manuel pas prioritaire sous pause")
        equal(state["queue"][1]["id"], "playlist-old", "playlist ordre cassé")


def test_repair_reorders_legacy_manual_tail():
    with tempfile.TemporaryDirectory(prefix="kitty-priority-repair-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_priority_repair_{os.getpid()}_{time.time_ns()}",
            home,
        )

        now = time.time()

        def seed(data):
            data["active"] = {
                "id": "active",
                "url": "https://www.youtube.com/watch?v=ACTIVE00001",
                "mode": "audio",
                "status": "downloading",
                "worker_pid": os.getpid(),
                "queued_at": now,
                "updated_at": now,
                "playlist_id": "PL_LEGACY",
                "playlist_position": 5,
                "playlist_total": 50,
            }
            data["queue"] = [
                {
                    "id": "pl-6",
                    "url": "https://www.youtube.com/watch?v=PLAY0000006",
                    "mode": "audio",
                    "status": "queued",
                    "playlist_id": "PL_LEGACY",
                    "playlist_position": 6,
                    "playlist_total": 50,
                },
                {
                    "id": "manual-tail",
                    "url": "https://www.youtube.com/watch?v=MANUALTAIL1",
                    "mode": "audio",
                    "status": "queued",
                },
                {
                    "id": "pl-7",
                    "url": "https://www.youtube.com/watch?v=PLAY0000007",
                    "mode": "audio",
                    "status": "queued",
                    "playlist_id": "PL_LEGACY",
                    "playlist_position": 7,
                    "playlist_total": 50,
                },
            ]
            data["history"] = []
            data["queue_paused"] = True

        host.with_state(seed)
        host.repair_state()
        state = host.snapshot()

        equal(state["queue"][0]["id"], "manual-tail", "ancien manuel reste derrière playlist")
        equal(state["queue"][1]["id"], "pl-6", "ordre playlist 1 cassé")
        equal(state["queue"][2]["id"], "pl-7", "ordre playlist 2 cassé")


def test_priority_position_ui_contract():
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    pill = (EXT / "content-pill.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check('kind: "priority"' in shared, "position priority absente")
    check('return "prochain"' in shared, "compact prochain absent")
    check("En file • prochain" in pill, "pill prochain absent")
    check("priorité ${qpos.current}/${qpos.total}" in pill, "pill priorité multi absente")
    check('position?.kind === "priority"' in popup, "popup priorité absente")

    node = shutil.which("node")
    if node:
        script = f"""
require({json.dumps(str(EXT / "shared.js"))});

const state = {{
  active: {{
    id: "playlist-active",
    playlist_position: 13,
    playlist_total: 837
  }},
  queue: [
    {{id: "manual-1"}},
    {{id: "manual-2"}},
    {{id: "pl-14", playlist_position: 14, playlist_total: 837}},
    {{id: "pl-15", playlist_position: 15, playlist_total: 837}}
  ]
}};

const p1 = globalThis.KittyShared.queuePosition(state, "manual-1");
const p2 = globalThis.KittyShared.queuePosition(state, "manual-2");

if (!p1 || p1.kind !== "priority" || !p1.next || p1.current !== 1 || p1.total !== 2) {{
  console.error("p1", JSON.stringify(p1));
  process.exit(1);
}}
if (!p2 || p2.kind !== "priority" || p2.next || p2.current !== 2 || p2.total !== 2) {{
  console.error("p2", JSON.stringify(p2));
  process.exit(2);
}}
if (globalThis.KittyShared.compactPosition(state, "manual-1") !== "prochain") {{
  console.error("compact", globalThis.KittyShared.compactPosition(state, "manual-1"));
  process.exit(3);
}}
const pp = globalThis.KittyShared.queuePosition(state, "pl-14");
if (!pp || pp.kind !== "playlist" || pp.current !== 14 || pp.total !== 837) {{
  console.error("playlist", JSON.stringify(pp));
  process.exit(4);
}}
"""
        result = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        check(
            result.returncode == 0,
            f"logique UI priorité incorrecte: {result.stderr or result.stdout}",
        )


def test_clear_queue_preserves_active_job():
    with tempfile.TemporaryDirectory(prefix="kitty-clear-queue-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_clear_queue_{os.getpid()}_{time.time_ns()}",
            home,
        )

        now = time.time()
        active = {
            "id": "active-job",
            "url": "https://example.com/active",
            "mode": "1080",
            "status": "downloading",
            "queued_at": now,
            "output_dir": str(home / "Downloads"),
        }
        queued = [
            {
                "id": f"queued-{i}",
                "url": f"https://example.com/{i}",
                "mode": "1080",
                "status": "queued",
                "queued_at": now + i,
                "output_dir": str(home / "Downloads"),
            }
            for i in range(500)
        ]

        def seed(data):
            data["active"] = dict(active)
            data["queue"] = list(queued)
            data["history"] = []
            data["queue_paused"] = True

        host.with_state(seed)

        first = host.clear_queue()
        check(first.get("ok") is True, f"clear_queue échoué: {first}")
        equal(first.get("removed_count"), 500, "nombre supprimé")

        state = first["state"]
        equal(state.get("active", {}).get("id"), "active-job", "job actif supprimé")
        equal(len(state.get("queue", [])), 0, "file non vidée")
        check(state.get("queue_paused") is True, "pause globale modifiée")

        second = host.clear_queue()
        check(second.get("ok") is True, "clear_queue vide échoué")
        equal(second.get("removed_count"), 0, "clear_queue non idempotent")
        equal(second["state"].get("active", {}).get("id"), "active-job", "actif perdu")


def test_clear_queue_ui_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    js = (EXT / "popup.js").read_text(encoding="utf-8")

    check('id="clearQueue"' in html, "bouton Vider la file absent")
    check("clearQueueConfirming" in js, "confirmation Vider la file absente")
    check('action: "clear_queue"' in js, "action clear_queue absente")
    check("Confirmer (" in js, "compteur de confirmation absent")
    check("clearQueueBtn.disabled = !queue.length" in js, "désactivation file vide absente")


def test_playlist_progress_position_contract():
    shared = (EXT / "shared.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")

    check("function playlistPosition(job)" in shared, "helper position playlist absent")
    check("const playlistPos = playlistPosition(located.job);" in shared, "lecture playlist_position absente")
    check("if (playlistPos) return playlistPos;" in shared, "playlist_position ne reste pas prioritaire")
    check("const position = queuePosition({ active, queue }, job.id);" in popup, "popup n'utilise pas queuePosition")
    check('position?.kind === "playlist"' in popup, "total playlist non utilisé")

    node = shutil.which("node")
    if node:
        script = f"""
require({json.dumps(str(EXT / "shared.js"))});
const state = {{
  active: {{
    id: "p123",
    playlist_position: 123,
    playlist_total: 500
  }},
  queue: Array.from({{length: 377}}, (_, i) => ({{id: "q" + i}}))
}};
const pos = globalThis.KittyShared.queuePosition(state, "p123");
if (!pos || pos.current !== 123 || pos.total !== 500) {{
  console.error(JSON.stringify(pos));
  process.exit(1);
}}
const compact = globalThis.KittyShared.compactPosition(state, "p123");
if (compact !== "123 / 500") {{
  console.error(compact);
  process.exit(2);
}}
"""
        result = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        check(
            result.returncode == 0,
            f"position playlist active incorrecte: {result.stderr or result.stdout}",
        )


def test_playlist_ui_contract():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    js = (EXT / "popup.js").read_text(encoding="utf-8")
    bg = (EXT / "background.js").read_text(encoding="utf-8")

    check('id="modePicker"' in html, "picker format custom absent")
    check('data-mode="1080"' in html and 'data-mode="mp3"' in html, "formats absents")
    check('id="playlistModeToggle"' in html, "toggle Playlist absent")
    check('id="playlistPanel"' in html, "champ playlist absent")
    check('id="playlistUrl"' in html, "input URL playlist absent")
    check("SoundCloud" in html, "placeholder collections génériques absent")
    check("classifyCollectionUrl" in js, "validation collection générique absente")
    check("isYoutubePlaylistUrl" not in js, "ancienne validation YouTube-only encore présente")
    check("if (!playlistModeEnabled) setModeMenuOpen(false)" in js, "menu ne reste pas ouvert en playlist")
    check("playlistModeToggleEl.classList.toggle(\"active\", playlistModeEnabled)" in js, "surbrillance playlist absente")
    check("modeMenuItems.forEach" in js and "item.classList.toggle(\"active\", active)" in js, "surbrillance format absente")
    check('type: "kitty-download-playlist"' in js, "popup ne transmet pas playlist")
    check('message.type === "kitty-download-playlist"' in bg, "background playlist absent")


def test_playlist_backend_batch_semantics():
    with tempfile.TemporaryDirectory(prefix="kitty-playlist-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_playlist_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.WORKER.write_text("# worker", encoding="utf-8")

        # Pas de vraie requête réseau pendant le banc de tests.
        host.extract_collection_entries = lambda url: {
            "url": "https://www.youtube.com/playlist?list=PL_TEST_123456",
            "id": "PL_TEST_123456",
            "title": "Ma grosse playlist",
            "provider": "YouTube",
            "kind": "Playlist",
            "entries": [
                {
                    "url": "https://www.youtube.com/watch?v=AAAAAA11111",
                    "title": "Vidéo A",
                    "position": 1,
                },
                {
                    "url": "https://www.youtube.com/watch?v=BBBBBB22222",
                    "title": "Vidéo B",
                    "position": 2,
                },
                {
                    "url": "https://www.youtube.com/watch?v=CCCCCC33333",
                    "title": "Vidéo C",
                    "position": 3,
                },
            ],
            "unavailable_count": 0,
        }

        class FakeProc:
            pid = 888888

        spawned = []
        host.spawn = lambda job_id: (spawned.append(job_id) or FakeProc())
        host.time.sleep = lambda *_: None

        # La session YouTube dédiée doit être snapshotée au moment d'ajouter les jobs.
        host.youtube_auth_enabled = lambda: True
        host._youtube_auth_configured = lambda: True

        result = host.enqueue_playlist(
            "https://www.youtube.com/watch?v=AAAAAA11111&list=PL_TEST_123456",
            "1080",
        )

        check(result.get("ok") is True, f"enqueue playlist: {result}")
        equal(result.get("added_count"), 3, "nombre playlist ajouté")
        equal(result.get("skipped_count"), 0, "playlist skip inattendu")
        equal(result.get("collection_provider"), "YouTube", "provider collection")
        equal(result.get("collection_kind"), "Playlist", "type collection")
        equal(len(spawned), 1, "plusieurs workers démarrés en parallèle")

        state = result["state"]
        check(state.get("active") is not None, "premier job non actif")
        equal(len(state.get("queue", [])), 2, "reste playlist non mis en file")
        equal(state["active"]["title"], "Vidéo A", "titre flat non conservé")
        equal(state["active"]["metadata_status"], "ready", "metadata worker inutile")
        check(state["active"].get("youtube_auth") is True, "auth YouTube non snapshotée")
        equal(state["active"].get("playlist_position"), 1, "position playlist active")
        equal(state["active"].get("playlist_total"), 3, "total playlist active")
        equal(state["queue"][1].get("playlist_position"), 3, "position playlist queue")

        # Un second ajout de la même playlist ne doit pas dupliquer la file.
        again = host.enqueue_playlist(
            "https://www.youtube.com/playlist?list=PL_TEST_123456",
            "1080",
        )
        check(again.get("ok") is True, "second enqueue playlist")
        equal(again.get("added_count"), 0, "doublons playlist ajoutés")
        equal(again.get("skipped_count"), 3, "doublons playlist non détectés")


def test_playlist_url_canonicalization():
    with tempfile.TemporaryDirectory(prefix="kitty-playlist-url-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_playlist_url_{os.getpid()}_{time.time_ns()}",
            home,
        )

        expected = "https://www.youtube.com/playlist?list=PLabc_DEF-123"
        equal(
            host.normalize_collection_url(
                "https://www.youtube.com/watch?v=AAAAAA11111&list=PLabc_DEF-123&t=42"
            ),
            expected,
            "watch+list canonicalisation",
        )
        equal(
            host.normalize_collection_url(
                "https://youtu.be/AAAAAA11111?list=PLabc_DEF-123"
            ),
            expected,
            "youtu.be playlist canonicalisation",
        )

        soundcloud = "https://soundcloud.com/example-artist/tracks"
        equal(
            host.normalize_collection_url(soundcloud),
            soundcloud,
            "SoundCloud URL doit être préservée",
        )

        bandcamp = "https://example.bandcamp.com/album/my-album"
        equal(
            host.normalize_collection_url(bandcamp),
            bandcamp,
            "Bandcamp URL doit être préservée",
        )

        for bad in (
            "not-an-url",
            "file:///tmp/list",
            "javascript:alert(1)",
        ):
            try:
                host.normalize_collection_url(bad)
            except RuntimeError:
                pass
            else:
                raise TestFailure(f"URL collection invalide acceptée : {bad}")


def test_generic_collection_entry_resolution():
    with tempfile.TemporaryDirectory(prefix="kitty-collection-entry-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_collection_entry_{os.getpid()}_{time.time_ns()}",
            home,
        )

        sc = host._collection_entry_media_url(
            {
                "_type": "url",
                "id": "123",
                "title": "Track",
                "url": "https://soundcloud.com/example-artist/my-track",
                "ie_key": "Soundcloud",
            },
            "https://soundcloud.com/example-artist/tracks",
        )
        equal(
            sc,
            "https://soundcloud.com/example-artist/my-track",
            "résolution entrée SoundCloud",
        )

        yt = host._collection_entry_media_url(
            {
                "_type": "url",
                "id": "AAAAAA11111",
                "url": "AAAAAA11111",
                "ie_key": "Youtube",
            },
            "https://www.youtube.com/playlist?list=PL_TEST_123456",
        )
        equal(
            yt,
            "https://www.youtube.com/watch?v=AAAAAA11111",
            "reconstruction entrée YouTube flat",
        )

        nested = host._collection_entry_media_url(
            {
                "_type": "playlist",
                "id": "nested",
                "url": "https://soundcloud.com/example-artist/sets/nested",
                "ie_key": "SoundcloudSet",
            },
            "https://soundcloud.com/example-artist",
        )
        check(nested is None, "sous-playlist imbriquée transformée en job")


def test_soundcloud_collection_source_detection():
    with tempfile.TemporaryDirectory(prefix="kitty-collection-source-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_collection_source_{os.getpid()}_{time.time_ns()}",
            home,
        )

        equal(
            host._collection_source("https://soundcloud.com/artist"),
            {"provider": "SoundCloud", "kind": "Profil"},
            "SoundCloud profil",
        )
        equal(
            host._collection_source("https://soundcloud.com/artist/tracks"),
            {"provider": "SoundCloud", "kind": "Tracks"},
            "SoundCloud tracks",
        )
        equal(
            host._collection_source("https://soundcloud.com/artist/likes"),
            {"provider": "SoundCloud", "kind": "Likes"},
            "SoundCloud likes",
        )


def test_collection_youtube_cookie_isolation():
    with tempfile.TemporaryDirectory(prefix="kitty-collection-cookie-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_collection_cookie_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.YOUTUBE_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        host.YOUTUBE_COOKIE_FILE.write_text(
            "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1893456000\tSAPISID\tMASTER\n",
            encoding="utf-8",
        )
        os.chmod(host.YOUTUBE_COOKIE_FILE, 0o600)

        host.load_settings = lambda: {"youtube_auth_enabled": True}

        sc_copy = host._prepare_playlist_auth_cookie_copy(
            "https://soundcloud.com/example-artist/tracks"
        )
        check(sc_copy is None, "cookies YouTube exposés à SoundCloud")

        yt_copy = host._prepare_playlist_auth_cookie_copy(
            "https://www.youtube.com/playlist?list=PL_TEST_123456"
        )
        check(yt_copy is not None and yt_copy.is_file(), "copie cookie YouTube absente")
        host._cleanup_playlist_auth_cookie_copy(yt_copy)




def test_soundcloud_profile_enqueue_semantics():
    with tempfile.TemporaryDirectory(prefix="kitty-soundcloud-profile-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_soundcloud_profile_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host.WORKER.parent.mkdir(parents=True, exist_ok=True)
        host.WORKER.write_text("# worker", encoding="utf-8")

        host.extract_collection_entries = lambda url: {
            "url": "https://soundcloud.com/example-artist",
            "id": "example-artist",
            "title": "Example Artist",
            "provider": "SoundCloud",
            "kind": "Profil",
            "entries": [
                {
                    "url": "https://soundcloud.com/example-artist/track-one",
                    "title": "Track One",
                    "position": 1,
                },
                {
                    "url": "https://soundcloud.com/example-artist/track-two",
                    "title": "Track Two",
                    "position": 2,
                },
            ],
            "unavailable_count": 0,
        }

        class FakeProc:
            pid = 777777

        spawned = []
        host.spawn = lambda job_id: (spawned.append(job_id) or FakeProc())
        host.time.sleep = lambda *_: None

        result = host.enqueue_playlist(
            "https://soundcloud.com/example-artist",
            "audio",
        )

        check(result.get("ok") is True, f"enqueue SoundCloud: {result}")
        equal(result.get("added_count"), 2, "nombre SoundCloud ajouté")
        equal(result.get("collection_provider"), "SoundCloud", "provider SoundCloud")
        equal(result.get("collection_kind"), "Profil", "kind SoundCloud")
        equal(len(spawned), 1, "plusieurs workers SoundCloud démarrés")

        state = result["state"]
        equal(
            state["active"]["url"],
            "https://soundcloud.com/example-artist/track-one",
            "premier track SoundCloud",
        )
        check(state["active"].get("youtube_auth") is False, "auth YouTube appliquée à SoundCloud")
        equal(state["active"].get("collection_provider"), "SoundCloud", "metadata provider job")
        equal(state["active"].get("playlist_position"), 1, "position SoundCloud")
        equal(state["queue"][0].get("playlist_position"), 2, "position second SoundCloud")


def test_youtube_auth_profile_isolation_and_safety():
    with tempfile.TemporaryDirectory(prefix="kitty-ytauth-") as tmp:
        home = Path(tmp) / "real-home"
        home.mkdir()

        default_profile = home / ".mozilla" / "firefox" / "REAL.default-release"
        default_profile.mkdir(parents=True)
        sentinel_login = default_profile / "logins.json"
        sentinel_key = default_profile / "key4.db"
        sentinel_login.write_text("DO-NOT-TOUCH-LOGIN", encoding="utf-8")
        sentinel_key.write_text("DO-NOT-TOUCH-KEY", encoding="utf-8")

        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_ytauth_{os.getpid()}_{time.time_ns()}",
            home,
        )

        captured = {}
        class FakeProc:
            pid = 424242

        def fake_popen(command, **kwargs):
            captured["command"] = list(command)
            captured["env"] = dict(kwargs.get("env") or {})
            return FakeProc()

        host._find_firefox_executable = lambda: "/usr/bin/firefox"
        host.subprocess.Popen = fake_popen
        host.process_alive = lambda pid: True

        started = host.youtube_auth_start()
        check(started.get("ok") is True and started.get("pending"), "youtube_auth_start")

        pending = host._youtube_pending_load()
        check(pending is not None, "pending auth absent")
        paths = host._youtube_session_paths(pending["token"])

        command_text = "\n".join(map(str, captured["command"]))
        check(str(default_profile) not in command_text, "profil Firefox réel présent dans la commande")
        check("-no-remote" in captured["command"], "-no-remote absent")
        check("-profile" in captured["command"], "-profile absent")
        equal(captured["env"]["HOME"], str(paths["home"]), "HOME du Firefox dédié")
        check(str(paths["profile"]) in captured["command"], "profil jetable non imposé")

        prefs = (paths["profile"] / "user.js").read_text(encoding="utf-8")
        check('signon.rememberSignons", false' in prefs, "sauvegarde mots de passe non désactivée")
        check('identity.fxaccounts.enabled", false' in prefs, "Firefox Sync non désactivé")

        (paths["profile"] / "logins.json").write_text("TEMP-LOGIN", encoding="utf-8")
        (paths["profile"] / "key4.db").write_text("TEMP-KEY", encoding="utf-8")
        _make_fake_firefox_cookie_db(paths["profile"], include_auth=True)

        host.process_alive = lambda pid: False
        host._firefox_process_matches_session = lambda pid, profile: False

        finalized = host.youtube_auth_status(auto_finalize=True)
        check(finalized.get("ok") is True, f"finalisation auth: {finalized}")
        check(finalized.get("configured") is True, "snapshot non configuré")
        check(not paths["root"].exists(), "profil jetable conservé après finalisation")

        equal(sentinel_login.read_text(encoding="utf-8"), "DO-NOT-TOUCH-LOGIN", "logins.json réel modifié")
        equal(sentinel_key.read_text(encoding="utf-8"), "DO-NOT-TOUCH-KEY", "key4.db réel modifié")

        cookies = host.YOUTUBE_COOKIE_FILE.read_text(encoding="utf-8")
        check("AUTH_SECRET_VALUE" in cookies, "cookie YouTube auth absent")
        check("do-not-export" not in cookies, "cookie non-YouTube exporté")
        equal(stat.S_IMODE(host.YOUTUBE_COOKIE_FILE.stat().st_mode), 0o600, "permissions cookies")

        outside = home / "outside-sentinel"
        outside.mkdir()
        (outside / "keep").write_text("KEEP", encoding="utf-8")
        try:
            host._safe_remove_youtube_session("../outside-sentinel")
        except Exception:
            pass
        check((outside / "keep").is_file(), "garde-fou de suppression contourné")

        old_snapshot = host.YOUTUBE_COOKIE_FILE.read_bytes()

        host.process_alive = lambda pid: True
        renewed = host.youtube_auth_start()
        check(renewed.get("ok") is True, "début renouvellement")
        pending2 = host._youtube_pending_load()
        paths2 = host._youtube_session_paths(pending2["token"])
        _make_fake_firefox_cookie_db(paths2["profile"], include_auth=False)

        host.process_alive = lambda pid: False
        host._firefox_process_matches_session = lambda pid, profile: False
        failed = host.youtube_auth_status(auto_finalize=True)
        check(failed.get("ok") is False, "renouvellement invalide aurait dû échouer")
        equal(host.YOUTUBE_COOKIE_FILE.read_bytes(), old_snapshot, "ancien snapshot écrasé après échec")


def test_youtube_auth_stale_lock_after_close():
    with tempfile.TemporaryDirectory(prefix="kitty-ytauth-stale-lock-") as tmp:
        home = Path(tmp)
        host = load_module(
            NATIVE / "host.py",
            f"kitty_host_stale_lock_{os.getpid()}_{time.time_ns()}",
            home,
        )

        host._find_firefox_executable = lambda: "/usr/bin/firefox"

        captured = {}
        class FakeProc:
            pid = 555555

        def fake_popen(command, **kwargs):
            captured["command"] = command
            return FakeProc()

        host.subprocess.Popen = fake_popen
        started = host.youtube_auth_start()
        check(started.get("ok") is True, "démarrage session stale-lock")

        pending = host._youtube_pending_load()
        paths = host._youtube_session_paths(pending["token"])
        _make_fake_firefox_cookie_db(paths["profile"], include_auth=True)

        # Simule le lock orphelin que Firefox peut laisser après fermeture.
        stale_lock = paths["profile"] / ".parentlock"
        stale_lock.write_text("stale", encoding="utf-8")

        # Aucun Firefox réel n'utilise ce profil.
        host._linux_firefox_uses_profile = lambda profile: False
        host._firefox_process_matches_session = lambda pid, profile: False

        result = host.youtube_auth_status(auto_finalize=True)
        check(result.get("ok") is True, f"lock stale bloque encore : {result}")
        check(result.get("configured") is True, "snapshot non finalisé avec lock stale")
        check(not paths["root"].exists(), "profil jetable non supprimé après lock stale")


def test_worker_frozen_youtube_cookie_snapshot():
    with tempfile.TemporaryDirectory(prefix="kitty-ytauth-worker-") as tmp:
        home = Path(tmp)
        worker = load_module(
            NATIVE / "worker.py",
            f"kitty_worker_auth_{os.getpid()}_{time.time_ns()}",
            home,
        )

        worker.YOUTUBE_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        worker.YOUTUBE_COOKIE_FILE.write_text(
            "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1893456000\tSAPISID\tMASTER\n",
            encoding="utf-8",
        )
        os.chmod(worker.YOUTUBE_COOKIE_FILE, 0o600)

        copy = worker.prepare_youtube_job_cookiefile(
            "job-auth",
            "https://www.youtube.com/watch?v=abc123",
            True,
        )
        check(copy is not None and copy.is_file(), "copie cookie job absente")
        equal(stat.S_IMODE(copy.stat().st_mode), 0o600, "permissions copie job")

        master_before = worker.YOUTUBE_COOKIE_FILE.read_bytes()
        copy.write_text("ROTATED-BY-JOB", encoding="utf-8")
        equal(worker.YOUTUBE_COOKIE_FILE.read_bytes(), master_before, "snapshot master modifié par job")

        worker.cleanup_youtube_job_cookiefile(copy)
        check(not copy.exists(), "copie cookie job non nettoyée")


def test_history_limit_and_atomicity():
    with tempfile.TemporaryDirectory(prefix="kitty-history-") as tmp:
        home = Path(tmp)
        host = load_module(NATIVE / "host.py", f"kitty_host_history_{os.getpid()}_{time.time_ns()}", home)

        def seed(data):
            data["history"] = [{"id": str(i), "status": "finished"} for i in range(80)]

        host.with_state(seed)
        equal(len(json.loads(host.QUEUE_FILE.read_text())["history"]), 50,
              "historique non borné au moment du commit")
        state2 = host.load_state_locked()
        check(len(state2["history"]) <= 50, "historique dépasse 50 après normalisation")
        check(not host.QUEUE_FILE.with_suffix(".tmp").exists(), "écriture atomique laisse un .tmp")


def test_shared_queue_storage_behaviors():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "test-queue-store.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=clean_subprocess_env(), timeout=60,
    )
    check(proc.returncode == 0, proc.stdout + proc.stderr)


def main():
    print("Kitty Download Manager — tests de régression")
    print(f"Projet : {ROOT}")
    print()

    run_case("Stockage partagé : concurrence et interruptions", test_shared_queue_storage_behaviors)
    run_case("Structure du paquet", test_required_files)
    run_case("Contrat manifest Firefox", test_manifest_contract)
    run_case("Contrat Native Messaging", test_native_manifest_contract)
    run_case("Syntaxe Python", test_python_syntax)
    run_case("Versions cohérentes", test_version_consistency)
    run_case("Gardes de coût du resolver", test_resolver_cost_guards)

    node = shutil.which("node")
    if node:
        def node_syntax():
            for js in [
                EXT / "i18n.js",
                EXT / "shared.js",
                EXT / "media-resolver.js",
                EXT / "content-pill.js",
                EXT / "background.js",
                EXT / "popup.js",
            ]:
                proc = subprocess.run(
                    [node, "--check", str(js)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                    check=False,
                )
                check(proc.returncode == 0, f"{js.name}: {proc.stderr.strip()}")
        run_case("Syntaxe JavaScript", node_syntax)

        def resolver_node():
            proc = subprocess.run(
                [node, str(ROOT / "tests" / "test-media-resolver.js")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
            )
            check(proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}".strip())
            check("assertions OK" in proc.stdout, "suite resolver sans résumé")
        run_case("Universal Media Resolver", resolver_node)
    else:
        skip_case("Syntaxe JavaScript", "Node.js non installé")
        skip_case("Universal Media Resolver", "Node.js non installé")

    run_case("Installation dans HOME isolé", test_installer_sandbox)
    run_case("Compatibilité frontend/backend", test_frontend_backend_compatibility_contract)
    run_case("Blocage mutations incompatibles", test_native_protocol_blocks_incompatible_mutations)
    run_case("Updater sûr conserve état", test_safe_updater_preserves_user_state)
    run_case("Uninstaller safe + purge", test_uninstaller_safe_and_purge_preserve_media)
    run_case("Migration V7 → V8 complète", test_v8_full_legacy_migration)
    run_case("Migration conserve destination custom", test_v8_preserves_custom_destination)
    run_case("Migration bloque worker V7 actif", test_v8_migration_refuses_live_legacy_worker)
    run_case("Identité runtime V8 propre", test_v8_runtime_identity_is_clean)
    run_case("Protocole Native Messaging", test_native_protocol)
    run_case("Canonicalisation backend", test_host_url_canonicalization)
    run_case("Migration + récupération queue.json", test_state_migration_recovery)
    run_case("Réglages + reset sûr", test_settings_and_safe_reset)
    run_case("Sémantique de la file sans réseau", test_queue_semantics_without_network)
    run_case("Noms + nettoyage des fichiers", test_worker_filename_and_cleanup_helpers)
    run_case("Clic/drag des pills compactes", test_compact_pill_click_drag_contract)
    run_case("Fond lisible du Chat ASCII", test_ascii_cat_has_readable_surface_contract)
    run_case("UI pills dans Chromium", test_pill_ui_in_real_browser)
    run_case("Aperçu Classique plus lisible", test_classic_preview_is_more_readable)
    run_case("Aperçus pill sans chevauchement", test_pill_style_preview_no_overlap_contract)
    run_case("Style Kitty renommé", test_kitty_style_display_name_contract)
    run_case("Menu des styles de pill", test_pill_style_picker_contract)
    run_case("Chat ASCII par défaut", test_pill_style_default_is_ascii_cat)
    run_case("Trois variantes de pill", test_content_pill_three_variants_contract)
    run_case("Couleurs d’état + switch live", test_pill_variants_keep_state_colors_and_live_switch)
    run_case("Accents colorés des réglages", test_settings_color_accents_contract)
    run_case("Indicateur Cookies actif/inactif", test_cookies_header_reflects_enabled_state_contract)
    run_case("Indicateur Dépendances dynamique", test_dependencies_header_tracks_diagnostics_contract)
    run_case("Réglages repliables", test_collapsible_settings_groups_contract)
    run_case("État repliable mémorisé", test_settings_sections_default_collapsed_and_persisted)
    run_case("Capsule source stable entre les polls", test_source_capsule_dom_stability_contract)
    run_case("Historique stable entre les polls", test_history_dom_stability_contract)
    run_case("Capsule source aplatie", test_flat_source_capsule_contract)
    run_case("Toute la capsule ouvre la source", test_source_capsule_click_target_is_whole_badge)
    run_case("Icônes sources + bouton cliquable", test_source_icons_and_clickable_source_contract)
    run_case("Détection visuelle des plateformes", test_source_info_known_sites_contract)
    run_case("SIGTERM externe gèle + requeue", test_external_worker_stop_freezes_and_requeues)
    run_case("SIGTERM manuel respecte lane prioritaire", test_external_stop_manual_job_returns_to_manual_lane)
    run_case("Signal externe vs annulation Kitty", test_signal_handler_distinguishes_cancel_from_external_stop)
    run_case("Annuler marque le contrôle avant SIGTERM", test_host_cancel_marks_control_before_sigterm)
    run_case("Arrêt externe ne lance pas le suivant", test_external_stop_does_not_schedule_next)
    run_case("Catalogue erreurs demandées", test_error_catalog_required_messages)
    run_case("Familles d’erreurs backend", test_error_catalog_extended_backend_families)
    run_case("Payload erreur stable + détail", test_error_payload_keeps_flow_code_and_detail)
    run_case("Contrat erreurs terminales worker", test_worker_terminal_error_contract)
    run_case("UI messages d’erreur personnalisés", test_error_ui_contract)
    run_case("État structuré des dépendances", test_dependency_diagnostics_contract)
    run_case("Dépendance requise absente", test_dependency_missing_required_changes_overall)
    run_case("UI diagnostic système", test_diagnostic_ui_contract)
    run_case("Rapport mises à jour sans réseau", test_dependency_update_risk_report_without_network)
    run_case("Rotation bornée des logs", test_log_rotation_is_bounded)
    run_case("Nettoyage cache sûr", test_cache_cleanup_is_safe_and_reports_sizes)
    run_case("UI maintenance cache", test_cache_maintenance_ui_contract)
    run_case("i18n catalogue erreurs complet", test_i18n_backend_error_catalog_is_complete)
    run_case("i18n popup statique couvert", test_i18n_static_popup_french_is_covered)
    run_case("Audit English sans résidu français", test_english_ui_has_no_french_residue_in_real_browser)
    run_case("i18n sans changement des clés internes", test_i18n_display_layer_keeps_internal_contracts)
    run_case("Toggle FR/EN popup dans Chromium", test_language_toggle_popup_in_real_browser)
    run_case("Toggle FR/EN pill dans Chromium", test_language_toggle_pill_in_real_browser)
    run_case("Ordre init protocole popup", test_popup_native_protocol_initialization_order)
    run_case("Démarrage popup avec chargements différés", test_popup_startup_async_order)
    run_case("Popup interactive dans Chromium", test_popup_ui_smoke_in_real_browser)
    run_case("UI compatibilité + updates", test_update_diagnostic_ui_contract)
    run_case("Clic droit Kitty en un clic", test_context_menu_one_click_uses_saved_mode)
    run_case("Release GitHub + SHA-256", test_github_release_check_and_sha256_download)
    run_case("Rejet release SHA-256 invalide", test_github_release_rejects_bad_sha256)
    run_case("Diagnostic copié sans contenu job", test_diagnostic_copy_has_no_job_content)
    run_case("Supervision métadonnées", test_metadata_spawn_is_observable_and_failure_is_terminal)
    run_case("Fallback UI métadonnées", test_metadata_ui_has_error_fallback)
    run_case("Collections refusent les pochettes", test_collection_rejects_artwork_assets)
    run_case("Validation média refuse les images", test_worker_media_validation_rejects_image)
    run_case("Sélection finale préfère le média", test_worker_final_media_selection_ignores_thumbnail)
    run_case("Manuels devant backlog playlist (FIFO)", test_manual_jobs_preempt_playlist_backlog_fifo)
    run_case("Priorité respecte pause globale", test_priority_queue_respects_global_pause_and_existing_queue)
    run_case("Réparation ancienne queue mixte", test_repair_reorders_legacy_manual_tail)
    run_case("Contrat UI priorité de file", test_priority_position_ui_contract)
    run_case("Vider la file préserve l’actif", test_clear_queue_preserves_active_job)
    run_case("Contrat UI Vider la file", test_clear_queue_ui_contract)
    run_case("Progression Playlist persistante", test_playlist_progress_position_contract)
    run_case("Contrat UI Playlist", test_playlist_ui_contract)
    run_case("Canonicalisation URL Playlist", test_playlist_url_canonicalization)
    run_case("Résolution entrées de collection", test_generic_collection_entry_resolution)
    run_case("Détection collections SoundCloud", test_soundcloud_collection_source_detection)
    run_case("Isolation cookies YouTube collections", test_collection_youtube_cookie_isolation)
    run_case("Profil SoundCloud dans la file", test_soundcloud_profile_enqueue_semantics)
    run_case("File Playlist sans réseau", test_playlist_backend_batch_semantics)
    run_case("Isolation session YouTube", test_youtube_auth_profile_isolation_and_safety)
    run_case("Fermeture Firefox + lock orphelin", test_youtube_auth_stale_lock_after_close)
    run_case("Snapshot YouTube figé par job", test_worker_frozen_youtube_cookie_snapshot)
    run_case("Historique + écritures atomiques", test_history_limit_and_atomicity)

    print()
    print(f"Résultat : {PASS} OK, {FAIL} échec(s), {SKIP} ignoré(s)")

    if DETAILS:
        print()
        print("Détails des échecs :")
        for name, trace in DETAILS:
            print(f"\n--- {name} ---")
            print(trace.rstrip())

    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
