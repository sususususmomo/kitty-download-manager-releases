"""Offline session lifecycle, including the Windows branch. No real login."""
import http.cookiejar
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native-host"))
import host
import platform_support


class YoutubeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kitty-session-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Kitty Français & 100% !"
        config, cache = self.root / "config", self.root / "cache"
        auth = config / "youtube-auth"
        patches = patch.multiple(host, CACHE_DIR=cache, CONFIG_DIR=config,
            SETTINGS_FILE=config / "settings.json", YOUTUBE_AUTH_DIR=auth,
            YOUTUBE_COOKIE_FILE=auth / "cookies.txt", YOUTUBE_AUTH_META_FILE=auth / "metadata.json",
            YOUTUBE_SESSION_ROOT=cache / "youtube-auth-sessions",
            YOUTUBE_PENDING_FILE=cache / "youtube-auth-pending.json", WINDOWS=True, MACOS=False)
        patches.start()
        self.addCleanup(patches.stop)
        process_library = SimpleNamespace(process_iter=lambda *a: iter(()), Process=lambda *a: None,
            pid_exists=lambda *a: False, NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        library_patch = patch.dict(sys.modules, {"psutil": process_library})
        library_patch.start()
        self.addCleanup(library_patch.stop)

    def start(self, failure=None):
        with patch.object(host.sys, "platform", "win32"), \
             patch.object(host, "_find_firefox_executable", return_value="C:/Program Files/Mozilla Firefox/firefox.exe"), \
             patch.object(host, "spawn_options", return_value={"creationflags": 0x09000000}), \
             patch.object(host.subprocess, "Popen", side_effect=failure, return_value=SimpleNamespace(pid=4242)) as launch:
            result = host.youtube_auth_start()
        return result, launch

    def cookies(self, profile, signed_in=True):
        conn = sqlite3.connect(profile / "cookies.sqlite")
        with conn:
            conn.execute("PRAGMA user_version=16")
            conn.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT, path TEXT, expiry INTEGER, isSecure INTEGER)")
            conn.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?)", [
                (".youtube.com", "SAPISID" if signed_in else "PREF", "fixture", "/", 1893456000000, 1),
                (".google.com", "SID", "excluded", "/", 1893456000000, 1),
            ])
        conn.close()

    def test_windows_opens_separate_profile_and_private_environment(self):
        result, launch = self.start()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "browser_open")
        paths = host._youtube_session_paths(host._youtube_pending_load()["token"])
        args, kwargs = launch.call_args
        self.assertEqual(args[0][1:4], ["-no-remote", "-profile", str(paths["profile"])])
        self.assertEqual(kwargs["creationflags"], 0x09000000)
        self.assertTrue(kwargs["close_fds"])
        for variable, suffix in [("USERPROFILE", ""), ("APPDATA", "AppData/Roaming"), ("LOCALAPPDATA", "AppData/Local")]:
            self.assertEqual(kwargs["env"][variable], str(paths["home"] / suffix))
        self.assertTrue((paths["profile"] / "user.js").is_file())

    def test_close_snapshots_only_youtube_and_removes_temporary_profile(self):
        self.start()
        pending = host._youtube_pending_load()
        pending['created_at'] = time.time() - 3
        host._youtube_pending_save(pending)
        paths = host._youtube_session_paths(pending["token"])
        self.cookies(paths["profile"])
        with patch.object(host, "firefox_uses_profile", return_value=True):
            self.assertEqual(host.youtube_auth_status()["state"], "browser_open")
            self.assertFalse(host.YOUTUBE_COOKIE_FILE.exists())
        with patch.object(host, "firefox_uses_profile", return_value=False):
            result = host.youtube_auth_status()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["configured"])
        self.assertTrue(result["enabled"])
        self.assertFalse(paths["root"].exists())
        self.assertFalse(host.YOUTUBE_PENDING_FILE.exists())
        jar = http.cookiejar.MozillaCookieJar(str(host.YOUTUBE_COOKIE_FILE))
        jar.load(ignore_discard=True, ignore_expires=True)
        self.assertEqual([(c.domain, c.name, c.expires) for c in jar], [(".youtube.com", "SAPISID", 1893456000)])

    def test_failed_renewal_preserves_existing_snapshot(self):
        host.YOUTUBE_AUTH_DIR.mkdir(parents=True)
        host.YOUTUBE_COOKIE_FILE.write_text("old-snapshot", encoding="utf-8")
        self.start()
        pending = host._youtube_pending_load()
        pending['created_at'] = time.time() - 3
        host._youtube_pending_save(pending)
        paths = host._youtube_session_paths(host._youtube_pending_load()["token"])
        self.cookies(paths["profile"], signed_in=False)
        with patch.object(host, "firefox_uses_profile", return_value=False):
            result = host.youtube_auth_status()
        self.assertFalse(result["ok"])
        self.assertEqual(host.YOUTUBE_COOKIE_FILE.read_text(), "old-snapshot")

    def test_launch_failure_cleans_session_and_keeps_previous_snapshot(self):
        host.YOUTUBE_AUTH_DIR.mkdir(parents=True)
        host.YOUTUBE_COOKIE_FILE.write_text("old-snapshot", encoding="utf-8")
        with self.assertRaises(OSError):
            self.start(failure=OSError("launch failed"))
        self.assertEqual(list(host.YOUTUBE_SESSION_ROOT.iterdir()), [])
        self.assertFalse(host.YOUTUBE_PENDING_FILE.exists())
        self.assertEqual(host.YOUTUBE_COOKIE_FILE.read_text(), "old-snapshot")

    def test_concurrent_starts_open_only_one_disposable_firefox(self):
        with patch.object(host.sys, "platform", "win32"), \
             patch.object(host, "_find_firefox_executable", return_value="firefox.exe"), \
             patch.object(host, "spawn_options", return_value={}), \
             patch.object(host.subprocess, "Popen", return_value=SimpleNamespace(pid=123)) as launch:
            with ThreadPoolExecutor(max_workers=4) as pool:
                replies = list(pool.map(lambda _:host.youtube_auth_start(), range(8)))
        self.assertTrue(all(reply['ok'] and reply['pending'] for reply in replies))
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(len(list(host.YOUTUBE_SESSION_ROOT.iterdir())), 1)

    def test_unknown_process_state_cannot_delete_pending_or_old_session(self):
        self.start()
        host.YOUTUBE_COOKIE_FILE.write_text('old-snapshot')
        prior = host.YOUTUBE_PENDING_FILE.read_bytes()
        with patch.object(host, '_youtube_auth_browser_running', side_effect=platform_support.ProcessAccessError('blocked')):
            with self.assertRaises(platform_support.ProcessAccessError): host.youtube_auth_delete()
        self.assertEqual(host.YOUTUBE_PENDING_FILE.read_bytes(), prior)
        self.assertEqual(host.YOUTUBE_COOKIE_FILE.read_text(), 'old-snapshot')

    def test_partial_cleanup_failure_keeps_marker_and_allows_retry(self):
        self.start()
        pending = host._youtube_pending_load()
        paths = host._youtube_session_paths(pending['token'])
        with patch.object(host.shutil, 'rmtree', side_effect=PermissionError('file still open')):
            with self.assertRaises(PermissionError): host._safe_remove_youtube_session(pending['token'])
        self.assertTrue(paths['marker'].is_file())
        host._safe_remove_youtube_session(pending['token'])
        self.assertFalse(paths['root'].exists())

    def test_profile_detection_ignores_other_firefox_windows(self):
        profile = self.root / "profile"
        other = SimpleNamespace(info={"name": "firefox.exe", "cmdline": ["firefox.exe", "-profile", str(self.root / "other")]})
        ours = SimpleNamespace(info={"name": "firefox.exe", "cmdline": ["firefox.exe", "-profile", str(profile)]})
        psutil = SimpleNamespace(process_iter=lambda _: [other], NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        with patch.object(platform_support, "WINDOWS", True), \
             patch.dict(sys.modules, {"psutil": psutil}):
            self.assertFalse(platform_support.firefox_uses_profile(profile))
        psutil.process_iter = lambda _: [other, ours]
        with patch.object(platform_support, "WINDOWS", True), \
             patch.dict(sys.modules, {"psutil": psutil}):
            self.assertTrue(platform_support.firefox_uses_profile(profile))


if __name__ == "__main__":
    unittest.main(verbosity=2)
