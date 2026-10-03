"""Per-user macOS setup with a private relocatable Python and rollback."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from urllib.request import Request
import uuid

NATIVE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(NATIVE_DIR))
from platform_support import open_url as urlopen
from app_paths import macos_root, native_manifest_path, default_output_dir
from installer_support import (check_private_path, atomic_bytes, atomic_json, verified_download,
                               safe_extract, native_query, checked_version_path, current_install,
                               paused_maintenance)
from queue_store import queue_lock

HOST_NAME = "com.kitty.download_manager"
EXTENSION_ID = "kitty-download-manager@local"
BACKEND_FILES = ("host.py", "worker.py", "metadata.py", "errors.py", "app_paths.py",
                 "compatibility.py", "runtime_storage.py", "queue_store.py", "platform_support.py",
                 "installer_support.py", "macos_install.py")
# Pinned provider checksums verified on 2026-10-03.
FFMPEG_BUILDS = {
    "x86_64": {"path": "amd64/1789931006_9.0.2",
               "ffmpeg": "7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4",
               "ffprobe": "2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd"},
    "aarch64": {"path": "arm64/1789931890_9.0.2",
                "ffmpeg": "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924",
                "ffprobe": "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6"},
}


def fetch_json(url):
    request = Request(url, headers={"User-Agent": "Kitty-Download-Manager/8.30",
                                   "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=40) as response:
        return json.loads(response.read(4_000_000))


def install_archive(url, digest, stage, name, size=None):
    archive = Path(stage) / ("download-" + uuid.uuid4().hex + ".zip")
    unpacked = Path(stage) / ("unpack-" + uuid.uuid4().hex)
    try:
        verified_download(url, archive, digest, size)
        safe_extract(archive, unpacked)
        candidates = [p for p in unpacked.rglob(name) if p.is_file()]
        if len(candidates) != 1:
            raise RuntimeError(f"Exécutable {name} absent ou ambigu.")
        binary = Path(stage) / "bin" / name
        binary.parent.mkdir(exist_ok=True)
        shutil.copy2(candidates[0], binary)
        binary.chmod(0o700)
        for path in unpacked.rglob("*"):
            if path.is_file() and path.name.lower().startswith(("license", "copying", "copyright", "notice")):
                notice = Path(stage) / "notices" / name / path.relative_to(unpacked)
                notice.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, notice)
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(unpacked, ignore_errors=True)


def install_binaries(stage, arch):
    records = []
    build = FFMPEG_BUILDS[arch]
    base = "https://ffmpeg.martin-riedl.de/download/macos/" + build["path"]
    for name in ("ffmpeg", "ffprobe"):
        url = f"{base}/{name}.zip"
        digest = build[name]
        install_archive(url, digest, stage, name)
        records.append({"name": name, "version": "9.0.2", "url": url, "sha256": digest})
    release = fetch_json("https://api.github.com/repos/denoland/deno/releases/latest")
    asset_name = f"deno-{arch}-apple-darwin.zip"
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    digest = str((asset or {}).get("digest") or "")
    expected_prefix = "https://github.com/denoland/deno/releases/download/"
    size = int((asset or {}).get("size") or 0)
    if (not asset or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or not str(asset.get("browser_download_url", "")).startswith(expected_prefix)
            or not 0 < size <= 350 * 1024 * 1024):
        raise RuntimeError("Release Deno ou SHA-256 GitHub invalide.")
    install_archive(asset["browser_download_url"], digest[7:], stage, "deno", size)
    records.append({"name": "deno", "version": release["tag_name"],
                    "url": asset["browser_download_url"], "sha256": digest[7:]})
    atomic_json(Path(stage) / "binary-dependencies.json", records)
    for name in ("ffmpeg", "ffprobe", "deno"):
        command = [str(Path(stage) / "bin" / name), "--version" if name == "deno" else "-version"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        if result.returncode:
            raise RuntimeError(f"Exécutable {name} invalide : " + result.stderr.decode("utf-8", "replace")[-1000:])


def launcher_content(version_dir, command="host.py"):
    version_dir = Path(version_dir)
    executable = version_dir / "runtime/bin/python3"
    script = version_dir / "backend" / command
    # An absolute executable and private bin path work with Finder's small PATH.
    return ("#!/bin/sh\n"
            f"PATH={shlex.quote(str(version_dir / 'bin'))}:/usr/bin:/bin:/usr/sbin:/sbin\n"
            "export PATH\n"
            f"exec {shlex.quote(str(executable))} -I -u -B {shlex.quote(str(script))}"
            + (" uninstall" if command == "macos_install.py" else "") + "\n").encode("utf-8")


def manifest_owned(path, root):
    if not Path(path).exists():
        return
    check_private_path(path)
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("name") != HOST_NAME or manifest.get("path") != str(Path(root) / "native-host.sh"):
        raise RuntimeError("Le manifeste Firefox appartient à une autre installation Kitty.")


def commit_install(root, stage, version, *, manifest_path=None, validate=None):
    root, stage = check_private_path(root), check_private_path(stage)
    manifest_path = check_private_path(manifest_path or native_manifest_path())
    manifest_owned(manifest_path, root)
    version_dir = root / "versions" / f"{version}-{uuid.uuid4().hex}"
    check_private_path(version_dir.parent)
    version_dir.parent.mkdir(exist_ok=True)
    files = [root / name for name in ("native-host.sh", "Uninstall.command", "current.json")]
    files.append(manifest_path)
    saved = {path: path.read_bytes() if path.exists() else None for path in files}
    extension = root / "extension"
    check_private_path(extension)
    old_extension = root / ("extension-backup-" + uuid.uuid4().hex)
    moved_extension = False
    published_extension = False
    os.replace(stage, version_dir)
    try:
        if validate:
            validate(version_dir)
        if extension.exists():
            os.replace(extension, old_extension)
            moved_extension = True
        published_extension = True
        shutil.copytree(version_dir / "extension", extension)
        atomic_bytes(root / "native-host.sh", launcher_content(version_dir))
        (root / "native-host.sh").chmod(0o700)
        atomic_bytes(root / "Uninstall.command", launcher_content(version_dir, "macos_install.py"))
        (root / "Uninstall.command").chmod(0o700)
        manifest = {"name": HOST_NAME, "description": "Kitty Download Manager macOS",
                    "path": str(root / "native-host.sh"), "type": "stdio", "allowed_extensions": [EXTENSION_ID]}
        atomic_json(manifest_path, manifest)
        manifest_path.chmod(0o600)
        atomic_json(root / "current.json", {"app": "KittyDownloadManager", "version": version,
                                           "directory": version_dir.relative_to(root).as_posix(),
                                           "installed_at": time.time(), "platform": "macos"})
    except BaseException:
        if published_extension:
            shutil.rmtree(extension, ignore_errors=True)
        if moved_extension:
            os.replace(old_extension, extension)
        for path, data in saved.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_bytes(path, data)
                path.chmod(0o700 if path.suffix in (".sh", ".command") else 0o600)
        shutil.rmtree(version_dir, ignore_errors=True)
        raise
    shutil.rmtree(old_extension, ignore_errors=True)
    return version_dir


def prune_versions(root, keep):
    """Bound old runtimes, retaining versions still used by a Kitty process."""
    import psutil
    paths = []
    for proc in psutil.process_iter(["cmdline"]):
        try:
            paths.extend(proc.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for directory in (Path(root) / "versions").iterdir():
        if (directory.name in keep or not re.fullmatch(r"[0-9.]+-[0-9a-f]{32}", directory.name)
                or directory.is_symlink()):
            continue
        if any(str(arg).startswith(str(directory) + os.sep) for arg in paths):
            continue
        shutil.rmtree(directory, ignore_errors=True)


def install(args):
    root = check_private_path(macos_root())
    stage = check_private_path(Path(args.stage).absolute())
    source = Path(args.source).resolve()
    if stage.parent != root or not re.fullmatch(r"stage-[A-Za-z0-9]+", stage.name):
        raise RuntimeError("Dossier de préparation inattendu.")
    manifest = json.loads((source / "extension/manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise RuntimeError("Version Kitty invalide.")
    backend = stage / "backend"
    backend.mkdir()
    for filename in BACKEND_FILES:
        origin = source / "native-host" / filename
        compile(origin.read_text(encoding="utf-8"), str(origin), "exec")
        shutil.copy2(origin, backend / filename)
    shutil.copytree(source / "extension", stage / "extension")
    shutil.copy2(source / "THIRD-PARTY-NOTICES.md", stage / "THIRD-PARTY-NOTICES.md")
    if not args.no_dependencies:
        print("Préparation de FFmpeg et Deno…", flush=True)
        install_binaries(stage, args.arch)
    def validate_runtime(path, full=True):
        python = path / "runtime/bin/python3"
        result = subprocess.run([str(python), "-I", "-B", "-c", "import yt_dlp, mutagen, psutil, ssl"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if result.returncode:
            raise RuntimeError("Dépendances Python privées invalides : " + result.stderr.decode("utf-8", "replace")[-1000:])
        native_query(python, path / "backend", "get_settings")
        response = native_query(python, path / "backend", "compatibility")
        if response.get("compatibility", {}).get("backend_version") != version:
            raise RuntimeError("Versions du backend et de l’extension différentes.")
        if full:
            # Diagnostics repair state outside maintenance; run only once the
            # queue is frozen, so an upgrade never starts a preparation worker.
            diagnostics = native_query(python, path / "backend", "diagnostics")
            if diagnostics.get("dependencies", {}).get("required_ok") is not True:
                raise RuntimeError("Dépendances privées indisponibles : " + str(diagnostics.get("dependencies")))
    print("Vérification du protocole Firefox…", flush=True)
    validate_runtime(stage, full=False)
    with queue_lock(root / "install.lock"):
        previous = current_install(root)
        if previous and tuple(map(int, previous["version"].split('.'))) > tuple(map(int, version.split('.'))):
            raise RuntimeError("Retour à une version plus ancienne refusé.")
        with paused_maintenance(root, previous):
            installed = commit_install(root, stage, version, validate=validate_runtime)
        keep = {installed.name}
        if previous:
            keep.add(checked_version_path(root, previous).name)
        prune_versions(root, keep)
    print("Kitty installé. Réglages, historique et téléchargements conservés; file en pause.", flush=True)


def uninstall():
    root = check_private_path(macos_root())
    with queue_lock(root / "install.lock"):
        previous = current_install(root)
        if previous is None:
            raise RuntimeError("Aucune installation Kitty reconnue.")
        manifest_path = check_private_path(native_manifest_path())
        manifest_owned(manifest_path, root)
        with paused_maintenance(root, previous):
            manifest_path.unlink(missing_ok=True)
            for name in ("current.json", "native-host.sh", "Uninstall.command"):
                check_private_path(root / name).unlink(missing_ok=True)
            for name in ("extension", "versions"):
                directory = check_private_path(root / name)
                if directory.exists():
                    shutil.rmtree(directory)
    print("Kitty désinstallé. Réglages, historique et téléchargements conservés.")


def main():
    if sys.platform != "darwin":
        raise RuntimeError("Cet installateur est réservé à macOS.")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("install")
    setup.add_argument("--source", required=True)
    setup.add_argument("--stage", required=True)
    setup.add_argument("--arch", choices=("aarch64", "x86_64"), required=True)
    setup.add_argument("--no-dependencies", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("uninstall")
    args = parser.parse_args()
    install(args) if args.command == "install" else uninstall()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERREUR : " + str(exc), file=sys.stderr)
        if os.environ.get("KITTY_INSTALL_TRACEBACK") == "1":
            import traceback
            traceback.print_exc()
        sys.exit(1)
