"""Real GPU FBO resolve, depth/stencil, resize, lifetime and Shot PNG parity.

python -B tests/shot_msaa_smoke.py [output-dir]
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
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    pygame.init()
    pygame.display.set_mode((64, 64), pygame.OPENGL | pygame.HIDDEN)
    renderer = GLRenderer(64, 64)
    renderer.render_mode = 'REALISTIC'
    target, caller = RenderTarget(), RenderTarget()
    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                  gl=gl.glGetString(gl.GL_VERSION).decode(), checks={})
    try:
        caller.bind()
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
        texture = target.texture
        target.resize(17, 13, samples=4)
        assert gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING) == target.framebuffer
        assert gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING) == caller.framebuffer
        assert target.texture == texture
        target.bind()
        assert gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) == gl.GL_FRAMEBUFFER_COMPLETE
        assert gl.glGetIntegerv(gl.GL_SAMPLES) == 4
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDepthMask(True); gl.glStencilMask(255)
        gl.glClearColor(.25, .5, .75, 1); gl.glClearDepth(.375); gl.glClearStencil(7)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        gl.glEnable(gl.GL_SCISSOR_TEST); gl.glScissor(0, 0, 1, 1)
        target.resolve()
        assert gl.glIsEnabled(gl.GL_SCISSOR_TEST)
        color = np.frombuffer(gl.glReadPixels(0, 0, 17, 13, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE), np.uint8).reshape(13, 17, 4)
        np.testing.assert_allclose(color, np.broadcast_to([64, 128, 191, 255], color.shape), atol=1)
        depth = gl.glReadPixels(0, 0, 17, 13, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)
        np.testing.assert_allclose(depth, .375, atol=1e-6)
        stencil = gl.glReadPixels(0, 0, 17, 13, gl.GL_STENCIL_INDEX, gl.GL_UNSIGNED_BYTE)
        assert np.all(np.frombuffer(stencil, np.uint8) == 7)
        report['checks']['four_samples_color_depth_stencil_full_resolve'] = True
        old = (target.multisample_framebuffer, target.multisample_color, target.multisample_depth)
        target.resize(29, 21, samples=4)
        target.resize(29, 21, samples=1)
        assert not gl.glIsFramebuffer(old[0]) and not any(gl.glIsRenderbuffer(h) for h in old[1:])
        assert target.texture == texture
        target.bind(); assert gl.glGetIntegerv(gl.GL_SAMPLES) == 0
        report['checks']['resize_and_editor_single_sample_release'] = True
        api = Mini3DAPI(renderer)
        api.spawn(ROOT / 'model/06_stl_cube/cube.STL')
        api.create_shot_camera(position=[110, -150, 95], target=[0, 0, 20])
        api.set_antialiasing(4)
        gl.glDisable(gl.GL_MULTISAMPLE)
        render_shot(api._app.scene, api._app.shot_camera, renderer, target)
        assert not gl.glIsEnabled(gl.GL_MULTISAMPLE)
        size = api._app.shot_camera.size
        preview = np.frombuffer(gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE), np.uint8).reshape(size[1], size[0], 3)[::-1]
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, caller.framebuffer)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
        gl.glViewport(3, 4, 29, 21)
        api.capture(output / 'shot-msaa.png')
        assert gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING) == caller.framebuffer
        assert gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING) == target.framebuffer
        np.testing.assert_array_equal(gl.glGetIntegerv(gl.GL_VIEWPORT), [3, 4, 29, 21])
        png = pygame.surfarray.array3d(pygame.image.load(str(output / 'shot-msaa.png'))).transpose(1, 0, 2)
        np.testing.assert_array_equal(preview, png)
        assert not gl.glIsEnabled(gl.GL_MULTISAMPLE)
        report['checks']['shot_preview_png_parity_and_caller_state'] = True
        api.save_scene(output / 'scene.json')
        fresh = Mini3DAPI(renderer)
        assert fresh.load_scene(output / 'scene.json')['shot_camera']['samples'] == 4
        fresh.capture(output / 'shot-reopened.png')
        np.testing.assert_array_equal(png, pygame.surfarray.array3d(
            pygame.image.load(str(output / 'shot-reopened.png'))).transpose(1, 0, 2))
        report['checks']['four_sample_scene_reload_png_exact'] = True
        handles = (target.framebuffer, target.texture, target.depth,
                   target.multisample_framebuffer, target.multisample_color, target.multisample_depth)
        target.close(); target.close()
        assert not gl.glIsFramebuffer(handles[0]) and not gl.glIsTexture(handles[1])
        assert not gl.glIsRenderbuffer(handles[2]) and not gl.glIsFramebuffer(handles[3])
        assert not any(gl.glIsRenderbuffer(h) for h in handles[4:])
        assert gl.glGetError() == gl.GL_NO_ERROR
        report['checks']['idempotent_close_no_live_gpu_handles'] = True
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)
    finally:
        target.close(); caller.close(); renderer.close(); pygame.quit()


if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'captures/shot-msaa')
