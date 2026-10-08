"""Visible SDL/ImGui acceptance run using the locally supplied four real assets.

Run: F:/gymenv/python.exe -B tests/placement_smoke.py [output-directory]
The output directory receives a scene and screenshot. Models are not downloaded.
Only fixture setup calls commands directly; acceptance actions use actual input.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import editor_app
import imgui
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d import editor
from mini3d.editor_tools import segment_distance
from mini3d.editor_ui import EditorUI
from mini3d.picking import project_point, pick_entity
from mini3d.placement import SurfaceHit, geometry_bounds, raycast_surface
from mini3d.scene import rotation_xyz


def run_smoke(output):
    records = [dict(name=name, path=str(ROOT / path)) for name, path in (
        ('Roman legionnaire', 'model/05_roman_soldier/roman_legionnaire.glb'),
        ('Side Table', 'model/03_side_table/side_table.glb'),
        ('Box', 'model/01_box/Box.glb'),
        ('Water Bottle', 'model/02_water_bottle/WaterBottle.glb'))]
    for record in records:
        if not Path(record['path']).is_file():
            raise FileNotFoundError('Acceptance requires existing local asset: ' + record['path'])
    state = dict(frame=0, items={}, values={}, mouse=(0, 0), done=False, drops=0, checks=[])
    real_get, real_flip = pygame.event.get, pygame.display.flip
    widget_originals = {name: getattr(imgui, name) for name in
                        ('button', 'radio_button', 'selectable', 'tree_node', 'drag_float3')}

    class TestEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.assets = [dict(next(item for item in self.assets
                              if Path(item['path']) == Path(record['path'])), name=record['name'])
                           for record in records]
            self.scene_path = output / 'placement-scene.json'
            # Fixture only: enlarge the existing table to fit the native-unit scan.
            table = self.commands.spawn(records[1]['path'], name='Acceptance Table', scale=[40] * 3)
            self.commands.place_on_surface(table, SurfaceHit([0, 0, 0], [0, 0, 1]))
            state['table'] = table
            self.commands.clear_history()
            self.viewer.controller.focus_bounds([-45, -20, 0], [20, 20, 65], aspect=1.4)
            self.viewer.controller.target = np.array([-6., 0, 22])
            self.viewer.controller.distance = 115
            self.viewer.controller.yaw, self.viewer.controller.pitch = -.9, .65
            self.viewer.controller.update()
            self.viewer.save_camera()
            state['app'] = self

        def drop_asset(self, *args, **kwargs):
            state['drops'] += 1
            return super().drop_asset(*args, **kwargs)

    class TestUI(EditorUI):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state['ui'] = self

    def tracked_widget(kind):
        def tracked(label, *args, **kwargs):
            result = widget_originals[kind](label, *args, **kwargs)
            low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            state['items'][label] = (low.x, low.y, high.x - low.x, high.y - low.y)
            if kind == 'drag_float3':
                state['values'][label] = np.asarray(args[:3], dtype=float)
            return result
        return tracked

    def center(rect):
        x, y, w, h = rect
        return np.array([x + w / 2, y + h / 2])

    def move(point, held=False):
        previous = state['mouse']
        state['mouse'] = tuple(map(int, point))
        return pygame.event.Event(pygame.MOUSEMOTION, pos=state['mouse'],
            rel=tuple(b - a for a, b in zip(previous, state['mouse'])), buttons=(int(held), 0, 0))

    def mouse(kind):
        return pygame.event.Event(kind, button=1, pos=state['mouse'])

    def click_point(point):
        yield [move(point), mouse(pygame.MOUSEBUTTONDOWN)]
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []

    def click(label):
        assert label in state['items'], ('Missing UI control', label)
        yield from click_point(center(state['items'][label]))

    def key(code, control=False, shift=False):
        app = state['app']
        x, y, w, h = app.viewport_rect
        mod = (pygame.KMOD_CTRL if control else 0) | (pygame.KMOD_SHIFT if shift else 0)
        yield [move((x + w - 20, y + h - 20)),
               pygame.event.Event(pygame.KEYDOWN, key=code, mod=mod, unicode='')]
        yield [pygame.event.Event(pygame.KEYUP, key=code, mod=0, unicode='')]
        yield []

    def screen(world):
        app = state['app']
        point = project_point(app.viewer.camera, world, app.viewport_rect)
        assert point is not None
        x, y, w, h = app.viewport_rect
        assert x < point[0] < x + w and y < point[1] < y + h, ('Target outside viewport', world, point)
        return point

    def asset_drag(index, world):
        label = next(label for label in state['items'] if '##asset' + str(index) in label)
        yield [move(center(state['items'][label])), mouse(pygame.MOUSEBUTTONDOWN)]
        yield [move(np.asarray(state['mouse']) + [20, 0], True)]
        yield [move(screen(world), True)]
        yield []
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []
        yield []

    def check(name):
        state['checks'].append(name)
        print('PASS:', name, flush=True)

    def rotate_z():
        app = state['app']
        app.gizmo.geometry(app.viewport_rect)
        handles = dict(app.gizmo.handles)
        candidates = []
        for index in range(4, 48):
            point = handles[2][index]
            if point is None:
                continue
            clearance = min(segment_distance(point, a, b) for axis in (0, 1)
                            for a, b in zip(handles[axis], handles[axis][1:])
                            if a is not None and b is not None)
            candidates.append((clearance, index, point))
        _, index, start = max(candidates, key=lambda item: item[0])
        end = handles[2][index + 8]
        yield [move(start), mouse(pygame.MOUSEBUTTONDOWN)]
        assert app.gizmo.drag is not None and app.gizmo.drag['axis'] == 2, 'Z rotation handle not captured'
        yield [move(end, True)]
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []

    def drive():
        for _ in range(3):
            yield []
        app, table = state['app'], state['table']
        yield from asset_drag(0, [-23, 0, 0])
        roman = app.selection
        assert state['drops'] == 1 and roman is not table
        assert roman.placement_type == 'character' and roman.keep_upright
        np.testing.assert_allclose(geometry_bounds(roman)[0][2], 0, atol=1e-6)
        check('Real Roman asset drag -> Ground -> feet at Z=0')
        top = geometry_bounds(table)[1][2]
        target = np.array([0, 0, top])
        yield from click('Place on Surface')
        assert app.place_selected_mode
        yield from click_point(screen(target))
        np.testing.assert_allclose(geometry_bounds(roman)[0][2], top, atol=.015)
        assert not app.place_selected_mode
        check('Place on Surface -> actual Side Table triangles -> Bounds Bottom at tabletop')
        yield from key(pygame.K_r)
        before_history = app.commands.undo_count
        yield from rotate_z()
        assert abs(roman.rot[2]) > .1
        assert app.commands.undo_count == before_history + 1
        np.testing.assert_allclose(rotation_xyz(roman.rot)[:, 2], [0, 0, 1], atol=1e-7)
        yield from click('Place on Surface')
        yield from click_point(screen(target))
        np.testing.assert_allclose(geometry_bounds(roman)[0][2], top, atol=.015)
        np.testing.assert_allclose(rotation_xyz(roman.rot)[:, 2], [0, 0, 1], atol=1e-7)
        check('Rotation then surface replacement preserves upright character')
        yield from key(pygame.K_g)
        app.gizmo.geometry(app.viewport_rect)
        world_end = np.asarray(app.gizmo.handles[0][1][-1])
        yield from click('Local')
        assert app.transform_space == 'local'
        app.gizmo.geometry(app.viewport_rect)
        a, b = map(np.asarray, app.gizmo.handles[0][1])
        assert np.linalg.norm(b - world_end) > 5
        before_pos, before_history = roman.pos.copy(), app.commands.undo_count
        yield [move(a + .85 * (b - a)), mouse(pygame.MOUSEBUTTONDOWN)]
        assert app.gizmo.drag is not None and app.gizmo.drag['axis'] == 0
        for factor in (.02, .04, .06):
            yield [move(a + (.85 + factor) * (b - a), True)]
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []
        delta = roman.pos - before_pos
        assert np.linalg.norm(delta) > .01
        np.testing.assert_allclose(delta / np.linalg.norm(delta), rotation_xyz(roman.rot)[:, 0], atol=.03)
        np.testing.assert_allclose(state['values']['##pos'], roman.pos, atol=1e-5)
        assert app.commands.undo_count == before_history + 1
        check('Local axis visibly differs; real Gizmo gesture -> one history entry -> Inspector sync')
        yield from key(pygame.K_d, control=True)
        duplicate = app.selection
        assert duplicate is not roman and duplicate.entity_id != roman.entity_id
        def meshes(entity):
            return ([entity.model] if entity.model is not None else []) + [mesh for child in entity.children for mesh in meshes(child)]
        assert all(a is b for a, b in zip(meshes(roman), meshes(duplicate)))
        assert all(a.material is b.material for a, b in zip(meshes(roman), meshes(duplicate)))
        check('Ctrl+D gives new stable ID while retaining shared meshes/materials/textures')
        table_label = next(label for label in state['items'] if label.startswith('Acceptance Table') and '##node' in label)
        yield from click(table_label)
        assert app.selection is table, 'Outliner must select the table'
        yield from click('Lock selected')
        assert table.locked
        hit_point = screen([6, -5, top])
        hit = raycast_surface(app.scene, app.viewer.camera, hit_point, app.viewport_rect)
        assert hit is not None and hit.entity is table
        picked, _ = pick_entity(app.scene, app.viewer.camera, hit_point, app.viewport_rect)
        assert picked is not table
        yield from key(pygame.K_q)
        yield from click_point(hit_point)
        assert app.selection is not table
        check('Locked Table still raycasts as surface, ordinary left click cannot select it')
        yield from key(pygame.K_z, control=True)
        assert not table.locked
        yield from key(pygame.K_y, control=True)
        assert table.locked
        check('Undo/Redo restores lock reliably')
        # Existing props also exercise the same drag/drop anchor path.
        for index, world in ((2, [-10, -12, 0]), (3, [6, -5, top])):
            # The table has a shaped lip: use the actual triangle hit at the
            # integer mouse pixel, not the maximum height of its entire AABB.
            support = raycast_surface(app.scene, app.viewer.camera,
                tuple(map(int, screen(world))), app.viewport_rect)
            assert support.entity is (None if index == 2 else table)
            yield from asset_drag(index, world)
            prop = app.selection
            expected = support.position[2]
            np.testing.assert_allclose(geometry_bounds(prop)[0][2], expected, atol=.02)
        check('Box drops to Ground; Water Bottle drops onto locked tabletop')
        yield from key(pygame.K_s, control=True)
        assert app.scene_path.is_file(), app.status
        saved = json.loads(app.scene_path.read_text(encoding='utf8'))
        identities = {entity.entity_id: (entity.pos.copy(), entity.rot.copy(), entity.scale.copy(),
                       entity.locked, entity.placement_type, entity.placement_anchor)
                      for entity in app.scene.root_entities}
        yield from key(pygame.K_o, control=True)
        assert len(app.scene.root_entities) == len(identities)
        for entity_id, expected in identities.items():
            entity = app.scene.find_by_id(entity_id)
            assert entity is not None
            for actual, value in zip((entity.pos, entity.rot, entity.scale), expected[:3]):
                np.testing.assert_allclose(actual, value)
            assert (entity.locked, entity.placement_type, entity.placement_anchor) == expected[3:]
        check('Ctrl+S / Ctrl+O round trip restores stable IDs, transforms, locks and placement metadata')
        assert state['drops'] == 3
        assert len(saved['objects']) == 5
        state['done'] = True
        yield []

    workflow = drive()

    def events():
        real_get()
        try:
            return next(workflow)
        except StopIteration:
            return [pygame.event.Event(pygame.QUIT)]

    def inspect():
        assert gl.glGetError() == gl.GL_NO_ERROR
        if state['done']:
            w, h = pygame.display.get_window_size()
            pixels = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            surface = pygame.image.fromstring(pixels, (w, h), 'RGB', True)
            pygame.image.save(surface, str(output / 'placement-editor.png'))
        real_flip()
        state['frame'] += 1

    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.object(editor, 'Editor', TestEditor))
        stack.enter_context(patch('mini3d.editor_ui.EditorUI', TestUI))
        stack.enter_context(patch.object(pygame.event, 'get', events))
        stack.enter_context(patch.object(pygame.display, 'flip', inspect))
        for kind in widget_originals:
            stack.enter_context(patch.object(imgui, kind, tracked_widget(kind)))
        editor_app.main(['--empty', '--frames', '240'])
    assert state['done'], 'Acceptance workflow did not reach save/load'
    (output / 'placement-result.json').write_text(json.dumps(dict(frames=state['frame'],
        checks=state['checks'], asset_drops=state['drops']), indent=2), encoding='utf8')
    print('PASS: Placement V1 visible Editor workflow; output:', output)


if __name__ == '__main__':
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='mini3d-placement-'))
    output.mkdir(parents=True, exist_ok=True)
    run_smoke(output)
