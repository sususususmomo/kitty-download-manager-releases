#!/usr/bin/env python3
"""Identity and filesystem layout for Kitty Download Manager."""
from pathlib import Path
import os
import sys

WINDOWS = sys.platform == "win32"

def windows_root():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "KittyDownloadManager"

APP_NAME = "Kitty Download Manager"
APP_SLUG = "kitty-download-manager"
FIREFOX_EXTENSION_ID = "kitty-download-manager@local"
NATIVE_HOST_NAME = "com.kitty.download_manager"

LEGACY_APP_SLUG = "firefox-ytdlp"
LEGACY_FIREFOX_EXTENSION_ID = "ytdlp-downloader@local"
LEGACY_NATIVE_HOST_NAME = "com.example.ytdlp_downloader"


def install_dir():
    if WINDOWS:
        return Path(__file__).resolve().parent
    return Path.home() / ".local" / "lib" / APP_SLUG


def config_dir():
    if WINDOWS:
        return windows_root() / "config"
    return Path.home() / ".config" / APP_SLUG


def cache_dir():
    if WINDOWS:
        return windows_root() / "cache"
    return Path.home() / ".cache" / APP_SLUG


def default_output_dir():
    if WINDOWS:
        from platform_support import windows_downloads_dir
        return windows_downloads_dir() / APP_SLUG
    return Path.home() / "Downloads" / APP_SLUG


def native_manifest_dir():
    if WINDOWS:
        return windows_root()
    return Path.home() / ".mozilla" / "native-messaging-hosts"


def native_manifest_path():
    return native_manifest_dir() / f"{NATIVE_HOST_NAME}.json"


def migration_file():
    return config_dir() / "migration-v8.json"


def legacy_install_dir():
    return Path.home() / ".local" / "lib" / LEGACY_APP_SLUG


def legacy_config_dir():
    return Path.home() / ".config" / LEGACY_APP_SLUG


def legacy_cache_dir():
    return Path.home() / ".cache" / LEGACY_APP_SLUG


def legacy_default_output_dir():
    return Path.home() / "Downloads" / "videoytdlp"


def legacy_native_manifest_path():
    return native_manifest_dir() / f"{LEGACY_NATIVE_HOST_NAME}.json"
