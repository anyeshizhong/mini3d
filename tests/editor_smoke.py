"""Exercise the actual editor/ImGui/OpenGL loop in a hidden desktop window.

Run with: F:/gymenv/python.exe -B tests/editor_smoke.py
The test requires a desktop OpenGL driver; it is separate from headless tests.
"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import imgui
import numpy as np
import pygame
from OpenGL import GL as gl

from mini3d import editor
from mini3d.editor_ui import EditorUI


def run_smoke():
    state = dict(frame=0, app=None, ui=None, mouse=(0, 0), items={}, failures=[], modes=set())
    real_get, real_flip = pygame.event.get, pygame.display.flip
    real_menu, real_item = imgui.begin_menu, imgui.menu_item
    real_input_text = imgui.input_text

    class CaptureEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Use the distributed STL fixture, tinted red for pixel assertions.
            index = next(i for i, item in enumerate(self.assets) if Path(item['path']).suffix.lower() == '.stl')
            self.assets = [self.assets[index]]
            asset = self.cache.load(self.assets[0]['path'])
            asset.root.model.material['pbrMetallicRoughness']['baseColorFactor'] = [.8, .08, .03, 1]
            state['app'] = self

    class CaptureUI(EditorUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state['ui'] = self

    def remember(label):
        low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        state['items'][label] = ((low.x + high.x) / 2, (low.y + high.y) / 2)

    def menu(label, *args, **kwargs):
        result = real_menu(label, *args, **kwargs)
        if label == 'Render' and not result.opened:
            remember(label)
        return result

    def item(label, *args, **kwargs):
        result = real_item(label, *args, **kwargs)
        if label in ('Lit', 'Unlit', 'Wireframe'):
            remember(label)
        return result

    def input_text(label, *args, **kwargs):
        result = real_input_text(label, *args, **kwargs)
        if label == '##asset_filter':
            remember('Asset filter')
        return result

    def key(kind, code, mod=0, text=''):
        return pygame.event.Event(kind, key=code, mod=mod, unicode=text)

    def move(position, rel=(0, 0), buttons=(0, 0, 0)):
        state['mouse'] = tuple(map(int, position))
        return pygame.event.Event(pygame.MOUSEMOTION, pos=state['mouse'], rel=rel, buttons=buttons)

    def button(kind, number):
        return pygame.event.Event(kind, pos=state['mouse'], button=number)

    def click_label(label):
        if label not in state['items']:
            state['failures'].append('UI item not exposed: ' + label)
            return []
        return [move(state['items'][label]), button(pygame.MOUSEBUTTONDOWN, 1)]

    def events():
        real_get()  # Pump the OS queue, then supply reproducible input events.
        frame, app = state['frame'], state['app']
        x, y, width, height = app.viewport_rect
        center = (x + width / 2, y + height / 2)
        if frame == 1:
            return [move((x + 18, y + height - 18)), button(pygame.MOUSEBUTTONDOWN, 1)]
        if frame == 2:
            return [button(pygame.MOUSEBUTTONUP, 1), move(center), key(pygame.KEYDOWN, pygame.K_q)]
        if frame == 3:
            return [key(pygame.KEYUP, pygame.K_q), button(pygame.MOUSEBUTTONDOWN, 1)]
        if frame == 4:
            return [button(pygame.MOUSEBUTTONUP, 1)]
        if frame == 5:
            return [key(pygame.KEYDOWN, pygame.K_g)]
        if frame == 6:
            return [key(pygame.KEYUP, pygame.K_g), key(pygame.KEYDOWN, pygame.K_r)]
        if frame == 7:
            return [key(pygame.KEYUP, pygame.K_r), key(pygame.KEYDOWN, pygame.K_LCTRL, pygame.KMOD_CTRL),
                    key(pygame.KEYDOWN, pygame.K_d, pygame.KMOD_CTRL)]
        if frame == 8:
            return [key(pygame.KEYUP, pygame.K_d), key(pygame.KEYUP, pygame.K_LCTRL)]
        if frame == 9:
            return [key(pygame.KEYDOWN, pygame.K_DELETE)]
        if frame == 10:
            state['yaw'] = app.viewer.controller.yaw
            return [key(pygame.KEYUP, pygame.K_DELETE), button(pygame.MOUSEBUTTONDOWN, 2)]
        if frame == 11:
            return [move((center[0] + 30, center[1] + 15), (30, 15), (0, 1, 0))]
        if frame == 12:
            return [button(pygame.MOUSEBUTTONUP, 2)]
        if frame == 13:
            return [key(pygame.KEYDOWN, pygame.K_s)]
        if frame == 14:
            return [key(pygame.KEYUP, pygame.K_s), key(pygame.KEYDOWN, pygame.K_q)]
        if frame == 15:
            return [key(pygame.KEYUP, pygame.K_q), move((x + 18, y + height - 18)),
                    button(pygame.MOUSEBUTTONDOWN, 1)]
        if frame == 16:
            return [button(pygame.MOUSEBUTTONUP, 1), move(center)]
        if frame == 17:
            return [button(pygame.MOUSEBUTTONDOWN, 1)]
        if frame == 18:
            return [button(pygame.MOUSEBUTTONUP, 1)]
        if frame == 19:
            from pygame._sdl2 import Window
            state['before_resize'] = app.viewport_rect
            Window.from_display_module().size = (1200, 800)
            return [pygame.event.Event(pygame.VIDEORESIZE, w=1200, h=800, size=(1200, 800))]
        if frame == 20:
            return [move(center)]
        if frame in (21, 27, 33):
            return click_label('Render')
        if frame == 23:
            return click_label('Unlit')
        if frame == 29:
            return click_label('Wireframe')
        if frame == 35:
            return click_label('Lit')
        if frame in (22, 24, 28, 30, 34, 36):
            return [button(pygame.MOUSEBUTTONUP, 1)]
        if frame == 38:
            state['before_text_tool'] = app.tool
            state['before_text_roots'] = list(app.scene.root_entities)
            return click_label('Asset filter')
        if frame == 39:
            return [button(pygame.MOUSEBUTTONUP, 1)]
        if frame == 40:
            # Hovering the viewport must not steal keys from an active text field.
            return [move(center), key(pygame.KEYDOWN, pygame.K_g, text='g')]
        if frame == 41:
            return [key(pygame.KEYUP, pygame.K_g), key(pygame.KEYDOWN, pygame.K_r, text='r')]
        if frame == 42:
            return [key(pygame.KEYUP, pygame.K_r), key(pygame.KEYDOWN, pygame.K_DELETE)]
        if frame == 43:
            return [key(pygame.KEYUP, pygame.K_DELETE)]
        return []

    def check(condition, description):
        if not condition:
            ui = state['ui']
            state['failures'].append('frame {}: {} (hover={}, keyboard_capture={}, text={}, active={})'.format(
                state['frame'], description, ui.viewport_hovered, ui.keyboard_captured,
                imgui.get_io().want_text_input, imgui.is_any_item_active()))

    def inspect():
        frame, app = state['frame'], state['app']
        check(gl.glGetError() == gl.GL_NO_ERROR, 'OpenGL error')
        if frame == 1:
            check(app.selection is None, 'Blank viewport click must clear selection')
        if frame == 2:
            check(app.tool == 'select', 'Q shortcut must reach viewport')
        if frame in (4, 18):
            check(app.selection is app.scene.root_entities[0], 'Model click must select original instance')
        if frame == 5:
            check(app.tool == 'move', 'G shortcut must reach viewport')
        if frame == 6:
            check(app.tool == 'rotate', 'R shortcut must reach viewport')
        if frame == 8:
            check(len(app.scene.root_entities) == 2, 'Ctrl+D must duplicate selected object')
        if frame == 9:
            check(len(app.scene.root_entities) == 1, 'Delete must remove the duplicate')
        if frame == 12:
            check(abs(app.viewer.controller.yaw - state['yaw']) > .05, 'Middle drag must orbit')
            check(not app._orbiting, 'Middle release must stop orbit')
        if frame == 13:
            check(app.tool == 'scale', 'S shortcut must reach viewport')
        if frame == 15:
            check(app.selection is None, 'Select tool blank click must deselect')
        if frame == 20:
            check(pygame.display.get_window_size() == (1200, 800), 'Resize must retain live display')
            check(app.viewport_rect[2] < state['before_resize'][2] and
                  app.viewport_rect[3] < state['before_resize'][3],
                  'Viewport layout must follow the actual SDL window size')
            check(app.viewer.width == app.viewport_rect[2] and app.viewer.height == app.viewport_rect[3],
                  'Camera dimensions must follow resized viewport')
        if frame in (40, 41, 42, 43):
            check(app.tool == state['before_text_tool'], 'Text input G/R must not switch viewport tools')
            check(app.scene.root_entities == state['before_text_roots'], 'Text input Delete must not remove scene objects')
            check(state['ui'].keyboard_captured, 'Active asset filter must capture keyboard while viewport hovered')
        if frame == 43:
            check(state['ui'].asset_filter == 'gr', 'Real ImGui text input must receive typed characters')
        for expected_frame, mode in ((24, 'Unlit'), (30, 'Wireframe'), (36, 'Lit')):
            if frame == expected_frame:
                check(app.render_mode == mode, 'Render menu must switch to {} (actual {})'.format(mode, app.render_mode))
                state['modes'].add(app.render_mode)
        if os.environ.get('MINI3D_SMOKE_DEBUG') and frame >= 19:
            print(frame, state['mouse'], state['items'], app.render_mode, pygame.display.get_window_size())
        if frame in (4, 20, 24, 36):
            x, y, width, height = app.viewport_rect
            window_height = pygame.display.get_window_size()[1]
            pixels = gl.glReadPixels(x, window_height - y - height, width, height,
                                     gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            rgb = np.frombuffer(pixels, np.uint8).reshape(-1, 3).astype(np.int16)
            red = (rgb[:, 0] > rgb[:, 1] + 25) & (rgb[:, 0] > rgb[:, 2] + 25) & (rgb[:, 0] > 60)
            check(np.count_nonzero(red) > 300, 'Viewport must contain red Box model pixels')
        real_flip()
        state['frame'] += 1

    with patch.object(editor, 'Editor', CaptureEditor), \
            patch('mini3d.editor_ui.EditorUI', CaptureUI), \
            patch.object(pygame.event, 'get', events), \
            patch.object(pygame.display, 'flip', inspect), \
            patch.object(pygame.key, 'get_mods', return_value=0), \
            patch.object(imgui, 'begin_menu', menu), patch.object(imgui, 'menu_item', item), \
            patch.object(imgui, 'input_text', input_text):
        editor.run(initial_asset=0, frames=45, hidden=True)
    if state['failures']:
        raise AssertionError('\n'.join(state['failures']))
    print('PASS: real editor ImGui shortcuts, text capture, selection, duplicate/delete, orbit, resize, render menus, model pixels and GL errors')


if __name__ == '__main__':
    run_smoke()
