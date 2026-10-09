"""Compare real PNG output across process restart without recreating the shot.

python -B tests/shot_camera_persistence_smoke.py [output-directory]
Requires desktop OpenGL; uses the distributed STL fixture and a hidden window.
"""
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch_json
from mini3d.gl_renderer import GLRenderer


def call(api, command, **args):
    response = json.loads(dispatch_json(api, json.dumps(dict(command=command, args=args))))
    assert response['ok'], response
    return response['result']


def pixels(path):
    surface = pygame.image.load(str(path))
    assert surface.get_size() == (1920, 1440)
    return pygame.surfarray.array3d(surface)


def phase(output, restore):
    pygame.init()
    renderer = None
    try:
        pygame.display.set_mode((640, 360), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
        renderer = GLRenderer(640, 360)
        api = Mini3DAPI(renderer=renderer)
        scene_path = str(output / 'scene.json')
        if restore:
            expected = json.loads((output / 'state.json').read_text(encoding='utf8'))
            with patch.object(api, 'create_shot_camera', side_effect=AssertionError('Must restore shot')):
                actual = call(api, 'load_scene', path=scene_path)
                for key in expected.keys() - {'history'}:
                    assert actual[key] == expected[key], key
                call(api, 'capture', path=str(output / 'after.png'))
                np.testing.assert_array_equal(pixels(output / 'before.png'), pixels(output / 'after.png'))
                # Browsing the editor and switching views must not change the saved shot.
                app = api._app
                app.set_camera_view(True)
                app.set_camera_view(False)
                app.viewer.controller.orbit(80, 20)
                app.viewer.controller.pan(12, 8, 360)
                app.viewer.controller.zoom(-1)
                app.set_camera_view(True)
                call(api, 'capture', path=str(output / 'after-navigation.png'))
                np.testing.assert_array_equal(pixels(output / 'before.png'),
                                              pixels(output / 'after-navigation.png'))
                assert call(api, 'get_shot_camera') == expected['shot_camera']
                call(api, 'save_scene', path=str(output / 'resaved.json'))
            result = dict(ok=True, gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                          size=[1920, 1440], changed_pixels_after_restart=0,
                          changed_pixels_after_navigation=0, camera=expected['shot_camera'])
            (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        else:
            cube = api.spawn(ROOT / 'model/06_stl_cube/cube.STL', scale=[.1] * 3)
            api.place_on_ground(cube['entity_id'], x=0, y=0)
            api.spawn('builtin:ground')
            api.set_lighting(mode='Scene', direction=[1, -1, 2], ambient=.2, diffuse=1.8)
            api.set_shadows(enabled=True, resolution=1024, bias=.001, pcf=True)
            api.create_shot_camera(position=[6, -8, 6], target=[0, 0, .5],
                                   focal_mm=35, aspect='4:3', near=.05, far=100)
            call(api, 'capture', path=str(output / 'before.png'))
            rgb = pixels(output / 'before.png').astype(float)
            assert np.count_nonzero(np.max(np.abs(rgb - [30, 30, 35]), axis=2) > 5) > 10000
            assert np.unique(rgb.reshape(-1, 3), axis=0).shape[0] > 8, 'Expected shaded geometry and shadow detail'
            call(api, 'save_scene', path=scene_path)
            (output / 'state.json').write_text(json.dumps(api.get_scene_state(), indent=2), encoding='utf8')
        assert gl.glGetError() == gl.GL_NO_ERROR
    finally:
        if renderer is not None:
            renderer.close()
        pygame.quit()


if __name__ == '__main__':
    output = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'captures/shot-camera-persistence').resolve()
    output.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 2:
        phase(output, restore=sys.argv[2] == 'restore')
    else:
        for mode in ('save', 'restore'):
            subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), str(output), mode],
                           check=True, cwd=str(ROOT))
        print('PASS: fresh process restores Shot Camera through JSON API; restart/navigation PNGs exactly match')
        print(output / 'result.json')
