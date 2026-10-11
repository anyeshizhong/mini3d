"""Human acceptance: attach, observe a manual move, then move the same entity.

Never starts an Editor. Leave the resulting API move visible for inspection.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mini3d.ipc_client import connect


def run(instance_id, entity_id, output, wait_seconds=180, delta=(.5, 0, 0)):
    client = connect(instance_id)
    def call(command, **args):
        result = client.call(command, **args)
        if not result['ok']:
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        return result['result']
    state = call('get_scene_state')
    entity_id = entity_id or state['primary_selection_id']
    if entity_id is None:
        raise ValueError('Select the soldier in the current editor, or supply --entity')
    entity = call('get_entity', entity_id=entity_id)
    output.mkdir(parents=True, exist_ok=False)
    call('screenshot', path=str(output / 'before.png'))
    print('Attached to instance={} pid={} entity={} name={}'.format(
        client.instance['instance_id'], client.instance['pid'], entity_id, entity['name']), flush=True)
    print('Current position: {}'.format(entity['position']), flush=True)
    print('Move this soldier manually in the editor and release the mouse. '
          'The API will then add {} to its position.'.format(list(delta)), flush=True)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        current = call('get_entity', entity_id=entity_id)
        scene = call('get_scene_state')
        if current['position'] != entity['position'] and not scene['history']['active_transaction']:
            # Re-read after the gesture commit on the same editor main thread.
            manual = call('get_entity', entity_id=entity_id)
            if manual['position'] == entity['position']:
                continue
            print('Latest manual position: {}'.format(manual['position']), flush=True)
            call('screenshot', path=str(output / 'manual.png'))
            target = [value + step for value, step in zip(manual['position'], delta)]
            moved = call('set_transform', entity_id=entity_id, position=target)
            actual = call('get_entity', entity_id=entity_id)
            if moved['position'] != target or actual['position'] != target:
                raise RuntimeError('The live entity did not reach the requested API position')
            screenshot = call('screenshot', path=str(output / 'api-moved.png'))
            result = dict(passed=True, instance_id=client.instance['instance_id'],
                editor_pid=client.instance['pid'], entity_id=entity_id,
                before=entity['position'], manual=manual['position'], api=actual['position'],
                screenshot=screenshot, gesture='human movement observed on the live editor API')
            (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            return result
        time.sleep(.25)
    raise TimeoutError('No completed manual movement observed; no API move was issued')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', help='Instance ID from python -m mini3d.ipc_client --list')
    parser.add_argument('--entity', help='Stable entity ID; defaults to the current primary selection')
    parser.add_argument('--output', type=Path, required=True, help='New acceptance evidence directory')
    parser.add_argument('--wait', type=float, default=180, help='Seconds to wait for manual movement')
    parser.add_argument('--delta', type=float, nargs=3, default=[.5, 0, 0])
    args = parser.parse_args()
    try:
        run(args.instance, args.entity, args.output.resolve(), args.wait, args.delta)
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
