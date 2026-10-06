"""Real process timeout, slow network response and child cleanup checks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('public_metadata', Path(__file__).with_name('check-public-metadata.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TimeoutTests(unittest.TestCase):
    def test_successful_process(self):
        result = probe.bounded_command([sys.executable, '-c', 'print(\'{"ok":true,"status":"ready"}\')'], 3)
        self.assertTrue(result['ok'])

    def test_bad_result_is_terminal(self):
        result = probe.bounded_command([sys.executable, '-c', 'print("not JSON")'], 3)
        self.assertEqual(result['status'], 'invalid_result')

    def test_invalid_timeout(self):
        for seconds in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                probe.bounded_command([], seconds)

    def test_interrupt_stops_probe_before_propagating(self):
        command = [sys.executable, '-c', 'import time; time.sleep(60)']
        def interrupted(process, *_args, **_kwargs):
            raise KeyboardInterrupt()
        with patch.object(subprocess.Popen, 'communicate', interrupted), \
                patch.object(probe, 'stop_probe', wraps=probe.stop_probe) as stop:
            with self.assertRaises(KeyboardInterrupt):
                probe.bounded_command(command, 3)
            self.assertEqual(stop.call_count, 1)
            self.assertIsNotNone(stop.call_args.args[0].returncode)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process group')
    def test_blocked_process_and_grandchild_are_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            heartbeat = Path(temp) / 'heartbeat'
            # Observe this child's work rather than /proc: container runtimes
            # can expose a procfs belonging to another PID namespace.
            child = ('import time; from pathlib import Path; '
                     f'p=Path({str(heartbeat)!r}); end=time.monotonic()+3; '
                     '\nwhile time.monotonic()<end: p.write_text(str(time.monotonic())); time.sleep(.03)')
            script = ('import subprocess,sys,time; '
                      f'subprocess.Popen([sys.executable,"-c",{child!r}]); '
                      'time.sleep(60)')
            result = probe.bounded_command([sys.executable, '-c', script], .8)
            self.assertEqual(result['status'], 'timeout')
            self.assertLess(result['elapsed_seconds'], 3)
            self.assertTrue(heartbeat.is_file(), 'The child must actually start')
            stopped_at = heartbeat.stat().st_mtime_ns
            time.sleep(.3)
            self.assertEqual(heartbeat.stat().st_mtime_ns, stopped_at,
                             'The probe left a running child')

    def test_continuous_slow_response_cannot_extend_global_budget(self):
        arrived = threading.Event()
        class Slow(BaseHTTPRequestHandler):
            def do_GET(self):
                arrived.set()
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                self.send_header('Content-Length', '10000')
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b'#'); self.wfile.flush(); time.sleep(.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Slow)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                report = Path(temp) / 'result.json'
                process = subprocess.run([sys.executable, str(Path(probe.__file__)),
                    f'http://127.0.0.1:{server.server_port}/slow.m3u8', '--timeout', '2',
                    '--report', str(report)], capture_output=True, text=True, timeout=5)
                self.assertEqual(process.returncode, 124, process.stdout + process.stderr)
                result = json.loads(report.read_text())
            self.assertTrue(arrived.is_set(), 'Actual yt-dlp must reach the slow server')
            self.assertEqual(result['status'], 'timeout')
            self.assertLess(result['elapsed_seconds'], 4)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
