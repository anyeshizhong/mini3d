"""Lighting V1 end-to-end acceptance on desktop OpenGL, using public AI APIs.

python -B tests/lighting_api_smoke.py [output-directory]
The original PBR cube is committed with the directional-light experiment.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch_json
from mini3d.camera import Camera
from mini3d.gl_renderer import GLRenderer


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((640, 480), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer = GLRenderer(640, 480)
    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(), captures={})
    api = Mini3DAPI(renderer=renderer)
    position, target = [4, -6, 4], [0, 0, 0]

    def shot(client, name):
        result = client.capture(output/(name+'.png'))
        surface = pygame.image.load(result['path'])
        assert surface.get_size() == (1920, 1080)
        rgb = pygame.surfarray.array3d(surface)
        info = client.get_shot_camera()
        camera = Camera(info['position'], info['rotation'], info['fov_y'], info['near'], info['far'])
        samples = {}
        for face, point in (('+X', [.7, 0, 0]), ('-Y', [0, -.7, 0]), ('+Z', [0, 0, .7])):
            clip = camera.projection_matrix(1920/1080) @ camera.view_matrix @ np.append(point, 1)
            screen = (clip[:2]/clip[3]*[1, -1]+1)*np.array([1920, 1080])/2
            x, y = screen.astype(int)
            assert 2 <= x < 1918 and 2 <= y < 1078
            samples[face] = np.median(rgb[x-1:x+2, y-1:y+2], axis=(0, 1)).tolist()
        report['captures'][name] = dict(lighting=client.get_lighting(), camera=info, face_rgb=samples)
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return rgb, samples

    try:
        entity = api.spawn(ROOT/'docs/lighting/pbr-cube.gltf', name='Lighting API PBR cube')
        report['entity_id'] = entity['entity_id']
        reply = json.loads(dispatch_json(api, json.dumps(dict(command='set_lighting', args=dict(
            mode='Studio', direction=[5, 0, 0], diffuse=1, ambient=0)))))
        assert reply['ok'], reply
        initial = api.get_lighting()
        api.create_shot_camera(position=position, target=target, focal_mm=50, aspect='16:9')
        before, faces = shot(api, '01-x-light')
        assert min(faces['+X']) > 30 and max(faces['-Y']+faces['+Z']) == 0
        api.set_lighting(mode='Scene')
        scene_mode, _ = shot(api, '02-scene-preview-mode')
        np.testing.assert_array_equal(before, scene_mode)
        api.set_lighting(mode='Studio')
        assert api.get_lighting() == initial
        # Same world faces with moved/rotated Camera; never compare fixed screen pixels.
        for name, eye, aim in (('03-orbit', [7, -3, 3], target),
                               ('04-translate', [7.4, -3, 3], [.4, 0, 0]),
                               ('05-rotate', [7.4, -3, 3], [.2, .1, 0])):
            api.create_shot_camera(position=eye, target=aim)
            _, faces = shot(api, name)
            assert min(faces['+X']) > 30 and max(faces['-Y']+faces['+Z']) == 0
            assert api.get_lighting() == initial
        api.create_shot_camera(position=position, target=target)
        api.set_lighting(direction=[0, -7, 0])
        _, bright = shot(api, '06-y-light')
        assert max(bright['+X']) == 0 and min(bright['-Y']) > 30
        api.set_lighting(diffuse=.25)
        _, dim = shot(api, '07-y-dim')
        assert np.all(np.array(bright['-Y']) > np.array(dim['-Y']))
        assert min(dim['-Y']) > 0 and max(dim['+X']) == 0
        api.set_lighting(ambient=.2)
        filled, ambient = shot(api, '08-ambient-fill')
        assert min(ambient['+X']) > 0
        assert np.all(np.array(ambient['-Y']) > np.array(dim['-Y']))
        expected = api.get_lighting()
        api.save_scene(output/'scene.json')
        restored = Mini3DAPI(renderer=renderer)
        assert restored.load_scene(output/'scene.json')['lighting'] == expected
        restored.create_shot_camera(position=position, target=target)
        reloaded, _ = shot(restored, '09-reloaded')
        np.testing.assert_array_equal(filled, reloaded)
        state = restored.get_scene_state()
        for invalid in (dict(mode='Scene', direction=[1, 0, 0], diffuse=-1),
                        dict(mode='Scene', direction=[0, 0, 0], ambient=.8),
                        dict(direction=[1, 0, 0], ambient=float('inf'))):
            try:
                restored.set_lighting(**invalid)
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid lighting accepted')
            assert restored.get_scene_state() == state
        unchanged, _ = shot(restored, '10-invalid-unchanged')
        np.testing.assert_array_equal(reloaded, unchanged)
        report.update(shot_ignores_preview_mode=True, reload_pixels_equal=True,
                      invalid_update_pixels_equal=True, world_direction_camera_independent=True)
        (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        # Contact sheet: actual PNGs resized only, never synthetic scene images.
        pygame.font.init()
        sheet = pygame.Surface((1280, 820))
        sheet.fill((24, 28, 35))
        font = pygame.font.SysFont('Segoe UI', 20)
        labels = [('01-x-light', 'Direction +X / direct 1 / ambient 0'),
                  ('06-y-light', 'Direction -Y / direct 1 / ambient 0'),
                  ('07-y-dim', 'Direction -Y / direct 0.25 / ambient 0'),
                  ('08-ambient-fill', 'Direction -Y / direct 0.25 / ambient 0.2')]
        for i, (name, title) in enumerate(labels):
            x, y = (i % 2)*640, (i // 2)*410
            sheet.blit(font.render(title, True, (238, 242, 249)), (x+14, y+14))
            source = pygame.image.load(str(output/(name+'.png')))
            sheet.blit(pygame.transform.smoothscale(source, (640, 360)), (x, y+42))
        pygame.image.save(sheet, str(output/'comparison.png'))
        print('PASS: API spawn -> JSON lighting -> camera-independent faces -> Shot PNG -> lighting changes'
              ' -> v3 reload -> atomic invalid input; Studio/Scene Shot PNGs exactly equal')
        print(json.dumps({name: record['face_rgb'] for name, record in report['captures'].items()}))
    finally:
        if hasattr(renderer, 'material_renderer'):
            renderer.material_renderer.close()
        pygame.quit()


if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT/'captures/lighting-v1')
