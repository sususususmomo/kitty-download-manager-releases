#!/usr/bin/env python3
"""Behavioral regression tests: persistence, fault injection and real processes."""
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

NATIVE = Path(__file__).resolve().parents[1] / 'native-host'
sys.path.insert(0, str(NATIVE))
import queue_store as store


def load_backend(name, home):
    with patch.dict(os.environ, {'HOME': str(home)}):
        spec = importlib.util.spec_from_file_location(f'queue_test_{name}_{id(home)}', NATIVE / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def count_writer(path, lock, barrier):
    barrier.wait(timeout=15)
    for _ in range(30):
        store.mutate_state(path, lock, lambda d: d.update(counter=d.get('counter', 0) + 1))


def duplicate_writer(home, barrier, results):
    host = load_backend('host', Path(home))
    host.WORKER = NATIVE / 'worker.py'
    host.spawn_metadata = lambda _job: None
    barrier.wait(timeout=15)
    result = host.enqueue('https://example.com/same-media', 'audio')
    results.put((result['ok'], result.get('code')))


class QueueStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kitty-store-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / 'queue.json'
        self.lock = self.home / 'queue.lock'
        self.backups = self.home / 'backups'

    def seed(self, **changes):
        state = store.default_state()
        state.update(changes)
        store.atomic_json(self.path, state)

    def mutate(self, fn):
        return store.mutate_state(self.path, self.lock, fn)

    def test_reads_and_noops_do_not_replace_file(self):
        self.seed()
        before = self.path.stat()
        original = self.path.read_bytes()
        with patch.object(store, 'atomic_json', side_effect=AssertionError('unexpected write')):
            for _ in range(12):
                store.read_state(self.path, self.lock)
                self.mutate(lambda d: None)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.path.stat().st_ino, before.st_ino)

    def test_missing_read_and_late_metadata_do_not_create_queue(self):
        self.assertEqual(store.read_state(self.path, self.lock), store.default_state())
        self.mutate(lambda d: store.update_job(d, 'removed', {'title': 'late'}))
        self.assertFalse(self.path.exists())

    def test_read_returns_independent_snapshot(self):
        self.seed(queue=[{'id': 'one', 'status': 'queued', 'extra': {'x': 1}}])
        first = store.read_state(self.path, self.lock)
        first['queue'][0]['extra']['x'] = 2
        self.assertEqual(store.read_state(self.path, self.lock)['queue'][0]['extra']['x'], 1)

    def test_host_worker_snapshots_are_readonly(self):
        host = load_backend('host', self.home)
        worker = load_backend('worker', self.home)
        host.with_state(lambda d: d.update(queue_paused=True))
        with patch.object(store, 'atomic_json', side_effect=AssertionError('unexpected write')):
            self.assertEqual(host.snapshot(), worker.get_state())
            host.repair_state()

    def test_migration_is_persisted_and_backed_up_once(self):
        old = {'queue': [{'id': 'q', 'status': 'paused_queue'}], 'history': []}
        self.path.write_text(json.dumps(old))
        state = store.read_state(self.path, self.lock, recover=True, backup_dir=self.backups)
        self.assertTrue(state['queue'][0]['paused'])
        self.assertEqual(json.loads(self.path.read_text()), state)
        self.assertEqual(len(list(self.backups.glob('queue-pre-migration-*.json'))), 1)
        with patch.object(store, 'atomic_json', side_effect=AssertionError('second migration')):
            store.read_state(self.path, self.lock, recover=True, backup_dir=self.backups)

    def test_changed_current_schema_is_backed_up(self):
        self.seed(queue=['invalid'], history=[{'id': str(i)} for i in range(70)])
        state = store.read_state(self.path, self.lock, recover=True, backup_dir=self.backups)
        self.assertEqual(state['queue'], [])
        self.assertEqual(len(state['history']), 50)
        self.assertEqual(len(list(self.backups.glob('queue-pre-migration-*.json'))), 1)

    def test_corrupt_utf8_recovery_preserves_original(self):
        original = b'\xff\xfe corrupt'
        self.path.write_bytes(original)
        state = store.read_state(self.path, self.lock, recover=True, backup_dir=self.backups)
        self.assertEqual(state, store.default_state())
        backup = next(self.backups.glob('queue-corrupt-*.json'))
        self.assertEqual(backup.read_bytes(), original)

    def test_corrupt_file_refused_by_worker_and_maintenance(self):
        for name in ('worker', 'maintenance'):
            backend = load_backend(name, self.home)
            backend.QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            backend.QUEUE_FILE.write_bytes(b'{ broken')
            action = backend.get_state if name == 'worker' else backend._freeze_queue_and_collect_pids
            with self.assertRaises(store.QueueStateError):
                action()
            self.assertEqual(backend.QUEUE_FILE.read_bytes(), b'{ broken')

    def test_future_schema_blocks_all_writers(self):
        for name in ('host', 'worker', 'metadata', 'maintenance'):
            backend = load_backend(name, self.home)
            backend.QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            original = json.dumps({'state_version': 999, 'queue': [{'id': 'future'}]}).encode()
            backend.QUEUE_FILE.write_bytes(original)
            if name == 'metadata':
                self.assertFalse(backend.mutate_job('future', title='bad'))
            else:
                action = {'host': lambda: backend.with_state(lambda d: d.clear()),
                          'worker': lambda: backend.locked_mutate(lambda d: d.clear()),
                          'maintenance': backend._freeze_queue_and_collect_pids if name == 'maintenance' else None}[name]
                with self.assertRaises(store.FutureStateVersion):
                    action()
            self.assertEqual(backend.QUEUE_FILE.read_bytes(), original)

    def test_failed_backup_never_resets_corruption(self):
        self.path.write_bytes(b'{ bad')
        with patch.object(store, 'backup_state_file', side_effect=PermissionError('backup denied')):
            with self.assertRaises(PermissionError):
                store.read_state(self.path, self.lock, recover=True, backup_dir=self.backups)
        self.assertEqual(self.path.read_bytes(), b'{ bad')

    def test_read_permission_error_never_triggers_recovery(self):
        self.seed()
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('read denied')):
            with patch.object(store, 'backup_state_file') as backup:
                with self.assertRaises(PermissionError):
                    store.read_state(self.path, self.lock, recover=True, backup_dir=self.backups)
                backup.assert_not_called()

    def test_failed_callback_keeps_original_and_releases_lock(self):
        self.seed()
        original = self.path.read_bytes()
        def fail(d):
            d['queue_paused'] = True
            raise RuntimeError('interrupted mutation')
        with self.assertRaises(RuntimeError):
            self.mutate(fail)
        self.assertEqual(self.path.read_bytes(), original)
        self.mutate(lambda d: d.update(queue_paused=True))
        self.assertTrue(store.read_state(self.path, self.lock)['queue_paused'])

    def test_failed_replace_and_signal_leave_no_temporary_file(self):
        self.seed()
        original = self.path.read_bytes()
        for failure in (OSError('disk failure'), KeyboardInterrupt()):
            with patch.object(store.os, 'replace', side_effect=failure):
                with self.assertRaises(type(failure)):
                    self.mutate(lambda d: d.update(queue_paused=True))
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(list(self.home.glob('.queue.json.tmp-*')), [])
        self.mutate(lambda d: d.update(queue_paused=True))

    def test_every_writer_bounds_history(self):
        self.mutate(lambda d: d.update(history=[{'id': str(i)} for i in range(80)]))
        self.assertEqual(len(json.loads(self.path.read_text())['history']), 50)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_real_concurrent_writers_lose_no_updates(self):
        ctx = multiprocessing.get_context('spawn')
        barrier = ctx.Barrier(6)
        processes = [ctx.Process(target=count_writer, args=(str(self.path), str(self.lock), barrier)) for _ in range(6)]
        for p in processes:
            p.start()
            self.addCleanup(lambda p=p: p.terminate() if p.is_alive() else None)
        for p in processes:
            p.join(20)
            self.assertEqual(p.exitcode, 0)
        self.assertEqual(store.read_state(self.path, self.lock)['counter'], 180)

    def test_simultaneous_enqueue_keeps_one_job(self):
        host = load_backend('host', self.home)
        host.with_state(lambda d: d.update(queue_paused=True))
        ctx = multiprocessing.get_context('spawn')
        barrier = ctx.Barrier(6)
        results = ctx.Queue()
        processes = [ctx.Process(target=duplicate_writer, args=(str(self.home), barrier, results)) for _ in range(6)]
        for p in processes:
            p.start()
            self.addCleanup(lambda p=p: p.terminate() if p.is_alive() else None)
        for p in processes:
            p.join(20)
            self.assertEqual(p.exitcode, 0)
        outcomes = [results.get(timeout=3) for _ in processes]
        self.assertEqual(sum(ok for ok, _ in outcomes), 1)
        self.assertEqual(sum(code == 'already_queued' for _, code in outcomes), 5)
        self.assertEqual(len(host.snapshot()['queue']), 1)
        results.close()

    def test_stale_worker_cannot_update_or_finish_successor(self):
        host = load_backend('host', self.home)
        worker = load_backend('worker', self.home)
        host.with_state(lambda d: d.update(active={'id': 'new', 'status': 'downloading'}))
        worker.current_job_id = 'old'
        self.assertFalse(worker.update_active(downloaded=999, worker_pid=999))
        worker.finish_active('finished', filepath='wrong-file')
        state = host.snapshot()
        self.assertEqual(state['active'], {'id': 'new', 'status': 'downloading'})
        self.assertEqual(state['history'], [])

    def test_worker_pid_write_does_not_overwrite_successor(self):
        worker = load_backend('worker', self.home)
        worker.current_job_id = 'old'
        worker.locked_mutate(lambda d: d.update(queue=[{'id': 'next', 'status': 'queued'}]))
        def fast_child(*args, **kwargs):
            worker.locked_mutate(lambda d: d.update(active={'id': 'successor', 'status': 'downloading', 'worker_pid': 77}))
            return SimpleNamespace(pid=88)
        with patch.object(worker.subprocess, 'Popen', side_effect=fast_child), patch.object(worker.time, 'sleep'):
            worker.start_next_if_any()
        self.assertEqual(worker.get_state()['active']['worker_pid'], 77)

    def test_metadata_launch_is_reserved_once_and_missing_job_not_spawned(self):
        host = load_backend('host', self.home)
        host.META_WORKER = NATIVE / 'metadata.py'
        job = {'id': 'meta', 'url': 'https://example.com/media', 'status': 'queued'}
        host.with_state(lambda d: d['queue'].append(job))
        with patch.object(host.subprocess, 'Popen', return_value=SimpleNamespace(pid=99)) as popen:
            self.assertEqual(host.spawn_metadata(job), 99)
            self.assertIsNone(host.spawn_metadata(job))
            self.assertIsNone(host.spawn_metadata(dict(job, id='removed')))
            self.assertEqual(popen.call_count, 1)

    def test_signal_handler_never_acquires_log_lock(self):
        worker = load_backend('worker', self.home)
        with patch.object(worker, 'log', side_effect=AssertionError('lock in signal')):
            with self.assertRaises(worker.WorkerShutdown):
                worker.handle_signal(15, None)

    def test_failed_spawn_restores_job_and_pauses_queue(self):
        for name in ('host', 'worker'):
            backend = load_backend(name, self.home)
            def seed(d):
                d.clear()
                d.update(store.default_state())
                d['queue'] = [{'id': 'launch', 'status': 'queued'}]
            mutate = backend.with_state if name == 'host' else backend.locked_mutate
            mutate(seed)
            action = backend.start_next_if_idle if name == 'host' else backend.start_next_if_any
            with patch.object(backend.subprocess, 'Popen', side_effect=OSError('cannot spawn')):
                with self.assertRaises(OSError):
                    action()
            state = backend.snapshot() if name == 'host' else backend.get_state()
            self.assertIsNone(state['active'])
            self.assertTrue(state['queue_paused'])
            self.assertEqual([job['id'] for job in state['queue']], ['launch'])

    def test_future_schema_native_response_is_framed(self):
        host = load_backend('host', self.home)
        host.QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        original = b'{"state_version":999,"queue":[]}'
        host.QUEUE_FILE.write_bytes(original)
        payload = json.dumps({'action': 'status', 'client': {'version': '8.31', 'protocol': 1}}).encode()
        env = os.environ.copy()
        env['HOME'] = str(self.home)
        proc = subprocess.run([sys.executable, str(NATIVE/'host.py')], input=struct.pack('<I',len(payload))+payload,
                              env=env, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        size = struct.unpack('<I', proc.stdout[:4])[0]
        result = json.loads(proc.stdout[4:4+size])
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'queue_state_unavailable')
        self.assertEqual(host.QUEUE_FILE.read_bytes(), original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
