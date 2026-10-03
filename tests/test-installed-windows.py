"""Opt-in smoke tests for a fresh Windows CI installation, no media network.

This suite installs a second runtime and uninstalls Kitty at the end. It only
runs with KITTY_INSTALLED_TEST=1 on Windows; never run against a personal setup.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import unittest
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "native-host"))
import windows_install

@unittest.skipUnless(sys.platform == "win32" and os.environ.get("KITTY_INSTALLED_TEST") == "1",
                     "Exige une installation Windows neuve et KITTY_INSTALLED_TEST=1")
class InstalledWindowsTests(unittest.TestCase):
    def query_launcher(self, action):
        root = windows_install.app_root()
        command = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        payload = json.dumps({"action": action}).encode()
        proc = subprocess.run([str(command), "/d", "/s", "/c", '""' + str(root / "native-host.bat") + '""'],
                              input=struct.pack("<I", len(payload)) + payload,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(len(proc.stdout), 4, proc.stderr)
        size = struct.unpack("<I", proc.stdout[:4])[0]
        self.assertEqual(size, len(proc.stdout) - 4)
        result = json.loads(proc.stdout[4:])
        self.assertTrue(result.get("ok"), result)
        return result

    def test_01_installed_batch_launcher_and_registry_both_views(self):
        import winreg
        root = windows_install.app_root()
        self.query_launcher("get_settings")
        diagnostics = self.query_launcher("diagnostics")
        self.assertEqual(diagnostics["dependencies"]["required_missing"], [])
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, windows_install.REG_NATIVE, 0, winreg.KEY_READ | view) as key:
                value = winreg.QueryValueEx(key, "")[0]
                self.assertEqual(value, str(root / (windows_install.HOST_NAME + ".json")))

    def test_02_upgrade_preserves_configuration_and_history(self):
        root = windows_install.app_root()
        previous = windows_install.current_install(root)
        version_dir = windows_install.checked_version_path(root, previous)
        stage = root / ("stage-" + uuid.uuid4().hex)
        stage.mkdir()
        for name in ("runtime", "packages", "bin"):
            shutil.copytree(version_dir / name, stage / name)
        settings = root / "config/settings.json"
        original = settings.read_bytes() if settings.exists() else None
        queue = root / "cache/queue.json"
        state = json.loads(queue.read_text(encoding="utf-8"))
        state["history"] = [{"id": "preserved-history", "status": "finished", "title": "Français & 100% !"}]
        windows_install.atomic_json(queue, state)
        proc = subprocess.run([str(version_dir / "runtime/python.exe"), "-I", "-u", "-B",
                               str(SOURCE / "native-host/windows_install.py"), "install", "--source", str(SOURCE),
                               "--stage", str(stage), "--no-dependencies"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotEqual(windows_install.current_install(root)["directory"], previous["directory"])
        self.assertEqual(settings.read_bytes() if settings.exists() else None, original)
        state = self.query_launcher("status")["state"]
        self.assertTrue(state["queue_paused"])
        self.assertEqual(state["history"][0]["id"], "preserved-history")

    def test_03_remux_original_audio_without_network(self):
        root = windows_install.app_root()
        current = windows_install.checked_version_path(root, windows_install.current_install(root))
        ffmpeg = current / "bin/ffmpeg.exe"
        media = root / "fixture française & 100% !.webm"
        proc = subprocess.run([str(ffmpeg), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.25",
                               "-c:a", "libopus", str(media)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        script = root / "smoke_audio.py"
        script.write_text('''import os, sys
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
            proc = subprocess.run([str(current / "runtime/python.exe"), "-I", "-B", str(script), str(current / "backend"), str(media)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            script.unlink(missing_ok=True)
            media.unlink(missing_ok=True)
            media.with_suffix(".opus").unlink(missing_ok=True)

    def test_99_uninstall_preserves_data_and_removes_native_registration(self):
        import winreg
        root = windows_install.app_root()
        current = windows_install.checked_version_path(root, windows_install.current_install(root))
        config = root / "config/settings.json"
        original_config = config.read_bytes() if config.exists() else None
        history = (root / "cache/queue.json").read_bytes()
        proc = subprocess.run([str(current / "runtime/python.exe"), "-I", "-u", "-B", str(current / "backend/windows_install.py"), "uninstall"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((root / "current.json").exists())
        self.assertEqual(config.read_bytes() if config.exists() else None, original_config)
        # Pause is a deliberate uninstall change; history must survive.
        old = json.loads(history)
        new = json.loads((root / "cache/queue.json").read_text(encoding="utf-8"))
        self.assertEqual(new["history"], old["history"])
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            with self.assertRaises(FileNotFoundError):
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, windows_install.REG_NATIVE, 0, winreg.KEY_READ | view)


if __name__ == "__main__":
    unittest.main(verbosity=2)
