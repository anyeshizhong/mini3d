"""Real subprocess + SDL/ImGui/OpenGL acceptance, with injected mouse gestures.

python -B tests/live_editor_ipc_smoke.py --output captures/live-ipc-smoke
The UI gesture is automated; this is not a claim that a human moved the mouse.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def editor_process(output):
    import threading
    from unittest.mock import patch
    import pygame
    from OpenGL import GL as gl
    from mini3d.editor import Editor
    from mini3d.editor_runtime import run
    from mini3d.editor_ui import EditorUI
    created = []
    gesture = dict(done=False)
    real_events, real_draw = pygame.event.get, EditorUI.draw

    class App(Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)
            soldier = self.commands.spawn(ROOT / 'model/05_roman_soldier/roman_legionnaire.glb',
                                          name='IPC acceptance soldier', scale=[.06] * 3)
            from mini3d.api import Mini3DAPI
            Mini3DAPI(editor=self).place_on_ground(soldier.entity_id)
            self.select(soldier)
            self.frame_all()

    def draw(ui, *args):
        result = real_draw(ui, *args)
        if gesture.get('events'):
            ui.viewport_hovered, ui.mouse_captured, ui.asset_dragging = True, False, False
        return result

    def events():
        result = real_events()
        if (output / 'stop').exists():
            return [pygame.event.Event(pygame.QUIT)]
        if (output / 'drag').exists() and not gesture['done']:
            app = created[0]
            _, center, _ = app.gizmo.geometry(app.viewport_rect)
            start = tuple(map(int, center))
            end = (start[0] + 55, start[1] - 12)
            gesture.update(done=True, events=True)
            result += [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start, mod=0),
                       pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(55, -12), buttons=(1, 0, 0)),
                       pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end)]
        else:
            gesture['events'] = False
        return result

    original_handle = App.handle_event
    def handle(self, event, ui):
        original_handle(self, event, ui)
        if gesture.get('events') and event.type == pygame.MOUSEBUTTONUP:
            assert not self.commands.active_transaction
            (output / 'manual.json').write_text(json.dumps(self.api.get_entity(self.selection.entity_id)), encoding='utf8')
        assert threading.current_thread() is threading.main_thread()
        assert self.api._app is self and self.api._commands is self.commands
        assert len(created) == 1
        assert gl.glGetError() == gl.GL_NO_ERROR
    with patch.object(pygame.event, 'get', events), patch.object(EditorUI, 'draw', draw), \
            patch.object(App, 'handle_event', handle):
        run(App, initial_asset=None, hidden=True, ipc_directory=output / 'registry')


def acceptance(output):
    from mini3d.ipc_client import EditorClient, discover
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'editor.log').open('w', encoding='utf8') as log:
        process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                                    '--editor', '--output', str(output)], cwd=str(ROOT), stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            instances = []
            while not instances and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError((output / 'editor.log').read_text(encoding='utf8'))
                instances = discover(output / 'registry')
                time.sleep(.05)
            assert len(instances) == 1, instances
            assert instances[0]['pid'] == process.pid
            client = EditorClient(instances[0])
            def call(command, **args):
                result = client.call(command, **args)
                assert result['ok'], result
                return result['result']
            state = call('get_scene_state')
            soldier = state['entities'][0]
            entity_id = soldier['entity_id']
            before = soldier['position']
            call('screenshot', path=str(output / 'before.png'))
            (output / 'drag').touch()
            deadline = time.monotonic() + 10
            while not (output / 'manual.json').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            manual = json.loads((output / 'manual.json').read_text(encoding='utf8'))
            latest = call('get_entity', entity_id=entity_id)
            assert latest['position'] == manual['position'] != before
            call('screenshot', path=str(output / 'manual.png'))
            expected = [latest['position'][0] + .75, latest['position'][1] + .25, latest['position'][2]]
            moved = call('set_transform', entity_id=entity_id, position=expected)
            assert moved['position'] == expected
            assert call('get_entity', entity_id=entity_id)['position'] == expected
            call('screenshot', path=str(output / 'api-moved.png'))
            assert call('undo')['changed']
            assert call('get_entity', entity_id=entity_id)['position'] == manual['position']
            assert call('redo')['changed']
            assert call('get_entity', entity_id=entity_id)['position'] == expected
            editor_camera = call('get_editor_camera')
            call('set_lighting', mode='Scene', ambient=.35, diffuse=.9)
            assert call('get_lighting')['ambient'] == .35
            call('create_shot_camera', focal_mm=50, aspect='16:9')
            call('set_lens', focal_mm=35)
            call('set_aspect', aspect='4:3')
            call('set_antialiasing', samples=4)
            call('set_lens', focal_mm=85)
            focus = call('focus_on', entity_id=entity_id)['focus_distance']
            call('set_depth_of_field', enabled=True, f_number=1.4)
            call('capture', path=str(output / 'shot.png'))
            call('set_depth_of_field', focus_distance=focus*.5)
            call('capture', path=str(output / 'defocused-shot.png'))
            call('set_depth_of_field', focus_distance=focus)
            saved = call('get_scene_state')
            call('save_scene', path=str(output / 'scene.json'))
            call('set_transform', entity_id=entity_id, position=[0, 0, 0])
            restored = call('load_scene', path=str(output / 'scene.json'))
            assert restored['entities'] == saved['entities']
            assert restored['shot_camera'] == saved['shot_camera']
            call('capture', path=str(output / 'restored-shot.png'))
            import pygame
            import numpy as np
            sharp = pygame.surfarray.array3d(pygame.image.load(str(output / 'shot.png')))
            blurred = pygame.surfarray.array3d(pygame.image.load(str(output / 'defocused-shot.png')))
            assert np.count_nonzero(sharp != blurred) > 1000, 'IPC focus change did not affect the photo'
            np.testing.assert_array_equal(sharp, pygame.surfarray.array3d(
                pygame.image.load(str(output / 'restored-shot.png'))))
            a = pygame.surfarray.array3d(pygame.image.load(str(output / 'manual.png')))
            b = pygame.surfarray.array3d(pygame.image.load(str(output / 'api-moved.png')))
            x, y, width, height = editor_camera['viewport']
            changed = int(np.count_nonzero(a[x:x+width, y:y+height] != b[x:x+width, y:y+height]))
            assert changed > 1000, changed
            results = dict(passed=True, instance_id=instances[0]['instance_id'], editor_pid=process.pid,
                gesture='injected SDL mouse events through Editor.handle_event and Gizmo',
                before=before, manual=manual['position'], api=expected,
                changed_viewport_channels=changed,
                checks=['same live Scene', 'real soldier', 'UI mouse move visible through IPC',
                        'IPC transform visible in rendered viewport', 'shared undo/redo',
                        'lighting/camera/4x MSAA/capture', 'scene and shot persistence',
                        'IPC focus/aperture changes affect real photo', 'DOF reload pixels exactly match'])
            (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf8')
            print(json.dumps(results, indent=2))
        finally:
            (output / 'stop').touch()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
        assert process.returncode == 0, (output / 'editor.log').read_text(encoding='utf8')
        assert not list((output / 'registry').glob('*.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--editor', action='store_true')
    options = parser.parse_args()
    if options.editor:
        editor_process(options.output.resolve())
    else:
        acceptance(options.output.resolve())
