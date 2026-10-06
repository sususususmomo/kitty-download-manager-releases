"""OS services used by the backend; Windows never uses os.kill(pid, 0)."""
from __future__ import annotations

import base64
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
_worker_job_handle = None


class ProcessSupportError(RuntimeError):
    code = "process_support_invalid"


class ProcessAccessError(RuntimeError):
    code = "process_access_denied"


def require_psutil(*names):
    """Never mistake an invalid process library for a dead worker/browser."""
    try:
        import psutil
        missing = [name for name in names if not callable(getattr(psutil, name, None))]
        if missing:
            raise AttributeError("API absente : " + ", ".join(missing))
        return psutil
    except (ImportError, AttributeError) as exc:
        raise ProcessSupportError(f"Support des processus psutil invalide : {exc}. Réinstalle le backend Kitty.") from exc


def replace_file(source, destination):
    """Retry transient Windows sharing conflicts without deleting the old file."""
    for attempt in range(8):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if not WINDOWS or getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 7:
                raise
            time.sleep(0.02 * (attempt + 1))


def open_url(request, **kwargs):
    from urllib.request import urlopen
    if MACOS and "context" not in kwargs:
        # The private CPython/OpenSSL does not use Apple's Keychain directly.
        # yt-dlp[default] installs certifi alongside the private runtime.
        import ssl
        import certifi
        kwargs["context"] = ssl.create_default_context(cafile=certifi.where())
    return urlopen(request, **kwargs)


def acquire_file_lock(handle):
    if not WINDOWS:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    import msvcrt
    # Windows can lock beyond EOF. Writing an initial byte before acquiring
    # the lock races with another handle that has already locked byte zero.
    while True:
        os.lseek(handle.fileno(), 0, os.SEEK_SET)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            time.sleep(0.05)


def release_file_lock(handle):
    if WINDOWS:
        import msvcrt
        os.lseek(handle.fileno(), 0, os.SEEK_SET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def process_alive(pid):
    psutil = require_psutil("pid_exists", "Process", "NoSuchProcess", "AccessDenied") if WINDOWS or MACOS else None
    if psutil is not None:
        try:
            pid = int(pid)
            if pid <= 1:
                return False
            if WINDOWS:
                return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (ValueError, TypeError, psutil.NoSuchProcess):
            return False
        except psutil.AccessDenied as exc:
            raise ProcessAccessError("Kitty ne peut pas vérifier ce processus : accès refusé par le système.") from exc
        except Exception as exc:
            raise ProcessSupportError(f"Support des processus psutil invalide : {exc}. Réinstalle le backend Kitty.") from exc
    try:
        pid = int(pid)
        if pid <= 1:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError):
        return False
    except Exception:
        return False


def process_args(pid):
    psutil = require_psutil("Process", "NoSuchProcess", "AccessDenied") if WINDOWS or MACOS else None
    if psutil is not None:
        try:
            return psutil.Process(int(pid)).cmdline()
        except (ValueError, TypeError, psutil.NoSuchProcess):
            return []
        except psutil.AccessDenied as exc:
            raise ProcessAccessError("Kitty ne peut pas vérifier l'identité de ce processus : accès refusé par le système.") from exc
        except Exception as exc:
            raise ProcessSupportError(f"Support des processus psutil invalide : {exc}. Réinstalle le backend Kitty.") from exc
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        return [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
    except Exception:
        return []


def same_path(left, right):
    if MACOS:
        try:
            return os.path.samefile(left, right)
        except OSError:
            pass
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def script_process_matches(pid, script, job_id=None):
    args = process_args(pid)
    return bool(args and any(same_path(arg, script) for arg in args)
                and (job_id is None or str(job_id) in args))


def spawn_options(*, persistent=True):
    if not WINDOWS:
        return {"start_new_session": True}
    # Firefox kills its Native Messaging job on disconnect. Workers and the
    # disposable Firefox session must explicitly escape that job.
    flags = subprocess.CREATE_NO_WINDOW
    if persistent:
        flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
    return {"creationflags": flags}


def run_hidden(command, **kwargs):
    if WINDOWS:
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        if kwargs.get("text"):
            kwargs.setdefault("encoding", "utf-8")
            kwargs.setdefault("errors", "replace")
    return subprocess.run(command, **kwargs)


def windows_downloads_dir():
    """Use FOLDERID_Downloads, including relocated/OneDrive Downloads."""
    import ctypes
    from ctypes import wintypes
    import uuid
    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]
    guid = GUID((ctypes.c_ubyte * 16).from_buffer_copy(
        uuid.UUID("374de290-123f-4565-9164-39c4925e467b").bytes_le))
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32")
    shell.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                         wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.c_void_p()
    result = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0x4000, None, ctypes.byref(pointer))  # DONT_VERIFY
    if result != 0:
        raise OSError(f"SHGetKnownFolderPath: {result}")
    try:
        return Path(ctypes.wstring_at(pointer.value))
    finally:
        ole.CoTaskMemFree(pointer)


def find_firefox():
    if MACOS:
        for base in (Path("/Applications"), Path.home() / "Applications"):
            for name in ("Firefox.app", "Firefox Developer Edition.app", "Firefox Nightly.app"):
                candidate = base / name / "Contents/MacOS/firefox"
                if candidate.is_file():
                    return str(candidate)
    for name in ("firefox", "firefox-esr", "firefox-bin"):
        found = shutil.which(name)
        if found:
            return found
    if WINDOWS:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe", 0,
                                        winreg.KEY_READ | view) as key:
                        candidate = Path(winreg.QueryValueEx(key, "")[0])
                    if candidate.is_file():
                        return str(candidate)
                except OSError:
                    pass
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_name)
            if not base:
                continue
            for suffix in ("Mozilla Firefox/firefox.exe", "Programs/Mozilla Firefox/firefox.exe"):
                candidate = Path(base) / suffix
                if candidate.is_file():
                    return str(candidate)
    return None


def firefox_uses_profile(profile):
    if not (WINDOWS or MACOS):
        return False
    psutil = require_psutil("process_iter", "NoSuchProcess", "AccessDenied")
    unknown = False
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if str(proc.info["name"] or "").lower() not in ("firefox.exe", "firefox", "firefox-bin"):
                continue
            args = proc.info["cmdline"]
            if args is None:
                unknown = True
                continue
            for i, arg in enumerate(args[:-1]):
                if arg.lower() in ("-profile", "--profile") and same_path(args[i + 1], profile):
                    return True
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            unknown = True
    if unknown:
        raise ProcessAccessError("Impossible de vérifier la fermeture de Firefox : accès aux processus refusé. Ferme la fenêtre dédiée puis réessaie.")
    return False


def choose_macos_folder(current):
    # Arguments are data, never interpolated into AppleScript source.
    script = '''on run argv
try
 set chosen to choose folder with prompt "Kitty Download Manager — dossier de destination" default location (POSIX file (item 1 of argv))
 return POSIX path of chosen
on error number -128
 return ""
end try
end run'''
    result = run_hidden(["/usr/bin/osascript", "-e", script, str(current)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Sélecteur macOS indisponible.")
    return result.stdout.rstrip("\r\n")


def open_macos_path(path):
    result = run_hidden(["/usr/bin/open", str(path)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Ouverture macOS impossible.")


def choose_windows_folder(current):
    # The path is serialized as JSON inside an encoded script, never shell code.
    script = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog=New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description='Kitty Download Manager — dossier de destination'
$dialog.SelectedPath=__PATH__
try { if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
 [Console]::Write($dialog.SelectedPath)
} } finally { $dialog.Dispose() }
"""
    # PowerShell single-quoted literals escape only the apostrophe.
    literal = "'" + str(current).replace("'", "''") + "'"
    encoded = base64.b64encode(script.replace("__PATH__", literal).encode("utf-16-le")).decode("ascii")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = run_hidden([str(executable), "-NoProfile", "-STA", "-EncodedCommand", encoded],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Sélecteur Windows indisponible.")
    return result.stdout.strip()


def configure_worker_job():
    """Keep FFmpeg/Deno children owned; terminate them if their worker dies."""
    global _worker_job_handle
    if not WINDOWS or _worker_job_handle is not None:
        return
    import ctypes
    from ctypes import wintypes
    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x0800  # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(handle)
        raise error
    # Do not close early: Windows would terminate this worker too.
    _worker_job_handle = handle


def terminate_own_children():
    psutil = require_psutil("Process", "wait_procs", "NoSuchProcess", "AccessDenied")
    # A successor worker can already have been launched. Never terminate Python
    # children; only the external tools belonging to this runtime are stopped.
    bin_dir = (Path(__file__).resolve().parent.parent / "bin" if MACOS else
               Path(sys.executable).resolve().parent.parent / "bin")
    children = []
    for child in psutil.Process().children(recursive=True):
        try:
            executable = Path(child.exe())
            if executable.name.lower() in ("ffmpeg.exe", "ffprobe.exe", "deno.exe", "ffmpeg", "ffprobe", "deno") and same_path(executable.parent, bin_dir):
                children.append(child)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    for child in reversed(children):
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, remaining = psutil.wait_procs(children, timeout=2)
    for child in remaining:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.wait_procs(remaining, timeout=2)


def watch_worker_controls(action_reader):
    """Cooperative IPC + Python signal handler, instead of Windows SIGTERM."""
    if not WINDOWS:
        return None
    import _thread
    import signal
    import threading
    done = threading.Event()
    def watch():
        while not done.wait(0.1):
            if action_reader() not in ("cancel", "stop"):
                continue
            try:
                terminate_own_children()
            finally:
                if not done.is_set() and action_reader() in ("cancel", "stop"):
                    _thread.interrupt_main(signal.SIGTERM)
            return
    threading.Thread(target=watch, daemon=True, name="kitty-control").start()
    return done


def maintenance_active(path):
    """A stale installer marker never blocks downloads after a crashed setup."""
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        import psutil
        proc = psutil.Process(int(data["pid"]))
        return proc.is_running() and abs(proc.create_time() - float(data["created"])) < 0.001
    except FileNotFoundError:
        return False
    except Exception:
        return False


def metadata_deadline(seconds=30):
    if not WINDOWS:
        return None
    import _thread
    import signal
    import threading
    done = threading.Event()
    def expire():
        if not done.wait(seconds):
            try:
                terminate_own_children()
            finally:
                if not done.is_set():
                    _thread.interrupt_main(signal.SIGINT)
    threading.Thread(target=expire, daemon=True, name="kitty-metadata-deadline").start()
    return done
