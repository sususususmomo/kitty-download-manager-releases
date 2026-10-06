"""Backend-only packaging and independent frontend versions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native-host"))
import installer_support
import maintenance

spec = importlib.util.spec_from_file_location("kitty_packages", ROOT / "tools/build-packages.py")
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


class BackendPackagingTests(unittest.TestCase):
    def test_backend_archives_need_no_frontend(self):
        with tempfile.TemporaryDirectory() as directory:
            for platform in packages.PLATFORMS:
                source = packages.stage_backend(platform, Path(directory) / platform)
                self.assertFalse((source / "extension").exists())
                self.assertEqual(installer_support.source_backend_version(source), json.loads((ROOT / "backend.json").read_text())["version"])
                self.assertTrue((source / "native-host/image_download.py").is_file())
                self.assertTrue((source / "native-host/hls.py").is_file())
                self.assertTrue((source / "native-host/direct_media.py").is_file())
                self.assertTrue((source / "native-host/metadata_guard.py").is_file())
                self.assertTrue((source / "native-host/download_planner.py").is_file())
                self.assertTrue((source / "native-host/media_item.py").is_file())
                self.assertTrue((source / "native-host/media_tracks.py").is_file())
                self.assertTrue((source / "native-host/runtime_check.py").is_file())
                self.assertTrue((source / "LICENSE").is_file())
                self.assertEqual(maintenance._source_release_info(source)["protocol"], 1)

    def test_bad_metadata_is_not_replaced_by_frontend_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            source = packages.stage_backend("linux", Path(directory) / "source")
            (source / "backend.json").write_text('{"version":"8.31","protocol":9}')
            with self.assertRaises(RuntimeError):
                installer_support.source_backend_version(source)
            with self.assertRaises(RuntimeError):
                maintenance._source_release_info(source)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux installer")
    def test_linux_fresh_and_upgrade_without_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            source = packages.stage_backend("linux", Path(directory) / "source")
            home = Path(directory) / "home"
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
            for _ in range(2):
                result = subprocess.run(["bash", str(source / "install.sh")], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((home / ".mozilla/native-messaging-hosts/com.kitty.download_manager.json").is_file())
            self.assertTrue((home / ".local/lib/kitty-download-manager/metadata_guard.py").is_file())
            self.assertTrue((home / ".local/lib/kitty-download-manager/direct_media.py").is_file())
            self.assertTrue((home / ".local/lib/kitty-download-manager/download_planner.py").is_file())
            self.assertTrue((home / ".local/lib/kitty-download-manager/media_item.py").is_file())
            self.assertTrue((home / ".local/lib/kitty-download-manager/media_tracks.py").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
