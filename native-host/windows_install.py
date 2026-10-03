"""Per-user Windows installer, update transaction and conservative uninstall.

The PowerShell entry point supplies a private, verified CPython runtime and
Python dependencies. This module never installs over a system Python.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid

NATIVE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(NATIVE_DIR))
from installer_support import (check_private_path, atomic_bytes, atomic_json, verified_download,
                               safe_extract, native_query, checked_version_path, current_install,
                               paused_maintenance, source_backend_version)

BACKEND_FILES = ("host.py", "worker.py", "metadata.py", "errors.py", "app_paths.py",
                 "compatibility.py", "runtime_storage.py", "queue_store.py", "platform_support.py",
                 "windows_install.py", "installer_support.py")
HOST_NAME = "com.kitty.download_manager"
EXTENSION_ID = "kitty-download-manager@local"
APP_ID = "KittyDownloadManager"
REG_NATIVE = rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}"
REG_UNINSTALL = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
MAX_DOWNLOAD = 350 * 1024 * 1024


def app_root():
    return Path(os.environ["LOCALAPPDATA"]) / APP_ID


def github_binary(repo, asset_name, stage, executable_names):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = Request(url, headers={"User-Agent": "Kitty-Download-Manager-Windows/8.31",
                                   "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        release = json.loads(response.read(4_000_000))
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    if asset is None:
        raise RuntimeError(f"Archive officielle absente : {repo}/{asset_name}")
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
        raise RuntimeError(f"SHA-256 GitHub absent pour {asset_name}; installation interrompue.")
    parsed = urlsplit(asset["browser_download_url"])
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not parsed.path.startswith(f"/{repo}/releases/download/"):
        raise RuntimeError("URL GitHub inattendue.")
    size = int(asset.get("size") or 0)
    if not 0 < size <= MAX_DOWNLOAD:
        raise RuntimeError("Taille de release invalide.")
    archive = Path(stage) / asset_name
    unpacked = Path(stage) / f"unpack-{uuid.uuid4().hex}"
    try:
        verified_download(asset["browser_download_url"], archive, digest[7:], size)
        safe_extract(archive, unpacked)
        bin_dir = Path(stage) / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name in executable_names:
            candidates = list(unpacked.rglob(name))
            if len(candidates) != 1:
                raise RuntimeError(f"Executable {name} absent ou ambigu.")
            shutil.copy2(candidates[0], bin_dir / name)
        for path in unpacked.rglob("*"):
            if path.is_file() and path.name.lower().startswith(("license", "copying", "copyright", "notice")):
                notice = Path(stage) / "notices" / repo.replace("/", "-") / path.relative_to(unpacked)
                notice.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, notice)
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(unpacked, ignore_errors=True)
    return {"repo": repo, "tag": release.get("tag_name"), "asset": asset_name, "sha256": digest[7:]}


def snapshot_registry():
    import winreg
    items = []
    for path, names in ((REG_NATIVE, ("",)), (REG_UNINSTALL, ("DisplayName", "DisplayVersion", "Publisher",
                         "InstallLocation", "UninstallString", "NoModify", "NoRepair"))):
        views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY) if path == REG_NATIVE else (winreg.KEY_WOW64_64KEY,)
        for view in views:
            for name in names:
                value = None
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | view) as key:
                        value = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    pass
                items.append((path, view, name, value))
    return items


def restore_registry(items):
    import winreg
    for path, view, name, value in reversed(items):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | view) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, value[1], value[0])


def register(root, version):
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_NATIVE, 0, winreg.KEY_WRITE | view) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(Path(root) / f"{HOST_NAME}.json"))
    values = {"DisplayName": "Kitty Download Manager", "DisplayVersion": version,
              "Publisher": "Kitty Download Manager", "InstallLocation": str(root),
              "UninstallString": '"' + str(Path(root) / "Uninstall.cmd") + '"',
              "NoModify": 1, "NoRepair": 1}
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_UNINSTALL, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ, value)


def commit_install(root, stage, version, *, register_host=True, validate=None):
    """Publish a tested version; restore launcher, extension and registry on failure."""
    root, stage = Path(root), Path(stage)
    version_dir = root / "versions" / f"{version}-{uuid.uuid4().hex}"
    version_dir.parent.mkdir(exist_ok=True)
    check_private_path(version_dir.parent)
    files = ("native-host.bat", f"{HOST_NAME}.json", "current.json", "Uninstall.cmd")
    saved = {name: (root / name).read_bytes() if (root / name).exists() else None for name in files}
    registry = snapshot_registry() if register_host else []
    old_extension = root / f"extension-backup-{uuid.uuid4().hex}"
    extension = root / "extension"
    moved_extension = False
    published_extension = False
    os.replace(stage, version_dir)
    try:
        if validate:
            validate(version_dir)
        relative = version_dir.relative_to(root).as_posix()
        windows_relative = relative.replace("/", "\\")
        launcher = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                    f'set "PATH=%~dp0{windows_relative}\\bin;%PATH%"\r\n'
                    f'"%~dp0{windows_relative}\\runtime\\python.exe" -I -u -B "%~dp0{windows_relative}\\backend\\host.py"\r\n')
        uninstaller = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                      f'"%~dp0{windows_relative}\\runtime\\python.exe" -I -u -B "%~dp0{windows_relative}\\backend\\windows_install.py" uninstall\r\n'
                      'exit /b %errorlevel%\r\n')
        manifest = {"name": HOST_NAME, "description": "Kitty Download Manager Windows",
                    "path": str(root / "native-host.bat"), "type": "stdio", "allowed_extensions": [EXTENSION_ID]}
        if (version_dir / "extension").is_dir():
            if extension.exists():
                check_private_path(extension)
                os.replace(extension, old_extension)
                moved_extension = True
            published_extension = True
            shutil.copytree(version_dir / "extension", extension)
        atomic_bytes(root / "native-host.bat", launcher.encode("utf-8"))
        atomic_json(root / f"{HOST_NAME}.json", manifest)
        atomic_bytes(root / "Uninstall.cmd", uninstaller.encode("utf-8"))
        if register_host:
            register(root, version)
        atomic_json(root / "current.json", {"app": APP_ID, "version": version, "directory": relative,
                                           "installed_at": time.time(), "native_registered": register_host})
    except BaseException:
        if published_extension or (extension.exists() and moved_extension):
            shutil.rmtree(extension, ignore_errors=True)
        if moved_extension:
            os.replace(old_extension, extension)
        for name, data in saved.items():
            if data is None:
                (root / name).unlink(missing_ok=True)
            else:
                atomic_bytes(root / name, data)
        if register_host:
            restore_registry(registry)
        # Retain the failed version for diagnosis if Windows still holds a file.
        shutil.rmtree(version_dir, ignore_errors=True)
        raise
    shutil.rmtree(old_extension, ignore_errors=True)
    return version_dir


def install(args):
    root = check_private_path(app_root())
    source, stage = Path(args.source).resolve(), check_private_path(Path(args.stage).resolve())
    if stage.parent != root or not re.fullmatch(r"stage-[0-9a-f]{32}", stage.name):
        raise RuntimeError("Dossier de preparation inattendu.")
    version = source_backend_version(source)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise RuntimeError("Version invalide.")
    backend = stage / "backend"
    backend.mkdir()
    for filename in BACKEND_FILES:
        origin = source / "native-host" / filename
        compile(origin.read_text(encoding="utf-8"), str(origin), "exec")
        shutil.copy2(origin, backend / filename)
    if (source / "extension").is_dir():
        shutil.copytree(source / "extension", stage / "extension")
    shutil.copy2(source / "THIRD-PARTY-NOTICES.md", stage / "THIRD-PARTY-NOTICES.md")
    if not args.no_dependencies:
        print("Preparation de FFmpeg et Deno...", flush=True)
        downloads = [github_binary("yt-dlp/FFmpeg-Builds", "ffmpeg-master-latest-win64-gpl.zip", stage, ("ffmpeg.exe", "ffprobe.exe")),
                     github_binary("denoland/deno", "deno-x86_64-pc-windows-msvc.zip", stage, ("deno.exe",))]
        atomic_json(stage / "binary-dependencies.json", downloads)
        for executable in ("ffmpeg", "ffprobe", "deno"):
            result = subprocess.run([str(stage / "bin" / f"{executable}.exe"), "--version" if executable == "deno" else "-version"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if result.returncode:
                raise RuntimeError(f"Executable {executable} invalide.")
    python = stage / "runtime/python.exe"
    print("Verification du protocole Firefox...", flush=True)
    def validate_runtime(path):
        query_python = path / "runtime/python.exe"
        query_backend = path / "backend"
        native_query(query_python, query_backend, "get_settings")
        report = native_query(query_python, query_backend, "compatibility")
        if report.get("compatibility", {}).get("backend_version") != version:
            raise RuntimeError("Versions de l’extension et du backend differentes; installation refusee.")
    validate_runtime(stage)
    sys.path.insert(0, str(backend))
    from queue_store import queue_lock
    with queue_lock(root / "install.lock"):
        previous = current_install(root)
        if previous and tuple(map(int, previous["version"].split('.'))) > tuple(map(int, version.split('.'))):
            raise RuntimeError("Downgrade refuse; utiliser une version au moins aussi recente.")
        with paused_maintenance(root, previous):
            commit_install(root, stage, version, register_host=not args.no_register, validate=validate_runtime)
    print("Backend installe. Configuration, historique et telechargements conserves.", flush=True)
    print("La file est en pause; reprendre depuis Kitty apres le rechargement de l’extension.", flush=True)


def unregister(root):
    import winreg
    keys = []
    for path in (REG_NATIVE, REG_UNINSTALL):
        views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY) if path == REG_NATIVE else (winreg.KEY_WOW64_64KEY,)
        for view in views:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | view) as key:
                    value = winreg.QueryValueEx(key, "" if path == REG_NATIVE else "InstallLocation")[0]
                expected = str(Path(root) / f"{HOST_NAME}.json") if path == REG_NATIVE else str(root)
                if os.path.normcase(value) != os.path.normcase(expected):
                    raise RuntimeError("Entree de registre d’une autre installation; suppression refusee.")
                keys.append((path, view))
            except FileNotFoundError:
                pass
    saved = snapshot_registry()
    try:
        for path, view in keys:
            try:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view)
            except FileNotFoundError:
                # HKCU\Software\Mozilla is shared across WOW64 views. The
                # first deletion can therefore remove the second logical
                # view too. Missing is success; other errors still roll back.
                pass
    except Exception:
        restore_registry(saved)
        raise


def uninstall(args):
    root = check_private_path(app_root())
    previous = current_install(root)
    if previous is None:
        raise RuntimeError("Aucune installation Kitty reconnue.")
    sys.path.insert(0, str(checked_version_path(root, previous) / "backend"))
    from queue_store import queue_lock
    with queue_lock(root / "install.lock"):
        with paused_maintenance(root, previous):
            unregister(root)
            for name in ("native-host.bat", f"{HOST_NAME}.json", "current.json"):
                (root / name).unlink(missing_ok=True)
            shutil.rmtree(root / "extension", ignore_errors=True)
            # Current interpreter cannot be deleted while running on Windows.
            # A detached PowerShell helper waits for THIS PID, then removes only
            # validated Kitty runtime versions; config/cache/downloads survive.
            cleanup = root / "cleanup-uninstall.ps1"
            script = """param([int]$OwnerPid)
$ErrorActionPreference='Stop'
Wait-Process -Id $OwnerPid -ErrorAction SilentlyContinue
$root=$PSScriptRoot
$lock=$null
try {
 for ($attempt=0; $attempt -lt 100 -and -not $lock; $attempt++) {
  try { $lock=[IO.File]::Open((Join-Path $root 'install.lock'),'OpenOrCreate','ReadWrite','None') }
  catch [IO.IOException] { Start-Sleep -Milliseconds 100 }
 }
 if (-not $lock) { throw 'Une autre installation est en cours.' }
 if (Test-Path -LiteralPath (Join-Path $root 'current.json')) { exit 0 }
 foreach ($name in @('versions','Uninstall.cmd','cleanup-uninstall.ps1')) {
  $path=Join-Path $root $name
  if (Test-Path -LiteralPath $path) {
   if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Lien refuse.' }
   if ($name -eq 'versions') {
    foreach ($item in (Get-ChildItem -LiteralPath $path -Recurse -Force)) {
     if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Lien interne refuse.' }
    }
   }
   Remove-Item -LiteralPath $path -Recurse -Force
  }
 }
} finally { if ($lock) { $lock.Dispose() } }
"""
            atomic_bytes(cleanup, script.encode("utf-8"))
            from platform_support import spawn_options
            powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            subprocess.Popen([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(cleanup), str(os.getpid())],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **spawn_options())
    print("Kitty desinstalle. Reglages, historique et fichiers telecharges conserves.")


def main():
    if sys.platform != "win32":
        raise RuntimeError("Cet installateur est reserve a Windows.")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("install")
    setup.add_argument("--source", required=True)
    setup.add_argument("--stage", required=True)
    setup.add_argument("--no-dependencies", action="store_true", help=argparse.SUPPRESS)
    setup.add_argument("--no-register", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("uninstall")
    args = parser.parse_args()
    return install(args) if args.command == "install" else uninstall(args)


if __name__ == "__main__":
    if sys.platform == "win32":
        # Match the UTF-8 console decoding configured by Install.ps1.
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except Exception as exc:
        if os.environ.get("KITTY_INSTALL_TRACEBACK") == "1":
            import traceback
            traceback.print_exc()
        print(f"ERREUR : {exc}", file=sys.stderr)
        raise SystemExit(1)
