"""Drive actual ImGui drag/drop, picking, gizmo and Inspector through editor_app.

Requires desktop OpenGL. Generates its own GLB in a temporary directory; no
downloaded asset, fake drag payload or mocked scene/render operation is used.
"""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import imgui
import numpy as np
import pygame
from OpenGL import GL as gl
import editor_app
from mini3d import editor
from mini3d.editor_ui import EditorUI
from mini3d.geometry import make_box


def write_glb(path):
    vertices, indices = make_box(1, 1, 1)
    positions = np.asarray(vertices, dtype='<f4').tobytes()
    triangles = np.asarray(indices, dtype='<u2').tobytes()
    binary = positions + triangles
    binary += b'\0' * (-len(binary) % 4)
    document = dict(asset={'version': '2.0'}, scene=0, scenes=[{'nodes': [0]}],
                    nodes=[{'mesh': 0}], meshes=[{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
                    materials=[{'pbrMetallicRoughness': {'baseColorFactor': [.8, .03, .02, 1], 'metallicFactor': 0}}],
                    buffers=[{'byteLength': len(binary)}],
                    bufferViews=[{'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions)},
                                 {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(triangles)}],
                    accessors=[{'bufferView': 0, 'componentType': 5126, 'count': len(vertices), 'type': 'VEC3'},
                               {'bufferView': 1, 'componentType': 5123, 'count': np.asarray(indices).size, 'type': 'SCALAR'}])
    data = json.dumps(document).encode('utf8')
    data += b' ' * (-len(data) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(data) + len(binary)) +
                     struct.pack('<I4s', len(data), b'JSON') + data +
                     struct.pack('<I4s', len(binary), b'BIN\0') + binary)


def run_smoke(path):
    state = dict(frame=0, mouse=(0, 0), items={}, values={}, drops=0)
    real_get, real_flip = pygame.event.get, pygame.display.flip
    real_selectable, real_drag = imgui.selectable, imgui.drag_float3

    class CaptureEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.assets = [dict(name='Integration cube', path=str(path))]
            self.show_grid = False
            state['app'] = self

        def drop_asset(self, *args):
            state['drops'] += 1
            return super().drop_asset(*args)

    class CaptureUI(EditorUI):
        def __init__(self, *args):
            super().__init__(*args)
            state['ui'] = self

    def remember(label):
        low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        state['items'][label] = (low.x, low.y, high.x - low.x, high.y - low.y)

    def selectable(label, *args, **kwargs):
        result = real_selectable(label, *args, **kwargs)
        if '##asset0' in label:
            remember('asset')
        return result

    def drag(label, *args, **kwargs):
        state['values'][label] = np.array(args[:3])
        result = real_drag(label, *args, **kwargs)
        remember(label)
        return result

    def move(pos, buttons=(0, 0, 0), mod=0):
        previous = state['mouse']
        state['mouse'] = tuple(map(int, pos))
        rel = tuple(b - a for a, b in zip(previous, state['mouse']))
        return pygame.event.Event(pygame.MOUSEMOTION, pos=state['mouse'], rel=rel, buttons=buttons, mod=mod)

    def button(kind, number=1):
        return pygame.event.Event(kind, button=number, pos=state['mouse'])

    def key(kind, code):
        return pygame.event.Event(kind, key=code, mod=0, unicode='')

    def center(rect):
        x, y, w, h = rect
        return (x + w / 2, y + h / 2)

    def events():
        real_get()
        frame, app = state['frame'], state['app']
        point = center(app.viewport_rect)
        down, up = pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP
        if frame == 2:
            return [move(center(state['items']['asset'])), button(down)]
        if frame == 3:
            return [move(np.array(state['mouse']) + [20, 0], (1, 0, 0))]
        if frame == 4:
            return [move(point, (1, 0, 0))]
        if frame == 6:
            return [button(up)]
        if frame == 8:
            return [key(pygame.KEYDOWN, pygame.K_f)]
        if frame == 9:
            return [key(pygame.KEYUP, pygame.K_f), key(pygame.KEYDOWN, pygame.K_q)]
        if frame == 10:
            state['camera_before_left'] = app.viewer.camera.view_matrix.copy()
            x, y, w, h = app.viewport_rect
            return [key(pygame.KEYUP, pygame.K_q), move((x + 18, y + h - 18)), button(down)]
        if frame == 11:
            return [button(up)]
        if frame == 12:
            return [move(point), button(down)]
        if frame == 13:
            return [button(up)]
        if frame == 14:
            return [key(pygame.KEYDOWN, pygame.K_g)]
        if frame == 15:
            return [key(pygame.KEYUP, pygame.K_g)]
        if frame == 16:
            app.gizmo.geometry(app.viewport_rect)
            _, points = app.gizmo.handles[0]
            a, b = map(np.asarray, points)
            state['axis_delta'] = .4 * (b - a)
            state['before_gizmo'] = app.selection.pos.copy()
            return [move(a + .75 * (b - a)), button(down)]
        if frame == 17:
            return [move(np.array(state['mouse']) + state['axis_delta'], (1, 0, 0))]
        if frame == 18:
            return [button(up)]
        if frame == 21:
            state['inspector_history'] = app.commands.undo_count
            state['before_inspector'] = app.selection.pos.copy()
            x, y, w, h = state['items']['##pos']
            return [move((x + w / 6, y + h / 2)), button(down)]
        if frame == 22:
            return [move(np.array(state['mouse']) + [40, 0], (1, 0, 0))]
        if frame == 23:
            return [move(point, (1, 0, 0))]
        if frame == 24:
            return [button(up)]
        if frame == 26:
            return [key(pygame.KEYDOWN, pygame.K_f)]
        if frame == 27:
            return [key(pygame.KEYUP, pygame.K_f)]
        if frame == 28:
            state['before_orbit'] = app.viewer.controller.yaw
            return [move(point), button(down, 2)]
        if frame == 29:
            return [move(np.array(point) + [20, 10], (0, 1, 0))]
        if frame == 30:
            return [button(up, 2)]
        if frame == 31:
            state['before_pan'] = app.viewer.controller.target.copy()
            state['pan_yaw'] = app.viewer.controller.yaw
            return [move(point), button(down, 2)]
        if frame == 32:
            return [move(np.array(point) + [20, 10], (0, 1, 0), pygame.KMOD_SHIFT)]
        if frame == 33:
            return [button(up, 2)]
        if frame == 34:
            state['before_zoom'] = app.viewer.controller.distance
            return [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)]
        if frame == 35:
            state['before_ui_wheel'] = app.viewer.controller.distance
            return [move(center(state['items']['##pos'])), pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=2)]
        return []

    def inspect():
        frame, app = state['frame'], state['app']
        assert gl.glGetError() == gl.GL_NO_ERROR
        if frame == 7:
            assert state['drops'] == 1, ('drag/drop delivery count', state['drops'])
            assert len(app.scene.root_entities) == 1
        if frame == 11:
            assert app.selection is None, 'Blank click must deselect'
        if frame == 13:
            assert app.selection is app.scene.root_entities[0], 'Geometry click must select'
        if frame == 19:
            assert app.selection.pos[0] > state['before_gizmo'][0], 'Gizmo must move X'
            np.testing.assert_allclose(state['values']['##pos'], app.selection.pos, atol=1e-5)
        if frame in (19, 23, 25):
            np.testing.assert_allclose(app.viewer.camera.view_matrix, state['camera_before_left'])
        if frame == 23:
            assert state['ui'].mouse_captured, 'Inspector drag must own mouse over viewport'
            assert app.gizmo.drag is None
        if frame == 25:
            assert app.commands.undo_count == state['inspector_history'] + 1
            assert not app.commands.active_transaction
            assert not np.allclose(app.selection.pos, state['before_inspector'])
            np.testing.assert_allclose(state['values']['##pos'], app.selection.pos, atol=1e-5)
        if frame == 30:
            assert app.viewer.controller.yaw != state['before_orbit']
        if frame == 33:
            assert not np.allclose(app.viewer.controller.target, state['before_pan'])
            assert app.viewer.controller.yaw == state['pan_yaw']
        if frame == 34:
            assert app.viewer.controller.distance < state['before_zoom']
        if frame == 35:
            assert app.viewer.controller.distance == state['before_ui_wheel']
        if frame == 14:
            x, y, w, h = app.viewport_rect
            pixels = gl.glReadPixels(x, pygame.display.get_window_size()[1] - y - h, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            rgb = np.frombuffer(pixels, np.uint8).reshape(-1, 3).astype(int)
            assert np.count_nonzero(rgb[:, 0] > rgb[:, 1] + 40) > 1000, 'Dropped GLB must be rendered'
        real_flip()
        state['frame'] += 1

    with patch.object(editor, 'Editor', CaptureEditor), patch('mini3d.editor_ui.EditorUI', CaptureUI), \
            patch.object(pygame.event, 'get', events), patch.object(pygame.display, 'flip', inspect), \
            patch.object(imgui, 'selectable', selectable), patch.object(imgui, 'drag_float3', drag):
        editor_app.main(['--empty', '--hidden', '--frames', '38'])
    print('PASS: GLB asset drag/drop -> scene -> viewport -> picking -> gizmo -> Inspector; camera and UI arbitration')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='mini3d-glb-integration-') as temporary:
        path = Path(temporary) / 'integration.glb'
        write_glb(path)
        run_smoke(path)
