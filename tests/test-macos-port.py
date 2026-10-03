"""Portable macOS regressions; runtime tests also run on actual Mac runners."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import types
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "native-host"))
import app_paths
import macos_install as installer
import platform_support
import installer_support
import queue_store


class MacInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / "Kitty français & 100% ' !"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def stage(self):
        stage = self.root / "stage-fixture"
        (stage / "extension").mkdir(parents=True)
        (stage / "extension/manifest.json").write_text('{"version":"8.31"}')
        return stage

    def test_mac_paths_and_backend_location(self):
        with patch.object(app_paths, "MACOS", True), patch.object(app_paths, "WINDOWS", False), \
             patch.object(Path, "home", return_value=self.root):
            expected = self.root / "Library/Application Support/KittyDownloadManager"
            self.assertEqual(app_paths.cache_dir(), expected / "cache")
            self.assertEqual(app_paths.config_dir(), expected / "config")
            self.assertEqual(app_paths.install_dir(), SOURCE / "native-host")
            self.assertEqual(app_paths.native_manifest_path(), self.root / "Library/Application Support/Mozilla/NativeMessagingHosts/com.kitty.download_manager.json")

    def test_publish_registers_executable_absolute_launcher(self):
        manifest = self.root / "Mozilla/NativeMessagingHosts/com.kitty.download_manager.json"
        installed = installer.commit_install(self.root, self.stage(), "8.31", manifest_path=manifest)
        data = json.loads(manifest.read_text())
        self.assertEqual(data["path"], str(self.root / "native-host.sh"))
        self.assertEqual(data["allowed_extensions"], [installer.EXTENSION_ID])
        self.assertTrue(os.access(self.root / "native-host.sh", os.X_OK))
        self.assertIn(str(installed / "runtime/bin/python3"), (self.root / "native-host.sh").read_text().replace("'\"'\"'", "'"))
        self.assertTrue((self.root / "extension/manifest.json").is_file())

    def test_launch_with_spaces_accents_apostrophe_and_minimal_path(self):
        stage = self.stage()
        (stage / "runtime/bin").mkdir(parents=True)
        (stage / "runtime/bin/python3").symlink_to(sys.executable)
        (stage / "backend").mkdir()
        (stage / "backend/host.py").write_text('import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())')
        installed = installer.commit_install(self.root, stage, "8.31", manifest_path=self.root / "manifest.json")
        payload = b'\x04\x00\x00\x00test'
        result = subprocess.run([str(self.root / "native-host.sh")], input=payload,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin"}, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, payload)

    def test_failed_manifest_write_restores_previous_version(self):
        manifest = self.root / "manifest.json"
        installer.commit_install(self.root, self.stage(), "8.31", manifest_path=manifest)
        old = {p: p.read_bytes() for p in (self.root / "current.json", self.root / "native-host.sh", manifest,
                                          self.root / "extension/manifest.json")}
        original = installer.atomic_json
        def failing_write(path, data):
            if Path(path) == manifest:
                raise PermissionError("Firefox inaccessible")
            return original(path, data)
        with patch.object(installer, "atomic_json", side_effect=failing_write):
            with self.assertRaisesRegex(PermissionError, "Firefox inaccessible"):
                installer.commit_install(self.root, self.stage(), "8.31", manifest_path=manifest)
        for p, content in old.items():
            self.assertEqual(p.read_bytes(), content)
        self.assertEqual(len(list((self.root / "versions").iterdir())), 1)

    def test_failed_first_copy_leaves_no_partial_installation(self):
        stage = self.stage()
        def broken_copy(source, dest):
            Path(dest).mkdir()
            (Path(dest) / "partial").write_text("partial")
            raise OSError("copie interrompue")
        with patch.object(installer.shutil, "copytree", side_effect=broken_copy):
            with self.assertRaises(OSError):
                installer.commit_install(self.root, stage, "8.31", manifest_path=self.root / "manifest.json")
        self.assertFalse((self.root / "extension").exists())
        self.assertFalse((self.root / "current.json").exists())

    def test_foreign_registration_is_preserved(self):
        manifest = self.root / "manifest.json"
        raw = '{"name":"com.kitty.download_manager","path":"/other/native-host.sh"}'
        manifest.write_text(raw)
        with self.assertRaisesRegex(RuntimeError, "autre installation"):
            installer.commit_install(self.root, self.stage(), "8.31", manifest_path=manifest)
        self.assertEqual(manifest.read_text(), raw)

    def test_linked_registration_directory_is_rejected(self):
        (self.root / "other").mkdir()
        (self.root / "linked").symlink_to(self.root / "other", target_is_directory=True)
        with self.assertRaises(RuntimeError):
            installer.commit_install(self.root, self.stage(), "8.31", manifest_path=self.root / "linked/manifest.json")
        self.assertEqual(list((self.root / "other").iterdir()), [])

    def test_folder_path_is_an_argument_and_cancel_is_empty(self):
        current = '/Users/test/Téléchargements " & \' ; do shell script "touch /tmp/no"'
        captured = []
        def fake_run(command, **kwargs):
            captured.extend(command)
            return subprocess.CompletedProcess(command, 0, "\n", "")
        with patch.object(platform_support, "run_hidden", side_effect=fake_run):
            self.assertEqual(platform_support.choose_macos_folder(current), "")
        self.assertEqual(captured[-1], current)
        self.assertNotIn(current, captured[2])

    def test_mac_process_identity_and_unreadable_pid_fail_closed(self):
        script = self.root / "worker.py"
        fake = types.SimpleNamespace(Process=lambda pid: types.SimpleNamespace(
            cmdline=lambda: [sys.executable, str(script), "unique-job"]))
        with patch.object(platform_support, "MACOS", True), patch.dict(sys.modules, {"psutil": fake}):
            self.assertTrue(platform_support.script_process_matches(42, script, "unique-job"))
            self.assertFalse(platform_support.script_process_matches(42, script, "different-job"))
            self.assertFalse(platform_support.script_process_matches(42, self.root / "other.py", "unique-job"))
        fake.Process = lambda pid: (_ for _ in ()).throw(PermissionError("processus inaccessible"))
        with patch.object(platform_support, "MACOS", True), patch.dict(sys.modules, {"psutil": fake}):
            self.assertFalse(platform_support.script_process_matches(42, script, "unique-job"))

    @unittest.skipUnless(sys.platform == "darwin", "Exige la table des processus d’un vrai Mac")
    def test_mac_process_identity_uses_command_line_without_proc(self):
        script = self.root / "worker.py"
        script.write_text('import time; time.sleep(30)')
        child = subprocess.Popen([sys.executable, str(script), "unique-job"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with patch.object(platform_support, "MACOS", True):
                self.assertTrue(platform_support.script_process_matches(child.pid, script, "unique-job"))
                self.assertFalse(platform_support.script_process_matches(child.pid, script, "different-job"))
                self.assertFalse(platform_support.script_process_matches(child.pid, self.root / "other.py", "unique-job"))
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_maintenance_status_does_not_modify_or_start_jobs(self):
        spec = importlib.util.spec_from_file_location("kitty_mac_host_test", SOURCE / "native-host/host.py")
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        state = queue_store.default_state()
        state["queue"] = [{"id": "waiting", "url": "https://example.com/video", "title": "CI", "status": "queued"}]
        queue = self.root / "queue.json"
        queue_store.atomic_json(queue, state)
        original = queue.read_bytes()
        with patch.object(host, "MACOS", True), patch.object(host, "maintenance_active", return_value=True), \
             patch.object(host, "QUEUE_FILE", queue), patch.object(host, "LOCK_FILE", self.root / "queue.lock"), \
             patch.object(host, "spawn", side_effect=AssertionError("worker inattendu")):
            self.assertEqual(host.repair_state()["queue"][0]["id"], "waiting")
            with self.assertRaises(queue_store.QueueStateError):
                host.with_state(lambda state: state.update(queue_paused=False))
        self.assertEqual(queue.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
