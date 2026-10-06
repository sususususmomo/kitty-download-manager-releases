"""Custom Windows layout, state relocation and rollback; no network."""
from contextlib import contextmanager, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native-host'))
import app_paths
import windows_install as installer
import queue_store


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Windows TEMP can use the RUNNER~1 short alias; production resolves
        # the same directory to its long name before storing install paths.
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'autre disque' / 'Kitty Français & 100% !'
        self.root.mkdir(parents=True)
        # No active process in these fixtures; process-control cases live in
        # test-windows-port.py and the native Windows smoke suite.
        fake_psutil = SimpleNamespace(Process=lambda _pid=None: SimpleNamespace(create_time=lambda: 10))
        self.psutil = patch.dict(sys.modules, {'psutil': fake_psutil})
        self.psutil.start()
        self.addCleanup(self.psutil.stop)

    def stage(self, prepared=False):
        if prepared:
            path = self.root / 'versions' / (installer.source_backend_version(ROOT) + '-' + uuid.uuid4().hex)
        else:
            path = self.root / ('stage-' + uuid.uuid4().hex)
        (path / 'runtime').mkdir(parents=True)
        (path / 'runtime/python.exe').write_bytes(b'fixture')
        return path

    def args(self, stage, previous=None):
        return SimpleNamespace(root=str(self.root), previous_root=str(previous) if previous else None,
                               source=str(ROOT), stage=str(stage), no_dependencies=True, no_register=True)

    def state(self, root):
        state = queue_store.default_state()
        state['history'] = [{'id': 'keep-history', 'status': 'finished', 'title': 'Épisode'}]
        installer.atomic_json(root / 'cache/queue.json', state)
        installer.atomic_json(root / 'config/settings.json', {'output_dir': str(self.base / 'mes vidéos')})
        (root / 'config/cookies.txt').write_bytes(b'keep-cookie')

    def query(self, _python, backend, action):
        spec = importlib.util.spec_from_file_location('custom_app_paths', Path(backend) / 'app_paths.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.WINDOWS = True
        # Stage and published version must never consult the old registry/C:.
        with patch.object(module, 'windows_registered_root', side_effect=AssertionError('old location')):
            self.assertEqual(module.config_dir(), self.root / 'config')
            self.assertEqual(module.cache_dir(), self.root / 'cache')
            self.assertEqual(module.native_manifest_path(), self.root / (installer.HOST_NAME + '.json'))
        return {'ok': True, 'compatibility': {'backend_version': installer.source_backend_version(ROOT)}}

    def test_fresh_custom_install_then_upgrade_resolves_paths_without_registry(self):
        with patch.object(installer, 'native_query', side_effect=self.query), redirect_stdout(io.StringIO()):
            installer.install(self.args(self.stage()))
            first = installer.current_install(self.root)
            self.state(self.root)
            installer.install(self.args(self.stage()))
        current = installer.current_install(self.root)
        self.assertNotEqual(first['directory'], current['directory'])
        state = json.loads((self.root / 'cache/queue.json').read_text())
        self.assertEqual(state['history'][0]['id'], 'keep-history')
        self.assertTrue(state['queue_paused'])
        self.assertEqual((self.root / 'config/cookies.txt').read_bytes(), b'keep-cookie')
        manifest = json.loads((self.root / (installer.HOST_NAME + '.json')).read_text())
        self.assertEqual(manifest['path'], str(self.root / 'native-host.bat'))
        self.assertEqual(json.loads((self.root / 'installation.json').read_text())['app'], installer.APP_ID)

    def test_prepared_version_is_validated_before_activation_and_never_moved(self):
        with patch.object(installer, 'native_query', side_effect=self.query), redirect_stdout(io.StringIO()):
            installer.install(self.args(self.stage()))
        original = (self.root / 'current.json').read_bytes()
        self.state(self.root)
        prepared = self.stage(prepared=True)
        def query(python, backend, action):
            self.assertEqual(Path(backend).parent, prepared)
            self.assertEqual((self.root / 'current.json').read_bytes(), original)
            return self.query(python, backend, action)
        replace = installer.os.replace
        def no_payload_rename(source, destination):
            if Path(source) == prepared:
                raise PermissionError(13, 'Windows denies moving this runtime')
            return replace(source, destination)
        with patch.object(installer, 'native_query', side_effect=query) as probe, \
             patch.object(installer.os, 'replace', side_effect=no_payload_rename), redirect_stdout(io.StringIO()):
            installer.install(self.args(prepared))
        self.assertEqual(probe.call_count, 3)
        self.assertTrue((prepared / 'backend/host.py').exists())
        self.assertEqual(installer.checked_version_path(self.root, installer.current_install(self.root)), prepared)
        self.assertEqual(queue_store.read_state(self.root / 'cache/queue.json', self.root / 'cache/queue.lock')['history'][0]['id'], 'keep-history')
        self.assertEqual((self.root / 'config/cookies.txt').read_bytes(), b'keep-cookie')

    def test_failed_prepared_validation_keeps_old_backend_and_removes_unpublished_version(self):
        with patch.object(installer, 'native_query', side_effect=self.query), redirect_stdout(io.StringIO()):
            installer.install(self.args(self.stage()))
        original = {name: (self.root / name).read_bytes() for name in ('current.json', 'native-host.bat', installer.HOST_NAME + '.json')}
        prepared = self.stage(prepared=True)
        with patch.object(installer, 'native_query', side_effect=RuntimeError('invalid runtime')), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'invalid runtime'):
                installer.install(self.args(prepared))
        for name, content in original.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertFalse(prepared.exists())
        self.assertFalse((self.root / 'cache/maintenance.json').exists())

    def test_existing_active_version_cannot_be_used_as_preparation(self):
        with patch.object(installer, 'native_query', side_effect=self.query), redirect_stdout(io.StringIO()):
            installer.install(self.args(self.stage(prepared=True)))
        active = installer.checked_version_path(self.root, installer.current_install(self.root))
        original = (active / 'backend/host.py').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'version active'):
            installer.install(self.args(active))
        self.assertEqual((active / 'backend/host.py').read_bytes(), original)
        with self.assertRaisesRegex(RuntimeError, 'version active'):
            installer.commit_install(self.root, active, installer.source_backend_version(ROOT), register_host=False)
        self.assertTrue(active.exists())

    def old(self):
        old = self.base / 'ancien C' / 'KittyDownloadManager'
        old.mkdir(parents=True)
        stage = old / ('stage-' + uuid.uuid4().hex)
        stage.mkdir()
        installer.commit_install(old, stage, '8.42', register_host=False)
        self.state(old)
        return old

    def test_move_preserves_history_settings_cookies_and_original(self):
        old = self.old()
        settings = (old / 'config/settings.json').read_bytes()
        with patch.object(installer, 'native_query', side_effect=self.query), redirect_stdout(io.StringIO()):
            installer.install(self.args(self.stage(), old))
        self.assertEqual((self.root / 'config/settings.json').read_bytes(), settings)
        self.assertEqual((self.root / 'config/cookies.txt').read_bytes(), b'keep-cookie')
        self.assertEqual(json.loads((self.root / 'cache/queue.json').read_text())['history'][0]['id'], 'keep-history')
        self.assertTrue((old / 'current.json').exists())
        self.assertTrue((old / 'config/cookies.txt').exists())
        self.assertFalse((old / 'cache/maintenance.json').exists())
        self.assertFalse((self.root / 'cache/maintenance.json').exists())

    def test_move_registry_failure_restores_original_registration_and_removes_copies(self):
        old = self.old()
        args = self.args(self.stage(), old)
        args.no_register = False
        with patch.object(installer, 'native_query', side_effect=self.query), \
             patch.object(installer, 'snapshot_registry', return_value=['old-registration']), \
             patch.object(installer, 'register', side_effect=OSError('registry failure')), \
             patch.object(installer, 'restore_registry') as restore, redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                installer.install(args)
        restore.assert_called_once_with(['old-registration'])
        self.assertTrue((old / 'current.json').exists())
        self.assertTrue((old / 'config/cookies.txt').exists())
        self.assertFalse((self.root / 'current.json').exists())
        self.assertFalse((self.root / 'installation.json').exists())
        self.assertFalse((self.root / 'config').exists())
        self.assertFalse((self.root / 'cache').exists())

    def test_copy_failure_removes_partial_destination_without_touching_original(self):
        old = self.old()
        def fail_copy(_source, target, **kwargs):
            Path(target).mkdir()
            (Path(target) / 'partial').write_bytes(b'partial')
            raise OSError('disk full')
        with patch.object(installer.shutil, 'copytree', side_effect=fail_copy):
            with self.assertRaises(OSError):
                with installer.relocated_state(old, self.root):
                    self.fail('should not commit')
        self.assertFalse((self.root / 'config').exists())
        self.assertTrue((old / 'config/settings.json').exists())

    def test_move_refuses_existing_destination_state(self):
        old = self.old()
        self.state(self.root)
        before = (self.root / 'config/settings.json').read_bytes()
        with self.assertRaises(RuntimeError):
            with installer.relocated_state(old, self.root):
                self.fail('overwrite')
        self.assertEqual((self.root / 'config/settings.json').read_bytes(), before)

    def test_move_rejects_links_before_copying_state(self):
        old = self.old()
        try:
            (old / 'config/external').symlink_to(self.base, target_is_directory=True)
        except OSError:
            self.skipTest('symlink privilege unavailable')
        with self.assertRaises(RuntimeError):
            with installer.relocated_state(old, self.root):
                self.fail('symlink copied')
        self.assertFalse((self.root / 'config').exists())

    def test_stage_outside_chosen_root_is_refused(self):
        stage = self.stage()
        args = self.args(stage)
        args.root = str(self.base)
        with self.assertRaisesRegex(RuntimeError, 'preparation'):
            installer.install(args)

    def test_source_installer_remembers_registered_root_and_default_remains_compatible(self):
        with patch.object(app_paths, 'windows_registered_root', return_value=self.root):
            self.assertEqual(installer.app_root(), self.root)
        with patch.object(app_paths, 'windows_registered_root', return_value=None), \
             patch.dict(os.environ, {'LOCALAPPDATA': str(self.base)}):
            self.assertEqual(installer.app_root(), self.base / 'KittyDownloadManager')

    def test_registered_location_is_read_from_registry(self):
        @contextmanager
        def open_key(*_args):
            yield object()
        api = SimpleNamespace(HKEY_CURRENT_USER=object(), KEY_READ=1, KEY_WOW64_64KEY=256,
                              OpenKey=open_key, QueryValueEx=lambda *_: (str(self.root), 1))
        with patch.object(app_paths, 'WINDOWS', True), patch.dict(sys.modules, {'winreg': api}):
            self.assertEqual(app_paths.windows_registered_root(), self.root)
            api.QueryValueEx = lambda *_: ('relative-path', 1)
            with self.assertRaises(RuntimeError):
                app_paths.windows_registered_root()


if __name__ == '__main__':
    unittest.main(verbosity=2)
