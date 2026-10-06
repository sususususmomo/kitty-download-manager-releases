#!/usr/bin/env python3
"""Identity and filesystem layout for Kitty Download Manager."""
from pathlib import Path
import os
import re
import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

def macos_root():
    return Path.home() / "Library" / "Application Support" / "KittyDownloadManager"

def windows_runtime_root(module_file=None):
    """Resolve the owning installation even before a stage is published."""
    backend = Path(module_file or __file__).resolve().parent
    version = backend.parent
    if backend.name != "backend":
        return None
    if version.parent.name == "versions" and re.fullmatch(r"[0-9.]+-[0-9a-f]{32}", version.name):
        return version.parent.parent
    if re.fullmatch(r"stage-[0-9a-f]{32}", version.name):
        return version.parent
    return None


def windows_registered_root():
    if not WINDOWS:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\KittyDownloadManager",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value = winreg.QueryValueEx(key, "InstallLocation")[0]
    except FileNotFoundError:
        return None
    root = Path(value)
    if not root.is_absolute() or root == Path(root.anchor):
        raise RuntimeError("Dossier Kitty enregistre invalide.")
    return root


def windows_root():
    return (windows_runtime_root() or windows_registered_root() or
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "KittyDownloadManager")

APP_NAME = "Kitty Download Manager"
APP_SLUG = "kitty-download-manager"
FIREFOX_EXTENSION_ID = "kitty-download-manager@local"
NATIVE_HOST_NAME = "com.kitty.download_manager"

LEGACY_APP_SLUG = "firefox-ytdlp"
LEGACY_FIREFOX_EXTENSION_ID = "ytdlp-downloader@local"
LEGACY_NATIVE_HOST_NAME = "com.example.ytdlp_downloader"


def install_dir():
    if WINDOWS or MACOS:
        return Path(__file__).resolve().parent
    return Path.home() / ".local" / "lib" / APP_SLUG


def config_dir():
    if WINDOWS:
        return windows_root() / "config"
    if MACOS:
        return macos_root() / "config"
    return Path.home() / ".config" / APP_SLUG


def cache_dir():
    if WINDOWS:
        return windows_root() / "cache"
    if MACOS:
        return macos_root() / "cache"
    return Path.home() / ".cache" / APP_SLUG


def default_output_dir():
    if WINDOWS:
        from platform_support import windows_downloads_dir
        return windows_downloads_dir() / APP_SLUG
    return Path.home() / "Downloads" / APP_SLUG


def native_manifest_dir():
    if WINDOWS:
        return windows_root()
    if MACOS:
        return Path.home() / "Library/Application Support/Mozilla/NativeMessagingHosts"
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
