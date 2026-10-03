"""Shared private-runtime installation primitives for Windows and macOS."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request
from platform_support import open_url as urlopen
import uuid
import zipfile
APP_ID = "KittyDownloadManager"
MAX_DOWNLOAD = 350 * 1024 * 1024

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
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; KittyDownloadManager/8.30)"})
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
            backup_state_file(queue, cache / "state-backups", "runtime-install")
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
            if sys.platform == "darwin":
                os.kill(int(active["worker_pid"]), signal.SIGTERM)
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
