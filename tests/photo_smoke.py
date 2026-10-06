"""Exercise the real photo buttons and compare PNGs with the preview FBO.

Usage: python -B tests/photo_smoke.py [output-directory]
Requires desktop OpenGL. A temporary generated GLB keeps this self-contained.
"""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from editor_integration_smoke import write_glb
import editor_app
import imgui
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d import editor
from mini3d.render_target import RenderTarget


def run_smoke(asset, output):
    state = dict(frame=0, items={}, mouse=(0, 0), pictures=[], existing=set(output.glob('*.png')))
    real_get, real_flip, real_button = pygame.event.get, pygame.display.flip, imgui.button

    class PhotoEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.assets = [dict(name='Photo cube', path=str(asset))]
            self.capture_directory = output
            self.render_mode = 'Wireframe'  # Photo output must still be clean Lit.
            state['app'] = self

        def add_asset(self, *args, **kwargs):
            result = super().add_asset(*args, **kwargs)
            self.viewer.controller.zoom(-6)
            return result

    class TrackedTarget(RenderTarget):
        def __init__(self):
            super().__init__()
            state.setdefault('preview', self)

    def button(label, *args, **kwargs):
        result = real_button(label, *args, **kwargs)
        low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        state['items'][label] = ((low.x + high.x) / 2, (low.y + high.y) / 2)
        return result

    def check_missing():
        assert state['app'].shot_camera is None
        assert set(output.glob('*.png')) == state['existing']

    def check_created():
        app = state['app']
        np.testing.assert_allclose(app.shot_camera.view_matrix, app.viewer.camera.view_matrix)
        assert app.shot_camera.fov_y == app.viewer.camera.fov_y
        state['shot_pose'] = app.shot_camera.view_matrix.copy()

    def check_lens(focal):
        assert abs(state['app'].shot_camera.focal_mm - focal) < 1e-6

    def check_ratio(name):
        app = state['app']
        assert app.shot_camera.aspect_name == name
        assert abs(app.viewport_rect[2] / app.viewport_rect[3] - app.shot_camera.aspect) < .01

    def check_capture():
        app = state['app']
        assert app.last_capture.is_file(), app.status
        assert app.last_capture not in state['pictures']
        surface = pygame.image.load(str(app.last_capture))
        assert surface.get_size() == app.shot_camera.size
        png = np.frombuffer(pygame.image.tostring(surface, 'RGB'), np.uint8).reshape(surface.get_height(), surface.get_width(), 3)
        assert png.std() > 10, 'Photo must contain rendered scene pixels'
        state['pictures'].append(app.last_capture)
        if app.camera_view:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, state['preview'].framebuffer)
            pixels = gl.glReadPixels(0, 0, *app.shot_camera.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
            preview = np.frombuffer(pixels, np.uint8).reshape(png.shape)[::-1]
            np.testing.assert_array_equal(png, preview, err_msg='PNG must exactly match the clean Shot Camera FBO')
        assert app.show_grid and app.scene.show_grid, 'Capture must preserve editor grid settings'
        if len(state['pictures']) == 1:
            state['grid_on_png'] = png.copy()
        if len(state['pictures']) == 2:
            np.testing.assert_array_equal(png, state['grid_on_png'], err_msg='Composition grid must not enter PNG')
        if app.shot_camera.aspect_name == '1:1':
            if 'square_png' in state:
                np.testing.assert_array_equal(png, state['square_png'], err_msg='Editor navigation must not change Shot Camera capture')
            else:
                state['square_png'] = png.copy()

    def check_orbit():
        app = state['app']
        assert not np.allclose(app.viewer.camera.view_matrix, state['editor_pose'])
        np.testing.assert_allclose(app.shot_camera.view_matrix, state['shot_pose'])

    actions = [('Capture', check_missing), ('Create Camera From View', check_created)]
    actions += [(str(focal) + 'mm', lambda f=focal: check_lens(f)) for focal in (24, 35, 50, 85, 35)]
    actions += [('Camera View', lambda: None), ('16:9', lambda: check_ratio('16:9')),
                ('Capture', check_capture), ('Grid On', lambda: None), ('Capture', check_capture),
                ('3:2', lambda: check_ratio('3:2')), ('Capture', check_capture),
                ('4:3', lambda: check_ratio('4:3')), ('Capture', check_capture),
                ('1:1', lambda: check_ratio('1:1')), ('Capture', check_capture),
                ('Editor View', lambda: None), ('Orbit', check_orbit), ('Capture', check_capture),
                ('Camera View', lambda: check_ratio('1:1'))]

    def event(kind, **kwargs):
        return pygame.event.Event(kind, **kwargs)

    def events():
        real_get()
        offset = state['frame'] - 2
        if offset < 0:
            return []
        index, phase = divmod(offset, 4)
        if index >= len(actions):
            return []
        label = actions[index][0]
        if label == 'Orbit':
            app = state['app']
            x, y, w, h = app.viewport_rect
            if phase == 0:
                state['editor_pose'] = app.viewer.camera.view_matrix.copy()
                state['mouse'] = (int(x + w / 2), int(y + h / 2))
                return [event(pygame.MOUSEMOTION, pos=state['mouse'], rel=(0, 0), buttons=(0, 0, 0)),
                        event(pygame.MOUSEBUTTONDOWN, button=2, pos=state['mouse'])]
            if phase == 1:
                state['mouse'] = (state['mouse'][0] + 40, state['mouse'][1] + 20)
                return [event(pygame.MOUSEMOTION, pos=state['mouse'], rel=(40, 20), buttons=(0, 1, 0))]
            if phase == 2:
                return [event(pygame.MOUSEBUTTONUP, button=2, pos=state['mouse'])]
        elif phase == 0:
            state['mouse'] = tuple(map(int, state['items'][label]))
            return [event(pygame.MOUSEMOTION, pos=state['mouse'], rel=(0, 0), buttons=(0, 0, 0)),
                    event(pygame.MOUSEBUTTONDOWN, button=1, pos=state['mouse'])]
        elif phase == 1:
            return [event(pygame.MOUSEBUTTONUP, button=1, pos=state['mouse'])]
        return []

    def inspect():
        assert gl.glGetError() == gl.GL_NO_ERROR
        offset = state['frame'] - 2
        index, phase = divmod(offset, 4)
        if offset >= 0 and index < len(actions) and phase == 3:
            actions[index][1]()
        real_flip()
        state['frame'] += 1

    with patch.object(editor, 'Editor', PhotoEditor), patch('mini3d.render_target.RenderTarget', TrackedTarget), \
            patch.object(imgui, 'button', button), patch.object(pygame.event, 'get', events), \
            patch.object(pygame.display, 'flip', inspect):
        editor_app.main(['--asset', '1', '--hidden', '--frames', str(2 + 4 * len(actions))])
    assert len(state['pictures']) == 6
    print('PASS: real photo buttons, 4 lenses/aspects, 6 PNGs, clean preview equality, grid exclusion and independent cameras')
    for path in state['pictures']:
        print(path)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='mini3d-photo-') as temporary:
        directory = Path(temporary)
        asset = directory / 'photo.glb'
        write_glb(asset)
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else directory
        output.mkdir(parents=True, exist_ok=True)
        run_smoke(asset, output)
