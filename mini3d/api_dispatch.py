"""Explicit JSON command whitelist; no eval, network server or NL parsing."""
import inspect
import json


METHODS = frozenset(('list_entities', 'get_entity', 'list_groups', 'get_group', 'get_scene_state',
    'spawn', 'delete', 'duplicate', 'set_transform', 'transform_many', 'place_on_ground', 'place_at',
    'lock', 'unlock', 'create_group', 'create_rectangular_formation', 'undo', 'redo',
    'save_scene', 'load_scene', 'create_shot_camera', 'get_shot_camera', 'set_lens', 'set_aspect', 'capture',
    'get_lighting', 'set_lighting', 'get_shadows', 'set_shadows', 'get_environment', 'set_environment'))
BATCH_METHODS = METHODS - {'undo', 'redo', 'save_scene', 'load_scene', 'create_shot_camera',
                         'set_lens', 'set_aspect', 'capture', 'create_rectangular_formation', 'set_lighting', 'set_shadows',
                         'set_environment'}


def _validate(api, command, allowed=METHODS):
    if not isinstance(command, dict) or set(command) - {'command', 'args'}:
        raise ValueError('Expected {"command": method, "args": {...}}')
    method, args = command.get('command'), command.get('args', {})
    if not isinstance(method, str) or method not in allowed:
        raise ValueError('Unknown or disallowed command: {!r}'.format(method))
    if not isinstance(args, dict) or any(not isinstance(key, str) for key in args):
        raise ValueError('args must be an object with named parameters')
    function = getattr(api, method)
    inspect.signature(function).bind(**args)
    return function, args


def dispatch(api, command):
    """Return JSON-safe {ok,result} or {ok,error:{type,message}}.

    transaction takes a list of placement commands with explicit stable IDs.
    No variable substitution; file/camera/lighting operations and self-transactional
    Formation cannot be mixed into a placement-only atomic batch.
    """
    try:
        if isinstance(command, dict) and command.get('command') == 'transaction':
            if set(command) - {'command', 'args'}:
                raise ValueError('Unknown transaction fields')
            args = command.get('args', {})
            if not isinstance(args, dict) or set(args) - {'label', 'commands'}:
                raise ValueError('Transaction args are label and commands')
            batch, label = args.get('commands'), args.get('label', 'JSON placement')
            if not isinstance(batch, list) or not isinstance(label, str):
                raise ValueError('Transaction requires commands list and optional string label')
            calls = [_validate(api, item, BATCH_METHODS) for item in batch]
            with api.transaction(label):
                result = [function(**values) for function, values in calls]
        else:
            function, args = _validate(api, command)
            result = function(**args)
        # Enforce the JSON boundary instead of leaking NumPy/internal objects.
        json.dumps(result, allow_nan=False)
        return dict(ok=True, result=result)
    except Exception as exc:
        # Driver/import errors also cross the JSON boundary as ordinary data.
        # BaseException (interrupts/system exit) is deliberately not swallowed.
        return dict(ok=False, error=dict(type=type(exc).__name__, message=str(exc)))


def dispatch_json(api, text):
    try:
        def invalid_constant(value):
            raise ValueError('Non-finite JSON number: ' + value)
        command = json.loads(text, parse_constant=invalid_constant)
    except (ValueError, TypeError) as exc:
        return json.dumps(dict(ok=False, error=dict(type=type(exc).__name__, message=str(exc))))
    return json.dumps(dispatch(api, command), ensure_ascii=False, allow_nan=False)
