"""Real native Arrange frames: depth, overlays, edits and shared Shot resources."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(output):
    from OpenGL import GL as gl
    from PIL import Image
    from mini3d.api import Mini3DAPI
    from mini3d.camera import Camera
    from mini3d.gl_renderer import GLRenderer
    from mini3d.gl_state import read_rgb, save_state
    from mini3d.native_renderer import NativeRenderError
    from mini3d.render_target import RenderTarget
    from mini3d.scene import Scene, Entity, Mesh
    from mini3d.scene_renderer import render_scene
    from mini3d.shot_camera import render_scene_view
    from tools.capture_sunset import desktop_context

    os.environ['MINI3D_RENDER_BACKEND'] = 'native'
    os.environ.pop('MINI3D_ARRANGE_BACKEND', None)
    os.environ.pop('MINI3D_PHOTO_BACKEND', None)
    output.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, checks=[])
    size = (640, 480)

    def done(message):
        report['checks'].append(message)
        print('PASS ' + message, flush=True)

    with desktop_context():
        renderer, target = GLRenderer(*size), RenderTarget()
        renderer.render_mode = 'REALISTIC'
        api = Mini3DAPI(renderer=renderer)
        scene = api._app.scene
        api.set_atmosphere(enabled=False, ground=False)
        api.set_shadows(enabled=False)
        scene.show_grid = scene.show_axes = False
        scene.grid_scale = .05
        camera = Camera([9, -11, 8], near=.001, far=100)
        camera.look_at([0, 0, 2])
        report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()

        def image():
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target.framebuffer)
            return np.frombuffer(read_rgb(0, 0, *size), np.uint8).reshape(size[1], size[0], 3).copy()

        def depth():
            raw = gl.glReadPixels(0, 0, *size, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)
            return np.frombuffer(raw, np.float32).reshape(size[1], size[0]).copy()

        def render(samples=1, backend='native-arrange'):
            render_scene(scene, camera, renderer, target, size, samples)
            assert renderer.render_stats['backend'] == backend, renderer.render_stats
            assert gl.glGetError() == gl.GL_NO_ERROR
            return image(), depth()

        try:
            empty_rgb, empty_depth = render()
            assert not scene.root_entities
            assert np.all(empty_depth == 1.)
            scene.show_grid = True
            grid_rgb, grid_depth = render()
            np.testing.assert_array_equal(grid_depth, empty_depth)
            assert np.count_nonzero(np.any(grid_rgb != empty_rgb, axis=2)) > 1000
            done('empty native scene and editor grid without synthetic geometry or depth writes')

            entity_id = api.spawn('builtin:roman-house')['entity_id']
            scene.show_grid = False
            base_rgb, base_depth = render()
            assert np.count_nonzero(base_depth < 1.) > 1000
            native = renderer.native_renderer
            builds = native.bundle_builds
            scene.show_grid = True
            grid_rgb, grid_depth = render()
            assert native.bundle_builds == builds
            np.testing.assert_array_equal(grid_depth, base_depth)
            # Points above the grid plane belong to geometry and must occlude it.
            rows, cols = np.nonzero(base_depth < 1.)
            clip = np.column_stack(((cols + .5) * 2 / size[0] - 1,
                                    (rows + .5) * 2 / size[1] - 1,
                                    base_depth[rows, cols] * 2 - 1, np.ones(len(rows))))
            effective = target.render_camera
            world = clip @ np.linalg.inv(effective.projection_matrix(size[0] / size[1]) @ effective.view_matrix).T
            above = world[:, 2] / world[:, 3] > .1
            np.testing.assert_array_equal(grid_rgb[rows[above], cols[above]], base_rgb[rows[above], cols[above]])
            Image.fromarray(grid_rgb[::-1]).save(output / 'arrange-grid.png')
            done('grid uses effective native projection, preserves depth and is occluded by the house')

            selection = api._entity(entity_id)
            selected = Scene()
            selected.add(selection)
            renderer.material_renderer.render_selection(selected.get_flat_render_list(), target.render_camera, *size)
            selection_rgb = image()
            assert np.count_nonzero(np.any(selection_rgb != grid_rgb, axis=2)) > 100
            np.testing.assert_array_equal(depth(), grid_depth)
            Image.fromarray(selection_rgb[::-1]).save(output / 'arrange-selection.png')
            done('selection outline composes over native color and preserves native depth')

            scene.show_grid = False
            updates = native.parameter_updates
            camera.look_at([2, 0, 2])
            render()
            assert native.bundle_builds == builds and native.parameter_updates > updates
            assert renderer.render_stats['shadow_draw_calls'] == 0
            camera.position += np.array([.2, 0, 0])
            updates = native.parameter_updates
            render()
            assert native.parameter_updates == updates and native.bundle_builds == builds
            done('Studio rotation updates camera-relative lights; translation reuses globals and assets')

            native_rgb, _ = render()
            os.environ['MINI3D_ARRANGE_BACKEND'] = 'python'
            python_rgb, _ = render(backend='python')
            os.environ.pop('MINI3D_ARRANGE_BACKEND')
            mean_error = float(np.mean(np.abs(native_rgb.astype(float) - python_rgb.astype(float))))
            assert mean_error < 1., mean_error
            report['studio_python_native_mean_rgb_error'] = mean_error
            done('Studio native material lighting agrees with the Python reference')

            api.set_lighting(mode='Scene')
            api.set_shadows(enabled=True, resolution=256)
            render()
            assert renderer.render_stats['shadow_draw_calls'] > 0
            api.set_lighting(mode='Studio')
            render()
            assert renderer.render_stats['shadow_draw_calls'] == 0
            api.set_lighting(mode='Scene')
            api.set_shadows(enabled=False)
            done('Scene lighting enables shadows and Studio suppresses them with the same native resources')
            before, _ = render()
            builds = native.bundle_builds
            transform_updates = native.transform_updates
            api.set_transform(entity_id, position=[-3, 1, 0])
            after, _ = render()
            assert native.bundle_builds == builds and native.transform_updates > transform_updates
            assert np.count_nonzero(np.any(before != after, axis=2)) > 100
            api.undo()
            undone, _ = render()
            np.testing.assert_array_equal(undone, before)
            api.redo()
            redone, _ = render()
            np.testing.assert_array_equal(redone, after)
            done('transform / undo / redo synchronize the authoritative scene without stale native frames')

            save_path = output / 'scene.json'
            api.save_scene(save_path)
            api.load_scene(save_path)
            scene = api._app.scene
            reloaded, _ = render()
            np.testing.assert_array_equal(reloaded, after)
            done('saved Scene reload retains the same native Arrange image')

            builds = native.bundle_builds
            handle = native.handle
            render_scene_view(scene, camera, renderer, target, size, 4)
            assert renderer.render_stats['backend'] == 'native-photo'
            assert native.handle == handle and native.bundle_builds == builds
            render(samples=1)
            assert native.handle == handle and native.bundle_builds == builds
            done('Arrange / Shot / Arrange and AA changes share one native scene handle')

            scene.render_mode = 'Unlit'
            unlit, _ = render()
            assert np.any(unlit != after)
            assert renderer.render_stats['shadow_draw_calls'] == 0
            done('Unlit uses native material settings without Scene shadows')

            scene.render_mode = 'Wireframe'
            try:
                render_scene(scene, camera, renderer, target, size)
            except NativeRenderError:
                pass
            else:
                raise AssertionError('required native Wireframe silently fell back')
            os.environ['MINI3D_ARRANGE_BACKEND'] = 'auto'
            render(backend='python-fallback')
            assert 'Wireframe' in renderer.render_stats['native_fallback_reason']
            os.environ.pop('MINI3D_ARRANGE_BACKEND')
            scene.render_mode = 'Lit'
            done('Wireframe fallback is observable in auto and rejected by required native')

            # Hostile caller state must neither clip helpers nor leak from native.
            scene.show_grid = scene.show_axes = True
            render()
            expected = image()
            gl.glEnable(gl.GL_SCISSOR_TEST)
            gl.glScissor(0, 0, 1, 1)
            gl.glColorMask(False, False, False, False)
            gl.glDepthRange(.2, .8)
            gl.glLineWidth(1.)
            state = save_state(texture_units=15, all_cubemaps=True)
            render_scene(scene, camera, renderer, target, size)
            restored = save_state(texture_units=15, all_cubemaps=True)
            for key in state:
                if isinstance(state[key], np.ndarray):
                    np.testing.assert_array_equal(state[key], restored[key])
                else:
                    assert state[key] == restored[key], key
            np.testing.assert_array_equal(image(), expected)
            np.testing.assert_allclose(gl.glGetDoublev(gl.GL_DEPTH_RANGE), [.2, .8], atol=1e-7)
            assert float(gl.glGetFloatv(gl.GL_LINE_WIDTH)) == 1.
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glColorMask(True, True, True, True)
            gl.glDepthRange(0., 1.)
            done('native pass and editor helpers preserve caller GL state')

            # A bad later index must not partially commit an earlier valid row.
            before_bad, _ = render()
            indices = np.array([0, 0xffffffff], dtype=np.uint32)
            worlds = np.tile(np.eye(4), (2, 1, 1)).astype(np.float64)
            worlds[0, 0, 3] = 1000
            normals = np.tile(np.eye(3), (2, 1, 1)).astype(np.float32)
            winding = np.zeros(2, dtype=np.uint32)
            uints = ctypes.POINTER(ctypes.c_uint32)
            assert native.library.spqr_photo_transforms(native.handle,
                indices.ctypes.data_as(uints), worlds.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                normals.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                winding.ctypes.data_as(uints), 2) == 0
            after_bad, _ = render()
            np.testing.assert_array_equal(after_bad, before_bad)
            done('malformed transform batches are rejected atomically by the actual DLL')

            for scale in ([-1, .8, 1.2], [0, 1, 1]):
                # Commands intentionally require positive scales. Imported
                # hierarchy transforms / public arrays can still be mirrored
                # or singular and are supported by the renderer's pinv normals.
                api.set_transform(entity_id, rotation=[.1, .2, .3])
                api._entity(entity_id).scale = np.asarray(scale, dtype=float)
                incremental, incremental_depth = render()
                native.close()
                rebuilt, rebuilt_depth = render()
                np.testing.assert_array_equal(incremental, rebuilt)
                np.testing.assert_array_equal(incremental_depth, rebuilt_depth)
            done('mirrored and singular-scale incremental transforms match freshly rebuilt color and depth')

            api.delete(entity_id)
            _rgb, final_depth = render()
            assert np.all(final_depth == 1.)
            native.close()
            native.close()
            render()
            assert native.handle is not None
            assert gl.glGetError() == gl.GL_NO_ERROR
            done('delete-last, idempotent close and rendering after close')

            from mini3d.geometry import make_box
            legacy = scene.add(Entity(Mesh(*make_box(3, 3, 3)), name='Legacy compatibility cube'))
            os.environ['MINI3D_ARRANGE_BACKEND'] = 'auto'
            _rgb, legacy_depth = render(backend='python-fallback')
            assert np.any(legacy_depth < 1.)
            assert 'legacy material' in renderer.render_stats['native_fallback_reason']
            os.environ.pop('MINI3D_ARRANGE_BACKEND')
            try:
                render_scene(scene, camera, renderer, target, size)
            except NativeRenderError:
                pass
            else:
                raise AssertionError('cached legacy scene failure bypassed required native')
            legacy.visible = False
            _rgb, hidden_depth = render()
            assert np.all(hidden_depth == 1.)
            done('legacy models render through reported compatibility fallback and recover native after hiding')
            report['passed'] = True
        finally:
            target.close()
            renderer.close()
            (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    run(parser.parse_args().output)
