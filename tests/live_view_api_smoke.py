"""Real SDL/ImGui/GL and IPC checks for the shared visible camera.

UI workspace actions are injected through the actual UI command handler;
this is automated acceptance, not a claim of human mouse testing.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def editor_process(output, scene):
    from unittest.mock import patch
    import pygame
    from mini3d.editor import Editor
    from mini3d.editor_runtime import run
    from mini3d.editor_ui import EditorUI
    real_events, real_init = pygame.event.get, EditorUI.__init__
    uis = []

    class App(Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.composition_grid = False
            self.show_grid = False
            if scene is None:
                self.commands.spawn('builtin:roman-soldier', name='View API subject')
                self.frame_all()

    def ui_init(ui, app):
        real_init(ui, app)
        uis.append(ui)

    def events():
        if (output / 'stop').exists():
            return [pygame.event.Event(pygame.QUIT)]
        if uis and (output / 'ui-lighting').exists() and not (output / 'ui-done').exists():
            uis[0]._choose_workspace('Lighting')
            (output / 'ui-done').write_text('done', encoding='utf8')
        return real_events()

    with patch.object(pygame.event, 'get', events), patch.object(EditorUI, '__init__', ui_init):
        run(App, initial_asset=None, hidden=True, ipc_directory=output / 'registry', scene_path=scene)


def acceptance(output, scene):
    from mini3d.ipc_client import EditorClient, discover
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'editor.log').open('w', encoding='utf8') as log:
        args = [sys.executable, '-B', str(Path(__file__).resolve()), '--editor', '--output', str(output)]
        if scene is not None:
            args += ['--scene', str(scene)]
        process = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 45
            instances = []
            while not instances and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError((output / 'editor.log').read_text(encoding='utf8'))
                instances = discover(output / 'registry')
                time.sleep(.05)
            assert len(instances) == 1, instances
            assert instances[0]['pid'] == process.pid
            client = EditorClient(instances[0])

            def call(command, **kwargs):
                result = client.call(command, **kwargs)
                assert result['ok'], result
                return result['result']

            def observe(view, workspace):
                state = call('get_view_state')
                assert state['view'] == view and state['workspace'] == workspace, state
                assert state['view_matches_displayed_frame'], state
                assert state['displayed_frame']['view_state']['active_camera'] == state['active_camera']
                return state

            entity = call('list_entities')[0]
            entity_id = entity['entity_id']
            call('set_view', view='Editor')
            call('set_workspace', workspace='Arrange')
            before = call('get_scene_state')['history']
            call('focus_entity', entity_id=entity_id)
            editor = observe('Editor', 'Arrange')
            screenshot = call('screenshot', path=str(output / 'focused-editor.png'))
            assert screenshot['displayed_frame']['view_state']['view'] == 'Editor'
            call('set_workspace', workspace='Shot')
            shot = call('create_camera_from_view')
            call('select_entities', entity_ids=[])
            call('set_view', view='Camera')
            photo = observe('Camera', 'Shot')
            assert photo['active_camera']['position'] == shot['position']
            assert shot['position'] == editor['editor_camera']['position']
            time.sleep(.25)  # Let the existing adaptive preview settle before the screenshot.
            screenshot = call('screenshot', path=str(output / 'camera-view.png'))
            assert screenshot['displayed_frame']['view_state']['active_camera']['position'] == shot['position']
            call('capture', path=str(output / 'camera-photo.png'))
            call('set_view', view='Editor')
            editing = observe('Editor', 'Shot')
            assert editing['active_camera']['position'] == shot['position']
            assert editing['active_camera']['fov_y'] == shot['fov_y']
            time.sleep(.25)
            call('screenshot', path=str(output / 'same-framing-editor.png'))
            from PIL import Image
            import numpy as np
            camera_pixels = np.asarray(Image.open(output / 'camera-view.png').convert('RGB'))
            editor_pixels = np.asarray(Image.open(output / 'same-framing-editor.png').convert('RGB'))
            x,y,w,h = editing['viewport']
            difference = np.abs(camera_pixels[y:y+h,x:x+w].astype(float) -
                                editor_pixels[y:y+h,x:x+w].astype(float))
            pixel_error = float(difference.mean())
            assert pixel_error < 1.0, pixel_error
            call('set_view', view='Camera')
            shot = call('get_shot_camera')
            (output / 'ui-lighting').touch()
            deadline = time.monotonic() + 5
            while not (output / 'ui-done').exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert (output / 'ui-done').exists()
            ui_state = observe('Editor', 'Lighting')
            call('frame_all')
            call('set_editor_view', preset='front')
            front = observe('Editor', 'Lighting')
            assert call('get_shot_camera') == shot
            assert call('get_scene_state')['history'] == before
            report = dict(ok=True, instance_id=instances[0]['instance_id'],
                          editor=editor, camera=photo, ui_workspace_change=ui_state, front=front,
                          history_preserved=True, same_editor_and_shot_pose=True)
            report['same_framing_mean_rgb_difference'] = pixel_error
            (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps(dict(ok=True, same_editor_and_shot_pose=True,
                                  shared_workspace=True, history_preserved=True)))
        finally:
            (output / 'stop').touch()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--editor', action='store_true')
    parser.add_argument('--scene', type=Path)
    args = parser.parse_args()
    (editor_process if args.editor else acceptance)(args.output.resolve(), args.scene)
