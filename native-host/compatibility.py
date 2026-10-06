#!/usr/bin/env python3
"""Frontend/backend and dependency compatibility policy for Kitty."""
from __future__ import annotations

import re
from typing import Any

APP_SERIES = 8
NATIVE_PROTOCOL_VERSION = 1
STATE_SCHEMA_VERSION = 2


def version_tuple(value: Any) -> tuple[int, ...]:
    text = str(value or "").strip()
    match = re.search(r"(\d+(?:\.\d+)+|\d+)", text)
    if not match:
        return ()
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except Exception:
        return ()


def app_series(value: Any) -> int | None:
    parts = version_tuple(value)
    return parts[0] if parts else None


def client_report(client: Any, backend_version: str) -> dict[str, Any]:
    """Describe whether a frontend can safely use this backend.

    Missing client metadata is tolerated for one-way/backend-first upgrades: old
    frontends keep working long enough for Firefox to be reloaded. New frontends
    always send metadata and enforce this report before mutating actions.
    """
    backend_series = app_series(backend_version)

    if not isinstance(client, dict):
        return {
            "compatible": True,
            "verified": False,
            "status": "client_unknown",
            "update_required": False,
            "potential_incompatibility": False,
            "backend_version": backend_version,
            "backend_protocol": NATIVE_PROTOCOL_VERSION,
            "frontend_version": None,
            "frontend_protocol": None,
            "message": "Frontend ancien/non identifié : recharge l’extension après la mise à jour du backend.",
        }

    frontend_version = str(client.get("version") or "").strip() or None
    try:
        frontend_protocol = int(client.get("protocol"))
    except Exception:
        frontend_protocol = None

    frontend_series = app_series(frontend_version)
    protocol_ok = frontend_protocol == NATIVE_PROTOCOL_VERSION
    series_ok = frontend_series == APP_SERIES == backend_series

    if not protocol_ok:
        status = "protocol_mismatch"
        compatible = False
        message = (
            f"Protocole frontend {frontend_protocol if frontend_protocol is not None else '?'} "
            f"≠ backend {NATIVE_PROTOCOL_VERSION}. Mets à jour Kitty avant de télécharger."
        )
    elif not series_ok:
        status = "series_mismatch"
        compatible = False
        message = "Frontend et backend appartiennent à des séries Kitty incompatibles."
    elif frontend_version != backend_version:
        status = "version_skew"
        compatible = True
        message = (
            f"Frontend {frontend_version or '?'} / backend {backend_version} : "
            "protocole compatible, versions différentes."
        )
    else:
        status = "compatible"
        compatible = True
        message = f"Frontend {frontend_version} ↔ backend {backend_version} compatibles."

    return {
        "compatible": compatible,
        "verified": True,
        "status": status,
        "update_required": not compatible,
        "potential_incompatibility": not compatible,
        "backend_version": backend_version,
        "backend_protocol": NATIVE_PROTOCOL_VERSION,
        "frontend_version": frontend_version,
        "frontend_protocol": frontend_protocol,
        "message": message,
    }


def assess_update_risk(dep_id: str, current: Any, available: Any) -> dict[str, Any]:
    """Conservative risk marker for dependency upgrades.

    Kitty never auto-upgrades system dependencies. The marker only tells the UI
    when a package-manager/PyPI update deserves a compatibility review.
    """
    dep_id = str(dep_id or "")
    old = version_tuple(current)
    new = version_tuple(available)

    if not old or not new:
        return {
            "risk": "unknown",
            "potential_incompatibility": True,
            "reason": "Version non comparable : vérification manuelle recommandée.",
        }

    if new <= old:
        return {"risk": "none", "potential_incompatibility": False, "reason": "À jour."}

    if dep_id == "python":
        # Python minor upgrades can affect distro Python modules and native wheels.
        old_mm = old[:2]
        new_mm = new[:2]
        risky = old_mm != new_mm
        return {
            "risk": "review" if risky else "low",
            "potential_incompatibility": risky,
            "reason": (
                "Changement de version Python mineure : vérifier yt-dlp/Mutagen après mise à jour."
                if risky else "Mise à jour corrective Python dans la même branche."
            ),
        }

    if dep_id in {"ffmpeg", "ffprobe"}:
        risky = old[0] != new[0]
        return {
            "risk": "review" if risky else "low",
            "potential_incompatibility": risky,
            "reason": (
                "Changement de version majeure ffmpeg : tester le post-traitement Kitty."
                if risky else "Mise à jour ffmpeg dans la même version majeure."
            ),
        }

    if dep_id == "mutagen":
        risky = old[0] != new[0]
        return {
            "risk": "review" if risky else "low",
            "potential_incompatibility": risky,
            "reason": (
                "Changement majeur Mutagen : vérifier l’intégration des pochettes."
                if risky else "Mise à jour Mutagen à faible risque."
            ),
        }

    # yt-dlp intentionally moves quickly; updates are usually needed for site
    # changes and are not treated as unsafe solely because the date version moves.
    if dep_id == "yt_dlp":
        return {
            "risk": "low",
            "potential_incompatibility": False,
            "reason": "Mise à jour yt-dlp recommandée pour suivre les changements des sites.",
        }

    return {
        "risk": "unknown",
        "potential_incompatibility": True,
        "reason": "Compatibilité de cette mise à jour non classée.",
    }
