"""Real SDL/GL acceptance for asset actions, popups, splitters and Shot flow."""
from pathlib import Path
import sys
from unittest.mock import patch
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import imgui
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.editor_runtime import run
from mini3d.editor_ui import EditorUI
from mini3d.native_renderer import NativeSceneRenderer


def smoke(output):
    output.mkdir(parents=True, exist_ok=False)
    state = dict(frame=0, mouse=(0, 0), items={}, splitters={}, checks=[], native_calls=0)
    original_get, original_flip = pygame.event.get, pygame.display.flip
    original_button, original_selectable, original_radio = imgui.button, imgui.selectable, imgui.radio_button
    original_native = NativeSceneRenderer.render

    class App(Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.assets = [dict(name='Test cube {:02d}'.format(i), path=str(ROOT / 'model/06_stl_cube/cube.STL')) for i in range(80)]
            self.add_asset(0)
            self.frame_all()
            self.scene_path = output / 'scene.json'
            state['app'] = self

    class UI(EditorUI):
        def __init__(self, app):
            super().__init__(app)
            state['ui'] = self

        def _splitter(self, name, x, y, width, height, vertical):
            state['splitters'][name] = (x, y, width, height)
            delta = super()._splitter(name, x, y, width, height, vertical)
            if name == '##left_split' and 14 <= state['frame'] <= 19:
                state.setdefault('split_trace', []).append((state['frame'], x, delta,
                    tuple(imgui.get_io().mouse_pos), bool(imgui.get_io().mouse_down[0])))
            return delta

    def remember(label):
        low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        state['items'][label] = (low.x, low.y, high.x-low.x, high.y-low.y)

    def button(label, *args, **kwargs):
        result = original_button(label, *args, **kwargs)
        remember(label)
        return result

    def selectable(label, *args, **kwargs):
        result = original_selectable(label, *args, **kwargs)
        if '##asset' in label:
            remember(label.split('##')[-1])
        return result

    def radio(label, *args, **kwargs):
        result = original_radio(label, *args, **kwargs)
        remember(label)
        return result

    def native(*args, **kwargs):
        # First visible frame must precede cold resource/shader initialization.
        assert state.get('first_frame_visible'), 'Native initialized before editor was shown'
        state['native_calls'] += 1
        return original_native(*args, **kwargs)

    def center(rect):
        x, y, w, h = rect
        return x+w/2, y+h/2

    def move(point, held=False):
        previous = state['mouse']
        state['mouse'] = tuple(map(int, point))
        return pygame.event.Event(pygame.MOUSEMOTION, pos=state['mouse'],
            rel=tuple(b-a for a,b in zip(previous,state['mouse'])), buttons=(int(held),0,0))

    def down(label=None, point=None):
        point = point if point is not None else center(state['items'][label])
        return [move(point), pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=state['mouse'])]

    def up():
        return [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=state['mouse'])]

    def events():
        actual = original_get()
        frame, app = state['frame'], state['app']
        if frame == 2:
            state['add_rect'] = state['items']['Add to scene']
            return [move(center(state['items']['asset0'])), pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-100)]
        if frame == 4:
            return down('asset79')
        if frame in (5, 8, 11, 13, 18, 22, 26, 31, 34, 37, 40, 43, 46, 49, 52):
            return up()
        if frame == 7:
            assert state['ui'].selected_asset == 79
            assert state['items']['Add to scene'] == state['add_rect']
            return down('Add to scene')
        if frame == 10:
            state['selection'] = app.selection.entity_id
            return down('More...')
        if frame == 12:
            return down(point=center(app.viewport_rect))
        if frame == 15:
            state['before_left'] = app.viewport_rect
            state['pose'] = app.viewer.camera.view_matrix.copy()
            return down(point=center(state['splitters']['##left_split']))
        if frame == 16:
            return [move(np.array(state['mouse']) + [30,0], True)]
        if frame == 17:
            return [move(np.array(state['mouse']) + [20,0], True)]
        if frame == 20:
            state['before_right'] = app.viewport_rect
            return down(point=center(state['splitters']['##right_split']))
        if frame == 21:
            return [move(np.array(state['mouse']) + [-30,0], True)]
        if frame == 24:
            state['before_horizontal'] = state['splitters']['##inspector_split'][1]
            return down(point=center(state['splitters']['##inspector_split']))
        if frame == 25:
            return [move(np.array(state['mouse']) + [0,40], True)]
        if frame == 28:
            from pygame._sdl2.video import Window
            state['window'] = Window.from_display_module()
            state['window'].size = (900,700)
        if frame == 30:
            state['library_rect'] = app.viewport_rect
            return down('Hide library')
        if frame == 33:
            assert app.viewport_rect[2] > state['library_rect'][2]
            return down('Show library')
        if frame == 36:
            assert app.viewport_rect[0] > 0
            return down('Shot##workspace')
        if frame == 39:
            assert app.shot_camera is None and not app.camera_view
            return down('Create Camera From View')
        if frame == 42:
            assert app.shot_camera is not None and not app.camera_view
            return down('Camera View')
        if frame == 45:
            assert app.camera_view
            return down('Arrange##workspace')
        if frame == 48:
            assert not app.camera_view
            return down('Undo')
        if frame == 51:
            assert len(app.scene.root_entities) == 1
            return down('Redo')
        return actual

    def flip():
        frame, app = state['frame'], state['app']
        if frame == 0:
            assert state['native_calls'] == 0
            app.api.screenshot(output / 'startup.png')
            state['first_frame_visible'] = True
        if frame == 9:
            assert len(app.scene.root_entities) == 2
            state['checks'].append('scrolled asset79 selected and fixed Add button added it')
        if frame == 14:
            app.api.screenshot(output / 'popup-after-outside.png')
            assert not imgui.is_popup_open('', imgui.POPUP_ANY_POPUP)
            assert app.selection.entity_id == state['selection']
            assert app.gizmo.drag is None
            state['checks'].append('popup click-away did not pick or begin a gizmo')
        if frame == 19:
            assert app.viewport_rect[0] > state['before_left'][0] + 20, (app.viewport_rect, state['before_left'], state.get('split_trace'))
            np.testing.assert_array_equal(app.viewer.camera.view_matrix, state['pose'])
        if frame == 23:
            assert app.viewport_rect[2] < state['before_right'][2] - 15
        if frame == 27:
            assert state['splitters']['##inspector_split'][1] > state['before_horizontal'] + 20
            assert app.selection.entity_id == state['selection']
            state['checks'].append('three splitters resize without camera or selection changes')
        if frame in (29,35,38,44):
            app.api.screenshot(output / ('frame-{}.png'.format(frame)))
        if frame == 53:
            assert len(app.scene.root_entities) == 2
            state['checks'].append('Undo and Redo via header buttons')
        if frame == 54:
            app.save_scene()
            app.load_scene()
            assert len(app.scene.root_entities) == 2 and app.shot_camera is not None
            app.api.capture(output / 'photo.png')
            state['checks'].append('Shot explicit creation, view switches, save/reload and clean capture')
        assert gl.glGetError() == gl.GL_NO_ERROR
        original_flip()
        state['frame'] += 1

    with patch('mini3d.editor_ui.EditorUI', UI), patch.object(pygame.event,'get',events), \
         patch.object(pygame.display,'flip',flip), patch.object(imgui,'button',button), \
         patch.object(imgui,'selectable',selectable), patch.object(imgui,'radio_button',radio), \
         patch.object(NativeSceneRenderer,'render',native):
        run(App, initial_asset=None, frames=57, ipc=False)
    report = dict(passed=True, checks=state['checks'], native_calls=state['native_calls'])
    (output / 'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    smoke(Path(sys.argv[1]).resolve())
