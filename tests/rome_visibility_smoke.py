"""Local Rome River Side visibility diagnosis with a real desktop GL context.

No production render switches: GL overrides exist only inside this test.
Run: python -B tests/rome_visibility_smoke.py [output-directory] [model-scale]
"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget


def run(output, scale=1.0):
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((960, 640), pygame.OPENGL | pygame.DOUBLEBUF)
    pygame.display.set_caption('Rome River Side visibility A/B diagnosis')
    renderer = GLRenderer(960, 640)
    target = RenderTarget()
    target.resize(960, 640)
    app = Editor()
    root = app.commands.spawn(ROOT / 'model/08_rome_river/rome_river_side.glb', scale=[scale]*3)
    from mini3d.placement import SurfaceHit
    app.commands.place_on_surface(root, SurfaceHit([0, 0, 0], [0, 0, 1]))
    app.select(root)
    app.focus_selected()
    app.scene.show_grid = app.scene.show_axes = False
    scene = app.scene
    camera, controller = app.viewer.camera, app.viewer.controller
    scene.update()
    mats = {id(e.model.material): e.model.material for e in scene.get_flat_render_list()
            if e.model is not None and e.model.material is not None}
    report = dict(materials=[{k: v for k, v in m.items() if k != 'textures'} for m in mats.values()],
                  gpu=gl.glGetString(gl.GL_RENDERER).decode(), model_scale=scale, views=[])
    real_enable, real_draw, real_offset = gl.glEnable, gl.glDrawElements, gl.glPolygonOffset
    last_depth = [None]

    def render(name, no_cull=False, fixed=False):
        draws = []
        def enable(cap):
            if no_cull and cap == gl.GL_CULL_FACE:
                gl.glDisable(cap)
            else:
                real_enable(cap)
        def draw(*args):
            draws.append(dict(cull=bool(gl.glIsEnabled(gl.GL_CULL_FACE)),
                              depth=bool(gl.glIsEnabled(gl.GL_DEPTH_TEST)),
                              depth_write=bool(gl.glGetBooleanv(gl.GL_DEPTH_WRITEMASK)),
                              blend=bool(gl.glIsEnabled(gl.GL_BLEND)),
                              offset=bool(gl.glIsEnabled(gl.GL_POLYGON_OFFSET_FILL))))
            return real_draw(*args)
        target.bind()
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDepthMask(True)
        gl.glEnable(gl.GL_CULL_FACE)
        if no_cull:
            gl.glDisable(gl.GL_CULL_FACE)
        renderer.resize(960, 640)
        def offset(factor, units):
            real_offset(factor if fixed else 0, units if fixed else 0)
        with patch.object(gl, 'glEnable', enable), patch.object(gl, 'glDrawElements', draw), \
                patch.object(gl, 'glPolygonOffset', offset):
            renderer.render(scene, camera)
        rgb = gl.glReadPixels(0, 0, 960, 640, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        array = np.frombuffer(rgb, np.uint8).reshape(640, 960, 3).copy()[::-1]
        last_depth[0] = np.asarray(gl.glReadPixels(0, 0, 960, 640, gl.GL_DEPTH_COMPONENT,
                                                gl.GL_FLOAT)).reshape(640, 960).copy()[::-1]
        pygame.image.save(pygame.image.fromstring(rgb, (960, 640), 'RGB', True), str(output / (name+'.png')))
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return array, draws

    def changed(a, b):
        return int(np.any(a != b, axis=2).sum())

    try:
        for index, (yaw, pitch) in enumerate(((0,.25),(1.57,.25),(3.14,.25),(-1.57,.25),
                                              (.8,.7),(2.4,.7),(-2.4,-.15),(-.8,-.15))):
            controller.yaw, controller.pitch = yaw, pitch
            controller.update()
            name = 'view-%02d' % index
            before, draws = render(name+'-A-original')
            off, _ = render(name+'-B-no-cull', no_cull=True)
            entry = dict(view=name, yaw=yaw, pitch=pitch, position=camera.position.tolist(),
                         near=camera.near, far=camera.far, cull_changed_pixels=changed(before,off), draws=draws)
            assert entry['cull_changed_pixels'] == 0
            assert all(not draw['cull'] and draw['depth'] for draw in draws)
            depths = []
            for e in scene.get_flat_render_list():
                if e is scene.ground:
                    continue
                vertices = np.column_stack((e.model.vertices[:,:3], np.ones(len(e.model.vertices))))
                depths.extend(-(vertices @ (camera.view_matrix @ e.world_matrix).T)[:,2])
            entry['model_depth_range'] = [float(min(depths)), float(max(depths))]
            assert camera.near < min(depths) < max(depths) < camera.far
            # Alpha/depth checks follow the culling A/B, preserving the same pose.
            alpha = [(m, m.get('alphaMode')) for m in mats.values()]
            try:
                for m in mats.values():
                    m['alphaMode'] = 'OPAQUE'
                opaque, _ = render(name+'-C-opaque')
            finally:
                for m, value in alpha:
                    if value is None: m.pop('alphaMode', None)
                    else: m['alphaMode'] = value
            scene.ground.visible = False
            isolated, _ = render(name+'-D-no-ground')
            model_depth = last_depth[0]
            scene.ground.visible = True
            root.visible = False
            ground, _ = render(name+'-ground-only')
            ground_depth = last_depth[0]
            root.visible = True
            # Unproject the ground depth buffer; actual Ground geometry has Z=0.
            yy, xx = np.mgrid[0:640, 0:960]
            clip = np.stack(((xx+.5)/960*2-1, 1-(yy+.5)/640*2,
                             ground_depth*2-1, np.ones_like(ground_depth)), axis=-1)
            world = clip @ np.linalg.inv(camera.projection_matrix(1.5) @ camera.view_matrix).T
            world = world[:,:,:3] / world[:,:,3:4]
            mask = (model_depth < 1) & (ground_depth < 1)
            entry['ground_world_z_error_on_model'] = [float(world[:,:,2][mask].min()),
                                                       float(world[:,:,2][mask].max())] if mask.any() else None
            entry['ground_occludes_model_pixels'] = int(((ground_depth < model_depth) & mask).sum())
            old_near, old_far = camera.near, camera.far
            camera.near, camera.far = old_near / 100, old_far * 100
            wide, _ = render(name+'-E-wide-clip')
            camera.near, camera.far = old_near, old_far
            camera.near = old_near * 25
            tight, _ = render(name+'-F-tight-near')
            camera.near = old_near
            scene.ground.scale[:] = .001 * scale
            scene.update()
            small, _ = render(name+'-G-small-ground')
            scene.ground.scale[:] = 1
            scene.update()
            fixed, fixed_draws = render(name+'-H-fixed', fixed=True)
            assert sum(draw['offset'] for draw in fixed_draws) == 1  # Ground only
            root.visible = False
            render(name+'-fixed-ground-only', fixed=True)
            fixed_ground_depth = last_depth[0]
            root.visible = True
            entry['fixed_ground_occludes_model_pixels'] = int(((fixed_ground_depth < model_depth) & mask).sum())
            if camera.position[2] > 0:
                assert entry['fixed_ground_occludes_model_pixels'] == 0
            entry.update(opaque_changed_pixels=changed(before,opaque),
                         no_ground_changed_pixels=changed(before,isolated),
                         wide_clip_changed_pixels=changed(before,wide),
                         tight_clip_changed_pixels=changed(before,tight),
                         small_ground_changed_pixels=changed(before,small))
            report['views'].append(entry)
            print({k:v for k,v in entry.items() if k!='draws'}, flush=True)
        # Per-material culling, mirrored winding and GL state restoration still work.
        material_renderer = renderer.material_renderer
        sample = next(e for e in scene.get_flat_render_list() if e is not scene.ground)
        material = sample.model.material
        original_double, original_matrix = material.get('doubleSided'), sample.world_matrix.copy()
        try:
            for sided, mirrored in ((False,False), (False,True), (True,False)):
                material['doubleSided'] = sided
                sample.world_matrix = original_matrix @ np.diag([-1 if mirrored else 1,1,1,1])
                gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
                gl.glPolygonOffset(7,9)
                def inspect_draw(*args):
                    assert bool(gl.glIsEnabled(gl.GL_CULL_FACE)) == (not sided)
                    assert int(gl.glGetIntegerv(gl.GL_FRONT_FACE)) == (gl.GL_CW if mirrored else gl.GL_CCW)
                    assert not gl.glIsEnabled(gl.GL_POLYGON_OFFSET_FILL)
                    return real_draw(*args)
                with patch.object(gl, 'glDrawElements', inspect_draw):
                    material_renderer.render([sample], camera, scene, 960, 640)
                assert gl.glIsEnabled(gl.GL_POLYGON_OFFSET_FILL)
                assert float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_FACTOR)) == 7
                assert float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_UNITS)) == 9
            try:
                with patch.object(material_renderer, '_material', side_effect=RuntimeError('injected draw failure')):
                    material_renderer.render([scene.ground], camera, scene, 960, 640)
            except RuntimeError as exc:
                assert str(exc) == 'injected draw failure'
            else:
                raise AssertionError('Expected injected failure')
            assert gl.glIsEnabled(gl.GL_POLYGON_OFFSET_FILL)
            assert float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_FACTOR)) == 7
            assert float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_UNITS)) == 9
        finally:
            sample.world_matrix = original_matrix
            material['doubleSided'] = original_double
            gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(0,0)
        report['state_and_winding_regressions'] = 'passed'
        assert gl.glGetError() == gl.GL_NO_ERROR
        (output/'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    finally:
        target.close()
        if hasattr(renderer, 'material_renderer'):
            renderer.material_renderer.close()
        pygame.quit()


def run_editor(output, scale=1.0):
    """Capture the same problem pose in the actual Editor window, before/after."""
    from mini3d import editor
    state = {'frame': 0}
    real_flip, real_offset = pygame.display.flip, gl.glPolygonOffset

    class RomeEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            root = self.commands.spawn(ROOT/'model/08_rome_river/rome_river_side.glb', scale=[scale]*3)
            from mini3d.placement import SurfaceHit
            self.commands.place_on_surface(root, SurfaceHit([0,0,0], [0,0,1]))
            self.select(root)
            self.focus_selected()
            self.select(None)
            self.viewer.controller.yaw, self.viewer.controller.pitch = .8, .7
            self.viewer.controller.update()
            self.show_grid = False
            self.tool = 'select'

    def offset(factor, units):
        real_offset(0 if state['frame'] < 4 else factor, 0 if state['frame'] < 4 else units)

    def flip():
        if state['frame'] in (3,6):
            size = pygame.display.get_window_size()
            pixels = gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            name = 'editor-before.png' if state['frame'] == 3 else 'editor-after.png'
            pygame.image.save(pygame.image.fromstring(pixels,size,'RGB',True),str(output/name))
        assert gl.glGetError() == gl.GL_NO_ERROR
        state['frame'] += 1
        real_flip()

    with patch.object(editor,'Editor',RomeEditor), patch.object(gl,'glPolygonOffset',offset), \
            patch.object(pygame.display,'flip',flip):
        editor.run(initial_asset=None, frames=8)


if __name__ == '__main__':
    destination = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/rome-visibility'
    model_scale = float(sys.argv[2]) if len(sys.argv)>2 else 1.0
    run(destination, model_scale)
    run_editor(destination, model_scale)
