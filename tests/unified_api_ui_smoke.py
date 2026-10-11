"""Actual single Editor window: JSON API edits, UI history, Shot and PNG."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pygame
from OpenGL import GL as gl
from mini3d import editor
from mini3d.api_dispatch import dispatch_json
import editor_app


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    state = dict(frame=0, checks={})
    real_get, real_flip = pygame.event.get, pygame.display.flip
    class App(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state['app'] = self
    def events():
        real_get()
        app = state['app']
        def call(command, **args):
            result = json.loads(dispatch_json(app.api, json.dumps(dict(command=command, args=args))))
            assert result['ok'], result
            return result['result']
        if state['frame'] == 0:
            entity = call('spawn', asset_path=str(ROOT/'model/06_stl_cube/cube.STL'), name='API in Editor')
            state['id'] = entity['entity_id']
            app.select(app.scene.find_by_id(state['id']))
            app.frame_all()
            state['checks']['api_uses_live_editor_and_history'] = (
                app.api._app is app and app.api._commands is app.commands)
        elif state['frame'] == 1:
            app.undo()
            assert app.scene.find_by_id(state['id']) is None
            app.redo()
            assert call('get_entity', entity_id=state['id'])['name'] == 'API in Editor'
            state['checks']['ui_undo_redo_visible_through_json'] = True
            call('create_shot_camera', position=[100,-150,80], target=[0,0,20])
            call('set_antialiasing', samples=4)
            call('set_environment', enabled=True, intensity=.8)
            call('set_shadows', enabled=True, resolution=1024)
            call('capture', path=str(output/'api-shot.png'))
            call('save_scene', path=str(output/'scene.json'))
            call('load_scene', path=str(output/'scene.json'))
            app.set_camera_view(True)
            state['checks']['api_shot_aa_environment_and_scene_in_same_ui'] = (
                app.shot_camera.samples == 4 and app.scene.environment_enabled and
                app.scene.shadows_enabled and app.camera_view)
            app.status = 'Unified V2: Editor + JSON API + Shot 4x MSAA'
        return []
    def inspect():
        if state['frame'] == 4:
            size = pygame.display.get_window_size()
            raw = gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            pygame.image.save(pygame.image.fromstring(raw,size,'RGB',True),str(output/'editor-api-camera.png'))
            assert gl.glGetError() == gl.GL_NO_ERROR
            state['checks']['camera_view_gpu_frame'] = True
        real_flip(); state['frame'] += 1
    with patch.object(editor,'Editor',App), patch.object(pygame.event,'get',events), \
            patch.object(pygame.display,'flip',inspect):
        editor_app.main(['--empty','--hidden','--frames','5'])
    assert all(state['checks'].values())
    (output/'results.json').write_text(json.dumps(state['checks'],indent=2),encoding='utf8')
    print('PASS: one Editor shares Scene, Undo/Redo, JSON API, Shot/4x MSAA/PNG')


if __name__ == '__main__':
    run(Path(sys.argv[1]))
