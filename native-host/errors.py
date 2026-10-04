#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

NATIVE_DIR = Path(__file__).resolve().parent
if str(NATIVE_DIR) not in sys.path:
    sys.path.insert(0, str(NATIVE_DIR))

from app_paths import APP_NAME, APP_SLUG


CATALOG = {
    "image_unavailable": ("Aucune image disponible", "Ce contenu ne fournit aucune miniature ou pochette accessible.", False),
    "image_invalid": ("Fichier image invalide", "Le site n’a pas fourni de fichier image exploitable.", True),
    "no_audio": ("Aucun flux audio disponible", "Ce contenu ne fournit aucun flux audio téléchargeable.", False),
    "no_video": ("Aucun flux vidéo disponible", "Ce contenu ne fournit aucun flux vidéo téléchargeable.", False),
    "youtube_session_expired": ("Session YouTube expirée", "Renouvelle la session dédiée YouTube dans les réglages.", True),
    "disk_full": ("Espace disque insuffisant", "Libère de l’espace dans le dossier de destination puis relance.", True),
    "ffmpeg_missing": ("ffmpeg introuvable", "Installe ffmpeg puis relance Kitty.", False),
    "ffprobe_missing": ("ffprobe introuvable", "Installe ffmpeg/ffprobe puis relance Kitty.", False),
    "ytdlp_missing": ("yt-dlp introuvable", "Installe le module Python yt-dlp puis relance Kitty.", False),
    "video_private": ("Vidéo privée", "Ce contenu n’est pas accessible avec la session actuelle.", False),
    "content_deleted": ("Contenu supprimé", "Le média n’est plus disponible sur le site source.", False),
    "collection_empty": ("Collection vide", "Aucun média accessible n’a été trouvé dans cette collection.", False),
    "network_interrupted": ("Connexion interrompue", "Vérifie la connexion Internet puis relance le téléchargement.", True),
    "rate_limited": ("Trop de requêtes", "Le site demande de ralentir. Attends un peu avant de relancer.", True),
    "access_denied": ("Accès refusé par le site", "Le serveur a refusé la requête. Une session ou un nouvel essai peut être nécessaire.", True),
    "login_required": ("Connexion au site requise", "Ce contenu nécessite une session authentifiée.", False),
    "geo_restricted": ("Contenu indisponible dans cette région", "Le site bloque ce média dans ta région.", False),
    "age_restricted": ("Contenu soumis à une restriction d’âge", "Une session authentifiée autorisée peut être nécessaire.", False),
    "drm_protected": ("Contenu protégé par DRM", "Kitty Download Manager ne peut pas télécharger un média protégé par DRM.", False),
    "unsupported_url": ("Site ou URL non pris en charge", "yt-dlp ne reconnaît pas cette URL comme un média téléchargeable.", False),
    "invalid_url": ("URL invalide", "Vérifie l’adresse puis réessaie.", False),
    "format_unavailable": ("Format demandé indisponible", "Essaie un autre format de téléchargement.", False),
    "media_invalid": ("Fichier média invalide", "Le site n’a pas produit de fichier audio/vidéo exploitable.", True),
    "permission_denied": ("Permission refusée", "Kitty Download Manager ne peut pas écrire dans le dossier concerné.", False),
    "output_unavailable": ("Dossier de destination indisponible", "Choisis un dossier de destination accessible en écriture.", False),
    "state_error": ("État de la file endommagé", "Kitty Download Manager a rencontré un problème avec son état local. Consulte les logs.", False),
    "worker_missing": ("Composant Kitty manquant", "Réinstalle Kitty Download Manager pour restaurer le worker local.", False),
    "firefox_missing": ("Firefox introuvable", "Firefox n’a pas été trouvé pour créer la session YouTube dédiée.", False),
    "youtube_auth_not_configured": ("Session YouTube non configurée", "Configure d’abord la session dédiée YouTube dans les réglages.", False),
    "youtube_auth_window_open": ("Fenêtre YouTube encore ouverte", "Ferme la fenêtre Firefox dédiée puis réessaie.", True),
    "already_active": ("Téléchargement déjà en cours", "Ce média est déjà le téléchargement actif.", False),
    "already_queued": ("Déjà dans la file", "Ce média attend déjà dans la file de téléchargement.", False),
    "already_downloaded": ("Déjà téléchargé", "Ce média existe déjà dans l’historique pour ce format et cette destination.", False),
    "history_missing": ("Téléchargement introuvable", "Cette entrée n’existe plus dans l’historique.", False),
    "retry_not_error": ("Relance impossible", "Seuls les téléchargements en erreur peuvent être relancés.", False),
    "queue_item_missing": ("Élément introuvable dans la file", "La file a probablement changé depuis l’affichage.", True),
    "no_active": ("Aucun téléchargement actif", "Il n’y a actuellement aucun téléchargement à modifier.", False),
    "active_changed": ("Le téléchargement actif a changé", "Actualise l’état puis réessaie.", True),
    "active_pause_disabled": ("Pause du téléchargement actif indisponible", "Kitty Download Manager désactive cette pause pour éviter les reprises HTTP instables.", False),
    "folder_open_failed": ("Impossible d’ouvrir le dossier", "Aucun gestionnaire de fichiers compatible n’a pu être lancé.", False),
    "logs_open_failed": ("Impossible d’ouvrir les logs", "Ouvre manuellement ~/.cache/kitty-download-manager/worker.log.", False),
    "postprocess_failed": ("Traitement final impossible", "ffmpeg n’a pas pu finaliser ou convertir le média.", True),
    "metadata_failed": ("Métadonnées indisponibles", "Le titre n’a pas pu être récupéré.", True),
    "extraction_failed": ("Impossible d’analyser ce contenu", "Le site a changé ou yt-dlp n’a pas pu extraire les informations du média.", True),
    "unsupported_action": ("Action non prise en charge", "Cette action n’est pas disponible dans cette version de Kitty Download Manager.", False),
    "incompatible_frontend_backend": ("Kitty doit être mise à jour", "Frontend et backend ne sont pas compatibles. Mets à jour Kitty puis recharge l’extension Firefox.", False),
    "kitty_update_check_failed": ("Vérification de la mise à jour Kitty impossible", "Vérifie ta connexion Internet puis réessaie depuis Diagnostic.", True),
    "kitty_update_unavailable": ("Aucune mise à jour Kitty disponible", "La version installée est déjà à jour ou plus récente que la dernière release publiée.", False),
    "kitty_update_digest_missing": ("SHA-256 de la release indisponible", "Kitty refuse de télécharger une release qui ne peut pas être vérifiée.", False),
    "kitty_update_integrity_failed": ("Vérification SHA-256 échouée", "L’archive reçue ne correspond pas au hash publié par GitHub et a été rejetée.", True),
    "kitty_update_download_failed": ("Téléchargement de la mise à jour impossible", "Réessaie depuis Diagnostic. Aucun fichier non vérifié n’est conservé.", True),
    "backend_error": ("Erreur du backend", "Consulte les logs pour le détail technique.", True),
}

FLOW_CODE_MAP = {
    "already_active": "already_active",
    "already_queued": "already_queued",
    "already_downloaded": "already_downloaded",
    "invalid_url": "invalid_url",
    "active_pause_disabled": "active_pause_disabled",
    "unsupported_action": "unsupported_action",
    "incompatible_frontend_backend": "incompatible_frontend_backend",
    "kitty_update_check_failed": "kitty_update_check_failed",
    "kitty_update_unavailable": "kitty_update_unavailable",
    "kitty_update_digest_missing": "kitty_update_digest_missing",
    "kitty_update_integrity_failed": "kitty_update_integrity_failed",
    "kitty_update_download_failed": "kitty_update_download_failed",
}


def _entry(code: str, detail: str, message_override: str | None = None) -> dict[str, Any]:
    message, hint, retryable = CATALOG.get(code, CATALOG["backend_error"])
    return {
        "code": code,
        "message": message_override or message,
        "hint": hint,
        "retryable": bool(retryable),
        "detail": detail[:4000],
    }


def _contains(text: str, *parts: str) -> bool:
    return any(part in text for part in parts)


def classify_backend_error(
    raw: Any,
    *,
    context: str = "",
    youtube_auth: bool = False,
    mode: str | None = None,
    code_hint: str | None = None,
) -> dict[str, Any]:
    detail = str(raw or "").strip()
    text = detail.casefold()
    mode = str(mode or "").casefold()

    if code_hint in FLOW_CODE_MAP:
        return _entry(FLOW_CODE_MAP[code_hint], detail)

    business = (
        ("seuls les téléchargements en erreur", "retry_not_error"),
        ("téléchargement introuvable dans l'historique", "history_missing"),
        ("élément introuvable dans la file", "queue_item_missing"),
        ("aucun téléchargement actif", "no_active"),
        ("le téléchargement actif a changé", "active_changed"),
        ("pause d'un téléchargement déjà lancé", "active_pause_disabled"),
        ("action non supportée", "unsupported_action"),
        ("firefox introuvable", "firefox_missing"),
        ("configure d'abord une session youtube", "youtube_auth_not_configured"),
        ("ferme d'abord la fenêtre firefox dédiée", "youtube_auth_window_open"),
    )
    for needle, code in business:
        if needle in text:
            return _entry(code, detail)

    if _contains(text, "no space left on device", "errno 28", "disk quota exceeded", "insufficient disk space"):
        return _entry("disk_full", detail)

    if _contains(text, "permission denied", "errno 13", "read-only file system"):
        return _entry("permission_denied", detail)

    if _contains(text, "dossier de destination invalide", "destination n’est pas accessible", "destination n'est pas accessible"):
        return _entry("output_unavailable", detail)

    if _contains(text, "ffmpeg not found", "ffmpeg is not installed", "ffmpeg introuvable", "ffmpeg est requis", "unable to find ffmpeg"):
        return _entry("ffmpeg_missing", detail)

    if _contains(text, "ffprobe not found", "ffprobe is not installed", "ffprobe introuvable", "ffprobe est requis", "unable to find ffprobe"):
        return _entry("ffprobe_missing", detail)

    if _contains(text, "no module named 'yt_dlp'", 'no module named "yt_dlp"', "yt-dlp python est introuvable"):
        return _entry("ytdlp_missing", detail)

    if "worker introuvable" in text:
        return _entry("worker_missing", detail)

    if _contains(text, "aucune miniature ou pochette", "aucune image n’a pu être téléchargée"):
        return _entry("image_unavailable", detail)
    if "image téléchargée invalide" in text:
        return _entry("image_invalid", detail)

    if _contains(text, "aucun flux audio", "no audio formats", "audio format is not available", "no audio stream"):
        return _entry("no_audio", detail)

    if _contains(text, "aucun flux vidéo", "aucun flux video", "no video formats", "no video stream"):
        return _entry("no_video", detail)

    if _contains(text, "requested format is not available", "requested format not available", "format is not available", "format de téléchargement invalide"):
        if mode in {"audio", "mp3"} and "audio" in text:
            return _entry("no_audio", detail)
        return _entry("format_unavailable", detail)

    if _contains(
        text,
        "aucun fichier média valide",
        "aucun fichier media valide",
        "fichier audio final est invalide",
        "fichier média invalide",
        "fichier media invalide",
        "n’a pas renvoyé de résultat média valide",
        "n'a pas renvoyé de résultat média valide",
    ):
        return _entry("media_invalid", detail)

    if _contains(text, "postprocessing", "post-processing", "ffmpeg a échoué", "ffmpeg a echoue", "error in ffmpeg"):
        return _entry("postprocess_failed", detail)

    youtube_marker = youtube_auth or "youtube" in text or "youtu.be" in text
    auth_marker = _contains(
        text,
        "sign in to confirm",
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "cookies",
        "cookie",
        "authentication",
        "not a bot",
        "account is required",
        "http error 401",
    )
    if youtube_marker and auth_marker:
        return _entry("youtube_session_expired", detail)

    if youtube_auth and _contains(text, "http error 403", "forbidden", "status code 403"):
        return _entry("youtube_session_expired", detail)

    if _contains(text, "private video", "this video is private", "private track", "track is private", "vidéo privée", "video privee"):
        return _entry("video_private", detail)

    if _contains(
        text,
        "video has been removed",
        "this video has been removed",
        "track has been removed",
        "has been deleted",
        "deleted video",
        "content deleted",
        "contenu supprimé",
        "contenu supprime",
        "404 not found",
        "http error 404",
    ):
        return _entry("content_deleted", detail)

    if _contains(
        text,
        "aucun média individuel accessible",
        "aucun media individuel accessible",
        "aucun média accessible",
        "aucun media accessible",
        "playlist is empty",
        "collection is empty",
        "empty playlist",
        "no entries",
    ):
        return _entry("collection_empty", detail)

    if _contains(text, "not available in your country", "geo restricted", "georestricted", "not available in your region"):
        return _entry("geo_restricted", detail)

    if _contains(text, "age-restricted", "age restricted", "confirm your age", "inappropriate for some users"):
        return _entry("age_restricted", detail)

    if _contains(text, "drm protected", "drm-protected", "this video is drm"):
        return _entry("drm_protected", detail)

    if _contains(text, "http error 429", "too many requests", "rate limit", "ratelimit"):
        return _entry("rate_limited", detail)

    if _contains(
        text,
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "connection aborted",
        "network is unreachable",
        "temporary failure in name resolution",
        "name or service not known",
        "remote end closed connection",
        "connection closed",
        "broken pipe",
        "ssl eof",
    ):
        return _entry("network_interrupted", detail)

    if _contains(text, "http error 403", "forbidden", "status code 403"):
        return _entry("access_denied", detail)

    if _contains(text, "login required", "login is required", "you must be logged in", "authentication required"):
        return _entry("login_required", detail)

    if _contains(text, "unsupported url", "no suitable extractor", "url non prise en charge"):
        return _entry("unsupported_url", detail)

    if _contains(text, "url invalide", "invalid url", "url de collection invalide", "url http/https"):
        return _entry("invalid_url", detail)

    if _contains(text, "queue.json illisible", "queue.json invalide", "état queue.json", "etat queue.json", "state_version"):
        return _entry("state_error", detail)

    if _contains(text, "unable to extract", "extractor error", "unable to download webpage", "unable to download api page", "unable to parse", "n’a pas reconnu cette url", "n'a pas reconnu cette url"):
        return _entry("extraction_failed", detail)

    if detail and len(detail) <= 140 and "\n" not in detail and not re.search(r"\b(traceback|errno|exception|error:)\b", text):
        return _entry("backend_error", detail, message_override=detail.rstrip("."))

    return _entry("backend_error", detail or "Erreur backend sans détail.")


def normalize_error_payload(
    payload: dict[str, Any],
    *,
    context: str = "",
    youtube_auth: bool = False,
    mode: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("ok") is not False:
        return payload

    raw = payload.get("error")
    if raw is None:
        return payload

    result = dict(payload)
    info = classify_backend_error(
        raw,
        context=context,
        youtube_auth=youtube_auth,
        mode=mode,
        code_hint=str(payload.get("code") or "") or None,
    )

    result["error_code"] = info["code"]
    result["error"] = info["message"]
    result["error_hint"] = info["hint"]
    result["retryable"] = info["retryable"]

    detail = str(raw or "").strip()
    if detail and detail != info["message"]:
        result["error_detail"] = detail[:4000]

    return result
