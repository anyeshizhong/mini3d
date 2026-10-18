"""API-driven masonry views and depth probes; requires a real desktop GL context.

Not a performance benchmark. --baseline records defects without failing.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np


def run(output, backend, baseline):
    os.environ['MINI3D_PHOTO_BACKEND'] = backend
    if backend == 'native':
        os.environ['MINI3D_REQUIRE_NATIVE_PHOTO'] = '1'
    from OpenGL import GL as gl
    import pygame
    from tools.capture_sunset import desktop_context
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_scene_view

    output.mkdir(parents=True, exist_ok=True)
    report = dict(backend=backend, baseline=baseline, views=[],
                  scope='Procedural Roman street assets only; no user camera or external glTF supplied.',
                  timing='PNG/readback correctness audit, not a realtime frame benchmark')
    size = (512, 512)
    with desktop_context():
        renderer, target = GLRenderer(*size), RenderTarget()
        report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()
        api = Mini3DAPI(renderer=renderer)
        try:
            api.set_atmosphere(enabled=True, ground=False, haze=0.)
            api.set_shadows(enabled=False)
            api.create_shot_camera(position=[0., -10., 4.], target=[0., 0., 4.],
                                   focal_mm=35, aspect='1:1', near=.05, far=100.)
            for asset in ('arch', 'house', 'shop', 'house-ochre', 'house-rose', 'shop-ochre', 'shop-rose'):
                entity = api.spawn('builtin:roman-' + asset)['entity_id']
                height = 5.8 if asset.startswith('house') else 3.6
                center = [0., 0., 3.8 if asset == 'arch' else height / 2]
                poses = [(name, position, center, None if asset == 'arch' else True) for name, position in (
                    ('front', [0., -13., 4.]), ('back', [0., 13., 4.]),
                    ('left', [-13., 0., 4.]), ('right', [13., 0., 4.]),
                    ('low', [8., -10., .25]), ('high', [-8., 10., 12.]))]
                if asset == 'arch':
                    poses += [('side-seal', [10., 0., 6.75], [0., 0., 6.75], True),
                              ('opening', [0., -10., 4.], [0., 0., 4.], False)]
                    for index, angle in enumerate((.985, 1.12, 1.45)):
                        x, z = 3.674 * math.cos(angle), 3. + 3.674 * math.sin(angle)
                        poses.append(('seam-' + str(index), [x, -2., z], [x, 0., z], True))
                for name, position, lookat, expected in poses:
                    api.set_shot_camera_pose(position=position, target=lookat)
                    camera = api._app.shot_camera
                    render_scene_view(api._app.scene, camera, renderer, target, size)
                    target.bind()
                    color = gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                    depth = np.asarray(gl.glReadPixels(0, 0, *size, gl.GL_DEPTH_COMPONENT,
                                                       gl.GL_FLOAT)).reshape(size[1], size[0]).copy()
                    # The target is the center camera ray. A 2x2 block excludes
                    # raster edge ambiguity at an exact center on even-sized FBOs.
                    block = depth[255:257, 255:257]
                    hit = bool(np.all(block < 1.))
                    image = output / (asset + '-' + name + '.png')
                    pygame.image.save(pygame.image.fromstring(color, size, 'RGB', True), str(image))
                    stats = dict(renderer.render_stats)
                    if backend == 'native' and stats.get('backend') != 'native-photo':
                        raise AssertionError('Required native backend not used: ' + str(stats))
                    error = int(gl.glGetError())
                    if error:
                        raise AssertionError('GL error: ' + str(error))
                    row = dict(asset=asset, view=name, pose=api.get_shot_camera(),
                               depth_hit=hit, center_depth=block.tolist(), expected_hit=expected,
                               backend=stats.get('backend', 'python'), gl_error=error)
                    report['views'].append(row)
                    print(json.dumps(dict(asset=asset, view=name, hit=hit, expected=expected)), flush=True)
                scene_file = output / (asset + '-scene.json')
                api.save_scene(scene_file)
                fresh = Mini3DAPI(renderer=renderer)
                try:
                    fresh.load_scene(scene_file)
                    render_scene_view(fresh._app.scene, fresh._app.shot_camera, renderer, target, size)
                    target.bind()
                    reloaded_color = gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                    reloaded_depth = np.asarray(gl.glReadPixels(0, 0, *size, gl.GL_DEPTH_COMPONENT,
                                                               gl.GL_FLOAT)).reshape(size[1], size[0])
                    if bytes(color) != bytes(reloaded_color) or not np.array_equal(depth, reloaded_depth):
                        raise AssertionError('Scene v3 reload changed color/depth for ' + asset)
                    report['views'][-1]['scene_v3_color_depth_identical'] = True
                finally:
                    fresh._app.model_dialog.close()
                api.delete(entity)
            (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            if not baseline:
                failures = [row for row in report['views'] if row['expected_hit'] is not None
                            and row['depth_hit'] != row['expected_hit']]
                if failures:
                    raise AssertionError('Masonry depth probes failed: ' + str(failures))
        finally:
            api._app.model_dialog.close()
            target.close()
            renderer.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', choices=('python', 'native'), default='python')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    run(args.output.resolve(), args.backend, args.baseline)
