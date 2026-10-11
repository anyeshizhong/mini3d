"""Real GPU regressions for export isolation, clean shots and failed startup.

--record-only records pre-fix failures without treating them as a passing test.
Uses tiny photos, actual GL state and the same editor runtime as the app.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from examples.legacy_scene import Entity, Mesh, Scene
from mini3d.camera import Camera
from mini3d.geometry import make_box
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import ShotCamera, render_shot, capture_png


def run(output, record_only=False):
    output.mkdir(parents=True, exist_ok=True)
    report = dict(checks={}, errors={}, gpu=None)
    pygame.init()
    pygame.display.set_mode((64, 64), pygame.OPENGL | pygame.HIDDEN)
    report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()
    renderer, target = GLRenderer(128, 96), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    scene = Scene()
    scene.show_grid, scene.show_axes = False, False
    entity = Entity(Mesh(*make_box(2, 2, 2)), name='legacy mesh')
    scene.add(entity)
    scene.update()
    camera = Camera([5, -7, 5], near=.01, far=200)
    camera.look_at([0, 0, 0])
    shot = ShotCamera(camera)
    pack_names = ('ALIGNMENT', 'ROW_LENGTH', 'SKIP_ROWS', 'SKIP_PIXELS')
    try:
        with patch.dict(ShotCamera.ASPECTS, {'16:9': (128, 96)}):
            def picture():
                render_shot(scene, shot, renderer, target)
                return bytes(gl.glReadPixels(0, 0, 128, 96, gl.GL_RGB, gl.GL_UNSIGNED_BYTE))
            plain = picture()
            entity.isaxes = True
            helpers = picture()
            report['checks']['shot_hides_entity_axes'] = plain == helpers
            for name, raw in (('clean-reference', plain), ('shot-with-axis-flag', helpers)):
                pygame.image.save(pygame.image.fromstring(raw, (128, 96), 'RGB', True),
                                  str(output / (name + '.png')))
            # The compatibility editor/demo axes must remain available.
            entity.isaxes = False
            target.bind(); renderer.render(scene, camera)
            no_axis = bytes(gl.glReadPixels(0, 0, 128, 96, gl.GL_RGB, gl.GL_UNSIGNED_BYTE))
            entity.isaxes = True
            renderer.render(scene, camera)
            axis = bytes(gl.glReadPixels(0, 0, 128, 96, gl.GL_RGB, gl.GL_UNSIGNED_BYTE))
            report['checks']['editor_entity_axes_retained'] = no_axis != axis
            entity.isaxes = False
            capture_png(scene, shot, renderer, output / 'export-reference.png')
            pbo = int(gl.glGenBuffers(1))
            original = {name: int(gl.glGetIntegerv(getattr(gl, 'GL_PACK_' + name)))
                        for name in pack_names}
            hostile = dict(ALIGNMENT=8, ROW_LENGTH=136, SKIP_ROWS=2, SKIP_PIXELS=3)
            try:
                gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, pbo)
                gl.glBufferData(gl.GL_PIXEL_PACK_BUFFER, 100000, None, gl.GL_STREAM_READ)
                for name, value in hostile.items():
                    gl.glPixelStorei(getattr(gl, 'GL_PACK_' + name), value)
                try:
                    capture_png(scene, shot, renderer, output / 'export-hostile-state.png')
                    report['checks']['export_ignores_pack_state_and_pbo'] = (
                        (output / 'export-reference.png').read_bytes() ==
                        (output / 'export-hostile-state.png').read_bytes())
                except Exception as exc:
                    report['checks']['export_ignores_pack_state_and_pbo'] = False
                    report['errors']['export'] = type(exc).__name__ + ': ' + str(exc)
                report['checks']['export_restores_pack_state_and_pbo'] = (
                    int(gl.glGetIntegerv(gl.GL_PIXEL_PACK_BUFFER_BINDING)) == pbo and
                    all(int(gl.glGetIntegerv(getattr(gl, 'GL_PACK_' + name))) == value
                        for name, value in hostile.items()))
                report['pack_state_after_export'] = {
                    name: int(gl.glGetIntegerv(getattr(gl, 'GL_PACK_' + name)))
                    for name in pack_names}
                report['pbo_restored'] = int(gl.glGetIntegerv(gl.GL_PIXEL_PACK_BUFFER_BINDING)) == pbo
            finally:
                gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, 0)
                for name, value in original.items():
                    gl.glPixelStorei(getattr(gl, 'GL_PACK_' + name), value)
                gl.glDeleteBuffers(1, [pbo])
            report['checks']['gl_error_zero'] = gl.glGetError() == gl.GL_NO_ERROR
    finally:
        target.close(); renderer.close(); pygame.quit()

    # Constructor failure used to bypass the runtime's finally block.
    from mini3d.editor_runtime import run as run_editor
    import mini3d.gl_renderer as renderer_module
    import mini3d.render_target as target_module
    calls = dict(renderer=0, target=0)
    class RecordingRenderer(GLRenderer):
        def close(self):
            calls['renderer'] += 1
            super().close()
    class RecordingTarget(RenderTarget):
        def close(self):
            calls['target'] += 1
            super().close()
    def fail_editor(*args, **kwargs):
        raise RuntimeError('controlled editor constructor failure')
    try:
        with patch.object(renderer_module, 'GLRenderer', RecordingRenderer), \
                patch.object(target_module, 'RenderTarget', RecordingTarget):
            try:
                run_editor(fail_editor, None, frames=1, hidden=True)
            except RuntimeError as exc:
                assert str(exc) == 'controlled editor constructor failure'
        report['startup_close_calls'] = calls
        report['checks']['failed_startup_releases_resources'] = (
            calls == dict(renderer=1, target=1) and not pygame.display.get_init())
    finally:
        if pygame.display.get_init():
            import imgui
            context = imgui.get_current_context()
            if context is not None:
                imgui.destroy_context(context)
            pygame.quit()
    (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))
    if not record_only:
        assert all(report['checks'].values()), report['checks']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--record-only', action='store_true')
    args = parser.parse_args()
    run(args.output, args.record_only)
