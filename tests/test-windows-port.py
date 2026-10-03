#!/usr/bin/env python3
"""Portable fault tests plus real Windows-only process/locking tests.

python tests/test-windows-port.py
No network request is made by this suite.
"""
import base64
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

NATIVE = Path(__file__).resolve().parents[1] / "native-host"
sys.path.insert(0, str(NATIVE))
import platform_support as platform_api
import queue_store
import windows_install as installer
import app_paths


def increment_process(path, lock):
    for _ in range(25):
        queue_store.mutate_state(path, lock, lambda data: data.update(counter=data.get("counter", 0) + 1))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kitty-windows-port-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Kitty Français & 100% !"
        self.root.mkdir()

    def stage(self):
        stage = self.root / ("stage-" + "a" * 32)
        (stage / "extension").mkdir(parents=True)
        (stage / "extension/manifest.json").write_text('{"version":"8.26"}', encoding="utf-8")
        return stage

    def old_install(self):
        for name in ("native-host.bat", "Uninstall.cmd", "current.json", f"{installer.HOST_NAME}.json"):
            (self.root / name).write_bytes(("ancien:" + name).encode())
        (self.root / "extension").mkdir()
        (self.root / "extension/manifest.json").write_text("ancien", encoding="utf-8")
        for name in ("config/settings.json", "cache/queue.json", "download/video.mp4"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"conserver")

    def test_publish_uses_stable_manifest_and_private_runtime(self):
        version = installer.commit_install(self.root, self.stage(), "8.26", register_host=False)
        manifest = json.loads((self.root / f"{installer.HOST_NAME}.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["allowed_extensions"], ["kitty-download-manager@local"])
        self.assertEqual(manifest["path"], str(self.root / "native-host.bat"))
        launch = (self.root / "native-host.bat").read_text(encoding="utf-8")
        self.assertIn("DisableDelayedExpansion", launch)
        self.assertIn("-I -u -B", launch)
        self.assertNotIn("%*", launch)
        self.assertIn(version.name, launch)
        self.assertNotIn(str(self.root), launch)
        self.assertEqual(installer.checked_version_path(self.root, installer.current_install(self.root)), version)

    def test_registry_failure_rolls_back_every_published_file(self):
        self.old_install()
        originals = {name: (self.root / name).read_bytes() for name in
                     ("native-host.bat", "Uninstall.cmd", "current.json", f"{installer.HOST_NAME}.json")}
        with patch.object(installer, "snapshot_registry", return_value=["snapshot"]), \
             patch.object(installer, "register", side_effect=OSError("registre inaccessible")), \
             patch.object(installer, "restore_registry") as restore:
            with self.assertRaises(OSError):
                installer.commit_install(self.root, self.stage(), "8.26")
            restore.assert_called_once_with(["snapshot"])
        for name, content in originals.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertEqual((self.root / "extension/manifest.json").read_text(), "ancien")
        for name in ("config/settings.json", "cache/queue.json", "download/video.mp4"):
            self.assertEqual((self.root / name).read_bytes(), b"conserver")

    def test_validation_after_move_fails_without_replacing_old_install(self):
        self.old_install()
        with self.assertRaises(RuntimeError):
            installer.commit_install(self.root, self.stage(), "8.26", register_host=False,
                                     validate=lambda _path: (_ for _ in ()).throw(RuntimeError("backend casse")))
        self.assertEqual((self.root / "extension/manifest.json").read_text(), "ancien")
        self.assertEqual((self.root / "current.json").read_bytes(), b"ancien:current.json")

    def test_partial_extension_copy_is_removed_on_failed_first_install(self):
        stage = self.stage()
        def broken_copy(source, destination):
            Path(destination).mkdir()
            (Path(destination) / "partial.txt").write_text("partiel")
            raise OSError("disque plein")
        with patch.object(installer.shutil, "copytree", side_effect=broken_copy):
            with self.assertRaises(OSError):
                installer.commit_install(self.root, stage, "8.26", register_host=False)
        self.assertFalse((self.root / "extension").exists())
        self.assertFalse((self.root / "current.json").exists())

    def test_paths_in_metadata_cannot_escape_runtime_versions(self):
        for path in ("../other", "versions/../other", "C:/Users/else", "versions/8.26", "versions/8.26-" + "x" * 32):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                installer.checked_version_path(self.root, {"directory": path})

    def test_zip_unicode_and_spaces_round_trip(self):
        archive = self.root / "good.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("dossier/épisode 1.txt", "test ✓")
        installer.safe_extract(archive, self.root / "output")
        self.assertEqual((self.root / "output/dossier/épisode 1.txt").read_text(encoding="utf-8"), "test ✓")

    def test_zip_rejects_all_entries_before_extracting(self):
        for path in ("../outside", "/absolute", "C:/absolute", "a\\..\\outside", "a:stream", "trailing. /file", "trailing./file"):
            with self.subTest(path=path):
                archive = self.root / "bad.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("first.txt", "must not extract")
                    z.writestr(path, "danger")
                with self.assertRaises(RuntimeError):
                    installer.safe_extract(archive, self.root / "output")
                self.assertFalse((self.root / "output/first.txt").exists())

    def test_zip_rejects_symlinks(self):
        archive = self.root / "bad.zip"
        entry = zipfile.ZipInfo("link")
        entry.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(entry, "../outside")
        with self.assertRaises(RuntimeError):
            installer.safe_extract(archive, self.root / "output")

    def download(self, payload, digest, size):
        with patch.object(installer, "urlopen", return_value=io.BytesIO(payload)):
            return installer.verified_download("https://example.com/file", self.root / "download.zip", digest, size)

    def test_download_verifies_size_and_sha256(self):
        payload = b"archive complete"
        self.assertEqual(self.download(payload, hashlib.sha256(payload).hexdigest(), len(payload)).read_bytes(), payload)

    def test_bad_hash_is_removed(self):
        with self.assertRaises(RuntimeError):
            self.download(b"mauvais", "0" * 64, 7)
        self.assertFalse((self.root / "download.zip").exists())

    def test_truncated_or_oversized_download_is_removed(self):
        for expected in (1, 100):
            with self.subTest(size=expected), self.assertRaises(RuntimeError):
                self.download(b"archive", hashlib.sha256(b"archive").hexdigest(), expected)
            self.assertFalse((self.root / "download.zip").exists())

    def test_insecure_url_is_rejected_before_network(self):
        with patch.object(installer, "urlopen", side_effect=AssertionError("reseau")):
            with self.assertRaises(RuntimeError):
                installer.verified_download("http://example.com/file", self.root / "download.zip", "0" * 64)

    def test_windows_spawn_breaks_away_without_unix_session(self):
        with patch.object(platform_api, "WINDOWS", True), \
             patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             patch.object(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, create=True):
            self.assertEqual(platform_api.spawn_options(), {"creationflags": 0x09000000})
            self.assertEqual(platform_api.spawn_options(persistent=False), {"creationflags": 0x08000000})

    def test_windows_alive_never_uses_os_kill(self):
        fake = SimpleNamespace(pid_exists=lambda pid: pid == 123,
                               Process=lambda pid: SimpleNamespace(is_running=lambda: True))
        with patch.object(platform_api, "WINDOWS", True), patch.dict(sys.modules, {"psutil": fake}), \
             patch.object(os, "kill", side_effect=AssertionError("os.kill sous Windows")):
            self.assertTrue(platform_api.process_alive(123))
            self.assertFalse(platform_api.process_alive(124))

    def test_process_identity_requires_exact_script_and_job(self):
        script = self.root / "worker.py"
        with patch.object(platform_api, "process_args", return_value=["python.exe", str(script), "job1"]):
            self.assertTrue(platform_api.script_process_matches(123, script, "job1"))
            self.assertFalse(platform_api.script_process_matches(123, script, "job2"))
            self.assertFalse(platform_api.script_process_matches(123, self.root / "other/worker.py", "job1"))

    def test_windows_lock_uses_same_byte_with_retry_and_unlock(self):
        calls = []
        def locking(fd, mode, count):
            calls.append((mode, count, os.lseek(fd, 0, os.SEEK_CUR)))
            if len(calls) == 1:
                raise PermissionError(13, "occupe")
        fake = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
        with (self.root / "lock").open("a+") as handle, patch.object(platform_api, "WINDOWS", True), \
             patch.dict(sys.modules, {"msvcrt": fake}), patch.object(time, "sleep"):
            platform_api.acquire_file_lock(handle)
            platform_api.release_file_lock(handle)
        self.assertEqual(calls, [(1, 1, 0), (1, 1, 0), (2, 1, 0)])

    def test_windows_lock_propagates_io_errors(self):
        def locking(*args):
            raise OSError(5, "I/O")
        fake = SimpleNamespace(LK_NBLCK=1, locking=locking)
        with (self.root / "lock").open("a+") as handle, patch.object(platform_api, "WINDOWS", True), \
             patch.dict(sys.modules, {"msvcrt": fake}), self.assertRaises(OSError):
            platform_api.acquire_file_lock(handle)

    def test_windows_folder_chooser_escapes_apostrophes_and_metacharacters(self):
        current = "C:\\Users\\O'Neil & 100% !\\Téléchargements"
        def fake_run(command, **kwargs):
            script = base64.b64decode(command[-1]).decode("utf-16-le")
            self.assertIn("'C:\\Users\\O''Neil & 100% !\\Téléchargements'", script)
            self.assertIn("-STA", command)
            return SimpleNamespace(returncode=0, stdout=current, stderr="")
        with patch.dict(os.environ, {"SystemRoot": "C:\\Windows"}), patch.object(platform_api, "run_hidden", side_effect=fake_run):
            self.assertEqual(platform_api.choose_windows_folder(current), current)

    def test_maintenance_marker_checks_process_creation_time(self):
        path = self.root / "maintenance.json"
        installer.atomic_json(path, {"pid": 123, "created": 10})
        fake = SimpleNamespace(Process=lambda pid: SimpleNamespace(is_running=lambda: True, create_time=lambda: 11))
        with patch.dict(sys.modules, {"psutil": fake}):
            self.assertFalse(platform_api.maintenance_active(path))
        fake.Process = lambda pid: SimpleNamespace(is_running=lambda: True, create_time=lambda: 10)
        with patch.dict(sys.modules, {"psutil": fake}):
            self.assertTrue(platform_api.maintenance_active(path))

    def test_real_concurrent_transactions_do_not_lose_updates(self):
        path, lock = self.root / "queue.json", self.root / "queue.lock"
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=increment_process, args=(path, lock)) for _ in range(4)]
        for proc in processes:
            proc.start()
        for proc in processes:
            proc.join(25)
            if proc.is_alive():
                proc.terminate()
            self.assertEqual(proc.exitcode, 0)
        self.assertEqual(queue_store.read_state(path, lock)["counter"], 100)

    def test_maintenance_pauses_without_removing_history_and_always_clears_marker(self):
        cache = self.root / "cache"
        cache.mkdir()
        state = queue_store.default_state()
        state["history"] = [{"id": "old", "status": "finished"}]
        state["queue"] = [{"id": "next", "status": "queued"}]
        queue_store.atomic_json(cache / "queue.json", state)
        fake = SimpleNamespace(Process=lambda *args: SimpleNamespace(create_time=lambda: 10))
        with patch.dict(sys.modules, {"psutil": fake}), self.assertRaises(RuntimeError):
            with installer.paused_maintenance(self.root, None):
                self.assertTrue((cache / "maintenance.json").exists())
                raise RuntimeError("echec pendant l’installation")
        self.assertFalse((cache / "maintenance.json").exists())
        after = queue_store.read_state(cache / "queue.json", cache / "queue.lock")
        self.assertEqual(after["queue"], state["queue"])
        self.assertEqual(after["history"], state["history"])
        self.assertTrue(after["queue_paused"])

    def test_maintenance_refuses_future_schema_without_rewriting_it(self):
        cache = self.root / "cache"
        cache.mkdir()
        original = b'{"state_version":999,"active":null,"queue":[],"history":[]}'
        (cache / "queue.json").write_bytes(original)
        fake = SimpleNamespace(Process=lambda *args: SimpleNamespace(create_time=lambda: 10))
        with patch.dict(sys.modules, {"psutil": fake}), self.assertRaises(queue_store.FutureStateVersion):
            with installer.paused_maintenance(self.root, None):
                self.fail("Une queue future a ete acceptee")
        self.assertEqual((cache / "queue.json").read_bytes(), original)
        self.assertFalse((cache / "maintenance.json").exists())

    def test_windows_names_fit_traditional_path_limit_and_case_collisions(self):
        old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        import worker
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        output = self.root / "sortie"
        output.mkdir()
        (output / "TITRE.opus").write_bytes(b"existant")
        with patch.object(worker, "WINDOWS", True):
            self.assertEqual(worker.choose_unique_output_stem(output, "titre"), "titre (2)")
            stem = worker.choose_unique_output_stem(output, "É" * 500)
            total = len(str(output.resolve() / stem).encode("utf-16-le")) // 2 + 40
            self.assertLessEqual(total, 259)
            with self.assertRaises(RuntimeError):
                worker.output_stem_budget(output / ("x" * 240))

    def test_windows_release_never_selects_linux_asset(self):
        spec = importlib.util.spec_from_file_location("windows_asset_test", NATIVE / "host.py")
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        version = "8.27"
        linux = {"name": f"kitty-download-manager-v{version}.zip", "digest": "sha256:" + "a" * 64,
                 "size": 10, "browser_download_url": "https://github.com/repo/releases/download/v8.27/file.zip"}
        windows = dict(linux, name=f"kitty-download-manager-v{version}-windows-x64.zip")
        payload = {"tag_name": "v" + version, "assets": [linux, windows]}
        with patch.object(host, "WINDOWS", True), patch.object(host, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            self.assertEqual(host.check_kitty_release(save_cache=False)["asset_name"], windows["name"])
        payload["assets"] = [linux]
        with patch.object(host, "WINDOWS", True), patch.object(host, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            self.assertFalse(host.check_kitty_release(save_cache=False)["download_supported"])


class SimulatedControlTests(unittest.TestCase):
    """Run the actual Python control watcher, without pretending to run Win32."""
    def control_worker(self, action):
        with tempfile.TemporaryDirectory(prefix="kitty-control-simulation-") as tmp:
            home = Path(tmp)
            cache = home / ".cache/kitty-download-manager"
            cache.mkdir(parents=True)
            output = home / "output"
            output.mkdir()
            partial = output / "media.opus.part"
            partial.write_bytes(b"partiel")
            state = queue_store.default_state()
            state["queue_paused"] = True
            state["active"] = {"id": "simulated-job", "status": "starting", "url": "https://example.com/offline", "mode": "audio",
                               "output_dir": str(output), "output_stem": str(output / "media")}
            queue_store.atomic_json(cache / "queue.json", state)
            env = os.environ.copy()
            env["HOME"] = str(home)
            code = '''import sys, types, time
sys.path.insert(0, sys.argv[1])
import worker, platform_support as api
api.terminate_own_children=lambda: None
worker.WINDOWS=True
worker.configure_worker_job=lambda: None
def watch(action_reader):
 previous=api.WINDOWS
 api.WINDOWS=True
 try: return api.watch_worker_controls(action_reader)
 finally: api.WINDOWS=previous
worker.watch_worker_controls=watch
class YDL:
 def __init__(self, options): pass
 def __enter__(self): return self
 def __exit__(self, *args): pass
 def extract_info(self, *args, **kwargs):
  while True: time.sleep(.05)
sys.modules['yt_dlp']=types.SimpleNamespace(YoutubeDL=YDL)
sys.argv=[str(worker.WORKER),sys.argv[2]]
raise SystemExit(worker.main())
'''
            # The app_paths layout stays POSIX. Only the Python-level Windows
            # IPC watcher is simulated; Win32 job objects have separate tests.
            if sys.platform == "win32":
                self.skipTest("Simulation POSIX; les vrais tests Windows couvrent ce chemin")
            proc = subprocess.Popen([sys.executable, "-c", code, str(NATIVE), "simulated-job"], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    active = queue_store.read_state(cache / "queue.json", cache / "queue.lock").get("active")
                    if active and active.get("worker_pid") == proc.pid:
                        break
                    if proc.poll() is not None:
                        self.fail(proc.communicate()[1].decode("utf-8", "replace"))
                    time.sleep(.05)
                else:
                    self.fail("Simulation non demarree")
                installer.atomic_json(cache / "controls/simulated-job.json", {"action": action})
                _, error = proc.communicate(timeout=10)
                self.assertEqual(proc.returncode, 0 if action == "cancel" else 128 + int(signal.SIGTERM), error)
                state = queue_store.read_state(cache / "queue.json", cache / "queue.lock")
                self.assertIsNone(state["active"])
                if action == "cancel":
                    self.assertEqual(state["history"][0]["status"], "cancelled")
                    self.assertFalse(partial.exists())
                else:
                    self.assertEqual(state["queue"][0]["id"], "simulated-job")
                    self.assertTrue(state["queue_paused"])
                    self.assertTrue(partial.exists())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_cooperative_cancel_unwinds_real_worker_and_cleans_partial(self):
        self.control_worker("cancel")

    def test_cooperative_stop_unwinds_real_worker_and_preserves_partial(self):
        self.control_worker("stop")


@unittest.skipUnless(sys.platform == "win32", "Exige un vrai Windows et psutil")
class WindowsProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A hosted runner may put Python in a Job that denies breakaway. Give
        # this test parent a nested Job that allows it, like Firefox's native
        # host context. Workers still use the actual production spawn flags;
        # the runner's outer Job continues to own the complete test tree.
        platform_api.configure_worker_job()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kitty-native-windows-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env["LOCALAPPDATA"] = str(self.base)
        self.cache = self.base / "KittyDownloadManager/cache"
        self.cache.mkdir(parents=True)

    def seed(self, job_id="test-job"):
        output = self.base / "sortie française & 100% !"
        output.mkdir()
        state = queue_store.default_state()
        state["active"] = {"id": job_id, "url": "https://example.com/test", "mode": "audio", "status": "starting", "output_dir": str(output)}
        queue_store.atomic_json(self.cache / "queue.json", state)
        return output

    def fake_ytdlp(self):
        fake = self.base / "fake"
        fake.mkdir()
        (fake / "yt_dlp.py").write_text('''import time
class YoutubeDL:
 def __init__(self, opts): self.opts=opts
 def __enter__(self): return self
 def __exit__(self, *args): pass
 def extract_info(self, url, download=False):
  while True: time.sleep(.05)
''', encoding="utf-8")
        self.env["PYTHONPATH"] = str(fake)

    def worker(self):
        self.fake_ytdlp()
        proc = subprocess.Popen([sys.executable, str(NATIVE / "worker.py"), "test-job"], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **platform_api.spawn_options())
        def cleanup_worker():
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=10)
        self.addCleanup(cleanup_worker)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            active = queue_store.read_state(self.cache / "queue.json", self.cache / "queue.lock").get("active")
            if active and active.get("worker_pid") == proc.pid:
                return proc
            if proc.poll() is not None:
                self.fail(proc.communicate()[1].decode("utf-8", "replace"))
            time.sleep(.05)
        self.fail("Worker non demarre")

    def test_native_protocol_uses_binary_utf8_on_real_windows(self):
        payload = json.dumps({"action": "get_settings"}).encode()
        result = subprocess.run([sys.executable, "-u", str(NATIVE / "host.py")], env=self.env,
                                input=struct.pack("<I", len(payload)) + payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        size = struct.unpack("<I", result.stdout[:4])[0]
        self.assertEqual(size, len(result.stdout) - 4)
        self.assertTrue(json.loads(result.stdout[4:])["ok"])

    def test_real_windows_cancel_runs_cleanup_and_does_not_signal_linux_style(self):
        output = self.seed()
        partial = output / "video.opus.part"
        partial.write_bytes(b"partiel")
        queue_store.mutate_state(self.cache / "queue.json", self.cache / "queue.lock", lambda d: d["active"].update(output_stem=str(output / "video")))
        proc = self.worker()
        installer.atomic_json(self.cache / "controls/test-job.json", {"action": "cancel"})
        _, error = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 0, error.decode("utf-8", "replace"))
        state = queue_store.read_state(self.cache / "queue.json", self.cache / "queue.lock")
        self.assertIsNone(state["active"])
        self.assertEqual(state["history"][0]["status"], "cancelled")
        self.assertFalse(partial.exists())

    def test_real_windows_stop_preserves_partial_and_requeues_job(self):
        output = self.seed()
        partial = output / "video.opus.part"
        partial.write_bytes(b"partiel")
        proc = self.worker()
        installer.atomic_json(self.cache / "controls/test-job.json", {"action": "stop"})
        _, error = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 128 + int(signal.SIGTERM), error.decode("utf-8", "replace"))
        state = queue_store.read_state(self.cache / "queue.json", self.cache / "queue.lock")
        self.assertTrue(state["queue_paused"])
        self.assertIsNone(state["active"])
        self.assertEqual(state["queue"][0]["id"], "test-job")
        self.assertTrue(partial.exists())
        self.assertEqual(state["history"], [])

    def test_windows_survival_after_parent_job_closes(self):
        output = self.seed()
        self.fake_ytdlp()
        helper = self.base / "job_parent.py"
        helper.write_text('''import subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from platform_support import configure_worker_job, spawn_options
configure_worker_job()
p=subprocess.Popen([sys.executable, sys.argv[1]+"/worker.py", "test-job"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **spawn_options())
print(p.pid, flush=True)
time.sleep(1)
''', encoding="utf-8")
        result = subprocess.run([sys.executable, str(helper), str(NATIVE)], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        pid = int(result.stdout.strip())
        import psutil
        self.addCleanup(lambda: psutil.Process(pid).kill() if psutil.pid_exists(pid) else None)
        self.assertTrue(platform_api.process_alive(pid), "Le worker a ete tue avec le job du parent")
        installer.atomic_json(self.cache / "controls/test-job.json", {"action": "stop"})
        psutil.Process(pid).wait(timeout=15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
