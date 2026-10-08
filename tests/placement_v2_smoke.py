"""Visible V2 acceptance with real assets, SDL input and actual ImGui widgets.

Run: F:/gymenv/python.exe -B tests/placement_v2_smoke.py [output-directory]
Asset setup normalizes the Roman scan to metre-scale using an explicit command;
the acceptance gestures themselves go through the real Editor input/UI paths.
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
from mini3d.picking import project_point
from mini3d.placement import SurfaceHit, geometry_bounds
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
    state = dict(frame=0, items={}, mouse=(0, 0), done=False, drops=0, checks=[], screenshot=None)
    real_get, real_flip = pygame.event.get, pygame.display.flip
    originals = {name: getattr(imgui, name) for name in
                 ('button', 'radio_button', 'selectable', 'tree_node', 'input_int', 'input_float')}

    class TestEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.assets = [dict(next(item for item in self.assets
                               if Path(item['path']) == Path(record['path'])), name=record['name'])
                           for record in records]
            self.scene_path = output / 'placement-v2-scene.json'
            table = self.commands.spawn(records[1]['path'], name='Acceptance Table', scale=[3] * 3)
            self.commands.place_on_surface(table, SurfaceHit([-5, 2, 0], [0, 0, 1]))
            self.commands.lock(table)
            state['table_id'] = table.entity_id
            self.commands.clear_history()
            self.viewer.controller.target = np.array([.5, 0., 1.])
            self.viewer.controller.distance = 23
            self.viewer.controller.yaw, self.viewer.controller.pitch = -.9, .75
            self.viewer.controller.update()
            self.viewer.save_camera()
            state['app'] = self

        def drop_asset(self, *args, **kwargs):
            state['drops'] += 1
            return super().drop_asset(*args, **kwargs)

    def tracked_widget(kind):
        def tracked(label, *args, **kwargs):
            result = originals[kind](label, *args, **kwargs)
            low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            state['items'][label] = (low.x, low.y, high.x - low.x, high.y - low.y)
            return result
        return tracked

    def center(rect):
        x, y, w, h = rect
        return np.array([x + w / 2, y + h / 2])

    def move(point, held=False, middle=False, shift=False):
        previous = state['mouse']
        state['mouse'] = tuple(map(int, point))
        return pygame.event.Event(pygame.MOUSEMOTION, pos=state['mouse'],
            rel=tuple(b - a for a, b in zip(previous, state['mouse'])),
            buttons=(int(held), int(middle), 0), mod=pygame.KMOD_SHIFT if shift else 0)

    def mouse(kind, button=1, shift=False):
        return pygame.event.Event(kind, button=button, pos=state['mouse'],
                                  mod=pygame.KMOD_SHIFT if shift else 0)

    def click_point(point, shift=False):
        if shift:
            yield [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LSHIFT, mod=pygame.KMOD_SHIFT, unicode='')]
        yield [move(point, shift=shift), mouse(pygame.MOUSEBUTTONDOWN, shift=shift)]
        yield [mouse(pygame.MOUSEBUTTONUP, shift=shift)]
        if shift:
            yield [pygame.event.Event(pygame.KEYUP, key=pygame.K_LSHIFT, mod=0, unicode='')]
        yield []

    def click(label, shift=False):
        assert label in state['items'], ('Missing UI control', label)
        yield from click_point(center(state['items'][label]), shift=shift)

    def key(code, control=False, shift=False):
        app = state['app']
        x, y, w, h = app.viewport_rect
        mod = (pygame.KMOD_CTRL if control else 0) | (pygame.KMOD_SHIFT if shift else 0)
        yield [move((x + w - 18, y + h - 18)),
               pygame.event.Event(pygame.KEYDOWN, key=code, mod=mod, unicode='')]
        yield [pygame.event.Event(pygame.KEYUP, key=code, mod=0, unicode='')]
        yield []

    def screen(world):
        app = state['app']
        point = project_point(app.viewer.camera, world, app.viewport_rect)
        assert point is not None
        x, y, w, h = app.viewport_rect
        assert x < point[0] < x + w and y < point[1] < y + h, ('Outside viewport', world, point)
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

    def node_label(entity):
        return next(label for label in state['items']
                    if label.startswith(entity.name + '##node') or
                    label.startswith(entity.name + ' [Locked]##node'))

    def check(name, screenshot=None):
        state['checks'].append(name)
        if screenshot:
            state['screenshot'] = screenshot
        print('PASS:', name, flush=True)

    def axis_move(factor=.25):
        app = state['app']
        app.gizmo.geometry(app.viewport_rect)
        a, b = map(np.asarray, app.gizmo.handles[0][1])
        start = a + .85 * (b - a)
        yield [move(start), mouse(pygame.MOUSEBUTTONDOWN)]
        assert app.gizmo.drag is not None and app.gizmo.drag['axis'] == 0, app.status
        for amount in np.linspace(.02, factor, 5):
            yield [move(start + amount * (b - a), True)]
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []

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
        end = handles[2][index + 5]
        yield [move(start), mouse(pygame.MOUSEBUTTONDOWN)]
        assert app.gizmo.drag is not None and app.gizmo.drag['axis'] == 2, app.status
        yield [move(end, True)]
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []

    def meshes(entity):
        return ([entity.model] if entity.model is not None else []) + [
            mesh for child in entity.children for mesh in meshes(child)]

    def drive():
        for _ in range(3):
            yield []
        app = state['app']
        yield from asset_drag(0, [-3, -3, 0])
        roman = app.selection
        assert state['drops'] == 1 and roman.placement_type == 'character'
        np.testing.assert_allclose(geometry_bounds(roman)[0][2], 0, atol=1e-6)
        # Explicit fixture scale, not a hidden automatic unit conversion feature.
        app.commands.set_transform(roman, scale=[.06] * 3, rotation=[0, 0, .35])
        app.commands.place_on_surface(roman, SurfaceHit([-3, -3, 0], [0, 0, 1]))
        app.commands.clear_history()
        state['roman_id'] = roman.entity_id
        yield []
        yield from click('Surface Move')
        assert app.tool == 'surface'
        before = roman.pos.copy()
        low, high = geometry_bounds(roman)
        start = screen((low + high) * .5)
        yield [move(start), mouse(pygame.MOUSEBUTTONDOWN)]
        assert app.surface_drag is not None and app.surface_drag.active, app.status
        positions = []
        for x in np.linspace(-2.9, -1.8, 12):
            yield [move(screen([x, -3, 0]), True)]
            positions.append(roman.pos.copy())
            np.testing.assert_allclose(geometry_bounds(roman)[0][2], 0, atol=1e-6)
            np.testing.assert_allclose(rotation_xyz(roman.rot)[:, 2], [0, 0, 1], atol=1e-8)
        yield [mouse(pygame.MOUSEBUTTONUP)]
        yield []
        after = roman.pos.copy()
        assert np.linalg.norm(after - before) > .5
        assert len({tuple(pos) for pos in positions}) > 8
        assert app.commands.undo_count == 1
        yield from key(pygame.K_z, control=True)
        np.testing.assert_array_equal(roman.pos, before)
        yield from key(pygame.K_y, control=True)
        np.testing.assert_array_equal(roman.pos, after)
        check('A: actual Roman drag -> Ground -> continuous Surface Move -> one Undo -> Redo',
              'surface-drag.png')

        yield from asset_drag(2, [2, -2, 0])
        boxes = [app.selection]
        yield from key(pygame.K_g)
        for _ in range(3):
            yield from key(pygame.K_d, control=True)
            boxes.append(app.selection)
            yield from axis_move(.20)
        assert len({box.entity_id for box in boxes}) == 4
        # Shift-click the actual Outliner nodes to construct a multi selection.
        yield from click(node_label(boxes[0]))
        for box in boxes[1:]:
            yield from click(node_label(box), shift=True)
        assert {e.entity_id for e in app.selected_entities} == {e.entity_id for e in boxes}
        before = np.array([e.pos.copy() for e in boxes])
        count = app.commands.undo_count
        yield from axis_move(.18)
        moved = np.array([e.pos.copy() for e in boxes])
        np.testing.assert_allclose(moved - before, np.tile(moved[0] - before[0], (4, 1)), atol=1e-8)
        assert app.commands.undo_count == count + 1
        yield from key(pygame.K_r)
        yield from rotate_z()
        rotated = np.array([e.pos.copy() for e in boxes])
        np.testing.assert_allclose(rotated.mean(axis=0), moved.mean(axis=0), atol=1e-7)
        np.testing.assert_allclose(np.linalg.norm(rotated - rotated[0], axis=1),
                                   np.linalg.norm(moved - moved[0], axis=1), atol=1e-7)
        assert np.linalg.norm(rotated - moved) > .01
        yield from click('Group selected')
        group = app.scene.find_group_by_id(app.scene.selected_group_id)
        assert group is not None and set(group.member_ids) == {e.entity_id for e in boxes}
        box_group_id, box_ids = group.group_id, list(group.member_ids)
        yield from key(pygame.K_s, control=True)
        yield from key(pygame.K_o, control=True)
        group = app.scene.find_group_by_id(box_group_id)
        assert group is not None and group.member_ids == box_ids
        np.testing.assert_allclose([app.scene.find_by_id(value).pos for value in box_ids], rotated)
        check('B: three Box duplicates -> actual Shift multi selection -> Move/Rotate -> Group -> Save/Load',
              'multi-group.png')

        # A locally available Bottle uses the same Ground placement path.
        yield from asset_drag(3, [-4, -1, 0])
        np.testing.assert_allclose(geometry_bounds(app.selection)[0][2], 0, atol=1e-6)
        roman = app.scene.find_by_id(state['roman_id'])
        yield from click(node_label(roman))
        assert app.selection is roman and len(app.selected_entities) == 1
        old_count, before_count = len(app.scene.root_entities), app.commands.undo_count
        origin, yaw = roman.pos.copy(), roman.rot[2]
        assert 'Rows' in state['items'] and 'Columns' in state['items']
        assert 'Spacing X' in state['items'] and 'Spacing Y' in state['items']
        yield from click('Create Formation')
        group = app.scene.find_group_by_id(app.scene.selected_group_id)
        assert group is not None and len(group.member_ids) == 40, app.status
        group_id, ids = group.group_id, list(group.member_ids)
        assert ids[0] == roman.entity_id and len(set(ids)) == 40
        assert len(app.scene.root_entities) == old_count + 39
        assert app.commands.undo_count == before_count + 1
        formation = [app.scene.find_by_id(value) for value in ids]
        basis = rotation_xyz([0, 0, yaw])
        expected = [origin + basis @ [column * 1.2, row * 1.4, 0]
                    for row in range(5) for column in range(8)]
        # ImGui numeric inputs round through float32; engine transforms remain float64.
        np.testing.assert_allclose([e.pos for e in formation], expected, atol=1e-6)
        source_meshes = meshes(roman)
        for entity in formation:
            assert all(a is b and a.material is b.material for a, b in zip(source_meshes, meshes(entity)))
            np.testing.assert_array_equal(entity.rot, roman.rot)
            np.testing.assert_array_equal(entity.scale, roman.scale)
            if entity is not roman:
                assert not np.shares_memory(entity.pos, roman.pos)
                assert not np.shares_memory(entity.rot, roman.rot)
                assert not np.shares_memory(entity.scale, roman.scale)
        yield from key(pygame.K_z, control=True)
        assert len(app.scene.root_entities) == old_count
        assert app.scene.find_by_id(roman.entity_id) is roman
        assert app.scene.find_group_by_id(group_id) is None
        np.testing.assert_array_equal(roman.pos, origin)
        yield from key(pygame.K_y, control=True)
        group = app.scene.find_group_by_id(group_id)
        assert group is not None and group.member_ids == ids
        np.testing.assert_allclose([app.scene.find_by_id(value).pos for value in ids], expected, atol=1e-6)
        assert {e.entity_id for e in app.selected_entities} == set(ids)
        check('C: Create Formation 5x8 -> 40 unique IDs, shared Mesh/Material/Texture; Undo preserves source; Redo restores IDs')
        yield from key(pygame.K_g)
        before = np.array([e.pos.copy() for e in formation])
        yield from axis_move(.12)
        moved = np.array([e.pos.copy() for e in formation])
        np.testing.assert_allclose(moved - before, np.tile(moved[0] - before[0], (40, 1)), atol=1e-7)
        yield from key(pygame.K_r)
        yield from rotate_z()
        rotated = np.array([e.pos.copy() for e in formation])
        np.testing.assert_allclose(rotated.mean(axis=0), moved.mean(axis=0), atol=1e-7)
        assert np.linalg.norm(rotated - moved) > .1
        check('40-member formation moves and rotates as one selection about Selection Center')

        controller = app.viewer.controller
        x, y, w, h = app.viewport_rect
        point = np.array([x + w * .5, y + h * .5])
        before_yaw, before_target, before_distance = controller.yaw, controller.target.copy(), controller.distance
        yield [move(point), mouse(pygame.MOUSEBUTTONDOWN, button=2)]
        yield [move(point + [15, 6], middle=True)]
        yield [mouse(pygame.MOUSEBUTTONUP, button=2)]
        assert controller.yaw != before_yaw
        yield [move(point), mouse(pygame.MOUSEBUTTONDOWN, button=2, shift=True)]
        yield [move(point + [10, -5], middle=True, shift=True)]
        yield [mouse(pygame.MOUSEBUTTONUP, button=2, shift=True)]
        assert not np.allclose(controller.target, before_target)
        yield [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)]
        assert controller.distance != before_distance
        yield from key(pygame.K_s, control=True)
        final_positions = {e.entity_id: e.pos.copy() for e in app.scene.root_entities}
        yield from key(pygame.K_o, control=True)
        assert app.scene.find_group_by_id(group_id).member_ids == ids
        for entity_id, position in final_positions.items():
            np.testing.assert_array_equal(app.scene.find_by_id(entity_id).pos, position)
        check('40 soldiers remain navigable with Orbit/Pan/Zoom; final Scene saves/loads formation IDs and transforms')
        state['formation_ids'], state['formation_group_id'] = ids, group_id
        state['done'] = True
        state['screenshot'] = 'placement-v2-editor.png'
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
        if state['screenshot']:
            w, h = pygame.display.get_window_size()
            pixels = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            surface = pygame.image.fromstring(pixels, (w, h), 'RGB', True)
            pygame.image.save(surface, str(output / state['screenshot']))
            state['screenshot'] = None
        real_flip()
        state['frame'] += 1

    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.object(editor, 'Editor', TestEditor))
        stack.enter_context(patch.object(pygame.event, 'get', events))
        stack.enter_context(patch.object(pygame.display, 'flip', inspect))
        for kind in originals:
            stack.enter_context(patch.object(imgui, kind, tracked_widget(kind)))
        editor_app.main(['--empty', '--frames', '420'])
    assert state['done'], 'V2 acceptance did not reach final save/load'
    result = dict(frames=state['frame'], checks=state['checks'], asset_drops=state['drops'],
                  formation_ids=state['formation_ids'], formation_group_id=state['formation_group_id'],
                  roman_fixture_scale=.06, formation_rows=5, formation_columns=8,
                  spacing_x=1.2, spacing_y=1.4)
    (output / 'placement-v2-result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print('PASS: Placement V2 visible Editor workflow; output:', output, flush=True)


if __name__ == '__main__':
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix='mini3d-placement-v2-'))
    output.mkdir(parents=True, exist_ok=True)
    run_smoke(output)
