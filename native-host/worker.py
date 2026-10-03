#!/usr/bin/env python3
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent
if str(NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(NATIVE_DIR))

from app_paths import cache_dir, config_dir, default_output_dir, install_dir
from platform_support import (WINDOWS, process_alive, script_process_matches, spawn_options,
                              run_hidden, find_firefox, firefox_uses_profile, choose_windows_folder,
                              configure_worker_job, watch_worker_controls)
from errors import classify_backend_error
from runtime_storage import append_log
from queue_store import (STATE_VERSION, default_state, read_state, mutate_state,
                         claim_next_job, update_job, insert_at_lane_head, release_failed_start)

CACHE_DIR = cache_dir()
QUEUE_FILE = CACHE_DIR / "queue.json"
LOCK_FILE = CACHE_DIR / "queue.lock"
CONTROL_DIR = CACHE_DIR / "controls"
INSTALL_DIR = install_dir()
WORKER = INSTALL_DIR / "worker.py"
DEFAULT_OUTPUT_DIR = default_output_dir()

CONFIG_DIR = config_dir()
YOUTUBE_COOKIE_FILE = CONFIG_DIR / "youtube-auth" / "cookies.txt"
AUTH_JOB_DIR = CACHE_DIR / "auth-jobs"

cancel_requested = False
external_stop_requested = False
current_job_id = None

class DownloadCancelled(Exception):
    pass

class WorkerShutdown(BaseException):
    """External SIGTERM/SIGINT: freeze the queue without consuming jobs."""
    def __init__(self, signum):
        super().__init__(f"external signal {signum}")
        self.signum = signum

class DownloadPaused(BaseException):
    pass

def log(message):
    append_log(message)

def locked_mutate(fn):
    return mutate_state(QUEUE_FILE, LOCK_FILE, fn)


def get_state():
    return read_state(QUEUE_FILE, LOCK_FILE)


def update_active(job_id=None, **kwargs):
    owned_id = job_id if job_id is not None else current_job_id
    if owned_id is None:
        return False
    return locked_mutate(lambda data: update_job(data, owned_id, kwargs, active_only=True))



def handle_signal(signum, frame):
    global cancel_requested, external_stop_requested

    controlled_cancel = (
        current_job_id is not None
        and control_action(current_job_id) == "cancel"
    )

    if controlled_cancel:
        cancel_requested = True
        raise DownloadCancelled()

    external_stop_requested = True
    # Do not acquire log/queue locks inside a signal handler: it may interrupt
    # code already holding those locks. Exceptions unwind the transaction first.
    raise WorkerShutdown(signum)

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

def control_path(job_id):
    return CONTROL_DIR / f"{job_id}.json"


def control_action(job_id):
    try:
        data = json.loads(control_path(job_id).read_text(encoding="utf-8"))
        return data.get("action")
    except Exception:
        return None


def clear_control(job_id):
    try:
        control_path(job_id).unlink()
    except FileNotFoundError:
        pass


def active_pause_requested(job_id):
    return control_action(job_id) == "pause"


def mark_active_paused(job_id):
    def mutate(data):
        active = data.get("active")
        if not active or active.get("id") != job_id:
            return
        active["status"] = "paused"
        active["worker_pid"] = None
        active["speed"] = None
        active["eta"] = None
        active["updated_at"] = time.time()
        active.pop("pause_requested", None)
    locked_mutate(mutate)
    clear_control(job_id)


def _truncate_utf8(text, max_bytes):
    """Tronque sans casser un caractère UTF-8."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    encoded = encoded[:max_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def _filename_stem(prepared_path):
    """
    Récupère le titre déjà nettoyé par yt-dlp, sans l'extension média.
    Exemple : "Titre.foo.webm" -> "Titre.foo".
    """
    path = Path(prepared_path)
    return path.stem or "media"


def _stem_occupied(output_dir, stem):
    """
    Un stem est réservé dès qu'un fichier associé existe :
      Titre.opus
      Titre.webp
      Titre.webm.part
      Titre.info.json
    Cela évite aussi les collisions de thumbnails entre deux médias.
    """
    prefix = stem + "."

    try:
        for child in output_dir.iterdir():
            name = child.name
            compared_name = name.casefold() if WINDOWS else name
            compared_stem = stem.casefold() if WINDOWS else stem
            compared_prefix = prefix.casefold() if WINDOWS else prefix
            if compared_name == compared_stem or compared_name.startswith(compared_prefix):
                return True
    except FileNotFoundError:
        return False

    return False


def output_stem_budget(output_dir):
    if WINDOWS:
        # Do not depend on the machine-wide LongPathsEnabled policy. Count
        # UTF-16 units in the directory and reserve room for yt-dlp sidecars.
        prefix_units = len(str(Path(output_dir).resolve()).encode("utf-16-le")) // 2
        available = min(215, 259 - prefix_units - 1 - 40)
        if available < 16:
            raise RuntimeError("Le chemin du dossier de destination est trop long; choisis un dossier plus court.")
        return available
    try:
        name_max = os.pathconf(output_dir, "PC_NAME_MAX")
    except (AttributeError, OSError, ValueError):
        name_max = 255
    return max(80, int(name_max) - 40)


def choose_unique_output_stem(output_dir, base_stem):
    """
    Retourne un stem lisible et unique :
      Titre
      Titre (2)
      Titre (3)

    L'ID du média n'est jamais utilisé dans le nom visible.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Laisser de la place à l'extension, aux .part et aux suffixes yt-dlp.
    max_stem_bytes = output_stem_budget(output_dir)
    base = _truncate_utf8((base_stem or "media").strip() or "media", max_stem_bytes)

    candidate = base
    number = 2

    while _stem_occupied(output_dir, candidate):
        suffix = f" ({number})"
        suffix_bytes = len(suffix.encode("utf-8"))
        root = _truncate_utf8(base, max(1, max_stem_bytes - suffix_bytes)).rstrip()
        candidate = f"{root}{suffix}"
        number += 1

    return candidate


def output_template_for_stem(output_dir, stem):
    """
    Le stem vient de prepare_filename(), donc les caractères interdits ont
    déjà été traités par yt-dlp. Il reste seulement à échapper '%' pour que
    le titre ne soit pas interprété comme une nouvelle expression outtmpl.
    """
    escaped = stem.replace("%", "%%")
    return str(output_dir / f"{escaped}.%(ext)s")


def cleanup_cancelled_files(paths, output_stem, started_at):
    """
    Nettoyage ciblé d'un job annulé.

    On ne cherche plus l'ID dans le nom. Le worker mémorise à la place le
    stem exact qui lui a été réservé. Tous les fichiers de ce job partagent
    ce stem, tandis que "Titre (2)" est un stem distinct.
    """
    threshold = float(started_at or 0) - 5.0 if started_at else 0
    candidates = set()

    for raw in paths:
        if not raw:
            continue
        path = Path(raw)
        candidates.update({
            path,
            Path(str(path) + ".part"),
            Path(str(path) + ".ytdl"),
        })
        try:
            candidates.update(path.parent.glob(path.name + "*"))
        except Exception:
            pass

    if output_stem:
        stem_path = Path(output_stem)
        parent = stem_path.parent
        prefix = stem_path.name + "."

        try:
            for child in parent.iterdir():
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
            log(f"annulation: fichier supprimé {candidate}")
        except Exception as exc:
            log(f"annulation: impossible de supprimer {candidate}: {exc!r}")

    return removed


def start_next_if_any():
    if external_stop_requested:
        log("scheduler ignoré: arrêt externe en cours")
        return

    next_job = None

    def mutate(data):
        nonlocal next_job
        next_job = claim_next_job(data)

    locked_mutate(mutate)

    if next_job:
        try:
            proc = subprocess.Popen(
                [sys.executable, str(WORKER), next_job["id"]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **spawn_options(),
                close_fds=True,
            )
        except OSError:
            locked_mutate(lambda data: release_failed_start(data, next_job["id"]))
            raise
        time.sleep(0.08)
        update_active(job_id=next_job["id"], worker_pid=proc.pid)
        log(f"job suivant lancé id={next_job['id']} pid={proc.pid}")

def freeze_after_external_stop(job_id, signum):
    """
    Safe shutdown:
    - pause whole queue;
    - restore active job to the head of its logical lane;
    - preserve partial files;
    - never archive/consume the job.
    """
    result = {"requeued": False}

    def mutate(data):
        data["queue_paused"] = True
        active = data.get("active")
        if not isinstance(active, dict) or active.get("id") != job_id:
            return

        active = dict(active)
        active["status"] = "queued"
        active["worker_pid"] = None
        active["speed"] = None
        active["eta"] = None
        active["updated_at"] = time.time()
        active["interrupted_at"] = time.time()
        active["interrupted_reason"] = "external_signal"
        active["interrupted_signal"] = int(signum)
        active.pop("pause_requested", None)
        active.pop("error", None)
        active.pop("error_code", None)
        active.pop("error_hint", None)
        active.pop("error_detail", None)
        active.pop("error_retryable", None)

        queue = data.setdefault("queue", [])
        queue[:] = [
            queued for queued in queue
            if not (isinstance(queued, dict) and queued.get("id") == job_id)
        ]
        insert_at_lane_head(queue, active)
        data["active"] = None
        result["requeued"] = True

    locked_mutate(mutate)
    return result


def finish_active(status, error=None, filepath=None, error_info=None):
    def mutate(data):
        active = data.get("active")
        if not active or active.get("id") != current_job_id:
            return
        active["status"] = status
        active["speed"] = None
        active["eta"] = 0 if status == "finished" else None

        if status == "error":
            info = error_info or classify_backend_error(error or "Erreur du worker.")
            active["error"] = info["message"]
            active["error_code"] = info["code"]
            active["error_hint"] = info["hint"]
            active["error_detail"] = info["detail"]
            active["error_retryable"] = info["retryable"]
        else:
            active["error"] = None
            active.pop("error_code", None)
            active.pop("error_hint", None)
            active.pop("error_detail", None)
            active.pop("error_retryable", None)

        active["finished_at"] = time.time()
        active["updated_at"] = time.time()
        active["worker_pid"] = None
        active.pop("pause_requested", None)
        if filepath:
            active["filepath"] = filepath
        data.setdefault("history", []).insert(0, dict(active))
        data["history"] = data["history"][:50]
        data["active"] = None
    locked_mutate(mutate)


def probe_audio_codec(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe est requis pour détecter le codec audio.")

    proc = run_hidden(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe a échoué : {proc.stderr.strip()}")

    try:
        data = json.loads(proc.stdout)
        streams = data.get("streams") or []
        codec = streams[0].get("codec_name") if streams else None
    except Exception as exc:
        raise RuntimeError("Impossible de lire le résultat de ffprobe.") from exc

    if not codec:
        raise RuntimeError("Codec audio introuvable.")
    return codec.lower()


def preferred_audio_container(codec):
    # Conteneurs naturels quand ils existent, sinon Matroska audio comme
    # fallback universel sans réencodage.
    mapping = {
        "opus": "opus",
        "vorbis": "ogg",
        "aac": "m4a",
        "alac": "m4a",
        "mp3": "mp3",
        "flac": "flac",
    }
    return mapping.get(codec, "mka")


def remux_original_audio(path):
    src = Path(path)
    codec = probe_audio_codec(src)
    target_ext = preferred_audio_container(codec)

    # Un fichier déjà dans le bon conteneur ne nécessite aucun remux.
    if src.suffix.lower().lstrip(".") == target_ext:
        log(f"audio original déjà dans .{target_ext} codec={codec}")
        return src, codec

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg est requis pour remuxer l'audio original.")

    dst = src.with_suffix("." + target_ext)
    temp = dst.with_name(dst.stem + ".remux-temp" + dst.suffix)

    cmd = [
        ffmpeg,
        "-y",
        "-v", "error",
        "-i", str(src),
        "-map", "0:a:0",
        "-map_metadata", "0",
        "-c:a", "copy",
        str(temp),
    ]

    proc = run_hidden(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        try:
            temp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(
            f"Remux sans perte impossible pour {codec} vers .{target_ext}: "
            f"{proc.stderr.strip()}"
        )

    os.replace(temp, dst)
    if src != dst:
        try:
            src.unlink()
        except FileNotFoundError:
            pass

    log(f"remux audio original codec={codec} {src.name!r} -> {dst.name!r}")
    return dst, codec


def embed_thumbnail_after_remux(ydl, info, media_path):
    """
    Réutilise le post-processeur officiel yt-dlp afin de gérer correctement
    MP3, M4A, OPUS, OGG, FLAC et MKA sans inventer notre propre format de tags.
    """
    try:
        from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP

        info["filepath"] = str(media_path)
        info["ext"] = media_path.suffix.lower().lstrip(".")
        pp = EmbedThumbnailPP(ydl, already_have_thumbnail=False)
        _, info = pp.run(info)
        log(f"thumbnail intégré dans {media_path.name!r}")
        return info
    except Exception as exc:
        # Le média reste valide même si l'environnement manque par ex. de
        # mutagen pour certains conteneurs. On garde alors le thumbnail externe.
        log(f"thumbnail non intégré: {exc!r}")
        return info


def _is_youtube_url(url):
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(str(url)).hostname or "").lower()
        return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    except Exception:
        return False


def prepare_youtube_job_cookiefile(job_id, url, use_auth):
    if not use_auth or not _is_youtube_url(url):
        return None
    if YOUTUBE_COOKIE_FILE.is_symlink() or not YOUTUBE_COOKIE_FILE.is_file():
        return None

    AUTH_JOB_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(AUTH_JOB_DIR, 0o700)
    except Exception:
        pass

    target = AUTH_JOB_DIR / f"{job_id}.cookies.txt"
    target.unlink(missing_ok=True)

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


def cleanup_youtube_job_cookiefile(path):
    if not path:
        return
    try:
        path = Path(path)
        root = AUTH_JOB_DIR.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if root not in resolved.parents:
            return
        if path.is_symlink() or path.is_file():
            path.unlink()
    except Exception:
        pass


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg",
}
NON_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | {
    ".json", ".vtt", ".srt", ".ass", ".lrc", ".description", ".part", ".ytdl",
}


def _is_obvious_non_media_path(path):
    path = Path(path)
    name = path.name.lower()

    if path.suffix.lower() in NON_MEDIA_EXTENSIONS:
        return True
    if name.endswith((".info.json", ".part", ".ytdl")):
        return True
    return False


def probe_media_streams(path):
    path = Path(path)
    ffprobe = shutil.which("ffprobe")

    if not ffprobe:
        if _is_obvious_non_media_path(path):
            return False, False
        return None, None

    proc = run_hidden(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "stream=codec_type",
            "-of", "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        return False, False

    try:
        data = json.loads(proc.stdout or "{}")
        types = {
            str(stream.get("codec_type") or "").lower()
            for stream in (data.get("streams") or [])
            if isinstance(stream, dict)
        }
    except Exception:
        return False, False

    return "audio" in types, "video" in types


def validate_media_file(path, mode):
    if not path:
        return False, "chemin vide"

    path = Path(path)
    if not path.is_file():
        return False, "fichier absent"

    try:
        if path.stat().st_size <= 0:
            return False, "fichier vide"
    except Exception:
        return False, "fichier illisible"

    if _is_obvious_non_media_path(path):
        return False, f"asset non média ({path.suffix.lower() or path.name})"

    has_audio, has_video = probe_media_streams(path)

    if mode in ("audio", "mp3"):
        if has_audio is False:
            return False, "aucun flux audio détecté"
    else:
        if has_video is False:
            return False, "aucun flux vidéo détecté"

    return True, None


def _iter_result_candidate_paths(result, prepared_path, output_dir, stem):
    seen = set()

    def add(raw):
        if not raw:
            return
        try:
            p = Path(str(raw))
        except Exception:
            return
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        yield p

    if isinstance(result, dict):
        for key in ("filepath", "_filename"):
            yield from add(result.get(key))

        files_to_move = result.get("__files_to_move")
        if isinstance(files_to_move, dict):
            for src, dst in files_to_move.items():
                yield from add(dst)
                yield from add(src)

    # Le nom préparé post-processé est prioritaire sur les fragments sources.
    yield from add(prepared_path)

    if isinstance(result, dict):
        for item in result.get("requested_downloads") or []:
            if isinstance(item, dict):
                yield from add(item.get("filepath"))
                yield from add(item.get("_filename"))

    if stem:
        try:
            candidates = sorted(
                (
                    child for child in Path(output_dir).iterdir()
                    if child.is_file()
                    and (
                        child.name == stem
                        or child.name.startswith(stem + ".")
                    )
                ),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for child in candidates:
                yield from add(child)
        except Exception:
            pass


def select_final_media_path(result, prepared_path, output_dir, stem, mode):
    reasons = []
    valid = []

    prepared_text = str(Path(prepared_path)) if prepared_path else None

    for candidate in _iter_result_candidate_paths(
        result, prepared_path, output_dir, stem
    ):
        ok, reason = validate_media_file(candidate, mode)
        if not ok:
            reasons.append(f"{candidate.name}: {reason}")
            continue

        has_audio, has_video = probe_media_streams(candidate)
        score = 0

        if prepared_text and str(candidate) == prepared_text:
            score += 20

        if mode == "mp3" and candidate.suffix.lower() == ".mp3":
            score += 100

        if mode not in ("audio", "mp3"):
            if has_video is True:
                score += 20
            if has_audio is True and has_video is True:
                score += 50

        try:
            score += min(candidate.stat().st_mtime_ns % 1000, 999) / 100000.0
        except Exception:
            pass

        valid.append((score, candidate))

    if valid:
        valid.sort(key=lambda item: item[0], reverse=True)
        return valid[0][1]

    detail = "; ".join(reasons[:6]) if reasons else "aucun candidat trouvé"
    raise RuntimeError(
        "Le téléchargement n’a produit aucun fichier média valide. "
        f"Détails : {detail}"
    )


def validate_extracted_info(info, mode):
    if not isinstance(info, dict):
        raise RuntimeError("L’extracteur n’a pas renvoyé de média.")

    if info.get("entries") is not None or str(info.get("_type") or "").lower() in {
        "playlist", "multi_video"
    }:
        raise RuntimeError(
            "Cette URL correspond à une collection. Utilise le mode Playlist."
        )

    formats = [fmt for fmt in (info.get("formats") or []) if isinstance(fmt, dict)]
    if not formats:
        return

    if mode in ("audio", "mp3"):
        explicit_audio = [
            str(fmt.get("acodec")).lower()
            for fmt in formats
            if fmt.get("acodec") is not None
        ]
        if explicit_audio and all(codec == "none" for codec in explicit_audio):
            raise RuntimeError("Aucun flux audio n’est disponible pour ce média.")
    else:
        explicit_video = [
            str(fmt.get("vcodec")).lower()
            for fmt in formats
            if fmt.get("vcodec") is not None
        ]
        if explicit_video and all(codec == "none" for codec in explicit_video):
            raise RuntimeError("Aucun flux vidéo n’est disponible pour ce média.")


def cleanup_failed_auxiliary_files(output_stem, started_at):
    if not output_stem:
        return

    stem_path = Path(output_stem)
    threshold = float(started_at or 0) - 5.0 if started_at else 0

    try:
        candidates = list(stem_path.parent.glob(stem_path.name + ".*"))
    except Exception:
        return

    for path in candidates:
        try:
            if not path.is_file():
                continue
            if threshold and path.stat().st_mtime < threshold:
                continue
            if _is_obvious_non_media_path(path) or path.name.endswith((".part", ".ytdl")):
                path.unlink()
                log(f"échec: sidecar temporaire supprimé {path}")
        except Exception as exc:
            log(f"échec: nettoyage sidecar impossible {path}: {exc!r}")



def build_opts(mode, progress_hook, output_dir, cookiefile=None):
    title_limit = min(200, output_stem_budget(output_dir)) if WINDOWS else 200
    template = str(output_dir / f"%(title).{title_limit}s.%(ext)s")
    opts = {
        "noplaylist": True,
        "windowsfilenames": WINDOWS,
        "outtmpl": template,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "socket_timeout": 15,
        "retries": 3,
        "extractor_retries": 2,
        "fragment_retries": 3,
        # Thumbnail téléchargée pour l'intégration/tags, jamais comme résultat final.
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegMetadata"},
        ],
    }
    if mode == "1080":
        opts.update({"format": "bv*[height<=1080][vcodec!=none]+ba[acodec!=none]/b[height<=1080][vcodec!=none][acodec!=none]/bv*[height<=1080]+ba/b[height<=1080]/b", "merge_output_format": "mp4"})
        opts["postprocessors"].append({"key": "EmbedThumbnail"})
    elif mode == "720":
        opts.update({"format": "bv*[height<=720][vcodec!=none]+ba[acodec!=none]/b[height<=720][vcodec!=none][acodec!=none]/bv*[height<=720]+ba/b[height<=720]/b", "merge_output_format": "mp4"})
        opts["postprocessors"].append({"key": "EmbedThumbnail"})
    elif mode == "best":
        opts.update({"format": "bv*[vcodec!=none]+ba[acodec!=none]/b[vcodec!=none][acodec!=none]/bv*+ba/b", "merge_output_format": "mp4"})
        opts["postprocessors"].append({"key": "EmbedThumbnail"})
    elif mode == "audio":
        # Original audio stream: no transcoding/extraction.
        # On YouTube this is commonly Opus audio inside a WebM container.
        opts.update({"format": "ba[acodec!=none]/b[acodec!=none]/ba/b"})
    elif mode == "mp3":
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg est requis pour le MP3.")
        opts.update({
            "format": "ba[acodec!=none]/b[acodec!=none]/ba/b",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ],
        })
    else:
        raise RuntimeError(f"Mode inconnu : {mode}")

    if cookiefile:
        opts["cookiefile"] = str(cookiefile)

    return opts

def main():
    global current_job_id

    log(f"worker V8.25 lancé pid={os.getpid()} argv={sys.argv[1:]}")
    if len(sys.argv) != 2:
        return 2

    job_id = sys.argv[1]
    current_job_id = job_id
    state = get_state()
    active = state.get("active")
    if not active or active.get("id") != job_id:
        log(f"job actif introuvable ou différent: demandé={job_id} active={active!r}")
        return 3

    url = active["url"]
    mode = active["mode"]
    output_dir = Path(active.get("output_dir") or DEFAULT_OUTPUT_DIR).expanduser()

    seen_paths = set()
    media_id = active.get("media_id")
    output_stem = active.get("output_stem")
    started_at = active.get("started_at") or time.time()
    last_pause_check = 0.0
    job_cookiefile = None
    control_watcher = None

    try:
        configure_worker_job()
        control_watcher = watch_worker_controls(lambda: control_action(job_id))
        output_dir.mkdir(parents=True, exist_ok=True)
        update_active(
            worker_pid=os.getpid(),
            status="starting",
            output_dir=str(output_dir),
            metadata_status="fetching",
            metadata_error=None,
            metadata_pid=None,
        )
        log(f"destination du job: {output_dir}")

        job_cookiefile = prepare_youtube_job_cookiefile(
            job_id,
            url,
            bool(active.get("youtube_auth")),
        )
        if job_cookiefile:
            log("session YouTube dédiée activée pour ce job")

        import yt_dlp

        last_bytes = None
        last_time = time.monotonic()
        saw_progress = False

        def progress_hook(d):
            nonlocal last_bytes, last_time, saw_progress, last_pause_check
            if cancel_requested:
                raise DownloadCancelled()

            now_control = time.monotonic()
            if now_control - last_pause_check >= 0.20:
                last_pause_check = now_control
                if active_pause_requested(job_id):
                    raise DownloadPaused()

            status = d.get("status")
            info = d.get("info_dict")
            if not isinstance(info, dict):
                info = {}
            title = info.get("title") or ""
            filename = d.get("filename")
            tmpfilename = d.get("tmpfilename")
            if filename:
                seen_paths.add(filename)
            if tmpfilename:
                seen_paths.add(tmpfilename)

            if status == "downloading":
                saw_progress = True
                downloaded = d.get("downloaded_bytes")
                total = d.get("total_bytes")
                estimated = d.get("total_bytes_estimate")
                speed = d.get("speed")
                eta = d.get("eta")
                now = time.monotonic()

                if not isinstance(speed, (int, float)) or speed <= 0:
                    if isinstance(downloaded, (int, float)) and isinstance(last_bytes, (int, float)):
                        dt = now - last_time
                        delta = downloaded - last_bytes
                        if dt > 0.15 and delta > 0:
                            speed = delta / dt

                if isinstance(downloaded, (int, float)):
                    last_bytes = downloaded
                    last_time = now

                update_active(
                    status="downloading",
                    title=title or None,
                    filepath=filename or None,
                    downloaded=downloaded,
                    total=total,
                    estimated_total=estimated,
                    speed=speed,
                    eta=eta,
                )
                log(f"HOOK bytes={downloaded!r} total={total!r} speed={speed!r} eta={eta!r}")

            elif status == "finished":
                update_active(
                    status="downloading",
                    title=title or None,
                    filepath=filename or None,
                    downloaded=d.get("downloaded_bytes"),
                    total=d.get("total_bytes"),
                    estimated_total=d.get("total_bytes_estimate"),
                    speed=None,
                    eta=0,
                )

        opts = build_opts(mode, progress_hook, output_dir, job_cookiefile)

        with yt_dlp.YoutubeDL(opts) as ydl:
            if active_pause_requested(job_id):
                raise DownloadPaused()

            # Extraction metadata first: gets the title before the first media bytes.
            info = ydl.extract_info(url, download=False)
            validate_extracted_info(info, mode)

            title = info.get("title") if isinstance(info, dict) else ""
            media_id = info.get("id") if isinstance(info, dict) else media_id

            # Demander d'abord à yt-dlp quel nom il utiliserait afin de garder
            # exactement sa sanitisation du titre, puis réserver un stem
            # lisible et unique sans exposer l'ID du média.
            prepared = ydl.prepare_filename(info)
            base_stem = _filename_stem(prepared)
            clean_stem = choose_unique_output_stem(output_dir, base_stem)
            output_stem = str(output_dir / clean_stem)

            update_active(
                status="downloading",
                title=title or "",
                media_id=media_id or None,
                output_stem=output_stem,
                metadata_status="ready" if title else "unavailable",
                metadata_error=None if title else "Titre non fourni par l’extracteur.",
                metadata_pid=None,
            )
            log(
                f"métadonnées récupérées title={title!r} "
                f"media_id={media_id!r} output_stem={output_stem!r}"
            )

            if active_pause_requested(job_id):
                raise DownloadPaused()

            # IMPORTANT : ne pas modifier ydl.params["outtmpl"] après
            # l'initialisation. yt-dlp normalise cette option en interne et
            # certaines versions attendent ensuite une structure de mapping.
            # On crée donc un contexte dédié au téléchargement avec le template
            # final dès sa construction.
            download_opts = build_opts(mode, progress_hook, output_dir, job_cookiefile)
            download_opts["outtmpl"] = output_template_for_stem(output_dir, clean_stem)

            with yt_dlp.YoutubeDL(download_opts) as download_ydl:
                result = download_ydl.process_ie_result(info, download=True)

                filepath = None
                if not isinstance(result, dict):
                    raise RuntimeError("yt-dlp n’a pas renvoyé de résultat média valide.")

                title = result.get("title") or title

                prepared_result = None
                try:
                    prepared_result = download_ydl.prepare_filename(result)
                    if mode == "mp3":
                        prepared_result = str(Path(prepared_result).with_suffix(".mp3"))
                except Exception:
                    prepared_result = None

                if mode == "audio":
                    raw_media = select_final_media_path(
                        result,
                        prepared_result,
                        output_dir,
                        clean_stem,
                        "audio",
                    )

                    remuxed, codec = remux_original_audio(raw_media)
                    filepath = str(remuxed)
                    result["filepath"] = filepath
                    result["ext"] = remuxed.suffix.lower().lstrip(".")
                    result["audio_original_codec"] = codec
                    result = embed_thumbnail_after_remux(
                        download_ydl, result, remuxed
                    )

                    ok, reason = validate_media_file(remuxed, "audio")
                    if not ok:
                        raise RuntimeError(
                            f"Le fichier audio final est invalide : {reason}"
                        )
                else:
                    final_media = select_final_media_path(
                        result,
                        prepared_result,
                        output_dir,
                        clean_stem,
                        mode,
                    )
                    filepath = str(final_media)

                log(f"fichier média final validé: {filepath!r}")

        clear_control(job_id)
        if saw_progress:
            finish_active("finished", filepath=filepath)
            log("job terminé avec succès")
        else:
            finish_active("finished", filepath=filepath)
            def mark_existing(data):
                for finished in data.get("history", []):
                    if finished.get("id") == job_id:
                        finished["already_present"] = True
                        break
            locked_mutate(mark_existing)
            log("job terminé sans octets téléchargés: fichier probablement déjà présent")
        start_next_if_any()
        return 0

    except DownloadPaused:
        mark_active_paused(job_id)
        log("job mis en pause; fichier .part conservé pour reprise")
        return 0

    except WorkerShutdown as stop:
        clear_control(job_id)
        outcome = freeze_after_external_stop(job_id, stop.signum)
        log(
            "arrêt externe sécurisé; "
            f"queue_paused=true requeued={outcome['requeued']} "
            "fichiers partiels conservés"
        )
        return 128 + int(stop.signum)

    except DownloadCancelled:
        clear_control(job_id)
        cleanup_cancelled_files(seen_paths, output_stem, started_at)
        finish_active("cancelled")
        log("job annulé par Kitty; fichiers partiels supprimés")
        start_next_if_any()
        return 0

    except Exception as exc:
        action = control_action(job_id)
        if WINDOWS and action == "cancel":
            clear_control(job_id)
            cleanup_cancelled_files(seen_paths, output_stem, started_at)
            finish_active("cancelled")
            start_next_if_any()
            return 0
        if WINDOWS and action == "stop":
            clear_control(job_id)
            freeze_after_external_stop(job_id, signal.SIGTERM)
            return 128 + int(signal.SIGTERM)
        clear_control(job_id)
        cleanup_failed_auxiliary_files(output_stem, started_at)

        raw_error = str(exc).strip() or exc.__class__.__name__
        error_info = classify_backend_error(
            raw_error,
            context="download",
            youtube_auth=bool(active.get("youtube_auth")),
            mode=mode,
        )
        log(
            f"ERREUR worker code={error_info['code']} "
            f"message={error_info['message']!r} detail={raw_error!r}"
        )
        finish_active("error", error=raw_error, error_info=error_info)
        start_next_if_any()
        return 1

    finally:
        if control_watcher is not None:
            control_watcher.set()
        cleanup_youtube_job_cookiefile(job_cookiefile)

if __name__ == "__main__":
    raise SystemExit(main())
