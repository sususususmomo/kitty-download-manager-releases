"""Destructive CI-only tests for a fresh macOS installation, no media network."""
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "native-host"))
import app_paths
import installer_support
import platform_support
import queue_store


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("KITTY_MACOS_INSTALLED_TEST") == "1"
                     and os.environ.get("GITHUB_ACTIONS") == "true", "Exige une installation macOS CI neuve")
class InstalledMacTests(unittest.TestCase):
    def current(self):
        root = app_paths.macos_root()
        return root, installer_support.checked_version_path(root, installer_support.current_install(root))

    def query(self, action):
        payload = json.dumps({"action": action}, ensure_ascii=False).encode("utf-8")
        proc = subprocess.run([str(app_paths.macos_root() / "native-host.sh")],
                              input=struct.pack("<I", len(payload)) + payload, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env={**os.environ, "PATH": "/usr/bin:/bin"}, timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(len(proc.stdout), 4, proc.stderr)
        self.assertEqual(struct.unpack("<I", proc.stdout[:4])[0], len(proc.stdout) - 4)
        response = json.loads(proc.stdout[4:])
        self.assertTrue(response.get("ok"), response)
        return response

    def test_01_private_launcher_native_registration_and_dependencies(self):
        root, current = self.current()
        self.query("get_settings")
        diagnostics = self.query("diagnostics")
        self.assertEqual(diagnostics["dependencies"]["required_missing"], [])
        self.assertTrue(diagnostics["system"]["runtime_files"]["ok"])
        manifest = json.loads(app_paths.native_manifest_path().read_text())
        self.assertEqual(manifest["path"], str(root / "native-host.sh"))
        self.assertEqual(manifest["allowed_extensions"], [app_paths.FIREFOX_EXTENSION_ID])
        self.assertEqual((root.stat().st_mode & 0o777), 0o700)
        self.assertEqual((app_paths.native_manifest_path().stat().st_mode & 0o777), 0o600)
        result = subprocess.run([str(current / "runtime/bin/python3"), "-I", "-c", "import platform; print(platform.machine())"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        arm = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], stdout=subprocess.PIPE).stdout.strip() == b"1"
        self.assertEqual(result.stdout.strip(), b"arm64" if arm else b"x86_64")

    def test_02_upgrade_preserves_settings_and_history(self):
        root, current = self.current()
        previous = installer_support.current_install(root)
        settings = root / "config/settings.json"
        settings.parent.mkdir(exist_ok=True)
        custom = {"output_dir": str(root / "destination française & 100% ' !"), "youtube_auth_enabled": False}
        installer_support.atomic_json(settings, custom)
        original = settings.read_bytes()
        queue = root / "cache/queue.json"
        state = json.loads(queue.read_text())
        state["history"] = [{"id": "preserved-history", "status": "finished", "title": "Français & 100% !"}]
        installer_support.atomic_json(queue, state)
        stage = root / ("stage-" + uuid.uuid4().hex)
        stage.mkdir()
        for name in ("runtime", "bin"):
            shutil.copytree(current / name, stage / name, symlinks=True)
        arch = "aarch64" if platform_support.run_hidden(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], stdout=subprocess.PIPE).stdout.strip() == b"1" else "x86_64"
        proc = subprocess.run([str(current / "runtime/bin/python3"), "-I", "-u", "-B",
                               str(SOURCE / "native-host/macos_install.py"), "install", "--source", str(SOURCE),
                               "--stage", str(stage), "--arch", arch, "--no-dependencies"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotEqual(installer_support.current_install(root)["directory"], previous["directory"])
        self.assertEqual(settings.read_bytes(), original)
        state = self.query("status")["state"]
        self.assertTrue(state["queue_paused"])
        self.assertEqual(state["history"][0]["id"], "preserved-history")

    def test_03_offline_audio_remux_with_unicode_paths(self):
        root, current = self.current()
        media = root / "fixture française & 100% ' !.webm"
        result = subprocess.run([str(current / "bin/ffmpeg"), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.25",
                                 "-c:a", "libopus", str(media)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        helper = root / "smoke-audio.py"
        helper.write_text('''import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
os.environ['PATH']=str(Path(sys.argv[1]).parent/'bin')+os.pathsep+os.environ.get('PATH','')
import worker
path,codec=worker.remux_original_audio(Path(sys.argv[2]))
assert path.suffix=='.opus' and codec=='opus', (path,codec)
assert worker.validate_media_file(path,'audio')[0]
path.unlink()
''', encoding="utf-8")
        try:
            result = subprocess.run([str(current / "runtime/bin/python3"), "-I", "-B", str(helper), str(current / "backend"), str(media)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            helper.unlink(missing_ok=True)
            media.unlink(missing_ok=True)
            media.with_suffix(".opus").unlink(missing_ok=True)

    def worker_control(self, action):
        root, current = self.current()
        with tempfile.TemporaryDirectory(prefix="kitty-mac-worker-") as temporary:
            base = Path(temporary).resolve()
            cache = base / "cache"
            cache.mkdir()
            output = base / "sortie française & 100% !"
            output.mkdir()
            partial = output / "video.opus.part"
            partial.write_bytes(b"partiel")
            state = queue_store.default_state()
            state["active"] = {"id": "ci-worker", "url": "https://example.com/ci", "mode": "audio", "status": "starting",
                               "output_dir": str(output), "output_stem": str(output / "video")}
            queue_store.atomic_json(cache / "queue.json", state)
            helper = base / "run-worker.py"
            helper.write_text('''import runpy, sys, types, time
from pathlib import Path
worker=Path(sys.argv[1]); base=Path(sys.argv[3])
sys.path.insert(0,str(worker.parent))
import app_paths
app_paths.cache_dir=lambda: base/'cache'
app_paths.config_dir=lambda: base/'config'
app_paths.default_output_dir=lambda: base/'sortie'
app_paths.install_dir=lambda: worker.parent
fake=types.ModuleType('yt_dlp')
class YoutubeDL:
 def __init__(self,opts): self.opts=opts
 def __enter__(self): return self
 def __exit__(self,*args): pass
 def extract_info(self,url,download=False):
  (base/'ready').write_text('ready')
  while True: time.sleep(.05)
fake.YoutubeDL=YoutubeDL
sys.modules['yt_dlp']=fake
sys.argv=[str(worker),sys.argv[2]]
runpy.run_path(str(worker),run_name='__main__')
''', encoding="utf-8")
            proc = subprocess.Popen([str(current / "runtime/bin/python3"), "-I", "-B", str(helper),
                                     str(current / "backend/worker.py"), "ci-worker", str(base)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, **platform_support.spawn_options())
            try:
                deadline = time.monotonic() + 12
                while not (base / "ready").exists() and time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(.05)
                self.assertTrue((base / "ready").exists(), "Worker non démarré")
                self.assertEqual(os.getpgid(proc.pid), proc.pid)
                self.assertTrue(platform_support.script_process_matches(proc.pid, current / "backend/worker.py", "ci-worker"))
                installer_support.atomic_json(cache / "controls/ci-worker.json", {"action": action})
                proc.send_signal(signal.SIGTERM)
                _, error = proc.communicate(timeout=15)
                self.assertEqual(proc.returncode, 0 if action == "cancel" else 128 + int(signal.SIGTERM), error)
                state = queue_store.read_state(cache / "queue.json", cache / "queue.lock")
                self.assertIsNone(state["active"])
                if action == "cancel":
                    self.assertFalse(partial.exists())
                    self.assertEqual(state["history"][0]["status"], "cancelled")
                else:
                    self.assertTrue(partial.exists())
                    self.assertTrue(state["queue_paused"])
                    self.assertEqual(state["queue"][0]["id"], "ci-worker")
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate(timeout=10)

    def test_04_cancel_cleans_partials_and_stop_preserves_them(self):
        for action in ("cancel", "stop"):
            with self.subTest(action=action):
                self.worker_control(action)

    def test_99_uninstall_preserves_data_and_removes_registration(self):
        root, current = self.current()
        settings = (root / "config/settings.json").read_bytes()
        history = json.loads((root / "cache/queue.json").read_text())["history"]
        result = subprocess.run([str(root / "Uninstall.command")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / "config/settings.json").read_bytes(), settings)
        self.assertEqual(json.loads((root / "cache/queue.json").read_text())["history"], history)
        self.assertFalse(app_paths.native_manifest_path().exists())
        for name in ("versions", "extension", "current.json", "native-host.sh", "Uninstall.command"):
            self.assertFalse((root / name).exists(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
