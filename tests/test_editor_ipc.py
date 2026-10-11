"""Transport must share live Editor state and never execute on an IO thread."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mini3d.api import Mini3DAPI
from mini3d.editor import Editor, PROJECT
from mini3d.editor_ipc import EditorIPC
from mini3d.ipc_client import EditorClient, connect, discover


class EditorIPCTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Editor()
        self.addCleanup(self.app.model_dialog.close)
        self.api = Mini3DAPI(editor=self.app)
        self.bridge = EditorIPC(self.api, self.directory.name, request_timeout=.2, capacity=2)
        self.addCleanup(self.bridge.close)
        self.client = EditorClient(self.bridge.info)
        self.pool = ThreadPoolExecutor(4)
        self.addCleanup(self.pool.shutdown)

    def request(self, command, **args):
        future = self.pool.submit(self.client.call, command, **args)
        deadline = time.monotonic() + 2
        while not future.done() and time.monotonic() < deadline:
            self.bridge.pump()
            self.bridge.pump('frame')
            time.sleep(.002)
        return future.result(2)

    def queued(self, command, **args):
        future = self.pool.submit(self.client.call, command, **args)
        deadline = time.monotonic() + 2
        phase = 'frame' if command == 'screenshot' else 'scene'
        while self.bridge.queues[phase].empty() and not future.done() and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertFalse(self.bridge.queues[phase].empty())
        return future

    def test_live_manual_state_transform_history_and_thread(self):
        entity = self.app.commands.spawn(PROJECT / 'model/06_stl_cube/cube.STL')
        with self.app.commands.transaction('Manual UI edit'):
            self.app.commands.set_transform(entity, position=[1, 2, 3])
        self.assertEqual(self.request('get_entity', entity_id=entity.entity_id)['result']['position'], [1, 2, 3])
        future = self.queued('set_transform', entity_id=entity.entity_id, position=[4, 5, 6])
        self.assertEqual(entity.pos.tolist(), [1, 2, 3])
        called_on = []
        original = self.api.set_transform
        def tracked(**args):
            called_on.append(threading.get_ident())
            return original(**args)
        with patch.object(self.api, 'set_transform', tracked):
            self.bridge.pump()
        self.assertTrue(future.result(2)['ok'])
        self.assertEqual(called_on, [threading.get_ident()])
        self.app.undo()
        self.assertEqual(entity.pos.tolist(), [1, 2, 3])
        self.assertTrue(self.request('redo')['result']['changed'])
        self.assertEqual(entity.pos.tolist(), [4, 5, 6])

    def test_gesture_reads_live_and_rejects_writes_without_merging_history(self):
        entity = self.app.commands.spawn(PROJECT / 'model/06_stl_cube/cube.STL')
        before = self.app.commands.undo_count
        self.app.commands.begin_transaction('Manual drag')
        self.app.commands.set_transform(entity, position=[7, 8, 9])
        self.assertEqual(self.request('get_entity', entity_id=entity.entity_id)['result']['position'], [7, 8, 9])
        for command, args in [('set_transform', dict(entity_id=entity.entity_id, position=[0, 0, 0])),
                              ('undo', {}), ('set_lighting', dict(ambient=.5)),
                              ('transaction', dict(commands=[]))]:
            self.assertEqual(self.request(command, **args)['error']['type'], 'EditorBusy')
        self.assertTrue(self.app.commands.active_transaction)
        self.app.commands.commit_transaction()
        self.assertEqual(self.app.commands.undo_count, before + 1)
        self.assertTrue(self.request('set_transform', entity_id=entity.entity_id, position=[0, 0, 0])['ok'])
        self.assertEqual(self.app.commands.undo_count, before + 2)

    def test_timeout_cancels_queued_write(self):
        entity = self.app.commands.spawn(PROJECT / 'model/06_stl_cube/cube.STL')
        initial = entity.pos.tolist()
        future = self.queued('set_transform', entity_id=entity.entity_id, position=[9, 9, 9])
        result = future.result(2)
        self.assertEqual(result['error']['type'], 'RequestTimeout')
        self.assertFalse(result['error']['outcome_unknown'])
        self.bridge.pump()
        self.assertEqual(entity.pos.tolist(), initial)

    def test_deadline_cancelled_by_pump_still_returns_json(self):
        future = self.queued('get_scene_state')
        # Expire in the pump before the HTTP waiting thread times out.
        command, pending, _ = self.bridge.queues['scene'].get_nowait()
        self.bridge.queues['scene'].put_nowait((command, pending, time.monotonic() - 1))
        self.bridge.pump()
        result = future.result(2)
        self.assertEqual(result['error']['type'], 'RequestTimeout')
        self.assertFalse(result['error']['outcome_unknown'])

    def test_started_call_timeout_reports_unknown_and_does_not_retry(self):
        calls = []
        def slow():
            calls.append(threading.get_ident())
            time.sleep(.3)
            return dict(changed=True)
        with patch.object(self.api, 'undo', slow):
            future = self.queued('undo')
            self.bridge.pump()
        result = future.result(2)
        self.assertEqual(result['error']['type'], 'RequestTimeout')
        self.assertTrue(result['error']['outcome_unknown'])
        self.assertEqual(calls, [threading.get_ident()])

    def test_auth_origin_size_and_nonfinite_json_rejected_before_queue(self):
        for headers, body in [({}, '{}'),
                ({'Authorization': 'Bearer ' + self.bridge.token, 'Origin': 'http://localhost'}, '{}'),
                ({'Authorization': 'Bearer ' + self.bridge.token}, '{"args":{"x":NaN}}'),
                ({'Authorization': 'Bearer ' + self.bridge.token,
                  'Content-Length': str(1024 * 1024 + 1)}, '{}')]:
            connection = http.client.HTTPConnection('127.0.0.1', self.bridge.info['port'], timeout=2)
            connection.request('POST', '/dispatch', body, headers)
            response = connection.getresponse()
            self.assertIn(response.status, (400, 403))
            self.assertFalse(json.loads(response.read())['ok'])
            connection.close()
            self.assertTrue(self.bridge.queues['scene'].empty())

    def test_queue_full_and_shutdown_reply_cleanup(self):
        first = self.queued('get_scene_state')
        second = self.pool.submit(self.client.call, 'get_scene_state')
        deadline = time.monotonic() + 2
        while self.bridge.queues['scene'].qsize() != 2 and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertEqual(self.client.call('get_scene_state')['error']['type'], 'QueueFull')
        self.bridge.close()
        self.assertFalse(self.bridge.discovery_path.exists())
        self.assertIn(first.result(2)['error']['type'], ('EditorClosed', 'RequestTimeout'))
        self.assertIn(second.result(2)['error']['type'], ('EditorClosed', 'RequestTimeout'))

    def test_screenshot_waits_for_completed_frame_and_wrong_thread_cannot_pump(self):
        recorded = []
        self.api._screenshot = lambda path: recorded.append(threading.get_ident()) or dict(path=str(path))
        future = self.queued('screenshot', path='captures/ipc-test.png')
        self.bridge.pump()
        self.assertFalse(future.done())
        self.bridge.pump('frame')
        self.assertTrue(future.result(2)['ok'])
        self.assertEqual(recorded, [threading.get_ident()])
        future = self.pool.submit(self.bridge.pump)
        with self.assertRaisesRegex(RuntimeError, 'main thread'):
            future.result(2)
        self.app.commands.begin_transaction('Manual drag')
        result = self.request([])
        self.assertEqual(result['error']['type'], 'EditorBusy')
        self.assertTrue(self.app.commands.active_transaction)
        self.app.commands.cancel_transaction()

    def test_discovery_stale_files_and_multiple_instances(self):
        other = EditorIPC(self.api, self.directory.name, request_timeout=.2)
        self.addCleanup(other.close)
        (Path(self.directory.name) / 'corrupt.json').write_text('{}')
        def run_discovery(function):
            future = self.pool.submit(function)
            deadline = time.monotonic() + 2
            while not future.done() and time.monotonic() < deadline:
                self.bridge.pump()
                other.pump()
                time.sleep(.002)
            return future.result(2)
        instances = run_discovery(lambda: discover(self.directory.name))
        self.assertEqual(len(instances), 2)
        with self.assertRaisesRegex(RuntimeError, 'found 2'):
            run_discovery(lambda: connect(directory=self.directory.name))
        client = run_discovery(lambda: connect(self.bridge.instance_id, self.directory.name))
        self.assertEqual(client.instance['instance_id'], self.bridge.instance_id)

    def test_client_does_not_import_editor(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-B', '-c',
            "import mini3d.ipc_client,sys; assert 'mini3d.editor' not in sys.modules; "
            "assert 'pygame' not in sys.modules; assert 'OpenGL' not in sys.modules"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
