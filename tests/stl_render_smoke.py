"""Render a real STL through the editor in all three material modes.

Usage: python -B tests/stl_render_smoke.py [model.stl] [screenshot-directory]
Requires a desktop OpenGL driver.
"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d import editor


def run_smoke(path, output=None):
    modes = ['Lit', 'Unlit', 'Wireframe']
    state = {'frame': 0}
    real_flip = pygame.display.flip

    class StlEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.import_asset(path)
            self.show_grid = False
            state['app'] = self

    def inspect():
        assert gl.glGetError() == gl.GL_NO_ERROR
        app = state['app']
        x, y, width, height = app.viewport_rect
        window_height = pygame.display.get_window_size()[1]
        pixels = gl.glReadPixels(x, window_height - y - height, width, height,
                                 gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        rgb = np.frombuffer(pixels, np.uint8).reshape(-1, 3).astype(int)
        gray = (rgb.min(axis=1) > 70) & (rgb.max(axis=1) - rgb.min(axis=1) < 40)
        model_pixels = (np.all(np.abs(rgb - [184, 212, 240]) <= 3, axis=1)
                        if app.render_mode == 'Wireframe' else gray)
        assert np.count_nonzero(model_pixels) > 200, 'STL missing in ' + app.render_mode
        if output:
            output.mkdir(parents=True, exist_ok=True)
            image = pygame.image.fromstring(pixels, (width, height), 'RGB', True)
            pygame.image.save(image, str(output / ('stl-' + app.render_mode + '.png')))
        real_flip()
        state['frame'] += 1
        if state['frame'] < len(modes):
            app.render_mode = modes[state['frame']]

    with patch.object(editor, 'Editor', StlEditor), patch.object(pygame.display, 'flip', inspect):
        editor.run(initial_asset=None, frames=3, hidden=True)
    print('PASS: STL Lit, Unlit, Wireframe model pixels and GL errors')


if __name__ == '__main__':
    candidates = [ROOT / 'model/06_stl_cube/cube.STL', ROOT / 'model/cube.STL']
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else next(path for path in candidates if path.is_file())
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    run_smoke(path, output)
