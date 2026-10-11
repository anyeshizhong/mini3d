"""Standard-library client/CLI; never imports or constructs Editor or OpenGL."""
import argparse
import http.client
import json
from pathlib import Path
import sys
import tempfile


class EditorClient:
    def __init__(self, instance, timeout=120):
        self.instance = dict(instance)
        if self.instance.get('protocol') != 1 or self.instance.get('host') != '127.0.0.1':
            raise ValueError('Expected a local Mini3D IPC v1 instance')
        self.timeout = timeout

    def dispatch(self, command):
        connection = http.client.HTTPConnection('127.0.0.1', self.instance['port'], timeout=self.timeout)
        try:
            connection.request('POST', '/dispatch', json.dumps(command, allow_nan=False).encode('utf8'),
                               {'Authorization': 'Bearer ' + self.instance['token'],
                                'Content-Type': 'application/json'})
            response = connection.getresponse()
            result = json.loads(response.read().decode('utf8'))
            return result
        finally:
            connection.close()

    def call(self, command, **args):
        return self.dispatch(dict(command=command, args=args))


def discover(directory=None):
    """Probe live instances, excluding stale files left by crashed editors."""
    directory = Path(tempfile.gettempdir()) / 'mini3d-ipc' if directory is None else Path(directory)
    instances = []
    for path in sorted(directory.glob('*.json')):
        try:
            info = json.loads(path.read_text(encoding='utf8'))
            client = EditorClient(info, timeout=2)
            # Read-only probe also proves that the editor frame loop is alive.
            if client.call('get_editor_camera').get('ok'):
                instances.append(info)
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            continue
    return instances


def connect(instance_id=None, directory=None):
    instances = discover(directory)
    if instance_id is not None:
        instances = [item for item in instances if item['instance_id'] == instance_id]
    if len(instances) != 1:
        raise RuntimeError('Expected one live editor; found {}. Use --list and --instance to select explicitly.'
                           .format(len(instances)))
    return EditorClient(instances[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Connect to an existing Mini3D Editor; never starts one')
    parser.add_argument('--list', action='store_true', help='List live editors without exposing capabilities')
    parser.add_argument('--instance', help='Exact instance ID from --list; required when multiple editors exist')
    parser.add_argument('--file', type=Path, help='Read the existing dispatcher JSON command from a UTF-8 file')
    parser.add_argument('command', nargs='?', help='Existing dispatcher JSON command; otherwise read stdin')
    args = parser.parse_args(argv)
    try:
        if args.list:
            result = [{key: value for key, value in item.items() if key != 'token'} for item in discover()]
        else:
            if args.file:
                raw = args.file.read_text(encoding='utf8-sig')
            else:
                raw = args.command if args.command is not None else sys.stdin.read()
            result = connect(args.instance).dispatch(json.loads(raw))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if isinstance(result, list) or result.get('ok') else 1
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
        print(json.dumps(dict(ok=False, error=dict(type=type(exc).__name__, message=str(exc))), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
