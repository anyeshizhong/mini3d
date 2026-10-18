"""Coverage, occlusion, depth and GL-state checks for the editor grid."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['MINI3D_PHOTO_BACKEND'] = 'python'


def run(args):
    if args.baseline_ref:
        from mini3d import gl_renderer
        source = subprocess.check_output(['git', 'show', args.baseline_ref + ':mini3d/gl_renderer.py'], cwd=str(ROOT))
        exec(compile(source, gl_renderer.__file__, 'exec'), gl_renderer.__dict__)
    from OpenGL import GL as gl
    from OpenGL.raw.GL.VERSION.GL_3_3 import glGetQueryObjectui64v
    from mini3d.api import Mini3DAPI
    from mini3d.camera import Camera
    from mini3d.gl_renderer import GLRenderer
    from mini3d.gl_state import save_state, restore_state
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_scene_view
    from tools.capture_sunset import desktop_context

    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(baseline_ref=args.baseline_ref, cases=[])
    with desktop_context():
        renderer, target = GLRenderer(512, 512), RenderTarget()
        renderer.render_mode = 'REALISTIC'
        api = Mini3DAPI(renderer=renderer)
        scene = api._app.scene
        api.set_atmosphere(enabled=False, ground=False)
        api.set_shadows(enabled=False)
        scene.show_axes = False
        scene.grid_scale = .05
        report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()
        try:
            def render(camera, visible, size=(512, 512), samples=1):
                target.resize(*size, samples=samples)
                target.bind()
                renderer.resize(*size)
                scene.show_grid = visible
                gl.glDisable(gl.GL_SCISSOR_TEST)
                gl.glDepthMask(True)
                renderer.render(scene, camera)
                target.resolve()
                rgb = np.frombuffer(gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE), np.uint8).reshape(size[1], size[0], 3).copy()
                depth = np.frombuffer(gl.glReadPixels(0, 0, *size, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT), np.float32).copy()
                assert gl.glGetError() == gl.GL_NO_ERROR
                return rgb, depth

            cases = [
                ('zoom-out', [0, 0, 40], [0, 0, 0], 0, .1, 500, True),
                ('pan', [1000, 2000, 40], [1000, 2000, 0], 0, .1, 500, True),
                ('coarse-pan', [1000, 2000, 40], [1000, 2000, 0], 0, .1, 500, True),
                ('plane-offset', [1000, 2000, 47], [1000, 2000, 7], 7, .1, 500, True),
                ('oblique', [8, -12, 8], [0, 0, 0], 0, .1, 200, True),
                ('below', [4, -8, -8], [0, 0, 0], 0, .1, 200, True),
                ('horizon', [0, -8, 1], [0, 0, 1], 0, .1, 200, True),
                ('upward', [0, 0, 8], [0, 0, 9], 0, .1, 200, False),
                ('away-below', [0, 0, -8], [0, 0, -9], 0, .1, 200, False),
                ('on-plane', [0, -8, 0], [0, 0, 0], 0, .1, 200, False),
                ('before-near', [0, 0, .05], [0, 0, 0], 0, .1, 10, False),
                ('after-far', [0, 0, 10], [0, 0, 0], 0, .1, 5, False),
            ]
            images = {}
            for label, eye, lookat, z, near, far, visible in cases:
                scene.grid_scale = .5 if label == 'coarse-pan' else .05
                camera = Camera(eye, near=near, far=far)
                camera.look_at(lookat)
                scene.placement_plane.z = z
                off, off_depth = render(camera, False)
                on, on_depth = render(camera, True)
                np.testing.assert_array_equal(on_depth, off_depth)
                changed = np.any(on != off, axis=2)
                edge = changed.copy()
                edge[64:-64, 64:-64] = False
                row = dict(name=label, changed_pixels=int(changed.sum()), outer_pixels=int(edge.sum()), depth_exact=True)
                if not args.baseline_ref:
                    assert bool(changed.any()) == visible, row
                    if label in ('zoom-out', 'pan', 'plane-offset'):
                        assert row['outer_pixels'] > 2000, row
                images[label] = on
                Image.fromarray(on[::-1]).save(args.output / (label + '.png'))
                report['cases'].append(row)
            np.testing.assert_array_equal(images['pan'], images['plane-offset'])
            scene.placement_plane.z = 0
            scene.grid_scale = .05

            # Known world-axis points retain their colors and world anchoring.
            top = images['zoom-out']
            red = (top[:, :, 0].astype(int) - top[:, :, 1]) > 15
            green = (top[:, :, 1].astype(int) - top[:, :, 0]) > 15
            assert red.any() and green.any()
            assert not np.any((images['pan'][:, :, 0].astype(int) - images['pan'][:, :, 1]) > 15)
            camera = Camera([0, 0, 40], near=.1, far=500)
            camera.look_at([0, 0, 0])
            vp = camera.projection_matrix(1.) @ camera.view_matrix
            for point, first, second in (([8, 0, 0, 1], 0, 1), ([0, 8, 0, 1], 1, 0)):
                clip = vp @ point
                x, y = np.floor((clip[:2] / clip[3] * .5 + .5) * 512).astype(int)
                patch = top[y-1:y+2, x-1:x+2].astype(int)
                assert np.max(patch[:, :, first] - patch[:, :, second]) > 15
            if not args.baseline_ref:
                counts = {row['name']: row['changed_pixels'] for row in report['cases']}
                assert 0 < counts['coarse-pan'] < counts['pan'] * .25

            entity = api.spawn('builtin:roman-house')['entity_id']
            camera = Camera([9, -11, 8], near=.1, far=200)
            camera.look_at([0, 0, 3])
            for samples in (1, 4):
                if samples == 4:
                    # A simple raised surface has no internal silhouette gaps.
                    # Resolved MSAA depth alone cannot identify uncovered
                    # background subsamples between a house's eaves and wall.
                    api.delete(entity)
                    entity = api.spawn('builtin:ground', position=[0, 0, 2], scale=[.5, .5, 1])['entity_id']
                    gl.glDepthRange(.2, .8)
                off, off_depth = render(camera, False, samples=samples)
                on, on_depth = render(camera, True, samples=samples)
                np.testing.assert_array_equal(on_depth, off_depth)
                # Exclude resolved multisample boundary pixels from color checks.
                mask = (off_depth.reshape(512, 512) < .999)
                interior = mask.copy()
                interior[1:-1, 1:-1] &= mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:]
                np.testing.assert_array_equal(on[interior], off[interior])
                Image.fromarray(on[::-1]).save(args.output / ('occlusion-' + str(samples) + 'x.png'))
            np.testing.assert_allclose(gl.glGetDoublev(gl.GL_DEPTH_RANGE), [.2, .8])
            gl.glDepthRange(0., 1.)
            report['geometry_occlusion_and_depth_exact'] = True

            # State deliberately differs from the grid pass's requirements.
            target.bind()
            scene.show_grid = True
            original = save_state(texture_units=0)
            try:
                gl.glDisable(gl.GL_DEPTH_TEST)
                gl.glDepthMask(True)
                gl.glEnable(gl.GL_BLEND)
                gl.glBlendEquationSeparate(gl.GL_FUNC_REVERSE_SUBTRACT, gl.GL_FUNC_SUBTRACT)
                gl.glBlendFuncSeparate(gl.GL_ONE, gl.GL_ZERO, gl.GL_DST_ALPHA, gl.GL_ONE)
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
                before = save_state(texture_units=0)
                renderer.render_editor_grid(scene, camera)
                after = save_state(texture_units=0)
                for name in before:
                    np.testing.assert_equal(after[name], before[name], err_msg=name)
                report['state_restored'] = True
            finally:
                restore_state(original)

            api.create_shot_camera(position=[9, -11, 8], target=[0, 0, 3], near=.1, far=200)
            for backend in ('python', 'native'):
                os.environ['MINI3D_PHOTO_BACKEND'] = backend
                pairs = []
                for visible in (False, True):
                    scene.show_grid = visible
                    render_scene_view(scene, api._app.shot_camera, renderer, target, (512, 512), 1)
                    pairs.append(bytes(gl.glReadPixels(0, 0, 512, 512, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)))
                    if backend == 'native':
                        assert renderer.render_stats.get('backend') == 'native-photo'
                assert pairs[0] == pairs[1]
            report['photo_grid_toggle_exact_both_backends'] = True
            os.environ['MINI3D_PHOTO_BACKEND'] = 'python'

            # Per-pass timings only: warmed guides at the tested preview size.
            api.delete(entity)
            camera = Camera([8, -12, 8], near=.1, far=200)
            camera.look_at([0, 0, 0])
            render(camera, False, size=(1081, 662))
            scene.show_grid = True
            query = int(gl.glGenQueries(1)[0])
            cpu, gpu, complete = [], [], []
            try:
                for index in range(70):
                    gl.glFinish()
                    start = time.perf_counter()
                    gl.glBeginQuery(gl.GL_TIME_ELAPSED, query)
                    renderer.render_editor_grid(scene, camera)
                    gl.glEndQuery(gl.GL_TIME_ELAPSED)
                    submitted = time.perf_counter()
                    gl.glFinish()
                    finished = time.perf_counter()
                    value = ctypes.c_uint64()
                    glGetQueryObjectui64v(query, gl.GL_QUERY_RESULT, ctypes.byref(value))
                    if index >= 10:
                        cpu.append((submitted-start)*1000)
                        complete.append((finished-start)*1000)
                        gpu.append(value.value/1e6)
                report['grid_pass_ms'] = {key: dict(zip(('p50', 'p95', 'p99'), np.percentile(values, [50, 95, 99])))
                                          for key, values in (('cpu_submit', cpu), ('complete', complete), ('gpu', gpu))}
            finally:
                gl.glDeleteQueries(1, [query])
            assert gl.glGetError() == gl.GL_NO_ERROR
        finally:
            api._app.model_dialog.close()
            renderer.close()
            renderer.close()
            target.close()
    (args.output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-ref')
    run(parser.parse_args())
