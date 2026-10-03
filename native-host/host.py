#!/usr/bin/env python3
import hashlib
import http.cookiejar
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import signal
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

NATIVE_DIR = Path(__file__).resolve().parent
if str(NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(NATIVE_DIR))

from app_paths import (
    APP_NAME,
    cache_dir,
    config_dir,
    default_output_dir,
    install_dir,
    migration_file,
)
from platform_support import (WINDOWS, process_alive, script_process_matches, spawn_options,
                              run_hidden, find_firefox, firefox_uses_profile, choose_windows_folder,
                              configure_worker_job, watch_worker_controls, maintenance_active)
from errors import normalize_error_payload
from compatibility import NATIVE_PROTOCOL_VERSION, assess_update_risk, client_report, version_tuple
from runtime_storage import (
    LOG_FILE,
    LOG_ARCHIVE_COUNT,
    LOG_MAX_BYTES,
    log_stats,
    purge_rotated_logs,
    safe_tree_stats,
)

from queue_store import (
    STATE_VERSION, MAX_STATE_BACKUPS, FutureStateVersion, QueueStateError,
    default_state, normalize_job, migrate_state, read_state, mutate_state,
    claim_next_job, queue_lock, release_failed_start,
    is_playlist_job, normalize_queue_priority, insert_interactive_job, append_playlist_job,
    backup_state_file as _backup_queue, trim_backups,
)

CURRENT_ACTION = ""

CACHE_DIR = cache_dir()
QUEUE_FILE = CACHE_DIR / "queue.json"
LOCK_FILE = CACHE_DIR / "queue.lock"
CONTROL_DIR = CACHE_DIR / "controls"

CONFIG_DIR = config_dir()
SETTINGS_FILE = CONFIG_DIR / "settings.json"

INSTALL_DIR = install_dir()
WORKER = INSTALL_DIR / "worker.py"
META_WORKER = INSTALL_DIR / "metadata.py"

DEFAULT_OUTPUT_DIR = default_output_dir()
DOWNLOADS_DIR = DEFAULT_OUTPUT_DIR.parent

STATE_BACKUP_DIR = CACHE_DIR / "state-backups"
APP_VERSION = "8.25"
UPDATE_CACHE_FILE = CACHE_DIR / "update-check.json"
KITTY_RELEASE_CACHE_FILE = CACHE_DIR / "kitty-release-check.json"
UPDATE_BACKUP_DIR = CACHE_DIR / "update-backups"
KITTY_RELEASE_REPO = "sususususmomo/kitty-download-manager-releases"
KITTY_RELEASE_API = f"https://api.github.com/repos/{KITTY_RELEASE_REPO}/releases/latest"
KITTY_RELEASE_MAX_BYTES = 250 * 1024 * 1024
AUTH_JOB_DIR = CACHE_DIR / "auth-jobs"
CACHE_TRANSIENT_MIN_AGE = 60 * 60
ORPHAN_PARTIAL_MIN_AGE = 24 * 60 * 60
MAX_UPDATE_BACKUPS_PER_KIND = 3

YOUTUBE_AUTH_DIR = CONFIG_DIR / "youtube-auth"
YOUTUBE_COOKIE_FILE = YOUTUBE_AUTH_DIR / "cookies.txt"
YOUTUBE_AUTH_META_FILE = YOUTUBE_AUTH_DIR / "metadata.json"
YOUTUBE_SESSION_ROOT = CACHE_DIR / "youtube-auth-sessions"
YOUTUBE_PENDING_FILE = CACHE_DIR / "youtube-auth-pending.json"
YOUTUBE_SESSION_MARKER = ".kitty-youtube-auth-session"
YOUTUBE_PLAYLIST_AUTH_DIR = CACHE_DIR / "playlist-auth"

YOUTUBE_AUTH_COOKIE_NAMES = {
    "SAPISID", "APISID", "SID", "HSID", "SSID", "LOGIN_INFO",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSID", "__Secure-3PSID",
}

def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) != 4:
        return None
    size = struct.unpack("<I", raw)[0]
    if size > 4 * 1024 * 1024:
        raise OSError("Message natif anormalement volumineux.")
    data = sys.stdin.buffer.read(size)
    if len(data) != size:
        return None
    return json.loads(data.decode("utf-8"))

def send_message(payload):
    if isinstance(payload, dict) and payload.get("ok") is False and payload.get("error") is not None:
        payload = normalize_error_payload(payload, context=CURRENT_ACTION)

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(raw)))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()

def trim_state_backups():
    trim_backups(STATE_BACKUP_DIR, MAX_STATE_BACKUPS)


def backup_state_file(reason, version=None, move=False):
    with queue_lock(LOCK_FILE):
        return _backup_queue(QUEUE_FILE, STATE_BACKUP_DIR, reason, version, move)


def load_state_locked():
    # Compatibility entry point; owns the lock rather than exposing unlocked IO.
    return snapshot()


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, SETTINGS_FILE)


def normalize_output_dir(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Dossier de destination invalide.")

    path = Path(value.strip()).expanduser()

    if not path.is_absolute():
        raise ValueError("Le dossier de destination doit être un chemin absolu.")

    return path


def get_output_dir():
    settings = load_settings()
    configured = settings.get("output_dir")

    try:
        return normalize_output_dir(configured)
    except Exception:
        return DEFAULT_OUTPUT_DIR


def set_output_dir(value):
    try:
        path = normalize_output_dir(value)
        path.mkdir(parents=True, exist_ok=True)

        if not path.is_dir():
            raise RuntimeError("La destination sélectionnée n'est pas un dossier.")

        settings = load_settings()
        settings["output_dir"] = str(path)
        save_settings(settings)

        return {
            "ok": True,
            "output_dir": str(path),
            "settings": {"output_dir": str(path)},
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_settings():
    path = get_output_dir()
    settings = load_settings()
    return {
        "ok": True,
        "settings": {
            "output_dir": str(path),
            "youtube_auth_enabled": bool(settings.get("youtube_auth_enabled", False)),
        },
    }



# ---------------------------------------------------------------------------
# Session YouTube dédiée
#
# Invariants :
# - aucun profil Firefox existant n'est recherché ou énuméré
# - aucun chemin de profil n'est reçu depuis l'extension
# - tous les chemins de session sont dérivés d'un UUID généré ici
# - toute suppression est confinée à YOUTUBE_SESSION_ROOT + marker interne
# - Firefox reçoit un HOME/XDG totalement séparé
# ---------------------------------------------------------------------------

def _path_is_within(path, root):
    try:
        resolved = Path(path).resolve(strict=False)
        root_resolved = Path(root).resolve(strict=False)
        return resolved == root_resolved or root_resolved in resolved.parents
    except Exception:
        return False


def _ensure_private_dir(path):
    path = Path(path)
    if path.exists() and path.is_symlink():
        raise RuntimeError(f"Répertoire de sécurité remplacé par un lien symbolique : {path}")
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except Exception:
        pass
    return path


def _secure_write_text(path, text, mode=0o600):
    path = Path(path)
    _ensure_private_dir(path.parent)
    if path.parent.is_symlink():
        raise RuntimeError("Répertoire parent symbolique refusé.")

    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(tmp, flags, mode)
    fd_open = True
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd_open = False
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
    except Exception:
        if fd_open:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            tmp.unlink()
        except Exception:
            pass
        raise


def _youtube_pending_load():
    try:
        data = json.loads(YOUTUBE_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    token = data.get("token")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        return None

    return {
        "token": token,
        "pid": data.get("pid"),
        "created_at": data.get("created_at"),
    }


def _youtube_pending_save(data):
    _secure_write_text(
        YOUTUBE_PENDING_FILE,
        json.dumps(data, ensure_ascii=False, indent=2),
        0o600,
    )


def _youtube_pending_clear():
    try:
        YOUTUBE_PENDING_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _youtube_session_paths(token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise RuntimeError("Token de session YouTube invalide.")

    root = YOUTUBE_SESSION_ROOT / token
    if not _path_is_within(root, YOUTUBE_SESSION_ROOT) or root == YOUTUBE_SESSION_ROOT:
        raise RuntimeError("Chemin de session YouTube hors zone privée.")

    return {
        "root": root,
        "home": root / "home",
        "profile": root / "profile",
        "marker": root / YOUTUBE_SESSION_MARKER,
    }


def _validate_youtube_session(token, require_exists=True):
    paths = _youtube_session_paths(token)
    root = paths["root"]

    if require_exists and not root.exists():
        raise RuntimeError("Session YouTube temporaire introuvable.")
    if root.exists() and root.is_symlink():
        raise RuntimeError("Session YouTube symbolique refusée.")

    marker = paths["marker"]
    if require_exists:
        if marker.is_symlink() or not marker.is_file():
            raise RuntimeError("Marker de session YouTube absent.")
        try:
            marker_token = marker.read_text(encoding="utf-8").strip()
        except Exception as exc:
            raise RuntimeError("Marker de session YouTube illisible.") from exc
        if marker_token != token:
            raise RuntimeError("Marker de session YouTube invalide.")

    for key in ("home", "profile"):
        path = paths[key]
        if path.exists() and path.is_symlink():
            raise RuntimeError(f"Chemin symbolique refusé dans la session YouTube : {key}")

    return paths


def _safe_remove_youtube_session(token):
    '''Unique primitive rmtree de l'auth YouTube, strictement confinée.'''
    paths = _validate_youtube_session(token, require_exists=True)
    root = paths["root"]

    if not _path_is_within(root, YOUTUBE_SESSION_ROOT):
        raise RuntimeError("Suppression hors zone privée refusée.")
    if root.parent.resolve(strict=False) != YOUTUBE_SESSION_ROOT.resolve(strict=False):
        raise RuntimeError("Profondeur de session YouTube invalide.")

    shutil.rmtree(root)


def _find_firefox_executable():
    return find_firefox()


def _write_youtube_profile_prefs(profile):
    profile = Path(profile)
    _ensure_private_dir(profile)
    prefs = (
        '// Kitty Download Manager - profil jetable YouTube\n'
        'user_pref("signon.rememberSignons", false);\n'
        'user_pref("signon.autofillForms", false);\n'
        'user_pref("browser.formfill.enable", false);\n'
        'user_pref("services.sync.engine.passwords", false);\n'
        'user_pref("identity.fxaccounts.enabled", false);\n'
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
        'user_pref("browser.aboutwelcome.enabled", false);\n'
        'user_pref("browser.startup.homepage_override.mstone", "ignore");\n'
        'user_pref("trailhead.firstrun.didSeeAboutWelcome", true);\n'
        'user_pref("browser.sessionstore.resume_from_crash", false);\n'
        'user_pref("browser.tabs.warnOnClose", false);\n'
        'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);\n'
        'user_pref("datareporting.healthreport.uploadEnabled", false);\n'
    )
    _secure_write_text(profile / "user.js", prefs, 0o600)


def _youtube_profile_has_lock(profile):
    profile = Path(profile)
    for name in ("lock", ".parentlock", "parent.lock"):
        try:
            if os.path.lexists(profile / name):
                return True
        except Exception:
            pass
    return False


def _firefox_process_matches_session(pid, profile):
    """
    Vérifie le process réel, jamais le PID seul.

    Important : un PID vivant n'est pas suffisant (launcher Firefox, PID
    réutilisé, process auxiliaire, etc.). Sous Linux on exige que cmdline
    contienne le chemin exact du profil jetable.
    """
    if WINDOWS:
        return firefox_uses_profile(profile) and process_alive(pid)

    if not process_alive(pid):
        return False

    if not sys.platform.startswith("linux"):
        return False

    profile_text = str(Path(profile).resolve(strict=False))
    proc_cmdline = Path(f"/proc/{int(pid)}/cmdline")

    try:
        raw = proc_cmdline.read_bytes()
        args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    except Exception:
        return False

    if not args:
        return False

    firefoxish = any("firefox" in Path(arg).name.lower() for arg in args[:2])
    if not firefoxish:
        return False

    normalized = []
    for arg in args:
        try:
            if arg.startswith("/"):
                normalized.append(str(Path(arg).resolve(strict=False)))
            else:
                normalized.append(arg)
        except Exception:
            normalized.append(arg)

    return profile_text in normalized or profile_text in "\n".join(args)


def _linux_firefox_uses_profile(profile):
    """
    Source de vérité Linux : cherche un process Firefox dont cmdline contient
    exactement notre profil jetable. On ne scanne aucun profil utilisateur ;
    on compare seulement avec le chemin UUID que Kitty a lui-même créé.
    """
    if not sys.platform.startswith("linux"):
        return False

    profile_text = str(Path(profile).resolve(strict=False))
    proc_root = Path("/proc")

    try:
        entries = list(proc_root.iterdir())
    except Exception:
        return False

    for entry in entries:
        if not entry.name.isdigit():
            continue
        cmdline = entry / "cmdline"
        try:
            raw = cmdline.read_bytes()
            args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        except Exception:
            continue
        if not args:
            continue

        firefoxish = any("firefox" in Path(arg).name.lower() for arg in args[:2])
        if not firefoxish:
            continue

        if profile_text in args or profile_text in "\n".join(args):
            return True

    return False


def _youtube_profile_database_ready(profile):
    """
    Confirme que Firefox a terminé ses écritures avant snapshot.
    Les locks de profil peuvent être orphelins ; l'accessibilité réelle de la
    DB + l'absence de process utilisant notre profil sont plus fiables.
    """
    db = Path(profile) / "cookies.sqlite"
    if db.is_symlink() or not db.is_file():
        return True, None

    try:
        uri = db.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.5)
        try:
            conn.execute("PRAGMA schema_version").fetchone()
        finally:
            conn.close()
        return True, None
    except sqlite3.OperationalError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _youtube_auth_browser_running(pending):
    paths = _validate_youtube_session(pending["token"], require_exists=True)
    profile = paths["profile"]

    if WINDOWS:
        return firefox_uses_profile(profile)

    # Linux : ne jamais bloquer uniquement à cause d'un lock de profil stale.
    if sys.platform.startswith("linux"):
        if _linux_firefox_uses_profile(profile):
            return True

        # Très courte grâce juste après Popen, avant que /proc/cmdline soit
        # observable. Au-delà, un PID seul ne compte plus.
        created_at = pending.get("created_at")
        pid = pending.get("pid")
        if (
            pid
            and isinstance(created_at, (int, float))
            and time.time() - created_at < 2.0
            and _firefox_process_matches_session(pid, profile)
        ):
            return True

        return False

    # Fallback conservateur pour les futures plateformes.
    if _youtube_profile_has_lock(profile):
        return True
    pid = pending.get("pid")
    return bool(pid and process_alive(pid))


def _cookie_domain_is_youtube(host):
    host = str(host or "").lower().lstrip(".")
    return host == "youtube.com" or host.endswith(".youtube.com")


def _extract_youtube_cookies_from_profile(profile, destination):
    '''Lit uniquement cookies.sqlite du profil jetable Kitty.'''
    profile = Path(profile)
    db = profile / "cookies.sqlite"

    if db.is_symlink() or not db.is_file():
        raise RuntimeError(
            "Aucun cookie Firefox trouvé. Connecte-toi à YouTube dans la fenêtre dédiée, "
            "puis ferme-la avant de rouvrir Kitty."
        )

    jar = http.cookiejar.MozillaCookieJar(str(destination))
    cookie_names = set()
    cookie_count = 0

    uri = db.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=3)
    try:
        schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(moz_cookies)").fetchall()}
        required = {"host", "name", "value", "path", "expiry", "isSecure"}
        if not required.issubset(columns):
            raise RuntimeError("Schéma cookies Firefox inattendu.")

        rows = conn.execute(
            "SELECT host, name, value, path, expiry, isSecure FROM moz_cookies"
        ).fetchall()

        for host, name, value, path, expiry, is_secure in rows:
            if not _cookie_domain_is_youtube(host):
                continue
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            if any(ch in name or ch in value for ch in ("\t", "\r", "\n")):
                continue

            if expiry:
                try:
                    expiry = float(expiry)
                    if schema_version >= 16 or expiry > 100_000_000_000:
                        expiry /= 1000.0
                    expiry = int(expiry)
                except Exception:
                    expiry = None
            else:
                expiry = None

            cookie = http.cookiejar.Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=host,
                domain_specified=bool(host),
                domain_initial_dot=str(host).startswith("."),
                path=path or "/",
                path_specified=True,
                secure=bool(is_secure),
                expires=expiry,
                discard=False,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
            jar.set_cookie(cookie)
            cookie_names.add(name)
            cookie_count += 1
    finally:
        conn.close()

    auth_names = sorted(
        name for name in cookie_names
        if name in YOUTUBE_AUTH_COOKIE_NAMES
        or name.endswith("SAPISID")
        or name.endswith("PSID")
    )

    if cookie_count == 0 or not auth_names:
        raise RuntimeError(
            "Aucune session YouTube connectée détectée. "
            "Connecte-toi au compte dans la fenêtre dédiée avant de la fermer."
        )

    old_umask = os.umask(0o077)
    try:
        jar.save(ignore_discard=True, ignore_expires=True)
    finally:
        os.umask(old_umask)

    os.chmod(destination, 0o600)
    with open(destination, "rb") as f:
        os.fsync(f.fileno())

    return {
        "cookie_count": cookie_count,
        "auth_cookie_names": auth_names,
        "firefox_cookie_schema": schema_version,
    }


def _youtube_auth_metadata():
    try:
        data = json.loads(YOUTUBE_AUTH_META_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _youtube_auth_configured():
    try:
        return (
            YOUTUBE_COOKIE_FILE.is_file()
            and not YOUTUBE_COOKIE_FILE.is_symlink()
            and YOUTUBE_COOKIE_FILE.stat().st_size > 0
        )
    except Exception:
        return False


def youtube_auth_enabled():
    return bool(load_settings().get("youtube_auth_enabled", False)) and _youtube_auth_configured()


def youtube_auth_start():
    if not sys.platform.startswith("linux"):
        return {
            "ok": False,
            "error": "La configuration automatique de la session YouTube est actuellement disponible sous Linux.",
        }

    pending = _youtube_pending_load()
    if pending:
        status = youtube_auth_status(auto_finalize=True)
        if status.get("pending"):
            return status

    firefox = _find_firefox_executable()
    if not firefox:
        return {"ok": False, "error": "Firefox introuvable sur le système."}

    _ensure_private_dir(CACHE_DIR)
    _ensure_private_dir(YOUTUBE_SESSION_ROOT)

    token = uuid.uuid4().hex
    paths = _youtube_session_paths(token)
    os.mkdir(paths["root"], 0o700)

    try:
        os.mkdir(paths["home"], 0o700)
        os.mkdir(paths["profile"], 0o700)
        _secure_write_text(paths["marker"], token + "\n", 0o600)
        _write_youtube_profile_prefs(paths["profile"])

        env = os.environ.copy()
        env["HOME"] = str(paths["home"])
        env["XDG_CONFIG_HOME"] = str(paths["home"] / ".config")
        env["XDG_CACHE_HOME"] = str(paths["home"] / ".cache")
        env["XDG_DATA_HOME"] = str(paths["home"] / ".local" / "share")
        if WINDOWS:
            env["APPDATA"] = str(paths["home"] / "AppData" / "Roaming")
            env["LOCALAPPDATA"] = str(paths["home"] / "AppData" / "Local")
            env["USERPROFILE"] = str(paths["home"])
            _ensure_private_dir(Path(env["APPDATA"]))
            _ensure_private_dir(Path(env["LOCALAPPDATA"]))
        env["MOZ_NO_REMOTE"] = "1"
        env["MOZ_CRASHREPORTER_DISABLE"] = "1"

        for dirname in (
            Path(env["XDG_CONFIG_HOME"]),
            Path(env["XDG_CACHE_HOME"]),
            Path(env["XDG_DATA_HOME"]),
        ):
            _ensure_private_dir(dirname)

        command = [
            firefox,
            "-no-remote",
            "-profile",
            str(paths["profile"]),
            "https://www.youtube.com/",
        ]

        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            **spawn_options(),
            close_fds=True,
        )

        _youtube_pending_save({
            "token": token,
            "pid": proc.pid,
            "created_at": time.time(),
        })

        return {
            "ok": True,
            "pending": True,
            "state": "browser_open",
            "configured": _youtube_auth_configured(),
            "enabled": youtube_auth_enabled(),
            "message": (
                "Firefox dédié ouvert. Connecte-toi à YouTube, puis ouvre "
                "youtube.com/robots.txt dans le même onglet et ferme cette fenêtre Firefox."
            ),
        }
    except Exception:
        try:
            if paths["root"].exists():
                _safe_remove_youtube_session(token)
        except Exception:
            pass
        raise


def _youtube_auth_finalize(pending):
    token = pending["token"]
    paths = _validate_youtube_session(token, require_exists=True)

    if _youtube_auth_browser_running(pending):
        return {
            "ok": True,
            "pending": True,
            "state": "browser_open",
            "configured": _youtube_auth_configured(),
            "enabled": youtube_auth_enabled(),
            "message": (
                "Fenêtre Firefox dédiée ouverte. Connecte-toi à YouTube, "
                "ouvre youtube.com/robots.txt dans le même onglet, puis ferme Firefox."
            ),
        }

    db_ready, db_error = _youtube_profile_database_ready(paths["profile"])
    if not db_ready:
        return {
            "ok": True,
            "pending": True,
            "state": "settling",
            "configured": _youtube_auth_configured(),
            "enabled": youtube_auth_enabled(),
            "message": "Firefox termine encore l'écriture de la session YouTube. Réessaie dans un instant.",
            "detail": db_error,
        }

    _ensure_private_dir(YOUTUBE_AUTH_DIR)
    candidate = YOUTUBE_AUTH_DIR / f".cookies-{token}.candidate"
    if candidate.exists() or candidate.is_symlink():
        candidate.unlink()

    try:
        extracted = _extract_youtube_cookies_from_profile(paths["profile"], candidate)

        # Le profil jetable doit disparaître AVANT de publier le nouveau snapshot.
        _safe_remove_youtube_session(token)
        _youtube_pending_clear()

        os.replace(candidate, YOUTUBE_COOKIE_FILE)
        os.chmod(YOUTUBE_COOKIE_FILE, 0o600)

        metadata = {
            "created_at": time.time(),
            "cookie_count": extracted["cookie_count"],
            "auth_cookie_names": extracted["auth_cookie_names"],
            "firefox_cookie_schema": extracted["firefox_cookie_schema"],
            "source": "kitty-isolated-firefox-profile",
            "profile_retained": False,
        }
        _secure_write_text(
            YOUTUBE_AUTH_META_FILE,
            json.dumps(metadata, ensure_ascii=False, indent=2),
            0o600,
        )

        settings = load_settings()
        settings["youtube_auth_enabled"] = True
        save_settings(settings)

        return {
            "ok": True,
            "pending": False,
            "state": "configured",
            "configured": True,
            "enabled": True,
            "created_at": metadata["created_at"],
            "cookie_count": metadata["cookie_count"],
            "message": "Session YouTube dédiée prête.",
        }
    except Exception as exc:
        try:
            candidate.unlink(missing_ok=True)
        except Exception:
            pass

        # Si Firefox est fermé, supprimer aussi le profil temporaire potentiellement sensible.
        try:
            if not _youtube_auth_browser_running(pending):
                _safe_remove_youtube_session(token)
                _youtube_pending_clear()
        except Exception:
            pass

        return {
            "ok": False,
            "pending": bool(_youtube_pending_load()),
            "state": "error",
            "configured": _youtube_auth_configured(),
            "enabled": youtube_auth_enabled(),
            "error": str(exc),
        }


def youtube_auth_status(auto_finalize=True):
    pending = _youtube_pending_load()
    if pending:
        try:
            if auto_finalize:
                return _youtube_auth_finalize(pending)
            if _youtube_auth_browser_running(pending):
                return {
                    "ok": True,
                    "pending": True,
                    "state": "browser_open",
                    "configured": _youtube_auth_configured(),
                    "enabled": youtube_auth_enabled(),
                }
            return {
                "ok": True,
                "pending": True,
                "state": "ready_to_finalize",
                "configured": _youtube_auth_configured(),
                "enabled": youtube_auth_enabled(),
            }
        except Exception as exc:
            return {
                "ok": False,
                "pending": True,
                "state": "error",
                "configured": _youtube_auth_configured(),
                "enabled": youtube_auth_enabled(),
                "error": str(exc),
            }

    metadata = _youtube_auth_metadata()
    configured = _youtube_auth_configured()
    return {
        "ok": True,
        "pending": False,
        "state": "configured" if configured else "not_configured",
        "configured": configured,
        "enabled": youtube_auth_enabled(),
        "created_at": metadata.get("created_at") if configured else None,
        "cookie_count": metadata.get("cookie_count") if configured else None,
    }


def set_youtube_auth_enabled(value):
    enabled = bool(value)
    if enabled and not _youtube_auth_configured():
        result = youtube_auth_status(auto_finalize=False)
        result.update({
            "ok": False,
            "error": "Configure d'abord une session YouTube dédiée.",
        })
        return result

    settings = load_settings()
    settings["youtube_auth_enabled"] = enabled
    save_settings(settings)
    return youtube_auth_status(auto_finalize=False)


def youtube_auth_delete():
    pending = _youtube_pending_load()
    if pending:
        try:
            if _youtube_auth_browser_running(pending):
                result = youtube_auth_status(auto_finalize=False)
                result.update({
                    "ok": False,
                    "error": "Ferme d'abord la fenêtre Firefox dédiée avant de supprimer la session.",
                })
                return result
        except Exception:
            pass

        try:
            _safe_remove_youtube_session(pending["token"])
        except Exception:
            pass
        _youtube_pending_clear()

    _ensure_private_dir(YOUTUBE_AUTH_DIR)
    for path in (YOUTUBE_COOKIE_FILE, YOUTUBE_AUTH_META_FILE):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
        except FileNotFoundError:
            pass

    settings = load_settings()
    settings["youtube_auth_enabled"] = False
    save_settings(settings)
    return youtube_auth_status(auto_finalize=False)


def youtube_auth_for_url(url):
    if not youtube_auth_enabled():
        return False
    try:
        host = (urlsplit(str(url)).hostname or "").lower()
    except Exception:
        return False
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def choose_output_dir():
    current = get_output_dir()
    current.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        try:
            selected = choose_windows_folder(current)
            return set_output_dir(selected) if selected else {"ok": True, "cancelled": True, "output_dir": str(current)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        + ":"
        + os.environ.get("DESKTOP_SESSION", "")
    ).lower()

    commands = []

    # Prefer the dialog that best matches the desktop when available.
    if "kde" in desktop or "plasma" in desktop:
        commands.append(("kdialog", [
            "--getexistingdirectory",
            str(current),
            "--title",
            "Kitty Download Manager — dossier de destination",
        ]))

    commands.extend([
        ("zenity", [
            "--file-selection",
            "--directory",
            f"--filename={str(current)}/",
            "--title=Kitty Download Manager — dossier de destination",
        ]),
        ("yad", [
            "--file-selection",
            "--directory",
            f"--filename={str(current)}/",
            "--title=Kitty Download Manager — dossier de destination",
        ]),
        ("qarma", [
            "--file-selection",
            "--directory",
            f"--filename={str(current)}/",
            "--title=Kitty Download Manager — dossier de destination",
        ]),
    ])

    if not ("kde" in desktop or "plasma" in desktop):
        commands.append(("kdialog", [
            "--getexistingdirectory",
            str(current),
            "--title",
            "Kitty Download Manager — dossier de destination",
        ]))

    seen = set()

    for name, args in commands:
        if name in seen:
            continue
        seen.add(name)

        executable = shutil.which(name)
        if not executable:
            continue

        try:
            proc = run_hidden(
                [executable, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except Exception:
            continue

        # User cancelled the chooser.
        if proc.returncode != 0:
            if proc.returncode in (1, 255):
                return {
                    "ok": True,
                    "cancelled": True,
                    "output_dir": str(get_output_dir()),
                }
            continue

        selected = proc.stdout.strip()
        if not selected:
            return {
                "ok": True,
                "cancelled": True,
                "output_dir": str(get_output_dir()),
            }

        return set_output_dir(selected)

    return {
        "ok": False,
        "error": (
            "Aucun sélecteur de dossier compatible n'est installé. "
            "Installe zenity, kdialog, yad ou qarma."
        ),
    }




def worker_matches_job(pid, job_id):
    if WINDOWS:
        return script_process_matches(pid, WORKER, job_id)
    if not process_alive(pid):
        return False

    # Sous Linux, vérifier aussi que le PID n'a pas été recyclé par un autre
    # processus. Si /proc n'est pas lisible, conserver le test classique.
    proc_cmdline = Path(f"/proc/{int(pid)}/cmdline")
    try:
        raw = proc_cmdline.read_bytes()
        args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if not args:
            return False
        has_worker = any(Path(arg).name == WORKER.name for arg in args)
        has_job = str(job_id) in args
        return has_worker and has_job
    except Exception:
        return process_alive(pid)

def with_state(fn):
    def guarded(data):
        if WINDOWS and maintenance_active(CACHE_DIR / "maintenance.json"):
            raise QueueStateError("Installation ou désinstallation Kitty en cours; file en pause.")
        return fn(data)
    return mutate_state(QUEUE_FILE, LOCK_FILE, guarded, recover=True,
                        backup_dir=STATE_BACKUP_DIR)


def snapshot():
    return read_state(QUEUE_FILE, LOCK_FILE, recover=True,
                      backup_dir=STATE_BACKUP_DIR)


def spawn(job_id):
    return subprocess.Popen(
        [sys.executable, str(WORKER), job_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **spawn_options(),
        close_fds=True,
    )

def _mutate_job_by_id(job_id, fn):
    def mutate(data):
        active = data.get("active")
        candidates = ([active] if isinstance(active, dict) else []) + data["queue"]
        for job in candidates:
            if job.get("id") == job_id:
                fn(job)
                job["updated_at"] = time.time()
                return True
        return False
    return with_state(mutate)


def metadata_process_matches_job(pid, job_id):
    if WINDOWS:
        return script_process_matches(pid, META_WORKER, job_id)
    if not pid or not process_alive(pid):
        return False

    proc_cmdline = Path(f"/proc/{int(pid)}/cmdline")
    try:
        raw = proc_cmdline.read_bytes()
        args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if not args:
            return False
        has_metadata = any(Path(arg).name == META_WORKER.name for arg in args)
        has_job = str(job_id) in args
        return has_metadata and has_job
    except Exception:
        return process_alive(pid)


def spawn_metadata(job):
    """
    Lance le probe de titre avec un état explicite et observable.
    """
    if not META_WORKER.exists() or not isinstance(job, dict) or not job.get("id"):
        return None

    job_id = str(job["id"])
    now = time.time()

    def reserve(data):
        for target in data["queue"]:
            if target.get("id") != job_id:
                continue
            if target.get("title") or target.get("metadata_status") == "fetching":
                return False
            target["metadata_status"] = "fetching"
            target["metadata_error"] = None
            target["metadata_started_at"] = now
            target["metadata_pid"] = None
            target["metadata_attempts"] = int(target.get("metadata_attempts") or 0) + 1
            return True
        return False

    if not with_state(reserve):
        return None

    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(META_WORKER),
                job_id,
                job["url"],
                "1" if job.get("youtube_auth") else "0",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **spawn_options(),
            close_fds=True,
        )
    except Exception as exc:
        error = f"Impossible de lancer le probe métadonnées : {exc}"

        def mark_failed(target):
            target["metadata_status"] = "error"
            target["metadata_error"] = error[:500]
            target["metadata_pid"] = None

        _mutate_job_by_id(job_id, mark_failed)
        return None

    def save_pid(target):
        # Ne jamais écraser un résultat qui aurait fini avant ce write.
        if target.get("metadata_status") == "fetching" and not target.get("title"):
            target["metadata_pid"] = proc.pid

    _mutate_job_by_id(job_id, save_pid)
    return proc.pid



def normalize_download_url(url):
    """Canonicalise uniquement les permalinks média connus et non ambigus."""
    if not isinstance(url, str):
        return url

    original = url.strip()
    try:
        parsed = urlsplit(original)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"

        def host_is(domain):
            return host == domain or host.endswith("." + domain)

        if host_is("tiktok.com"):
            match = re.match(r"^/@([^/]*)/video/(\d+)", path, re.IGNORECASE)
            if match:
                username, video_id = match.groups()
                return f"https://www.tiktok.com/@{username or '_'}/video/{video_id}"

        if host_is("instagram.com"):
            parts = [part for part in path.split("/") if part]
            for index, part in enumerate(parts[:-1]):
                kind = part.lower()
                if kind in {"p", "reel", "reels", "tv"}:
                    shortcode = re.match(r"^[A-Za-z0-9_-]+", parts[index + 1])
                    if shortcode:
                        kind = "reel" if kind == "reels" else kind
                        return f"https://www.instagram.com/{kind}/{shortcode.group(0)}/"

        if host_is("x.com") or host_is("twitter.com"):
            match = re.match(r"^/(?:i/web/status|statuses|[^/]+/status)/(\d+)", path, re.IGNORECASE)
            if match:
                return f"https://x.com/i/status/{match.group(1)}"

        if host_is("reddit.com") or host_is("redditmedia.com"):
            match = re.search(r"/(?:r/[^/]+/|user/[^/]+/)?comments/([^/?#&]+)", path, re.IGNORECASE)
            if match:
                return f"https://www.reddit.com/comments/{match.group(1)}"

        if re.match(r"^(?:[^.]+\.)*pinterest\.[a-z.]+$", host, re.IGNORECASE):
            match = re.match(r"^/pin/(?:[\w-]+--)?(\d+)(?:/|$)", path, re.IGNORECASE)
            if match:
                return f"https://www.pinterest.com/pin/{match.group(1)}/"

        if host_is("facebook.com"):
            match = re.match(r"^/reel/(\d+)", path, re.IGNORECASE)
            if match:
                return f"https://www.facebook.com/reel/{match.group(1)}"

            query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
            if re.match(r"^/watch/?$", path, re.IGNORECASE):
                video_id = query.get("v") or query.get("video_id")
                if video_id and video_id.isdigit():
                    return f"https://www.facebook.com/watch/?v={video_id}"

            if re.match(r"^/(?:video(?:/video)?\.php|story\.php|permalink\.php)$", path, re.IGNORECASE):
                video_id = query.get("v") or query.get("video_id") or query.get("story_fbid")
                if video_id and re.match(r"^(?:\d+|pfbid[A-Za-z0-9]+)$", video_id):
                    if path.lower().endswith("permalink.php"):
                        return f"https://www.facebook.com/permalink.php?story_fbid={video_id}"
                    return f"https://www.facebook.com/video.php?v={video_id}"

            match = re.search(r"/videos/(?:[^/]+/)?(\d+)(?:/|$)", path, re.IGNORECASE)
            if match:
                return f"https://www.facebook.com/video.php?v={match.group(1)}"

        if host_is("youtube.com") and path.lower() == "/watch":
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
            video_id = query.get("v")
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"

        if host_is("youtu.be"):
            video_id = path.strip("/").split("/")[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        pass

    return original


def _is_youtube_host(host):
    host = str(host or "").lower()
    return (
        host == "youtu.be"
        or host == "youtube.com"
        or host.endswith(".youtube.com")
    )


def normalize_youtube_playlist_url(url):
    """
    Canonicalisation stricte conservée pour les vraies playlists YouTube.
    Utilisée aussi par les tests/compatibilité des versions précédentes.
    """
    if not isinstance(url, str):
        raise RuntimeError("URL de playlist invalide.")

    raw = url.strip()
    try:
        parsed = urlsplit(raw)
    except Exception as exc:
        raise RuntimeError("URL de playlist invalide.") from exc

    if parsed.scheme not in ("http", "https"):
        raise RuntimeError("URL de playlist HTTP/HTTPS requise.")

    if not _is_youtube_host(parsed.hostname):
        raise RuntimeError("Cette URL n’est pas une playlist YouTube.")

    query = parse_qs(parsed.query)
    values = query.get("list") or []
    playlist_id = values[-1].strip() if values else ""

    if not playlist_id:
        raise RuntimeError("Cette URL YouTube ne contient pas d’identifiant de playlist.")

    if not re.fullmatch(r"[A-Za-z0-9_-]{6,200}", playlist_id):
        raise RuntimeError("Identifiant de playlist YouTube invalide.")

    return f"https://www.youtube.com/playlist?list={playlist_id}"


def normalize_collection_url(url):
    """
    Validation minimale et volontairement générique.

    YouTube + ?list= conserve la canonicalisation historique.
    Pour les autres collections, on laisse l'URL au format fourni :
    certains extracteurs yt-dlp ont besoin du chemin et/ou de la query exacte.
    """
    if not isinstance(url, str):
        raise RuntimeError("URL de collection invalide.")

    raw = url.strip()
    try:
        parsed = urlsplit(raw)
    except Exception as exc:
        raise RuntimeError("URL de collection invalide.") from exc

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError("URL HTTP/HTTPS de playlist ou collection requise.")

    if _is_youtube_host(parsed.hostname):
        query = parse_qs(parsed.query)
        if query.get("list"):
            return normalize_youtube_playlist_url(raw)

    return raw


def _collection_source(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().lstrip("www.")
        path_parts = [part for part in parsed.path.split("/") if part]
    except Exception:
        return {"provider": "Collection", "kind": "Collection"}

    if _is_youtube_host(host):
        query = parse_qs(parsed.query)
        kind = "Playlist" if query.get("list") else "Collection"
        return {"provider": "YouTube", "kind": kind}

    if host == "soundcloud.com" or host.endswith(".soundcloud.com"):
        section = path_parts[1].lower() if len(path_parts) >= 2 else ""
        kinds = {
            "tracks": "Tracks",
            "albums": "Albums",
            "sets": "Playlists",
            "likes": "Likes",
            "reposts": "Reposts",
            "spotlight": "Spotlight",
        }
        return {
            "provider": "SoundCloud",
            "kind": kinds.get(section, "Profil" if path_parts else "Collection"),
        }

    if host == "bandcamp.com" or host.endswith(".bandcamp.com"):
        kind = "Album" if "album" in path_parts else "Collection"
        return {"provider": "Bandcamp", "kind": kind}

    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        return {"provider": "Vimeo", "kind": "Collection"}

    if host in {"dailymotion.com", "www.dailymotion.com", "dai.ly"} or host.endswith(".dailymotion.com"):
        return {"provider": "Dailymotion", "kind": "Playlist"}

    if host == "audiomack.com" or host.endswith(".audiomack.com"):
        return {"provider": "Audiomack", "kind": "Collection"}

    if host == "audius.co" or host.endswith(".audius.co"):
        return {"provider": "Audius", "kind": "Collection"}

    return {"provider": host or "Collection", "kind": "Collection"}


def _prepare_playlist_auth_cookie_copy(collection_url):
    """
    Ne jamais envoyer les cookies YouTube à un autre site.

    La session dédiée n'est copiée que pour une collection dont l'URL source
    est YouTube. SoundCloud/Bandcamp/etc. n'ont accès à aucun cookie YouTube.
    """
    if not youtube_auth_for_url(collection_url):
        return None
    if YOUTUBE_COOKIE_FILE.is_symlink() or not YOUTUBE_COOKIE_FILE.is_file():
        return None

    _ensure_private_dir(YOUTUBE_PLAYLIST_AUTH_DIR)
    target = YOUTUBE_PLAYLIST_AUTH_DIR / f"{uuid.uuid4().hex}.cookies.txt"

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(target, flags, 0o600)
    fd_open = True
    try:
        with open(YOUTUBE_COOKIE_FILE, "rb") as src, os.fdopen(fd, "wb") as dst:
            fd_open = False
            shutil.copyfileobj(src, dst, length=1024 * 64)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(target, 0o600)
    except Exception:
        if fd_open:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            target.unlink()
        except Exception:
            pass
        raise

    return target


def _cleanup_playlist_auth_cookie_copy(path):
    if not path:
        return

    try:
        path = Path(path)
        root = YOUTUBE_PLAYLIST_AUTH_DIR.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if root not in resolved.parents:
            return
        if path.is_symlink() or path.is_file():
            path.unlink()
    except Exception:
        pass


_ARTWORK_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg",
}


def _looks_like_artwork_asset_url(raw_url):
    try:
        parsed = urlsplit(str(raw_url or "").strip())
        path = (parsed.path or "").lower()
        suffix = Path(path).suffix.lower()
        host = (parsed.hostname or "").lower()

        if suffix in _ARTWORK_EXTENSIONS:
            return True

        if host.endswith("sndcdn.com") and (
            "artworks-" in path or "/visuals-" in path or "/avatars-" in path
        ):
            return True
    except Exception:
        return True

    return False


def _same_web_host_family(candidate_url, collection_url):
    try:
        candidate = (urlsplit(candidate_url).hostname or "").lower().lstrip("www.")
        source = (urlsplit(collection_url).hostname or "").lower().lstrip("www.")
    except Exception:
        return False

    if not candidate or not source:
        return False

    return (
        candidate == source
        or candidate.endswith("." + source)
        or source.endswith("." + candidate)
    )


def _collection_entry_media_url(entry, collection_url):
    """
    Retourne une URL de page média, jamais une pochette/CDN opaque.
    """
    if not isinstance(entry, dict):
        return None

    entry_type = str(entry.get("_type") or "").lower()
    if entry_type in {"playlist", "multi_video"} or entry.get("entries") is not None:
        return None

    for key in ("webpage_url", "original_url"):
        raw = str(entry.get(key) or "").strip()
        if not raw.startswith(("http://", "https://")):
            continue
        if _looks_like_artwork_asset_url(raw):
            continue
        return normalize_download_url(raw)

    ie_key = str(entry.get("ie_key") or entry.get("extractor_key") or "").lower()
    video_id = str(entry.get("id") or "").strip()

    if (
        ("youtube" in ie_key or _is_youtube_host(urlsplit(collection_url).hostname))
        and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", video_id)
    ):
        return f"https://www.youtube.com/watch?v={video_id}"

    raw = str(entry.get("url") or "").strip()
    if raw.startswith(("http://", "https://")):
        if _looks_like_artwork_asset_url(raw):
            return None
        if _same_web_host_family(raw, collection_url):
            return normalize_download_url(raw)

    return None


def extract_collection_entries(url):
    """
    Extraction plate d'une collection reconnue par yt-dlp.

    Compatible notamment avec :
      - YouTube playlists/collections
      - SoundCloud profils, tracks, sets, likes, reposts...
      - Bandcamp albums/collections
      - Vimeo collections
      - Dailymotion playlists
      - autres collections exposées proprement par yt-dlp

    Aucun média n'est téléchargé ici.
    """
    canonical = normalize_collection_url(url)
    cookiefile = _prepare_playlist_auth_cookie_copy(canonical)

    try:
        try:
            import yt_dlp
        except Exception as exc:
            raise RuntimeError("yt-dlp Python est introuvable.") from exc

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": False,
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
        }
        if cookiefile:
            opts["cookiefile"] = str(cookiefile)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical, download=False)

        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp n’a pas reconnu cette URL.")

        raw_entries = info.get("entries")
        if raw_entries is None:
            raise RuntimeError(
                "Cette URL correspond à un média unique, pas à une playlist ou collection."
            )

        entries = []
        seen = set()
        unavailable = 0

        for position, entry in enumerate(raw_entries, start=1):
            media_url = _collection_entry_media_url(entry, canonical)
            if not media_url:
                unavailable += 1
                continue

            if media_url in seen:
                continue
            seen.add(media_url)

            title = str((entry or {}).get("title") or "").strip()
            if not title or title in ("[Deleted video]", "[Private video]"):
                title = f"Élément {position}"

            entries.append({
                "url": media_url,
                "title": title[:500],
                "position": position,
            })

        if not entries:
            raise RuntimeError(
                "Aucun média individuel accessible n’a été trouvé dans cette collection."
            )

        source = _collection_source(canonical)
        info_id = str(info.get("id") or "").strip()
        stable_id = info_id or uuid.uuid5(uuid.NAMESPACE_URL, canonical).hex

        title = str(
            info.get("title")
            or info.get("playlist_title")
            or info.get("uploader")
            or f"{source['provider']} · {source['kind']}"
        ).strip()[:500]

        return {
            "url": canonical,
            "id": stable_id,
            "title": title,
            "provider": source["provider"],
            "kind": source["kind"],
            "entries": entries,
            "unavailable_count": unavailable,
        }
    finally:
        _cleanup_playlist_auth_cookie_copy(cookiefile)


# Compatibilité interne V7.19-V7.22 : les appels existants continuent à
# fonctionner, mais utilisent désormais le moteur générique.
def extract_youtube_playlist_entries(url):
    return extract_collection_entries(url)



def enqueue_playlist(url, mode, output_dir=None):
    if not isinstance(mode, str) or mode not in {"1080", "720", "best", "audio", "mp3"}:
        return {"ok": False, "error": "Format de téléchargement invalide."}

    if not WORKER.exists():
        return {"ok": False, "error": f"Worker introuvable : {WORKER}"}

    try:
        playlist = extract_collection_entries(url)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        job_output_dir = normalize_output_dir(output_dir) if output_dir else get_output_dir()
        job_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"ok": False, "error": f"Dossier de destination invalide : {exc}"}

    entries = playlist.get("entries") or []
    playlist_total = len(entries)
    playlist_id = playlist.get("id") or ""
    playlist_title = playlist.get("title") or "Collection"
    collection_url = playlist.get("url") or normalize_collection_url(url)
    collection_provider = playlist.get("provider") or _collection_source(collection_url)["provider"]
    collection_kind = playlist.get("kind") or "Collection"

    first_job_id = None
    added_count = 0
    skipped_count = 0

    def mutate(data):
        nonlocal first_job_id, added_count, skipped_count

        active = data.get("active")
        queue = normalize_queue_priority(data.get("queue", []))
        data["queue"] = queue
        history = data.setdefault("history", [])

        existing = set()
        if active:
            existing.add((active.get("url"), active.get("mode")))
        for job in queue:
            existing.add((job.get("url"), job.get("mode")))

        finished = {
            (job.get("url"), job.get("mode"))
            for job in history
            if (
                job.get("status") == "finished"
                and Path(job.get("output_dir") or DEFAULT_OUTPUT_DIR) == job_output_dir
            )
        }

        for playlist_index, entry in enumerate(entries, start=1):
            media_url = normalize_download_url(entry.get("url", ""))
            key = (media_url, mode)

            if not media_url.startswith(("http://", "https://")):
                skipped_count += 1
                continue

            if key in existing or key in finished:
                skipped_count += 1
                continue

            now = time.time()
            job = {
                "id": uuid.uuid4().hex,
                "url": media_url,
                "mode": mode,
                "title": str(entry.get("title") or "")[:500],
                "status": "queued",
                "queued_at": now,
                "output_dir": str(job_output_dir),
                "metadata_status": "ready",
                "youtube_auth": youtube_auth_for_url(media_url),
                "playlist_id": playlist_id,
                "playlist_title": playlist_title,
                "playlist_position": playlist_index,
                "playlist_total": playlist_total,
                "collection_url": collection_url,
                "collection_provider": collection_provider,
                "collection_kind": collection_kind,
            }

            if first_job_id is None:
                first_job_id = job["id"]

            data["queue"] = append_playlist_job(data.get("queue", []), job)
            existing.add(key)
            added_count += 1

    with_state(mutate)

    # Le scheduler existant respecte active, queue_paused et les éléments
    # individuellement en pause. Une playlist ne démarre plus "en force".
    start_next_if_idle()

    return {
        "ok": True,
        "playlist_title": playlist_title,
        "playlist_id": playlist_id,
        "collection_provider": collection_provider,
        "collection_kind": collection_kind,
        "detected_count": playlist_total,
        "unavailable_count": int(playlist.get("unavailable_count") or 0),
        "added_count": added_count,
        "skipped_count": skipped_count,
        "first_job_id": first_job_id,
        "state": snapshot(),
    }


def enqueue(url, mode, force=False, output_dir=None):
    if not isinstance(mode, str) or mode not in {"1080", "720", "best", "audio", "mp3"}:
        return {"ok": False, "error": "Format de téléchargement invalide."}
    url = normalize_download_url(url)

    if not WORKER.exists():
        return {"ok": False, "error": f"Worker introuvable : {WORKER}"}

    try:
        job_output_dir = normalize_output_dir(output_dir) if output_dir else get_output_dir()
        job_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"ok": False, "error": f"Dossier de destination invalide : {exc}"}

    job = {
        "id": uuid.uuid4().hex,
        "url": url,
        "mode": mode,
        "title": "",
        "status": "queued",
        "queued_at": time.time(),
        "output_dir": str(job_output_dir),
        "metadata_status": "pending",
        "youtube_auth": youtube_auth_for_url(url),
    }

    def mutate(data):
        active = data.get("active")

        if active and active.get("url") == url and active.get("mode") == mode:
            return {
                "ok": False,
                "code": "already_active",
                "job_id": active.get("id"),
                "error": "Ce téléchargement est déjà en cours.",
                "state": data,
            }

        for queued in data.get("queue", []):
            if queued.get("url") == url and queued.get("mode") == mode:
                return {
                    "ok": False,
                    "code": "already_queued",
                    "job_id": queued.get("id"),
                    "error": "Ce téléchargement est déjà dans la file.",
                    "state": data,
                }

        if not force:
            for previous in data.get("history", []):
                if (
                    previous.get("url") == url
                    and previous.get("mode") == mode
                    and previous.get("status") == "finished"
                    and Path(previous.get("output_dir") or DEFAULT_OUTPUT_DIR) == job_output_dir
                ):
                    return {
                        "ok": False,
                        "code": "already_downloaded",
                        "error": "Ce média a déjà été téléchargé.",
                        "previous": {
                            "id": previous.get("id"),
                            "title": previous.get("title"),
                            "filepath": previous.get("filepath"),
                            "finished_at": previous.get("finished_at"),
                        },
                        "state": data,
                    }

        data["queue"] = insert_interactive_job(data.get("queue", []), dict(job))
        return None

    rejected = with_state(mutate)
    if rejected:
        return rejected

    # Une seule politique de démarrage pour popup, pill et retry :
    # pas de contournement de queue_paused, pas de saut d'une file existante.
    started_id = start_next_if_idle()

    if started_id != job["id"]:
        spawn_metadata(job)

    return {"ok": True, "state": snapshot(), "job_id": job["id"]}


def clear_queue():
    """
    Vide atomiquement tous les jobs EN ATTENTE.
    Le téléchargement actif reste strictement intact.
    """
    removed_ids = []

    def mutate(data):
        nonlocal removed_ids
        queue = data.get("queue")
        if not isinstance(queue, list):
            queue = []

        removed_ids = [
            str(job.get("id"))
            for job in queue
            if isinstance(job, dict) and job.get("id")
        ]
        data["queue"] = []

    with_state(mutate)

    # Best-effort uniquement pour d'anciens fichiers de contrôle de jobs
    # qui ne démarreront plus. Aucun chemin du job actif n'est utilisé ici.
    for job_id in removed_ids:
        try:
            clear_control(job_id)
        except Exception:
            pass

    return {
        "ok": True,
        "removed_count": len(removed_ids),
        "state": snapshot(),
    }



def retry_job(job_id):
    state = snapshot()
    previous = next(
        (job for job in state.get("history", []) if job.get("id") == job_id),
        None,
    )
    if not previous:
        return {"ok": False, "error": "Téléchargement introuvable dans l'historique."}
    if previous.get("status") != "error":
        return {"ok": False, "error": "Seuls les téléchargements en erreur peuvent être relancés."}

    return enqueue(
        previous.get("url", ""),
        previous.get("mode", "1080"),
        force=True,
        output_dir=previous.get("output_dir"),
    )


def control_path(job_id):
    return CONTROL_DIR / f"{job_id}.json"


def set_control(job_id, action):
    if not job_id:
        return
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    path = control_path(job_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"action": action, "updated_at": time.time()}), encoding="utf-8")
    os.replace(tmp, path)


def clear_control(job_id):
    if not job_id:
        return
    try:
        control_path(job_id).unlink()
    except FileNotFoundError:
        pass


def spawn_active_job(job_id):
    try:
        proc = spawn(job_id)
    except OSError:
        with_state(lambda data: release_failed_start(data, job_id))
        raise
    time.sleep(0.08)

    def save_pid(data):
        active = data.get("active")
        if active and active.get("id") == job_id:
            active["worker_pid"] = proc.pid
            active["updated_at"] = time.time()

    with_state(save_pid)
    return proc.pid


def start_next_if_idle():
    next_job = None

    def mutate(data):
        nonlocal next_job
        next_job = claim_next_job(data)

    with_state(mutate)

    if next_job:
        spawn_active_job(next_job["id"])
        return next_job["id"]
    return None


def pause_active(job_id=None):
    # Write the pause request before touching queue.json. This avoids waiting
    # behind frequent progress writes just to tell the worker to stop.
    if job_id:
        set_control(job_id, "pause")

    state = snapshot()
    active = state.get("active")

    if not active:
        clear_control(job_id)
        return {"ok": False, "error": "Aucun téléchargement actif.", "state": state}
    if active.get("status") == "paused":
        clear_control(active.get("id"))
        return {"ok": True, "state": state}

    active_id = active.get("id")
    if job_id and job_id != active_id:
        clear_control(job_id)
        return {"ok": False, "error": "Le téléchargement actif a changé.", "state": state}

    set_control(active_id, "pause")
    return {"ok": True, "state": snapshot()}


def resume_active():
    state = snapshot()
    active = state.get("active")

    if not active:
        return {"ok": False, "error": "Aucun téléchargement actif.", "state": state}
    if active.get("status") != "paused":
        return {"ok": True, "state": state}

    job_id = active.get("id")
    clear_control(job_id)

    def mutate(data):
        current = data.get("active")
        if current and current.get("id") == job_id and current.get("status") == "paused":
            current["status"] = "starting"
            current["worker_pid"] = None
            current["speed"] = None
            current["eta"] = None
            current["error"] = None
            current["updated_at"] = time.time()
            current.pop("pause_requested", None)
            current.pop("control_request", None)
            current.pop("paused_from_status", None)
            return True
        return False

    if with_state(mutate):
        spawn_active_job(job_id)
    return {"ok": True, "state": snapshot()}


def cleanup_paused_job_files(job):
    """
    Fallback de nettoyage pour un ancien état interrompu.

    Les nouvelles versions utilisent output_stem, qui identifie les fichiers
    du job sans avoir besoin d'afficher l'ID du média dans leur nom.
    """
    started_at = float(job.get("started_at") or job.get("queued_at") or 0)
    threshold = started_at - 5.0 if started_at else 0
    candidates = set()

    filepath = job.get("filepath")
    if filepath:
        path = Path(filepath)
        candidates.update({
            path,
            Path(str(path) + ".part"),
            Path(str(path) + ".ytdl"),
        })
        try:
            candidates.update(path.parent.glob(path.name + "*"))
        except Exception:
            pass

    output_stem = job.get("output_stem")
    if output_stem:
        stem_path = Path(output_stem)
        prefix = stem_path.name + "."

        try:
            for child in stem_path.parent.iterdir():
                if child.is_file() and (
                    child.name == stem_path.name or child.name.startswith(prefix)
                ):
                    candidates.add(child)
        except Exception:
            pass

    removed = []

    for candidate in candidates:
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            if threshold and candidate.stat().st_mtime < threshold:
                continue

            candidate.unlink()
            removed.append(str(candidate))
        except Exception:
            pass

    return removed


def cancel_paused_active(active):
    job_id = active.get("id")
    clear_control(job_id)
    cleanup_paused_job_files(active)

    def mutate(data):
        current = data.get("active")
        if not current or current.get("id") != job_id:
            return
        current["status"] = "cancelled"
        current["speed"] = None
        current["eta"] = None
        current["error"] = None
        current["worker_pid"] = None
        current["finished_at"] = time.time()
        current["updated_at"] = time.time()
        current.pop("pause_requested", None)
        data.setdefault("history", []).insert(0, dict(current))
        data["history"] = data["history"][:50]
        data["active"] = None

    with_state(mutate)
    start_next_if_idle()
    return {"ok": True, "state": snapshot()}


def toggle_queue_item_pause(job_id):
    result = {"found": False, "paused": False}

    def mutate(data):
        for job in data.get("queue", []):
            if job.get("id") != job_id:
                continue
            result["found"] = True
            job["paused"] = not bool(job.get("paused"))
            job["updated_at"] = time.time()
            result["paused"] = job["paused"]
            break

    with_state(mutate)

    if not result["found"]:
        return {"ok": False, "error": "Élément introuvable dans la file.", "state": snapshot()}

    if not result["paused"]:
        start_next_if_idle()

    return {"ok": True, "paused": result["paused"], "state": snapshot()}


def set_queue_paused(paused):
    def mutate(data):
        data["queue_paused"] = bool(paused)

    with_state(mutate)
    if not paused:
        start_next_if_idle()
    return {"ok": True, "queue_paused": bool(paused), "state": snapshot()}


def cancel_active():
    state = snapshot()
    active = state.get("active")
    if not active:
        return {"ok": True, "state": state}

    if active.get("status") == "paused":
        clear_control(active.get("id"))
        return cancel_paused_active(active)

    # Explicit Kitty cancel: mark intent BEFORE SIGTERM so the worker can
    # distinguish it from pkill/system shutdown/maintenance.
    set_control(active.get("id"), "cancel")

    pid = active.get("worker_pid")
    if not WINDOWS and pid and worker_matches_job(pid, active.get("id")):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    return {"ok": True, "state": snapshot()}

def remove_queued(job_id):
    def mutate(data):
        data["queue"] = [j for j in data.get("queue", []) if j.get("id") != job_id]
    with_state(mutate)
    start_next_if_idle()
    return {"ok": True, "state": snapshot()}

def repair_state():
    """Validate/migrate state and recover active jobs that cannot be real."""
    should_start_next = {"value": False}
    metadata_to_restart = []
    now = time.time()

    def archive_active_as_error(data, active, message):
        active["status"] = "error"
        active["error"] = message
        active["speed"] = None
        active["eta"] = None
        active["worker_pid"] = None
        active["finished_at"] = now
        active["updated_at"] = now
        active.pop("control_request", None)
        active.pop("pause_requested", None)
        active.pop("paused_from_status", None)
        data.setdefault("history", []).insert(0, dict(active))
        data["history"] = data["history"][:50]
        data["active"] = None
        should_start_next["value"] = True

    def mutate(data):
        data["state_version"] = STATE_VERSION
        data["queue_paused"] = bool(data.get("queue_paused", False))

        # Queue : uniquement des jobs encore en attente. Une pause de file est
        # un simple booléen et n'a aucun lien avec la mécanique de yt-dlp.
        normalized_queue = []
        for job in data.get("queue", []):
            clean = normalize_job(job, queued=True)
            if clean is None:
                continue

            if clean.get("title"):
                clean["metadata_status"] = "ready"
                clean["metadata_error"] = None
                clean["metadata_pid"] = None
            else:
                meta_status = clean.get("metadata_status") or "pending"
                meta_pid = clean.get("metadata_pid")
                attempts = int(clean.get("metadata_attempts") or 0)
                started = float(clean.get("metadata_started_at") or 0)

                if meta_status == "pending" and attempts < 2:
                    metadata_to_restart.append(dict(clean))
                elif meta_status == "fetching":
                    age = now - started if started else 999
                    if age > 3.0 and not metadata_process_matches_job(meta_pid, clean.get("id")):
                        if attempts < 2:
                            clean["metadata_status"] = "pending"
                            clean["metadata_pid"] = None
                            metadata_to_restart.append(dict(clean))
                        else:
                            clean["metadata_status"] = "error"
                            clean["metadata_error"] = (
                                "Le probe métadonnées s’est arrêté avant de renvoyer un titre."
                            )
                            clean["metadata_pid"] = None

            normalized_queue.append(clean)

        data["queue"] = normalize_queue_priority(normalized_queue)

        active = data.get("active")
        if not active:
            return

        status = active.get("status")

        # La pause active n'existe plus. Si un ancien état V7.2.2/V7.3 en
        # contient une, le libérer au lieu de bloquer toute la file.
        if status == "paused":
            clear_control(active.get("id"))
            archive_active_as_error(
                data,
                active,
                "Ancien état de pause actif détecté et libéré automatiquement.",
            )
            return

        # Un état final ne doit jamais rester dans active.
        if status in ("finished", "error", "cancelled"):
            data.setdefault("history", []).insert(0, dict(active))
            data["history"] = data["history"][:50]
            data["active"] = None
            should_start_next["value"] = True
            return

        if status not in ("starting", "downloading"):
            updated = float(active.get("updated_at") or active.get("started_at") or now)
            if now - updated >= 4.0:
                archive_active_as_error(
                    data,
                    active,
                    f"État actif inconnu ({status!r}) récupéré automatiquement.",
                )
            return

        pid = active.get("worker_pid")
        updated = float(active.get("updated_at") or active.get("started_at") or now)

        # Pendant quelques secondes après spawn, worker_pid peut encore être
        # absent : ne pas prendre un démarrage normal pour un crash.
        if now - updated < 4.0:
            return

        if worker_matches_job(pid, active.get("id")):
            return

        clear_control(active.get("id"))
        archive_active_as_error(
            data,
            active,
            "Le worker du téléchargement a disparu ou ne correspond plus au job actif.",
        )

    with_state(mutate)

    # Toujours spawn hors du lock de queue.json.
    seen_meta = set()
    for job in metadata_to_restart:
        job_id = job.get("id")
        if not job_id or job_id in seen_meta:
            continue
        seen_meta.add(job_id)
        spawn_metadata(job)

    if should_start_next["value"]:
        start_next_if_idle()
    return snapshot()


def clear_history():
    with_state(lambda d: d.update({"history": []}))
    return {"ok": True, "state": snapshot()}

def open_folder():
    output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    folder = str(output_dir)
    if WINDOWS:
        try:
            os.startfile(folder)
            return {"ok": True, "opener": "explorer"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        + ":"
        + os.environ.get("DESKTOP_SESSION", "")
    ).lower()

    # Préférences par environnement de bureau.
    preferred = []
    if "kde" in desktop or "plasma" in desktop:
        preferred += [["dolphin", folder]]
    if "gnome" in desktop or "ubuntu" in desktop:
        preferred += [["nautilus", folder]]
    if "xfce" in desktop:
        preferred += [["thunar", folder]]
    if "cinnamon" in desktop:
        preferred += [["nemo", folder]]
    if "mate" in desktop:
        preferred += [["caja", folder]]
    if "lxqt" in desktop:
        preferred += [["pcmanfm-qt", folder]]
    if "lxde" in desktop:
        preferred += [["pcmanfm", folder]]

    # Puis essaie les gestionnaires courants réellement installés.
    candidates = preferred + [
        ["nautilus", folder],
        ["dolphin", folder],
        ["thunar", folder],
        ["nemo", folder],
        ["caja", folder],
        ["pcmanfm-qt", folder],
        ["pcmanfm", folder],
    ]

    seen = set()
    errors = []

    for cmd in candidates:
        name = cmd[0]
        if name in seen:
            continue
        seen.add(name)

        executable = shutil.which(name)
        if not executable:
            continue

        try:
            subprocess.Popen(
                [executable, folder],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **spawn_options(),
            )
            return {"ok": True, "opener": name}
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    # Dernier recours : gio, puis xdg-open.
    for name, args in [
        ("gio", ["open", folder]),
        ("xdg-open", [folder]),
    ]:
        executable = shutil.which(name)
        if not executable:
            continue
        try:
            subprocess.Popen(
                [executable, *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **spawn_options(),
            )
            return {"ok": True, "opener": name}
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    detail = "; ".join(errors) if errors else "aucun gestionnaire de fichiers trouvé"
    return {"ok": False, "error": f"Impossible d'ouvrir le dossier ({detail})."}

def _first_output_line(text):
    lines = str(text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _command_probe(executable_name, args, required=True):
    executable = shutil.which(executable_name)
    result = {
        "id": executable_name,
        "label": executable_name,
        "required": bool(required),
        "ok": False,
        "version": None,
        "path": None,
        "error": None,
    }

    if not executable:
        result["error"] = "non installé"
        return result

    result["path"] = executable
    try:
        proc = run_hidden(
            [executable, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=4,
            check=False,
        )
        first = _first_output_line(proc.stdout)
        result["version"] = first or "version inconnue"
        result["ok"] = proc.returncode == 0
        if proc.returncode != 0:
            result["error"] = f"code de sortie {proc.returncode}"
    except subprocess.TimeoutExpired:
        result["error"] = "délai dépassé"
    except Exception as exc:
        result["error"] = str(exc)[:300]

    return result


def _python_module_probe(import_name, distribution_name, label, required=True):
    result = {
        "id": import_name,
        "label": label,
        "required": bool(required),
        "ok": False,
        "version": None,
        "path": None,
        "error": None,
    }

    try:
        module = importlib.import_module(import_name)
        result["ok"] = True
        module_file = getattr(module, "__file__", None)
        if module_file:
            result["path"] = str(module_file)

        try:
            result["version"] = importlib.metadata.version(distribution_name)
        except Exception:
            result["version"] = str(getattr(module, "version", None) or getattr(module, "__version__", None) or "installé")
    except Exception as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"[:300]

    return result


def _python_probe():
    return {
        "id": "python",
        "label": "Python",
        "required": True,
        "ok": True,
        "version": platform.python_version(),
        "path": sys.executable,
        "error": None,
    }


def dependency_status():
    """
    État des dépendances réellement utilisées par le runtime.

    yt-dlp est testé comme module Python, car worker.py/metadata.py l'importent
    directement. Le binaire CLI n'est donc pas considéré comme la source de
    vérité.
    """
    deps = [
        _python_probe(),
        _python_module_probe("yt_dlp", "yt-dlp", "yt-dlp", required=True),
        _command_probe("ffmpeg", ["-version"], required=True),
        _command_probe("ffprobe", ["-version"], required=True),
        _python_module_probe("mutagen", "mutagen", "Mutagen", required=False),
    ]
    if WINDOWS:
        deps.extend([
            _python_module_probe("psutil", "psutil", "Support Windows", required=True),
            _command_probe("deno", ["--version"], required=True),
        ])

    # Raccourcir les sorties ffmpeg/ffprobe, qui commencent généralement par
    # "ffmpeg version ..." / "ffprobe version ...".
    for dep in deps:
        version = dep.get("version")
        if isinstance(version, str) and len(version) > 160:
            dep["version"] = version[:157] + "…"

    required_missing = [
        dep["id"] for dep in deps
        if dep.get("required") and not dep.get("ok")
    ]
    optional_missing = [
        dep["id"] for dep in deps
        if not dep.get("required") and not dep.get("ok")
    ]

    return {
        "items": deps,
        "required_ok": not required_missing,
        "required_missing": required_missing,
        "optional_missing": optional_missing,
    }



def _run_update_command(command, timeout=18):
    try:
        proc = run_hidden(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or ""
    except Exception as exc:
        return 127, str(exc)


def _parse_package_manager_updates():
    """Return distro package updates without requiring root.

    Arch's checkupdates is preferred because it refreshes sync databases in a
    temporary location. Other package managers use their current local cache;
    the UI labels that limitation instead of pretending the result is fresh.
    """
    if WINDOWS:
        return {}, "indisponible", False, False

    updates = {}
    network_used = False
    fresh = False
    source = "indisponible"

    checkupdates = shutil.which("checkupdates")
    if checkupdates:
        code, output = _run_update_command([checkupdates], timeout=30)
        # checkupdates may use non-zero when no update is available.
        for line in output.splitlines():
            match = re.match(r"^([^\s]+)\s+([^\s]+)\s+->\s+([^\s]+)", line.strip())
            if match:
                updates[match.group(1)] = {"current": match.group(2), "available": match.group(3)}
        source = "Arch checkupdates"
        network_used = True
        fresh = True
        return updates, source, network_used, fresh

    pacman = shutil.which("pacman")
    if pacman:
        _, output = _run_update_command([pacman, "-Qu"], timeout=12)
        for line in output.splitlines():
            match = re.match(r"^([^\s]+)\s+([^\s]+)\s+->\s+([^\s]+)", line.strip())
            if match:
                updates[match.group(1)] = {"current": match.group(2), "available": match.group(3)}
        return updates, "pacman -Qu (cache locale)", False, False

    apt = shutil.which("apt")
    if apt:
        _, output = _run_update_command([apt, "list", "--upgradable"], timeout=12)
        for line in output.splitlines():
            # pkg/repo new arch [upgradable from: old]
            match = re.match(r"^([^/\s]+)/\S+\s+([^\s]+).*\[upgradable from:\s*([^\]]+)\]", line.strip())
            if match:
                updates[match.group(1)] = {"current": match.group(3), "available": match.group(2)}
        return updates, "apt (cache locale)", False, False

    dnf = shutil.which("dnf")
    if dnf:
        _, output = _run_update_command([dnf, "check-update", "--cacheonly", "--quiet"], timeout=15)
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "." in parts[0]:
                name = parts[0].rsplit(".", 1)[0]
                updates[name] = {"current": None, "available": parts[1]}
        return updates, "dnf (cache locale)", False, False

    return updates, source, network_used, fresh


def _pypi_latest(distribution, timeout=5):
    try:
        request = Request(
            f"https://pypi.org/pypi/{distribution}/json",
            headers={"User-Agent": f"Kitty-Download-Manager/{APP_VERSION}"},
        )
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(1_500_000).decode("utf-8"))
        version = str(data.get("info", {}).get("version") or "").strip()
        return version or None, None
    except Exception as exc:
        return None, str(exc)[:240]


def _candidate_packages(dep_id):
    return {
        "python": ("python", "python3"),
        "yt_dlp": ("yt-dlp", "yt_dlp"),
        "ffmpeg": ("ffmpeg",),
        "ffprobe": ("ffmpeg",),
        "mutagen": ("python-mutagen", "python3-mutagen", "mutagen"),
    }.get(dep_id, ())


def _available_from_packages(dep_id, package_updates):
    for name in _candidate_packages(dep_id):
        item = package_updates.get(name)
        if item:
            return item.get("available"), name, item.get("current")
    return None, None, None


def _atomic_update_cache(data):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = UPDATE_CACHE_FILE.with_name(UPDATE_CACHE_FILE.name + f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, UPDATE_CACHE_FILE)
    except Exception:
        pass


def cached_update_report():
    try:
        if not UPDATE_CACHE_FILE.is_file() or UPDATE_CACHE_FILE.is_symlink():
            return None
        data = json.loads(UPDATE_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        checked_at = float(data.get("checked_at") or 0)
        data["age_seconds"] = max(0, int(time.time() - checked_at)) if checked_at else None
        data["stale"] = not checked_at or (time.time() - checked_at) > 7 * 24 * 3600
        return data
    except Exception:
        return None



def _atomic_kitty_release_cache(data):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = KITTY_RELEASE_CACHE_FILE.with_name(KITTY_RELEASE_CACHE_FILE.name + f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, KITTY_RELEASE_CACHE_FILE)
    except Exception:
        pass


def cached_kitty_release_report():
    try:
        if not KITTY_RELEASE_CACHE_FILE.is_file() or KITTY_RELEASE_CACHE_FILE.is_symlink():
            return None
        data = json.loads(KITTY_RELEASE_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        checked_at = float(data.get("checked_at") or 0)
        data["age_seconds"] = max(0, int(time.time() - checked_at)) if checked_at else None
        data["stale"] = not checked_at or (time.time() - checked_at) > 24 * 3600
        return data
    except Exception:
        return None


def _normalize_release_version(tag):
    value = str(tag or "").strip()
    if value[:1].lower() == "v":
        value = value[1:]
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", value):
        raise RuntimeError(f"Tag de release Kitty invalide: {tag!r}")
    return value


def _kitty_release_error(message, *, save_cache=True):
    report = {
        "ok": False,
        "checked_at": time.time(),
        "current_version": APP_VERSION,
        "latest_version": None,
        "state": "error",
        "update_available": False,
        "up_to_date": False,
        "local_newer": False,
        "download_supported": False,
        "repository": KITTY_RELEASE_REPO,
        "error": str(message)[:500],
    }
    if save_cache:
        _atomic_kitty_release_cache(report)
    return report


def check_kitty_release(save_cache=True, timeout=10):
    """Explicit GitHub release check. Never called by local diagnostics."""
    try:
        request = Request(
            KITTY_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"Kitty-Download-Manager/{APP_VERSION}",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("Réponse GitHub invalide.")

        latest = _normalize_release_version(data.get("tag_name"))
        suffix = "-windows-x64" if WINDOWS else ""
        expected_name = f"kitty-download-manager-v{latest}{suffix}.zip"
        assets = data.get("assets") if isinstance(data.get("assets"), list) else []
        asset = next(
            (item for item in assets if isinstance(item, dict) and item.get("name") == expected_name),
            None,
        )

        current_key = version_tuple(APP_VERSION)
        latest_key = version_tuple(latest)
        if not current_key or not latest_key:
            raise RuntimeError("Version Kitty impossible à comparer.")

        if latest_key > current_key:
            state = "update_available"
        elif latest_key == current_key:
            state = "up_to_date"
        else:
            state = "local_newer"

        asset_url = str((asset or {}).get("browser_download_url") or "")
        digest = str((asset or {}).get("digest") or "").lower()
        digest_match = re.fullmatch(r"sha256:([0-9a-f]{64})", digest)
        asset_size = int((asset or {}).get("size") or 0)
        download_supported = bool(
            asset
            and asset_url.startswith("https://github.com/")
            and digest_match
            and 0 < asset_size <= KITTY_RELEASE_MAX_BYTES
        )

        report = {
            "ok": True,
            "checked_at": time.time(),
            "repository": KITTY_RELEASE_REPO,
            "current_version": APP_VERSION,
            "latest_version": latest,
            "state": state,
            "update_available": state == "update_available",
            "up_to_date": state == "up_to_date",
            "local_newer": state == "local_newer",
            "release_url": str(data.get("html_url") or ""),
            "published_at": data.get("published_at"),
            "asset_name": (asset or {}).get("name"),
            "asset_url": asset_url or None,
            "asset_size": asset_size or None,
            "asset_digest": digest or None,
            "asset_sha256": digest_match.group(1) if digest_match else None,
            "download_supported": download_supported,
            "error": None if asset else f"Asset attendu absent: {expected_name}",
        }
        if asset and not digest_match:
            report["error"] = "SHA-256 GitHub absent ou invalide pour cette release."
        elif asset and asset_size > KITTY_RELEASE_MAX_BYTES:
            report["error"] = "Archive de mise à jour anormalement volumineuse."
        elif asset and not asset_url.startswith("https://github.com/"):
            report["error"] = "URL de téléchargement de release inattendue."

        if save_cache:
            _atomic_kitty_release_cache(report)
        return report
    except Exception as exc:
        return _kitty_release_error(exc, save_cache=save_cache)


def download_kitty_update():
    """Download the latest release archive to ~/Downloads and verify GitHub SHA-256."""
    release = check_kitty_release(save_cache=True, timeout=12)
    if not release.get("ok"):
        return {
            "ok": False,
            "code": "kitty_update_check_failed",
            "error": release.get("error") or "Vérification GitHub impossible.",
            "release": release,
        }
    if not release.get("update_available"):
        return {
            "ok": False,
            "code": "kitty_update_unavailable",
            "error": "Aucune mise à jour Kitty plus récente n’est disponible.",
            "release": release,
        }
    if not release.get("download_supported") or not release.get("asset_sha256"):
        return {
            "ok": False,
            "code": "kitty_update_digest_missing",
            "error": release.get("error") or "SHA-256 de la release indisponible.",
            "release": release,
        }

    url = str(release.get("asset_url") or "")
    parsed = urlsplit(url)
    expected_prefix = f"/{KITTY_RELEASE_REPO}/releases/download/"
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not parsed.path.startswith(expected_prefix):
        return {
            "ok": False,
            "code": "kitty_update_download_failed",
            "error": "URL de téléchargement GitHub inattendue.",
            "release": release,
        }

    expected_size = int(release.get("asset_size") or 0)
    if expected_size <= 0 or expected_size > KITTY_RELEASE_MAX_BYTES:
        return {
            "ok": False,
            "code": "kitty_update_download_failed",
            "error": "Taille de l’archive de mise à jour invalide.",
            "release": release,
        }

    download_cache = CACHE_DIR / "release-downloads"
    download_cache.mkdir(parents=True, exist_ok=True)
    temp_path = download_cache / f".{release['asset_name']}.tmp-{os.getpid()}"
    try:
        temp_path.unlink(missing_ok=True)
    except Exception:
        pass

    hasher = hashlib.sha256()
    written = 0
    try:
        request = Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": f"Kitty-Download-Manager/{APP_VERSION}",
            },
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temp_path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=True) as out, urlopen(request, timeout=45) as response:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > KITTY_RELEASE_MAX_BYTES or written > expected_size:
                        raise RuntimeError("Archive de mise à jour plus volumineuse que prévu.")
                    hasher.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
        except Exception:
            # fd is owned by fdopen once entered; close only if fdopen itself failed.
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        if written != expected_size:
            raise RuntimeError(f"Taille reçue incorrecte ({written} au lieu de {expected_size} octets).")

        actual_sha = hasher.hexdigest().lower()
        expected_sha = str(release.get("asset_sha256") or "").lower()
        if actual_sha != expected_sha:
            return {
                "ok": False,
                "code": "kitty_update_integrity_failed",
                "error": f"SHA-256 reçu {actual_sha}, attendu {expected_sha}.",
                "release": release,
                "verified": False,
            }

        downloads = DOWNLOADS_DIR
        downloads.mkdir(parents=True, exist_ok=True)
        target = downloads / str(release["asset_name"])
        target_tmp = downloads / f".{release['asset_name']}.tmp-{os.getpid()}"
        try:
            target_tmp.unlink(missing_ok=True)
        except Exception:
            pass
        shutil.copyfile(temp_path, target_tmp)
        os.chmod(target_tmp, 0o644)
        os.replace(target_tmp, target)

        return {
            "ok": True,
            "release": release,
            "version": release.get("latest_version"),
            "filename": release.get("asset_name"),
            "path": _redact_home(target),
            "sha256": actual_sha,
            "verified": True,
            "size": written,
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": "kitty_update_download_failed",
            "error": str(exc),
            "release": release,
        }
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


def check_dependency_updates(client=None, save_cache=True):
    """Explicit dependency update check. Local diagnostics never call it automatically."""
    deps = dependency_status()
    package_updates, package_source, package_network, package_fresh = _parse_package_manager_updates()
    items = []
    network_used = bool(package_network)
    pypi_errors = []

    for dep in deps.get("items", []):
        dep_id = dep.get("id")
        current = dep.get("version") if dep.get("ok") else None
        available, package_name, manager_current = _available_from_packages(dep_id, package_updates)
        source = package_source if available else None
        fresh = package_fresh if available else False

        # PyPI fallback only for Python modules not represented by the distro
        # package-manager result. It is advisory; Kitty never pip-installs over
        # distro packages automatically.
        if not available and dep_id in {"yt_dlp", "mutagen"} and dep.get("ok"):
            distribution = "yt-dlp" if dep_id == "yt_dlp" else "mutagen"
            available, error = _pypi_latest(distribution)
            network_used = True
            source = "PyPI"
            fresh = True
            package_name = distribution
            if error:
                pypi_errors.append(f"{distribution}: {error}")

        current_compare = manager_current or current
        old_tuple = version_tuple(current_compare)
        new_tuple = version_tuple(available)
        update_available = bool(old_tuple and new_tuple and new_tuple > old_tuple)
        risk = assess_update_risk(dep_id, current_compare, available) if update_available else {
            "risk": "none",
            "potential_incompatibility": False,
            "reason": "À jour ou aucune mise à jour détectée.",
        }

        items.append({
            "id": dep_id,
            "label": dep.get("label") or dep_id,
            "required": bool(dep.get("required")),
            "installed": bool(dep.get("ok")),
            "current": current,
            "available": available,
            "update_available": update_available,
            "potential_incompatibility": bool(risk.get("potential_incompatibility")),
            "risk": risk.get("risk"),
            "reason": risk.get("reason"),
            "source": source,
            "source_fresh": bool(fresh),
            "package": package_name,
        })

    updates_available = sum(1 for item in items if item.get("update_available"))
    risky_updates = sum(1 for item in items if item.get("update_available") and item.get("potential_incompatibility"))
    compatibility = client_report(client, APP_VERSION)

    if package_source == "indisponible":
        source_note = "Gestionnaire de paquets non détecté; PyPI vérifie seulement yt-dlp/Mutagen."
    elif package_fresh:
        source_note = f"{package_source} + PyPI si nécessaire"
    else:
        source_note = f"{package_source}; base système potentiellement non rafraîchie + PyPI si nécessaire"

    report = {
        "checked_at": time.time(),
        "kitty_version": APP_VERSION,
        "items": items,
        "updates_available": updates_available,
        "risky_updates": risky_updates,
        "potential_incompatibility": risky_updates > 0 or not compatibility.get("compatible", True),
        "needs_attention": updates_available > 0 or not compatibility.get("compatible", True),
        "network_used": network_used,
        "package_source": package_source,
        "package_source_fresh": package_fresh,
        "source_note": source_note,
        "errors": pypi_errors,
        "compatibility": compatibility,
    }
    if save_cache:
        _atomic_update_cache(report)
    return report


def _redact_home(value):
    if not value:
        return value

    text = str(value)
    try:
        home = str(Path.home().resolve(strict=False))
        resolved = str(Path(text).expanduser().resolve(strict=False))
        if resolved == home:
            return "~"
        if resolved.startswith(home + os.sep):
            return "~" + resolved[len(home):]
    except Exception:
        pass
    return text


def _safe_file_size(path):
    try:
        path = Path(path)
        if path.is_file() and not path.is_symlink():
            return int(path.stat().st_size)
    except Exception:
        pass
    return 0


def _cache_path_is_safe(path):
    """True only for an entry lexically contained in Kitty's private cache."""
    try:
        path = Path(path)
        if CACHE_DIR.is_symlink() or path == CACHE_DIR:
            return False
        root = CACHE_DIR.resolve(strict=False)
        parent = path.parent.resolve(strict=False)
        return parent == root or root in parent.parents
    except Exception:
        return False


def _path_mtime(path):
    try:
        return float(Path(path).lstat().st_mtime)
    except Exception:
        return 0.0


def _safe_cache_remove(path):
    """Remove only an explicitly selected cache entry, never following links."""
    path = Path(path)
    if not _cache_path_is_safe(path):
        return {"removed": 0, "freed_bytes": 0}

    stats = safe_tree_stats(path)
    try:
        if path.is_symlink():
            path.unlink()
            return {"removed": 1, "freed_bytes": 0}
        if path.is_dir():
            shutil.rmtree(path)
            return {
                "removed": max(1, int(stats.get("files") or 0)),
                "freed_bytes": int(stats.get("bytes") or 0),
            }
        if path.is_file():
            size = _safe_file_size(path)
            path.unlink()
            return {"removed": 1, "freed_bytes": size}
    except Exception:
        return {"removed": 0, "freed_bytes": 0}
    return {"removed": 0, "freed_bytes": 0}


def _cache_job_context(state):
    state = state if isinstance(state, dict) else {}
    active = state.get("active") if isinstance(state.get("active"), dict) else None
    queued = [job for job in (state.get("queue") or []) if isinstance(job, dict)]
    history = [job for job in (state.get("history") or []) if isinstance(job, dict)]

    live_jobs = ([active] if active else []) + queued
    live_ids = {
        str(job.get("id")) for job in live_jobs
        if job.get("id") is not None
    }

    live_destinations = set()
    known_destinations = set()
    try:
        known_destinations.add(str(get_output_dir().resolve(strict=False)))
    except Exception:
        pass

    for job in live_jobs + history:
        raw = job.get("output_dir")
        if not raw:
            continue
        try:
            normalized = str(Path(raw).expanduser().resolve(strict=False))
        except Exception:
            continue
        known_destinations.add(normalized)
        if job in live_jobs:
            live_destinations.add(normalized)

    return {
        "live_ids": live_ids,
        "live_destinations": live_destinations,
        "known_destinations": known_destinations,
    }


def _cache_cleanup_candidates(state):
    """Return only private-cache entries proven safe to delete."""
    context = _cache_job_context(state)
    live_ids = context["live_ids"]
    now = time.time()
    candidates = []

    def add(category, path):
        path = Path(path)
        if _cache_path_is_safe(path) and (path.exists() or path.is_symlink()):
            candidates.append({"category": category, "path": path})

    # Control markers are meaningful only for the currently live job IDs.
    if CONTROL_DIR.is_dir() and not CONTROL_DIR.is_symlink():
        for path in CONTROL_DIR.iterdir():
            if path.name.startswith("."):
                continue
            if path.stem not in live_ids:
                add("temporary", path)

    # Per-job cookie snapshots are private cache copies. Keep every live job's
    # snapshot and discard copies left behind by completed/failed jobs.
    if AUTH_JOB_DIR.is_dir() and not AUTH_JOB_DIR.is_symlink():
        for path in AUTH_JOB_DIR.iterdir():
            keep = any(path.name.startswith(job_id + ".") for job_id in live_ids)
            if not keep:
                add("snapshots", path)

    # Collection cookie snapshots have random IDs. Normal flows remove them in
    # finally blocks; only old leftovers are reclaimed here to avoid racing a
    # collection extraction running in another Native Messaging process.
    if YOUTUBE_PLAYLIST_AUTH_DIR.is_dir() and not YOUTUBE_PLAYLIST_AUTH_DIR.is_symlink():
        for path in YOUTUBE_PLAYLIST_AUTH_DIR.iterdir():
            if now - _path_mtime(path) >= CACHE_TRANSIENT_MIN_AGE:
                add("snapshots", path)

    # YouTube login profiles are disposable snapshots. The exact pending token
    # is protected; only other marker-validated session roots are candidates.
    pending = _youtube_pending_load() or {}
    pending_token = pending.get("token")
    if YOUTUBE_SESSION_ROOT.is_dir() and not YOUTUBE_SESSION_ROOT.is_symlink():
        for root in YOUTUBE_SESSION_ROOT.iterdir():
            token = root.name
            if token == pending_token:
                continue
            if not re.fullmatch(r"[0-9a-f]{32}", token):
                continue
            marker = root / YOUTUBE_SESSION_MARKER
            try:
                if root.is_dir() and not root.is_symlink() and marker.is_file() and not marker.is_symlink():
                    if marker.read_text(encoding="utf-8").strip() == token:
                        add("snapshots", root)
            except Exception:
                continue

    # Update backups are intentionally bounded. Keep the three newest of each
    # recovery kind so a manual cache cleanup never removes the last rollback.
    if UPDATE_BACKUP_DIR.is_dir() and not UPDATE_BACKUP_DIR.is_symlink():
        groups = (
            ("backend-v*", "update_backups"),
            ("native-manifest-*.json", "update_backups"),
            ("queue-pre-*.json", "update_backups"),
        )
        for pattern, category in groups:
            items = []
            for path in UPDATE_BACKUP_DIR.glob(pattern):
                if path.exists() or path.is_symlink():
                    items.append(path)
            items.sort(key=_path_mtime, reverse=True)
            for old in items[MAX_UPDATE_BACKUPS_PER_KIND:]:
                add(category, old)

    # Atomic-write leftovers at cache root are safe only after an hour.
    if CACHE_DIR.is_dir() and not CACHE_DIR.is_symlink():
        for path in CACHE_DIR.iterdir():
            name = path.name
            if name in {QUEUE_FILE.name, LOCK_FILE.name, UPDATE_CACHE_FILE.name, KITTY_RELEASE_CACHE_FILE.name, LOG_FILE.name}:
                continue
            if (name.endswith(".tmp") or ".tmp-" in name) and now - _path_mtime(path) >= CACHE_TRANSIENT_MIN_AGE:
                add("temporary", path)

    return candidates


def _looks_like_partial_file(path):
    name = Path(path).name.lower()
    return name.endswith(".part") or name.endswith(".ytdl") or ".part-frag" in name


def _orphan_partial_health(state):
    """Conservative detection only. These files are never deleted by cache cleanup."""
    context = _cache_job_context(state)
    live_destinations = context["live_destinations"]
    now = time.time()
    count = 0
    size = 0
    scanned = 0

    for raw in sorted(context["known_destinations"]):
        try:
            directory = Path(raw)
            resolved = str(directory.resolve(strict=False))
            if resolved in live_destinations:
                # If any live job uses this folder, every partial there is
                # protected because yt-dlp's final stem is not always known yet.
                continue
            if directory.is_symlink() or not directory.is_dir():
                continue
            scanned += 1
            for child in directory.iterdir():
                try:
                    if child.is_symlink() or not child.is_file() or not _looks_like_partial_file(child):
                        continue
                    if now - child.stat().st_mtime < ORPHAN_PARTIAL_MIN_AGE:
                        continue
                    count += 1
                    size += int(child.stat().st_size)
                except Exception:
                    continue
        except Exception:
            continue

    return {
        "count": count,
        "bytes": size,
        "scanned_destinations": scanned,
        "deleted_by_cache_cleanup": False,
        "minimum_age_seconds": ORPHAN_PARTIAL_MIN_AGE,
    }


def _cache_storage_health(state=None):
    state = state if isinstance(state, dict) else repair_state()
    total = safe_tree_stats(CACHE_DIR)
    logs = log_stats()
    state_backups = safe_tree_stats(STATE_BACKUP_DIR)
    update_backups = safe_tree_stats(UPDATE_BACKUP_DIR)

    temporary = {"bytes": 0, "files": 0}
    for path in (CONTROL_DIR, AUTH_JOB_DIR, YOUTUBE_PLAYLIST_AUTH_DIR, YOUTUBE_SESSION_ROOT):
        stats = safe_tree_stats(path)
        temporary["bytes"] += int(stats.get("bytes") or 0)
        temporary["files"] += int(stats.get("files") or 0)

    candidates = _cache_cleanup_candidates(state)
    reclaimable_bytes = int(logs.get("archive_bytes") or 0)
    reclaimable_files = int(logs.get("archive_count") or 0)
    for item in candidates:
        stats = safe_tree_stats(item["path"])
        if item["path"].is_file() and not item["path"].is_symlink() and not stats.get("files"):
            stats = {"bytes": _safe_file_size(item["path"]), "files": 1}
        reclaimable_bytes += int(stats.get("bytes") or 0)
        reclaimable_files += max(1, int(stats.get("files") or 0))

    return {
        "total_bytes": int(total.get("bytes") or 0),
        "total_files": int(total.get("files") or 0),
        "logs_bytes": int(logs.get("total_bytes") or 0),
        "log_current_bytes": int(logs.get("current_bytes") or 0),
        "log_archive_bytes": int(logs.get("archive_bytes") or 0),
        "log_archive_count": int(logs.get("archive_count") or 0),
        "log_max_file_bytes": int(LOG_MAX_BYTES),
        "log_max_archives": int(LOG_ARCHIVE_COUNT),
        "temporary_bytes": int(temporary["bytes"]),
        "temporary_files": int(temporary["files"]),
        "update_backups_bytes": int(update_backups.get("bytes") or 0),
        "update_backups_files": int(update_backups.get("files") or 0),
        "state_backups_bytes": int(state_backups.get("bytes") or 0),
        "state_backups_files": int(state_backups.get("files") or 0),
        "reclaimable_bytes": reclaimable_bytes,
        "reclaimable_files": reclaimable_files,
        "orphan_partials": _orphan_partial_health(state),
    }


def clean_cache():
    """Clean only Kitty's private cache; completed/partial downloads are untouched."""
    state = repair_state()
    before = _cache_storage_health(state)
    categories = {}
    removed = 0
    freed = 0

    log_result = purge_rotated_logs()
    if log_result.get("removed"):
        categories["old_logs"] = {
            "removed": int(log_result.get("removed") or 0),
            "freed_bytes": int(log_result.get("freed_bytes") or 0),
        }
        removed += categories["old_logs"]["removed"]
        freed += categories["old_logs"]["freed_bytes"]

    for item in _cache_cleanup_candidates(state):
        category = item["category"]
        path = item["path"]
        result = {"removed": 0, "freed_bytes": 0}

        if category == "snapshots" and path.parent == YOUTUBE_SESSION_ROOT:
            try:
                token = path.name
                stats = safe_tree_stats(path)
                _safe_remove_youtube_session(token)
                result = {
                    "removed": max(1, int(stats.get("files") or 0)),
                    "freed_bytes": int(stats.get("bytes") or 0),
                }
            except Exception:
                result = {"removed": 0, "freed_bytes": 0}
        else:
            result = _safe_cache_remove(path)

        if result["removed"]:
            bucket = categories.setdefault(category, {"removed": 0, "freed_bytes": 0})
            bucket["removed"] += int(result["removed"])
            bucket["freed_bytes"] += int(result["freed_bytes"])
            removed += int(result["removed"])
            freed += int(result["freed_bytes"])

    after = _cache_storage_health(state)
    return {
        "ok": True,
        "removed": removed,
        "freed_bytes": freed,
        "categories": categories,
        "before": before,
        "cache": after,
        "downloads_touched": False,
        "orphan_partials_deleted": 0,
    }


def _destination_health(deep=False):
    path = get_output_dir()
    result = {
        "exists": False,
        "directory": False,
        "writable": False,
        "write_tested": False,
        "free_bytes": None,
        "error": None,
    }

    try:
        result["exists"] = path.exists()
        result["directory"] = path.is_dir()

        if not result["directory"]:
            result["error"] = "Le dossier de destination n’existe pas."
            return result

        result["writable"] = os.access(path, os.W_OK | os.X_OK)

        try:
            result["free_bytes"] = int(shutil.disk_usage(path).free)
        except Exception:
            result["free_bytes"] = None

        if deep:
            probe = path / f".kitty-diagnostic-{uuid.uuid4().hex}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW

            fd = None
            try:
                fd = os.open(probe, flags, 0o600)
                os.write(fd, b"kitty-diagnostic\n")
                os.fsync(fd)
                result["writable"] = True
                result["write_tested"] = True
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
                try:
                    probe.unlink(missing_ok=True)
                except Exception:
                    pass

        if not result["writable"]:
            result["error"] = "La destination n’est pas accessible en écriture."
    except Exception as exc:
        result["writable"] = False
        result["error"] = str(exc)[:300]

    return result


def _runtime_files_health():
    files = [
        ("host", Path(__file__).resolve()),
        ("worker", WORKER),
        ("metadata", META_WORKER),
    ]

    items = []
    for item_id, path in files:
        try:
            ok = path.is_file() and not path.is_symlink()
        except Exception:
            ok = False
        items.append({
            "id": item_id,
            "ok": ok,
            "path": _redact_home(path),
        })

    return {
        "items": items,
        "ok": all(item["ok"] for item in items),
    }


def _format_bytes(value):
    if value is None:
        return "inconnu"
    try:
        size = float(value)
    except Exception:
        return "inconnu"

    units = ["o", "Kio", "Mio", "Gio", "Tio"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}"


def diagnostics(deep=False, client=None):
    """
    Diagnostic strictement local.

    Il ne lance aucun accès réseau, ne lit aucun titre/URL de job et ne copie
    aucune valeur de cookie.
    """
    state = repair_state()
    active = state.get("active") or {}
    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        or os.environ.get("DESKTOP_SESSION", "")
        or "inconnu"
    )

    dependencies = dependency_status()
    destination = _destination_health(deep=bool(deep))
    runtime_files = _runtime_files_health()
    compatibility = client_report(client, APP_VERSION)
    updates_cached = cached_update_report()
    kitty_release_cached = cached_kitty_release_report()
    cache_health = _cache_storage_health(state)

    optional_warning = bool(dependencies.get("optional_missing"))
    required_error = not dependencies.get("required_ok", False)
    system_error = (
        not runtime_files.get("ok", False)
        or not destination.get("directory", False)
        or not destination.get("writable", False)
    )

    if required_error or system_error:
        overall = "error"
    elif optional_warning:
        overall = "warning"
    else:
        overall = "ready"

    backup_count = 0
    try:
        backup_count = len([
            path for path in STATE_BACKUP_DIR.iterdir()
            if path.is_file() and not path.is_symlink()
        ]) if STATE_BACKUP_DIR.is_dir() else 0
    except Exception:
        backup_count = 0

    migration = {}
    try:
        marker_path = migration_file()
        if marker_path.is_file() and not marker_path.is_symlink():
            loaded_migration = json.loads(marker_path.read_text(encoding="utf-8"))
            if isinstance(loaded_migration, dict):
                migration = loaded_migration
    except Exception:
        migration = {}

    diagnostic_payload = {
        "app_name": APP_NAME,
        "kitty_version": APP_VERSION,
        "state_version": STATE_VERSION,
        "python": platform.python_version(),
        "yt_dlp": next((d.get("version") for d in dependencies["items"] if d["id"] == "yt_dlp"), None) or "non installé",
        "ffmpeg": next((d.get("version") for d in dependencies["items"] if d["id"] == "ffmpeg"), None) or "non installé",
        "ffprobe": next((d.get("version") for d in dependencies["items"] if d["id"] == "ffprobe"), None) or "non installé",
        "mutagen": next((d.get("version") for d in dependencies["items"] if d["id"] == "mutagen"), None) or "non installé",
        "os": platform.platform(),
        "desktop": desktop,
        "host_path": _redact_home(Path(__file__).resolve()),
        "worker_path": _redact_home(WORKER),
        "metadata_path": _redact_home(META_WORKER),
        # Ne pas inclure le chemin complet de destination dans le texte copié.
        "destination_status": "écriture OK" if destination.get("writable") else "écriture impossible",
        "destination_write_tested": bool(destination.get("write_tested")),
        "destination_free": _format_bytes(destination.get("free_bytes")),
        "destination_free_bytes": destination.get("free_bytes"),
        "active_status": active.get("status") or "aucun",
        "queue_count": len(state.get("queue", [])),
        "history_count": len(state.get("history", [])),
        "log_path": _redact_home(LOG_FILE),
        "log_size": _format_bytes(cache_health.get("logs_bytes")),
        "log_size_bytes": cache_health.get("logs_bytes"),
        "cache_size": _format_bytes(cache_health.get("total_bytes")),
        "cache_size_bytes": cache_health.get("total_bytes"),
        "cache_reclaimable": _format_bytes(cache_health.get("reclaimable_bytes")),
        "cache_reclaimable_bytes": cache_health.get("reclaimable_bytes"),
        "cache_temporary": _format_bytes(cache_health.get("temporary_bytes")),
        "cache_temporary_bytes": cache_health.get("temporary_bytes"),
        "update_backups_size": _format_bytes(cache_health.get("update_backups_bytes")),
        "update_backups_size_bytes": cache_health.get("update_backups_bytes"),
        "orphan_partials_count": (cache_health.get("orphan_partials") or {}).get("count", 0),
        "orphan_partials_size": _format_bytes((cache_health.get("orphan_partials") or {}).get("bytes", 0)),
        "orphan_partials_size_bytes": (cache_health.get("orphan_partials") or {}).get("bytes", 0),
        "backup_count": backup_count,
        "youtube_auth": "active" if youtube_auth_enabled() else ("configured" if _youtube_auth_configured() else "not configured"),
        "migration": migration.get("status") or "fresh",
        "migration_output": migration.get("output_migration"),
        "overall": overall,
        "frontend_backend": compatibility.get("status"),
        "frontend_version": compatibility.get("frontend_version"),
        "backend_protocol": compatibility.get("backend_protocol"),
        "frontend_protocol": compatibility.get("frontend_protocol"),
        "updates_available": (updates_cached or {}).get("updates_available"),
        "risky_updates": (updates_cached or {}).get("risky_updates"),
        "latest_kitty_version": (kitty_release_cached or {}).get("latest_version"),
        "kitty_release_state": (kitty_release_cached or {}).get("state"),
    }

    return {
        "ok": True,
        "overall": overall,
        "dependencies": dependencies,
        "compatibility": compatibility,
        "updates_cached": updates_cached,
        "kitty_release_cached": kitty_release_cached,
        "system": {
            "destination": destination,
            "runtime_files": runtime_files,
            "state_ok": True,
            "queue_count": len(state.get("queue", [])),
            "history_count": len(state.get("history", [])),
            "log_size": _safe_file_size(LOG_FILE),
            "logs": log_stats(),
            "cache": cache_health,
            "backup_count": backup_count,
            "migration": {
                "status": migration.get("status") or "fresh",
                "legacy_found": bool(migration.get("legacy_found", False)),
                "legacy_removed": bool(migration.get("legacy_removed", False)),
                "output_migration": migration.get("output_migration"),
            },
        },
        "diagnostics": diagnostic_payload,
        "privacy": {
            "network_used": False,
            "includes_urls": False,
            "includes_titles": False,
            "includes_cookies": False,
        },
    }


def open_logs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    path = str(LOG_FILE)
    if WINDOWS:
        try:
            os.startfile(path)
            return {"ok": True, "log_path": path, "opener": "Windows"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP", "")
        + ":"
        + os.environ.get("DESKTOP_SESSION", "")
    ).lower()

    candidates = []
    if "kde" in desktop or "plasma" in desktop:
        candidates += [["kate", path], ["kwrite", path]]
    if "gnome" in desktop or "ubuntu" in desktop:
        candidates += [["gnome-text-editor", path], ["gedit", path]]
    if "xfce" in desktop:
        candidates += [["mousepad", path]]

    candidates += [
        ["xdg-open", path],
        ["gio", "open", path],
        ["kate", path],
        ["gedit", path],
        ["mousepad", path],
        ["xed", path],
    ]

    seen = set()
    errors = []
    for cmd in candidates:
        key = tuple(cmd[:2]) if cmd[0] == "gio" else cmd[0]
        if key in seen:
            continue
        seen.add(key)
        executable = shutil.which(cmd[0])
        if not executable:
            continue
        try:
            subprocess.Popen(
                [executable, *cmd[1:]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **spawn_options(),
            )
            return {"ok": True, "log_path": path, "opener": cmd[0]}
        except Exception as exc:
            errors.append(f"{cmd[0]}: {exc}")

    detail = "; ".join(errors) if errors else "aucune application compatible trouvée"
    return {"ok": False, "error": f"Impossible d'ouvrir les logs ({detail})."}


def _signal_worker_for_reset(active):
    if WINDOWS:
        pid = active.get("worker_pid")
        if not pid or not process_alive(pid):
            return
        if not worker_matches_job(pid, active.get("id")):
            raise RuntimeError("Identité du worker non vérifiée; remise à zéro annulée.")
        set_control(active.get("id"), "cancel")
        deadline = time.monotonic() + 35
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if process_alive(pid):
            raise RuntimeError("Le worker ne s’est pas arrêté; remise à zéro annulée, file en pause.")
        return
    pid = active.get("worker_pid") if isinstance(active, dict) else None
    if not pid or not process_alive(pid):
        return

    try:
        os.killpg(int(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and process_alive(pid):
        time.sleep(0.05)

    if process_alive(pid):
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except Exception:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass


def reset_kitty_state():
    """
    Remise à zéro sûre :
    - conserve settings.json et les fichiers terminés
    - arrête le worker actif
    - nettoie uniquement les restes du job actif
    - vide active / queue / history
    - garde une sauvegarde de queue.json avant reset
    """
    # snapshot() migre/valide l'état sans lancer de nouveau worker. Pour une
    # opération de reset, il faut absolument éviter que repair_state() puisse
    # promouvoir un job de la file juste avant qu'on la vide.
    state = snapshot()
    active = state.get("active") if isinstance(state, dict) else None

    backup_state_file("manual-reset", version=STATE_VERSION, move=False)

    # Empêcher le worker annulé de promouvoir un job de la file pendant le reset.
    def freeze(data):
        data["queue_paused"] = True
        data["queue"] = []

    with_state(freeze)

    if active:
        clear_control(active.get("id"))
        _signal_worker_for_reset(active)
        cleanup_paused_job_files(active)

    try:
        if CONTROL_DIR.exists():
            for child in CONTROL_DIR.iterdir():
                if child.is_file():
                    try:
                        child.unlink()
                    except Exception:
                        pass
    except Exception:
        pass

    def reset(data):
        data.clear()
        data.update(default_state())

    with_state(reset)
    return {"ok": True, "state": snapshot()}


def main():
    global CURRENT_ACTION
    if WINDOWS:
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    msg = read_message()
    if msg is None:
        return
    action = msg.get("action")
    CURRENT_ACTION = str(action or "")
    client = msg.get("client")
    compatibility = client_report(client, APP_VERSION)

    safe_when_incompatible = {
        "status", "get_settings", "diagnostics", "compatibility", "check_updates",
        "check_kitty_update", "download_kitty_update", "open_logs", "youtube_auth_status",
    }
    if isinstance(client, dict) and not compatibility.get("compatible") and action not in safe_when_incompatible:
        send_message({
            "ok": False,
            "code": "incompatible_frontend_backend",
            "error": compatibility.get("message") or "Frontend/backend Kitty incompatibles.",
            "compatibility": compatibility,
        })
        return

    if action == "status":
        send_message({"ok": True, "state": repair_state()})
    elif action == "download":
        url = msg.get("url")
        mode = msg.get("mode", "1080")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            send_message({"ok": False, "code": "invalid_url", "error": "URL invalide."})
        else:
            repair_state()
            send_message(enqueue(url, mode, force=bool(msg.get("force"))))
    elif action == "download_playlist":
        url = msg.get("url")
        mode = msg.get("mode", "1080")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            send_message({"ok": False, "code": "invalid_url", "error": "URL invalide."})
        else:
            repair_state()
            send_message(enqueue_playlist(url, mode))
    elif action == "retry":
        send_message(retry_job(msg.get("job_id")))
    elif action == "cancel":
        send_message(cancel_active())
    elif action in ("pause_active", "resume_active"):
        send_message({
            "ok": False,
            "code": "active_pause_disabled",
            "error": "La pause d'un téléchargement déjà lancé est désactivée pour éviter les reprises HTTP 403.",
            "state": repair_state(),
        })
    elif action == "toggle_queue_item_pause":
        send_message(toggle_queue_item_pause(msg.get("job_id")))
    elif action == "pause_queue":
        send_message(set_queue_paused(True))
    elif action == "resume_queue":
        send_message(set_queue_paused(False))
    elif action == "remove_queued":
        send_message(remove_queued(msg.get("job_id")))
    elif action == "clear_queue":
        send_message(clear_queue())
    elif action == "clear_history":
        send_message(clear_history())
    elif action == "get_settings":
        send_message(get_settings())
    elif action == "choose_output_dir":
        send_message(choose_output_dir())
    elif action == "set_output_dir":
        send_message(set_output_dir(msg.get("output_dir")))
    elif action == "open_folder":
        send_message(open_folder())
    elif action == "open_logs":
        send_message(open_logs())
    elif action == "diagnostics":
        send_message(diagnostics(deep=bool(msg.get("deep", False)), client=client))
    elif action == "compatibility":
        send_message({"ok": True, "compatibility": compatibility})
    elif action == "check_updates":
        send_message({
            "ok": True,
            "updates": check_dependency_updates(client=client, save_cache=True),
            "kitty_release": check_kitty_release(save_cache=True),
        })
    elif action == "check_kitty_update":
        send_message({"ok": True, "kitty_release": check_kitty_release(save_cache=True)})
    elif action == "download_kitty_update":
        send_message(download_kitty_update())
    elif action == "clean_cache":
        send_message(clean_cache())
    elif action == "reset_kitty":
        send_message(reset_kitty_state())
    elif action == "youtube_auth_status":
        send_message(youtube_auth_status(auto_finalize=True))
    elif action == "youtube_auth_start":
        try:
            send_message(youtube_auth_start())
        except Exception as exc:
            send_message({"ok": False, "error": str(exc)})
    elif action == "youtube_auth_set_enabled":
        send_message(set_youtube_auth_enabled(msg.get("enabled")))
    elif action == "youtube_auth_delete":
        send_message(youtube_auth_delete())
    else:
        send_message({"ok": False, "code": "unsupported_action", "error": "Action non supportée."})

if __name__ == "__main__":
    try:
        main()
    except QueueStateError as exc:
        send_message({"ok": False, "code": "queue_state_unavailable", "error": str(exc)})
    except OSError as exc:
        send_message({"ok": False, "code": "backend_io_failed", "error": str(exc)})
