"""Real IPC screenshots survive minimization, resize and UI workspaces.

This test owns one short-lived editor, and does not attach to a user's editor.
Run on a desktop GL context: python -B tests/editor_screenshot_smoke.py OUTPUT
"""
from concurrent.futures import ThreadPoolExecutor
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
from mini3d.editor_runtime import run
from mini3d.editor_ui import EditorUI
from mini3d.ipc_client import EditorClient


def smoke(output):
    output.mkdir(parents=True, exist_ok=False)
    state = dict(frame=0, results={}, futures={})
    original_flip = pygame.display.flip
    registry = output / 'registry'
    with ThreadPoolExecutor(2) as pool:
        class App(Editor):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                state['app'] = self
                actor = self.commands.spawn(ROOT / 'model/06_stl_cube/cube.STL')
                self.select(actor)
                self.frame_all()
                self.create_camera_from_view()

        class UI(EditorUI):
            def __init__(self, app):
                super().__init__(app)
                state['ui'] = self

        def submit(name):
            state['futures'][name] = pool.submit(state['client'].call, 'screenshot',
                                               path=str(output / (name + '.png')))

        def verify(name):
            # Never block the main thread waiting for an unpumped IPC command.
            future = state['futures'][name]
            assert future.done(), name
            result = future.result()
            assert result['ok'], result
            pixels = pygame.surfarray.array3d(pygame.image.load(str(output / (name + '.png'))))
            nonzero = int(np.count_nonzero(pixels))
            assert nonzero > pixels.size // 2, (name, nonzero)
            assert int(pixels.max()) == 255, name  # UI text/handles are present.
            state['results'][name] = dict(width=pixels.shape[0], height=pixels.shape[1],
                                          nonzero_channels=nonzero)

        def flip():
            frame = state['frame']
            if frame == 1:
                paths = list(registry.glob('*.json'))
                assert len(paths) == 1
                info = json.loads(paths[0].read_text(encoding='utf8'))
                state['client'] = EditorClient(info)
                submit('visible-arrange')
            elif frame == 5:
                verify('visible-arrange')
                assert pygame.display.iconify(), 'Could not minimize test window'
            elif frame == 8:
                assert not pygame.display.get_active(), 'Test window is not minimized'
                submit('minimized-arrange')
            elif frame == 12:
                verify('minimized-arrange')
                # Readback must restore a deliberately different read FBO/buffer.
                from mini3d.render_target import RenderTarget
                other = RenderTarget()
                try:
                    other.bind()
                    gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
                    before = (int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)),
                              int(gl.glGetIntegerv(gl.GL_READ_BUFFER)),
                              int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)))
                    state['app'].api.screenshot(output / 'different-read-fbo.png')
                    after = (int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)),
                             int(gl.glGetIntegerv(gl.GL_READ_BUFFER)),
                             int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)))
                    assert before == after
                    pixels = pygame.surfarray.array3d(pygame.image.load(str(output / 'different-read-fbo.png')))
                    assert np.count_nonzero(pixels) > pixels.size // 2
                finally:
                    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
                    other.close()
                state['ui']._choose_workspace('Lighting')
                state['app'].set_lighting(mode='Scene', ambient=.2)
                submit('minimized-lighting')
            elif frame == 16:
                verify('minimized-lighting')
                state['ui']._choose_workspace('Shot')
                submit('minimized-shot-editor')
            elif frame == 20:
                verify('minimized-shot-editor')
                x,y,w,h = state['app'].viewport_rect
                assert abs(w/h - state['app'].shot_camera.aspect) < .01
                state['shot_editor_rect'] = (x,y,w,h)
                state['app'].set_camera_view(True)
                submit('minimized-shot')
            elif frame == 24:
                verify('minimized-shot')
                assert state['app'].viewport_rect == state['shot_editor_rect']
                # SDL resize/restore preserves the GL context, as user resizing does.
                from pygame._sdl2.video import Window
                # SDL stores a borrowed PyObject*: retain it through event pumping.
                window = state['window'] = Window.from_display_module()
                window.restore()
                window.size = (900, 700)
                state['ui']._choose_workspace('Arrange')
            elif frame == 28:
                submit('resized-arrange')
            elif frame == 32:
                verify('resized-arrange')
                assert (state['results']['resized-arrange']['width'],
                        state['results']['resized-arrange']['height']) == (900, 700)
                assert state['ui'].workspace == 'Arrange'
                assert not state['app'].camera_view
                # UI compositor and clean Shot output must remain independent.
                state['app'].api.capture(output / 'clean-shot.png')
                submit('after-clean-capture')
            elif frame == 36:
                verify('after-clean-capture')
            assert gl.glGetError() == gl.GL_NO_ERROR
            original_flip()
            state['frame'] += 1

        with patch('mini3d.editor_ui.EditorUI', UI), patch.object(pygame.display, 'flip', flip):
            run(App, initial_asset=None, frames=38, ipc_directory=registry)
    assert not list(registry.glob('*.json'))
    result = dict(passed=True, checks=state['results'],
                  read_framebuffer_restored=True, clean_capture_preserved=True)
    (output / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    smoke(Path(sys.argv[1]).resolve())
