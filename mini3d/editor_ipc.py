"""Loopback transport only. Scene/API/GL work is performed by Runtime.pump.

The HTTP thread never touches Editor state. A random per-instance capability is
published in the user's temporary directory, and is required for every request.
"""
from concurrent.futures import Future, TimeoutError, CancelledError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
from queue import Queue, Empty, Full
import secrets
import tempfile
import threading
import time
import uuid


def registry_directory():
    return Path(tempfile.gettempdir()) / 'mini3d-ipc'


def error(kind, message, **extra):
    return dict(ok=False, error=dict(type=kind, message=message, **extra))


class EditorIPC:
    """Bounded, cancellable queue owned and pumped by the editor thread."""
    def __init__(self, api, directory=None, request_timeout=10, capacity=32):
        self.api = api
        self.owner = threading.get_ident()
        self.request_timeout = request_timeout
        self.queues = {'scene': Queue(capacity), 'frame': Queue(capacity)}
        self.closed = False
        self.queue_lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.instance_id = uuid.uuid4().hex
        directory = registry_directory() if directory is None else Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.discovery_path = directory / (self.instance_id + '.json')
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, result):
                body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (OSError, ConnectionError):
                    pass

            def do_POST(self):
                # Browser requests are not an authorized local client.
                if self.headers.get('Origin') is not None or not hmac.compare_digest(
                        self.headers.get('Authorization', '').encode('utf8'),
                        ('Bearer ' + bridge.token).encode('utf8')):
                    self.reply(403, error('Unauthorized', 'An instance capability is required'))
                    return
                if self.path != '/dispatch':
                    self.reply(404, error('NotFound', 'Use POST /dispatch'))
                    return
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                        raise ValueError('A JSON body of at most 1 MiB is required')
                    self.connection.settimeout(5)
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError('Incomplete request body')
                    def invalid(value):
                        raise ValueError('Non-finite JSON number: ' + value)
                    command = json.loads(raw.decode('utf8'), parse_constant=invalid)
                    if not isinstance(command, dict):
                        raise ValueError('Command must be an object')
                except (ValueError, UnicodeError, OSError) as exc:
                    self.reply(400, error('ValueError', str(exc)))
                    return
                future = Future()
                phase = 'frame' if command.get('command') == 'screenshot' else 'scene'
                try:
                    with bridge.queue_lock:
                        if bridge.closed:
                            self.reply(503, error('EditorClosed', 'Editor is shutting down'))
                            return
                        bridge.queues[phase].put_nowait((command, future, time.monotonic() + bridge.request_timeout))
                except Full:
                    self.reply(503, error('QueueFull', 'Editor request queue is full'))
                    return
                try:
                    result = future.result(timeout=bridge.request_timeout)
                except (TimeoutError, CancelledError):
                    cancelled = future.cancel()
                    result = error('RequestTimeout', 'Editor request timed out; do not automatically retry writes',
                                   outcome_unknown=not cancelled)
                self.reply(200, result)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.info = dict(protocol=1, instance_id=self.instance_id, pid=os.getpid(),
                         host='127.0.0.1', port=self.server.server_port, token=self.token,
                         project=str(Path(__file__).resolve().parents[1]),
                         title='Mini3D Editor 0.1', started_at=time.time())
        try:
            self.discovery_path.touch(mode=0o600, exist_ok=False)
            self.discovery_path.write_text(json.dumps(self.info), encoding='utf8')
            self.thread = threading.Thread(target=self.server.serve_forever, name='mini3d-ipc', daemon=True)
            self.thread.start()
        except BaseException:
            self.discovery_path.unlink(missing_ok=True)
            self.server.server_close()
            raise

    def pump(self, phase='scene', max_requests=8):
        """Only called at safe frame boundaries with the editor GL context."""
        if threading.get_ident() != self.owner:
            raise RuntimeError('IPC must be pumped by the Editor main thread')
        from .api_dispatch import dispatch, READ_METHODS
        queue = self.queues[phase]
        for _ in range(max_requests):
            try:
                command, future, deadline = queue.get_nowait()
            except Empty:
                break
            if time.monotonic() >= deadline:
                future.cancel()
            if not future.set_running_or_notify_cancel():
                continue
            if self.closed:
                result = error('EditorClosed', 'Editor is shutting down')
            elif self.api._commands.active_transaction and not (
                    isinstance(command.get('command'), str) and command['command'] in READ_METHODS):
                result = error('EditorBusy', 'Finish the current editor gesture before external writes')
            else:
                result = dispatch(self.api, command)
            future.set_result(result)

    def close(self):
        with self.queue_lock:
            if self.closed:
                return
            self.closed = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for queue in self.queues.values():
            while True:
                try:
                    _, future, _ = queue.get_nowait()
                except Empty:
                    break
                if future.set_running_or_notify_cancel():
                    future.set_result(error('EditorClosed', 'Editor is shutting down'))
        self.discovery_path.unlink(missing_ok=True)
