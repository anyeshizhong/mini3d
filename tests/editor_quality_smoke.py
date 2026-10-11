"""Replay the user's table/avocado scene and verify actual GL depth/IPC caches.

Run: python -B tests/editor_quality_smoke.py OUTPUT [BASELINE_PACKAGE_ROOT]
The baseline package must be an isolated pre-fix mini3d checkout.
"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT))
BASELINE = len(sys.argv) > 2
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import ShotCamera, render_shot
import mini3d.editor as editor_module
editor_module.PROJECT = ROOT


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    fixture = json.loads((ROOT/'tests/fixtures/editor_quality_scene.json').read_text(encoding='utf8'))
    pygame.init()
    pygame.display.set_mode((846,662), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    app, renderer, target = Editor(846,662), GLRenderer(846,662), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    try:
        for record in fixture['entities']:
            asset = record['asset_path']
            app.commands.spawn(asset if asset.startswith('builtin:') else ROOT/asset,
                position=record['position'], rotation=record['rotation'], scale=record['scale'])
        app.set_lighting(**dict(mode=fixture['lighting']['mode'],
            direction=fixture['lighting']['direction'], ambient=fixture['lighting']['ambient'],
            diffuse=fixture['lighting']['diffuse']))
        app.set_shadows(**fixture['shadows'])
        app.scene.show_grid = app.scene.show_axes = False
        avocado = app.scene.root_entities[-1]
        app.viewer.focus(avocado)
        camera = app.viewer.camera
        camera.position = np.array(fixture['camera']['position'])
        camera.rotation = np.array(fixture['camera']['rotation'])
        camera.fov_y = fixture['camera']['fov_y']
        app.viewer.controller.distance = float(np.linalg.norm(camera.position-app.viewer.controller.target))
        app.viewer.update_clipping()
        target.resize(846,662)
        report = dict(near=camera.near, far=camera.far, gpu=gl.glGetString(gl.GL_RENDERER).decode())

        def draw(name=None):
            app.scene.update()
            target.bind()
            gl.glDepthMask(True)
            gl.glDisable(gl.GL_SCISSOR_TEST)
            renderer.resize(846,662)
            renderer.render(app.scene,camera)
            raw = gl.glReadPixels(0,0,846,662,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            if name:
                pygame.image.save(pygame.image.fromstring(raw,(846,662),'RGB',True),str(output/(name+'.png')))
            return np.frombuffer(raw,np.uint8).reshape(662,846,3).copy()

        first = draw('user-view')
        matrix = renderer.shadow_map.matrix.copy()
        report['shadow_world_span'] = [float(2/np.linalg.norm(matrix[i,:3])) for i in (0,1)]
        # Isolate clipping's effect while keeping light, pose and geometry fixed.
        app.scene.shadows_enabled = False
        app.scene.render_mode = 'Unlit'
        off = draw('avocado-visible')
        avocado.visible = False
        absent = draw()
        avocado.visible = True
        diff = np.max(np.abs(off.astype(int)-absent.astype(int)),axis=2)
        report['avocado_visible_pixels'] = int(np.count_nonzero(diff>10))
        if not BASELINE:
            assert report['avocado_visible_pixels'] >= 50, report
            assert camera.near > .001, report
            # Repeated scene passes reuse depth; changes invalidate even when
            # they bypass Commands and mutate existing arrays/dicts in place.
            app.scene.shadows_enabled = True
            app.scene.render_mode = 'Lit'
            draw()
            cached = draw()
            assert renderer.shadow_map.cache_hit
            assert renderer.render_stats['shadow_draw_calls'] == 0
            np.testing.assert_array_equal(first, cached)
            avocado.pos[0] += .05
            moved = draw('avocado-moved')
            assert not renderer.shadow_map.cache_hit
            assert np.count_nonzero(first != moved) > 30
            app.scene.light_dir[0] += .2
            draw()
            assert not renderer.shadow_map.cache_hit
            assert gl.glGetError() == gl.GL_NO_ERROR
            report['shadow_cache_invalidation'] = True
            # Identical pose/lens/aspect, shared clean pass, same output size:
            # no shader/lighting discrepancy between editor and photo cameras.
            from mini3d.shot_camera import render_scene_view
            shot = ShotCamera(camera)
            shot.aspect_name = '4:3'
            size = (800,600)
            render_scene_view(app.scene,camera,renderer,target,size)
            a = gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            with patch.object(ShotCamera, 'ASPECTS', dict(ShotCamera.ASPECTS, **{'4:3': size})):
                render_shot(app.scene,shot,renderer,target)
            b = gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            assert bytes(a) == bytes(b)
            report['matched_view_pixels_identical'] = True
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report,indent=2))
    finally:
        target.close()
        renderer.close()
        pygame.quit()


if __name__ == '__main__':
    run(Path(sys.argv[1]))
