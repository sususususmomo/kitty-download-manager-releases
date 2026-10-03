"""Per-user Windows installer, update transaction and conservative uninstall.

The PowerShell entry point supplies a private, verified CPython runtime and
Python dependencies. This module never installs over a system Python.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid
import zipfile

BACKEND_FILES = ("host.py", "worker.py", "metadata.py", "errors.py", "app_paths.py",
                 "compatibility.py", "runtime_storage.py", "queue_store.py", "platform_support.py",
                 "windows_install.py")
HOST_NAME = "com.kitty.download_manager"
EXTENSION_ID = "kitty-download-manager@local"
APP_ID = "KittyDownloadManager"
REG_NATIVE = rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}"
REG_UNINSTALL = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
MAX_DOWNLOAD = 350 * 1024 * 1024


def app_root():
    return Path(os.environ["LOCALAPPDATA"]) / APP_ID


def check_private_path(path):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise RuntimeError(f"Lien ou jonction refuses : {part}")
    return path


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path, data):
    atomic_bytes(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def verified_download(url, destination, digest, expected_size=None):
    if urlsplit(url).scheme != "https" or not re.fullmatch(r"[0-9a-fA-F]{64}", digest or ""):
        raise RuntimeError("URL HTTPS et SHA-256 requis.")
    destination = Path(destination)
    total = 0
    hasher = hashlib.sha256()
    try:
        request = Request(url, headers={"User-Agent": "Kitty-Download-Manager-Windows/8.25"})
        with urlopen(request, timeout=90) as response, destination.open("xb") as out:
            while True:
                block = response.read(256 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_DOWNLOAD or (expected_size is not None and total > expected_size):
                    raise RuntimeError("Telechargement trop volumineux.")
                out.write(block)
                hasher.update(block)
        if expected_size is not None and total != expected_size:
            raise RuntimeError("Taille telechargee incorrecte.")
        if hasher.hexdigest() != digest.lower():
            raise RuntimeError("SHA-256 incorrect; fichier refuse.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def safe_extract(archive, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive) as z:
        total = sum(i.file_size for i in z.infolist())
        if total > 1_000_000_000:
            raise RuntimeError("Archive trop volumineuse apres extraction.")
        for item in z.infolist():
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts):
                raise RuntimeError("Chemin d’archive dangereux.")
            if any(p.rstrip(" .") != p for p in path.parts):
                raise RuntimeError("Chemin d’archive ambigu sous Windows.")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError("Lien symbolique d’archive refuse.")
        z.extractall(destination)


def github_binary(repo, asset_name, stage, executable_names):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = Request(url, headers={"User-Agent": "Kitty-Download-Manager-Windows/8.25",
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


def native_query(python, backend, action):
    payload = json.dumps({"action": action}, ensure_ascii=False).encode("utf-8")
    env = os.environ.copy()
    env["PATH"] = str(Path(backend).parent / "bin") + os.pathsep + env.get("PATH", "")
    result = subprocess.run([str(python), "-I", "-u", "-B", str(Path(backend) / "host.py")],
                            input=struct.pack("<I", len(payload)) + payload,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40, env=env)
    if result.returncode or len(result.stdout) < 4:
        raise RuntimeError("Backend natif invalide : " + result.stderr.decode("utf-8", "replace")[-1500:])
    size = struct.unpack("<I", result.stdout[:4])[0]
    if size != len(result.stdout) - 4:
        raise RuntimeError("Le backend a produit un flux natif invalide.")
    response = json.loads(result.stdout[4:])
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or response))
    return response


def checked_version_path(root, current):
    relative = str(current.get("directory") or "")
    if not re.fullmatch(r"versions/[0-9.]+-[0-9a-f]{32}", relative):
        raise RuntimeError("Metadonnees d’installation invalides.")
    path = check_private_path(Path(root) / relative)
    if path.parent != Path(root) / "versions":
        raise RuntimeError("Version hors du dossier Kitty.")
    return path


def current_install(root):
    path = Path(root) / "current.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("app") != APP_ID:
        raise RuntimeError("Le dossier existant n’est pas une installation Kitty reconnue.")
    checked_version_path(root, data)
    return data


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


@contextmanager
def paused_maintenance(root, previous):
    from queue_store import queue_lock, mutate_state, read_state, backup_state_file
    from platform_support import process_alive, script_process_matches
    import psutil
    cache = Path(root) / "cache"
    cache.mkdir(exist_ok=True)
    check_private_path(cache)
    flag = cache / "maintenance.json"
    atomic_json(flag, {"pid": os.getpid(), "created": psutil.Process().create_time()})
    try:
        queue = cache / "queue.json"
        lock = cache / "queue.lock"
        with queue_lock(lock):
            backup_state_file(queue, cache / "state-backups", "windows-install")
        captured = {}
        def freeze(state):
            state["queue_paused"] = True
            captured.update(json.loads(json.dumps(state)))
        mutate_state(queue, lock, freeze)
        active = captured.get("active")
        # A host may have claimed a job just before the maintenance marker was
        # published. Wait for the worker's own PID publication, never swap a
        # runtime while an unobserved worker is still being launched.
        deadline = time.monotonic() + 5
        while active and not active.get("worker_pid") and time.monotonic() < deadline:
            time.sleep(0.1)
            captured = read_state(queue, lock)
            active = captured.get("active")
        if active and not active.get("worker_pid"):
            raise RuntimeError("Demarrage du worker encore indetermine; mise a jour interrompue, file en pause.")
        if active and active.get("worker_pid") and process_alive(active["worker_pid"]):
            if previous is None:
                raise RuntimeError("Worker actif sans installation reconnue; interruption refusee.")
            script = checked_version_path(root, previous) / "backend/worker.py"
            if not script_process_matches(active["worker_pid"], script, active["id"]):
                raise RuntimeError("Identite du worker non verifiee; mise a jour interrompue.")
            atomic_json(cache / "controls" / f"{active['id']}.json", {"action": "stop"})
            deadline = time.monotonic() + 40
            while process_alive(active["worker_pid"]) and time.monotonic() < deadline:
                time.sleep(0.1)
            if process_alive(active["worker_pid"]):
                raise RuntimeError("Le worker ne s’est pas arrete. File conservee en pause.")
        if previous:
            metadata_script = checked_version_path(root, previous) / "backend/metadata.py"
            captured = read_state(queue, lock)
            for job in captured.get("queue", []):
                pid = job.get("metadata_pid")
                if pid:
                    try:
                        proc = psutil.Process(pid)
                        if not script_process_matches(pid, metadata_script, job.get("id")):
                            continue
                        for child in proc.children(recursive=True):
                            child.terminate()
                        proc.terminate()
                        proc.wait(timeout=5)
                    except psutil.NoSuchProcess:
                        pass
        yield
    finally:
        flag.unlink(missing_ok=True)


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
    manifest = json.loads((source / "extension/manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise RuntimeError("Version invalide.")
    backend = stage / "backend"
    backend.mkdir()
    for filename in BACKEND_FILES:
        origin = source / "native-host" / filename
        compile(origin.read_text(encoding="utf-8"), str(origin), "exec")
        shutil.copy2(origin, backend / filename)
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
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view)
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
    foreach ($item in Get-ChildItem -LiteralPath $path -Recurse -Force) {
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
    try:
        main()
    except Exception as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        raise SystemExit(1)
