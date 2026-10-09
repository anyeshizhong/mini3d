"""Issue #3 GPU evidence, written before the fix. --baseline expects clipping.

python -B tests/scene_clipping_smoke.py [output-directory] [--baseline]
Requires the existing local Roman and Side Table assets. Reference changes only
near/far on a Camera copy; camera pose, framing, geometry and lights stay fixed.
"""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget

SIZE = (900, 650)


def run(output, baseline=False):
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode(SIZE, pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer, target = GLRenderer(*SIZE), RenderTarget()
    target.resize(*SIZE)
    report = dict(baseline=baseline, gpu=gl.glGetString(gl.GL_RENDERER).decode(), views=[])

    def render(scene, camera, name):
        target.bind()
        gl.glDepthMask(True)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        renderer.render(scene, camera)
        rgb = gl.glReadPixels(0, 0, *SIZE, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        depth = np.asarray(gl.glReadPixels(0, 0, *SIZE, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)).reshape(SIZE[1], SIZE[0]).copy()
        pygame.image.save(pygame.image.fromstring(rgb, SIZE, 'RGB', True), str(output/(name+'.png')))
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return np.frombuffer(rgb, np.uint8).reshape(SIZE[1], SIZE[0], 3).copy(), depth

    try:
        app = Editor(*SIZE)
        app.assets = [dict(name='Roman', path=str(ROOT/'model/05_roman_soldier/roman_legionnaire.glb')),
                      dict(name='Small table', path=str(ROOT/'model/03_side_table/side_table.glb'))]
        soldier = app.add_asset(0)
        table = app.add_asset(1)  # The reported order and real automatic Focus path.
        soldier_position, table_position = soldier.pos.copy(), table.pos.copy()
        app.scene.show_grid = app.scene.show_axes = False
        for label, scale in (('auto-add', 1.), ('focus-selected', 1.), ('tiny', .0001), ('large', 100.)):
            if label != 'auto-add':
                # Root transforms and imported hierarchy use real Commands.
                app.commands.set_transform(soldier, position=soldier_position*scale,
                                           scale=[scale]*3)
                app.commands.set_transform(table, position=table_position*scale, scale=[scale]*3)
                app.select(table)
                app.focus_selected()
            controller = app.viewer.controller
            controller.yaw, controller.pitch = 0, .08
            controller.zoom(-31)
            controller.pan(0, 150, SIZE[1])
            app.scene.update()
            if hasattr(app.viewer, 'update_clipping'):
                app.viewer.update_clipping()
            camera = app.viewer.camera
            pose = camera.view_matrix.copy()
            # Vertex scan is ONLY an independent diagnostic oracle, never the frame loop.
            depths = []
            for entity in app.scene.get_flat_render_list():
                world = entity.model.vertices @ entity.world_matrix.T
                depths.append(-(world @ camera.view_matrix.T)[:, 2])
            depths = np.concatenate(depths)
            reference = copy.copy(camera)
            reference.far = max(float(depths.max())*1.02, camera.near*2)
            before, before_depth = render(app.scene, camera, label+('-before' if baseline else '-after'))
            expected, expected_depth = render(app.scene, reference, label+'-reference')
            foreground = expected_depth < 1
            missing = foreground & (before_depth >= 1)
            assert np.count_nonzero(foreground) > 2000, 'Reference must show model geometry inside the image frustum'
            changed = np.any(before != expected, axis=2) & foreground
            entry = dict(view=label, scale=scale, near=camera.near, far=camera.far,
                         reference_far=reference.far, geometry_depth=[float(depths.min()), float(depths.max())],
                         framing_radius=controller._bounds_radius, target=controller.target.tolist(),
                         distance=controller.distance, reference_pixels=int(foreground.sum()),
                         missing_pixels=int(missing.sum()), changed_pixels=int(changed.sum()))
            if baseline:
                assert missing.sum() > 100, entry
            else:
                assert missing.sum() == 0, entry
                # A different far maps 24-bit depth differently; coincident scan
                # triangles may swap at isolated pixels. Do not mistake that for
                # the contiguous silhouette loss this regression detects.
                assert changed.sum() <= max(3, foreground.sum()*.0005), entry
                # Compare reconstructed eye depths, since different far planes
                # encode a different depth-buffer value for the SAME world point.
                def eye_depth(depth, view):
                    z = depth.astype(float)*2-1
                    return 2*view.near*view.far/(view.far+view.near-z*(view.far-view.near))
                delta = np.abs(eye_depth(before_depth, camera)-eye_depth(expected_depth, reference))[foreground]
                entry['max_eye_depth_error'] = float(delta.max())
                assert delta.max() < max(scale*.02, 1e-10), entry
            np.testing.assert_array_equal(camera.view_matrix, pose)
            report['views'].append(entry)
            print(json.dumps(entry), flush=True)
        (output/('baseline.json' if baseline else 'results.json')).write_text(json.dumps(report, indent=2), encoding='utf8')
    finally:
        target.close()
        if hasattr(renderer, 'material_renderer'):
            renderer.material_renderer.close()
        pygame.quit()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--baseline']
    run(Path(args[0]) if args else ROOT/'captures/scene-clipping', '--baseline' in sys.argv)
