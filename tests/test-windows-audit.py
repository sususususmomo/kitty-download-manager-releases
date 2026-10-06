"""Portable Windows fault injection. Native integration runs separately on Windows."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native-host'))
import host
import platform_support as api
import runtime_check
import metadata_guard
from errors import classify_backend_error


class WindowsAuditTests(unittest.TestCase):
    def test_isolated_install_bootstrap_can_import_source_helpers(self):
        # Install.ps1 runs this source from a private Python whose _pth omits
        # the script directory. Imports must follow the explicit path setup.
        script = ROOT / 'native-host/windows_install.py'
        code = "import runpy,sys; namespace=runpy.run_path(sys.argv[1],run_name='kitty_import_only'); assert callable(namespace['install'])"
        result = subprocess.run([sys.executable, '-I', '-c', code, str(script)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_process_iter_has_actionable_error(self):
        broken = SimpleNamespace(Process=lambda: None)
        with self.assertRaisesRegex(RuntimeError, 'process_iter'):
            runtime_check.check_psutil_api(broken)
        error = classify_backend_error("module 'psutil' has no attribute 'process_iter'")
        self.assertEqual(error['code'], 'process_support_invalid')
        self.assertIn('Réinstalle', error['hint'])

    def test_invalid_library_does_not_claim_worker_has_disappeared(self):
        with patch.object(api, 'WINDOWS', True), patch.dict(sys.modules, {'psutil': SimpleNamespace()}):
            for function, arguments in [(api.process_alive, (123,)), (api.process_args, (123,))]:
                with self.assertRaises(api.ProcessSupportError):
                    function(*arguments)
        with patch.object(host, 'WINDOWS', True), patch.dict(sys.modules, {'psutil': SimpleNamespace()}), \
             patch.object(host, 'with_state') as mutate:
            with self.assertRaises(api.ProcessSupportError):
                host.repair_state()
            mutate.assert_not_called()

    def test_psutil_record_detects_missing_native_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'psutil'
            package.mkdir()
            (package / '__init__.py').write_bytes(b'# fixture\n')
            digest = base64.urlsafe_b64encode(hashlib.sha256(b'# fixture\n').digest()).decode().rstrip('=')
            record = f'psutil/__init__.py,sha256={digest},10\npsutil/_psutil_windows.pyd,sha256=missing,20\n'
            dist = SimpleNamespace(read_text=lambda _: record, locate_file=lambda p: root / p)
            with patch.object(runtime_check.importlib.metadata, 'distribution', return_value=dist):
                report = runtime_check.check_distribution_files('psutil', 'psutil', root)
            self.assertFalse(report['ok'])
            self.assertIn('psutil/_psutil_windows.pyd: fichier manquant', report['issues'])

    def test_firefox_access_denied_cannot_trigger_snapshot(self):
        blocked = SimpleNamespace(info={'name': 'firefox.exe', 'cmdline': None})
        library = SimpleNamespace(process_iter=lambda _: [blocked], NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        with patch.object(api, 'WINDOWS', True), patch.dict(sys.modules, {'psutil': library}):
            with self.assertRaisesRegex(api.ProcessAccessError, 'fermeture'):
                api.firefox_uses_profile(Path('dedicated-profile'))

    def test_process_permission_denied_is_unknown_instead_of_dead(self):
        class Blocked:
            def is_running(self): raise PermissionError('denied')
            def cmdline(self): raise PermissionError('denied')
        library = SimpleNamespace(Process=lambda _: Blocked(), pid_exists=lambda _:True,
                                  NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        with patch.object(api, 'WINDOWS', True), patch.dict(sys.modules, {'psutil':library}):
            for function in (api.process_alive, api.process_args):
                with self.assertRaises(api.ProcessAccessError): function(123)

    def test_missing_process_method_is_never_treated_as_dead(self):
        library = SimpleNamespace(Process=lambda _: SimpleNamespace(), pid_exists=lambda _:True,
                                  NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        with patch.object(api, 'WINDOWS', True), patch.dict(sys.modules, {'psutil':library}):
            with self.assertRaises(api.ProcessSupportError): api.process_alive(123)

    def test_windows_startup_grace_does_not_finalize_early(self):
        with patch.object(host, 'WINDOWS', True), patch.object(host, '_validate_youtube_session', return_value={'profile': Path('profile')}), \
             patch.object(host, 'firefox_uses_profile', side_effect=AssertionError('too early')):
            self.assertTrue(host._youtube_auth_browser_running({'token':'a'*32,'created_at':host.time.time()}))

    @unittest.skipUnless(importlib.util.find_spec('yt_dlp'), 'Requires real yt-dlp')
    def test_real_ytdlp_preserves_percent_in_directory_and_title(self):
        from yt_dlp import YoutubeDL
        import worker
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'Français & 100% !'
            options = worker.build_opts('audio', lambda _:None, output)
            info = {'id':'fixture','title':'Titre 100% !','ext':'opus'}
            with YoutubeDL(options) as ydl:
                result = Path(ydl.prepare_filename(info))
                self.assertEqual(result.parent, output)
                self.assertIn('100%', result.name)
            options['outtmpl'] = worker.output_template_for_stem(output, 'Titre 100% !')
            with YoutubeDL(options) as ydl:
                self.assertEqual(Path(ydl.prepare_filename(info)).parent, output)

    def test_windows_transient_file_lock_retries_without_losing_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / 'new', Path(directory) / 'old'
            source.write_bytes(b'new')
            destination.write_bytes(b'old')
            original = os.replace
            calls = []
            def busy(first, second):
                calls.append(1)
                if len(calls) < 3:
                    self.assertEqual(destination.read_bytes(), b'old')
                    error = PermissionError('sharing violation'); error.winerror = 32
                    raise error
                original(first, second)
            with patch.object(api, 'WINDOWS', True), patch.object(api.os, 'replace', side_effect=busy), patch.object(api.time, 'sleep'):
                api.replace_file(source, destination)
            self.assertEqual(destination.read_bytes(), b'new')
            self.assertEqual(len(calls), 3)

    def test_windows_permanent_permission_error_is_bounded(self):
        error = PermissionError('denied'); error.winerror = 5
        with patch.object(api, 'WINDOWS', True), patch.object(api.os, 'replace', side_effect=error) as replace, patch.object(api.time, 'sleep'):
            with self.assertRaises(PermissionError): api.replace_file('source', 'destination')
            self.assertEqual(replace.call_count, 8)

    def test_concurrent_preferences_keep_all_fields_and_leave_no_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(host, CONFIG_DIR=root, SETTINGS_FILE=root / 'settings.json'):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(lambda i: host.update_settings(**{f'preference-{i}':i}), range(24)))
                self.assertEqual(host.load_settings(), {f'preference-{i}':i for i in range(24)})
                self.assertEqual(list(root.glob('*.tmp')), [])

    def test_unicode_resume_checkpoint_keeps_original_keys(self):
        from source_refresh import SourceRefresh
        from queue_store import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / 'reprise française.json'
            ledger = {'direct': {'https://example.test/épisode': ['étiquette', 100]},
                      'hls': {}, 'dash': {}, 'segments': {}}
            atomic_json(checkpoint, ledger)
            resumed = SourceRefresh({'formats': []}, None, lambda *_: None, checkpoint=checkpoint)
            self.assertEqual(resumed.ledger, ledger)

    def test_unreadable_preferences_are_never_overwritten_with_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / 'settings.json'
            settings.write_text('{"youtube_auth_enabled":true}')
            prior = settings.read_bytes()
            with patch.multiple(host, CONFIG_DIR=root, SETTINGS_FILE=settings), \
                 patch.object(Path, 'read_text', side_effect=PermissionError('sharing denied')):
                with self.assertRaises(PermissionError): host.update_settings(output_dir='changed')
            self.assertEqual(settings.read_bytes(), prior)

    def test_completed_windows_metadata_never_taskkills_reused_pid(self):
        process = SimpleNamespace(pid=123, poll=lambda:0, wait=lambda **_:0, kill=lambda: self.fail('already exited'))
        with patch.object(metadata_guard, 'os', SimpleNamespace(name='nt')), patch.object(api, 'run_hidden') as kill:
            metadata_guard.stop_process(process)
            kill.assert_not_called()

    def test_cancel_still_interrupts_when_child_cleanup_fails(self):
        class Thread:
            def __init__(self, target, **kwargs): self.target=target
            def start(self):
                try: self.target()
                except RuntimeError: pass
        with patch.object(api, 'WINDOWS', True), patch('threading.Thread', Thread), \
             patch.object(api, 'terminate_own_children', side_effect=RuntimeError('cleanup denied')), \
             patch('_thread.interrupt_main') as interrupt:
            done = api.watch_worker_controls(lambda:'cancel')
            interrupt.assert_called_once_with(signal.SIGTERM)
            done.set()


if __name__ == '__main__':
    unittest.main(verbosity=2)
