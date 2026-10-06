"""Real package imports and faults; no external media or network requests."""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native-host'))
import runtime_check
import metadata_guard
from errors import classify_backend_error

HAS_YTDLP = importlib.util.find_spec('yt_dlp') is not None


class RuntimeTests(unittest.TestCase):
    def test_submodule_missing_is_an_installation_error(self):
        for name in ('yt_dlp', 'yt_dlp.postprocessor', 'yt_dlp.postprocessor.ffmpeg', 'yt_dlp_ejs'):
            for quote in ("'", '"'):
                error = classify_backend_error(f'No module named {quote}{name}{quote}')
                self.assertEqual(error['code'], 'ytdlp_missing')

    def test_metadata_initialization_failure_returns_structured_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            request, result = Path(directory) / 'request.json', Path(directory) / 'result.json'
            request.write_text(json.dumps({'job': {'url': 'https://example.test'}, 'options': {}}))
            with patch('platform_support.configure_worker_job'), \
                 patch.object(metadata_guard, 'install_ffmpeg_timeouts', side_effect=ModuleNotFoundError("No module named 'yt_dlp.postprocessor'")):
                metadata_guard._child(request, result)
            answer = json.loads(result.read_text())
            self.assertFalse(answer['ok'])
            self.assertEqual(answer['error']['code'], 'ytdlp_missing')
            self.assertIn('yt_dlp.postprocessor', answer['error']['detail'])

    @unittest.skipUnless(HAS_YTDLP, 'Requires real yt-dlp')
    def test_real_ytdlp_record_is_complete(self):
        result = runtime_check.check_ytdlp_files()
        self.assertTrue(result['ok'], result)
        self.assertGreater(result['checked'], 100)

    @unittest.skipUnless(HAS_YTDLP, 'Requires real yt-dlp')
    def test_real_download_imports_and_factories_are_ready(self):
        missing = [name for name in ('mutagen', 'psutil', 'yt_dlp_ejs') if importlib.util.find_spec(name) is None]
        if missing:
            self.skipTest('Requires default runtime dependencies: ' + ', '.join(missing))
        private = Path(importlib.util.find_spec('yt_dlp').origin).parent.parent
        result = runtime_check.check_runtime(private)
        self.assertTrue(result['ok'], result)
        self.assertTrue(all(item['ok'] for item in result['modules']))

    def clone_ytdlp(self, directory):
        distribution = importlib.metadata.distribution('yt-dlp')
        package = Path(distribution.locate_file('yt_dlp'))
        shutil.copytree(package, directory / 'yt_dlp', ignore=shutil.ignore_patterns('__pycache__'))
        metadata = next(p for p in distribution.files if str(p).endswith('.dist-info/METADATA'))
        origin = Path(distribution.locate_file(metadata)).parent
        shutil.copytree(origin, directory / origin.name)

    def probe(self, directory):
        env = {**os.environ, 'PYTHONPATH': str(directory) + os.pathsep + os.environ.get('PYTHONPATH', ''), 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, str(ROOT / 'native-host/runtime_check.py')], env=env,
                                capture_output=True, text=True, timeout=20)
        return result.returncode, json.loads(result.stdout)

    @unittest.skipUnless(HAS_YTDLP, 'Requires real yt-dlp')
    def test_missing_postprocessor_is_detected_before_any_download(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self.clone_ytdlp(directory)
            shutil.rmtree(directory / 'yt_dlp/postprocessor')
            status, result = self.probe(directory)
        self.assertEqual(status, 1)
        self.assertFalse(result['ok'])
        self.assertIn("No module named 'yt_dlp.postprocessor'", result['error'])
        self.assertFalse(result['integrity']['ok'])

    @unittest.skipUnless(HAS_YTDLP, 'Requires real yt-dlp')
    def test_modified_module_is_detected_even_if_import_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self.clone_ytdlp(directory)
            version = directory / 'yt_dlp/version.py'
            version.write_bytes(version.read_bytes() + b'\n# changed after installation\n')
            status, result = self.probe(directory)
        self.assertEqual(status, 1)
        self.assertFalse(result['ok'])
        self.assertIn('yt_dlp/version.py: empreinte incorrecte', result['integrity']['issues'])

    @unittest.skipUnless(HAS_YTDLP, 'Requires real yt-dlp')
    def test_modules_from_another_python_are_rejected_for_private_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            report = runtime_check.check_runtime(Path(directory))
        self.assertFalse(report['ok'])
        self.assertTrue(any('hors des paquets prives' in issue for issue in report['issues']), report)


if __name__ == '__main__':
    unittest.main(verbosity=2)
