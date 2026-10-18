"""Actual Roman building undersides, both photo backends; not an FPS test."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(args):
    os.environ['MINI3D_PHOTO_BACKEND'] = args.backend
    os.environ['MINI3D_REQUIRE_NATIVE_PHOTO'] = '1' if args.backend == 'native' else '0'
    if args.baseline_ref:
        from mini3d import roman_assets
        source = subprocess.check_output(['git', 'show', args.baseline_ref + ':mini3d/roman_assets.py'], cwd=str(ROOT))
        exec(compile(source, roman_assets.__file__, 'exec'), roman_assets.__dict__)
    from OpenGL import GL as gl
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_scene_view
    from tools.capture_sunset import desktop_context

    args.output.mkdir(parents=True, exist_ok=True)
    size = (512, 512)
    report = dict(backend=args.backend, baseline_ref=args.baseline_ref, views=[])
    with desktop_context():
        renderer, target = GLRenderer(*size), RenderTarget()
        renderer.render_mode = 'REALISTIC'
        report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()
        api = Mini3DAPI(renderer=renderer)
        try:
            api.set_atmosphere(enabled=False, ground=False, haze=0)
            api.set_shadows(enabled=False)
            api.set_lighting(mode='Scene', direction=[.3, -.2, -1.], diffuse=1.5, ambient=.3)
            api.create_shot_camera(position=[4, -8, -6], target=[0, 0, 0],
                                   focal_mm=35, aspect='1:1', near=.05, far=100)
            yy, xx = np.mgrid[:size[1], :size[0]]
            for asset in ('house', 'house-ochre', 'house-rose', 'shop', 'shop-ochre', 'shop-rose'):
                entity = api.spawn('builtin:roman-' + asset)['entity_id']
                for label, eye, lookat in (
                    ('below-left', [-4, -8, -6], [0, 0, 0]),
                    ('below-right', [4, -8, -6], [0, 0, 0]),
                    ('front', [0, -13, 3], [0, 0, 3]),
                    ('above', [5, -8, 8], [0, 0, 3])):
                    api.set_shot_camera_pose(position=eye, target=lookat)
                    render_scene_view(api._app.scene, api._app.shot_camera, renderer, target, size, 1)
                    rgb = np.frombuffer(gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE), np.uint8).reshape(512, 512, 3)
                    depth = np.frombuffer(gl.glReadPixels(0, 0, *size, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT), np.float32).reshape(512, 512)
                    row = dict(asset=asset, view=label)
                    if label.startswith('below'):
                        camera = target.render_camera
                        vp = camera.projection_matrix(1.).astype(np.float32).astype(float) @ camera.view_matrix.astype(np.float32).astype(float)
                        clip = np.stack(((xx+.5)/512*2-1, (yy+.5)/512*2-1, depth*2-1, np.ones_like(depth)), axis=-1)
                        world = clip.reshape(-1, 4) @ np.linalg.inv(vp).T
                        world /= world[:, 3:4]
                        world = world.reshape(512, 512, 4)
                        mask = ((depth < 1) & (np.abs(world[:, :, 2]) < 2e-4) &
                                (np.abs(world[:, :, 0]) < 1.8) & (np.abs(world[:, :, 1]) < 2.25))
                        pixels = rgb[mask]
                        row.update(underside_pixels=len(pixels), channel_range=np.ptp(pixels, axis=0).tolist())
                        assert len(pixels) > 100
                        if not args.baseline_ref:
                            # Allow the small smooth PBR specular variation of
                            # one rough material; alternating grey caps exceed it.
                            assert max(row['channel_range']) <= 8, row
                    if args.backend == 'native':
                        assert renderer.render_stats.get('backend') == 'native-photo'
                    assert gl.glGetError() == gl.GL_NO_ERROR
                    Image.fromarray(rgb[::-1]).save(args.output / (asset + '-' + label + '.png'))
                    report['views'].append(row)
                api.delete(entity)
            (args.output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps(report), flush=True)
        finally:
            api._app.model_dialog.close()
            target.close()
            renderer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('python', 'native'), default='python')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-ref')
    run(parser.parse_args())
