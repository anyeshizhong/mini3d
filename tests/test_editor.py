"""Headless editor behavior: instance lifecycle, persistence and viewport tools."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
import pygame

from mini3d.editor import Editor
from mini3d.scene import rotation_xyz


def model_nodes(root):
    result = [root] if root.model is not None else []
    for child in root.children:
        result.extend(model_nodes(child))
    return result


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.app = Editor(800, 600)
        self.app.viewport_rect = (100, 50, 800, 600)
        self.center = (500, 350)
        self.ui = SimpleNamespace(modal_open=False, viewport_hovered=True,
                                  asset_dragging=False, keyboard_captured=False, mouse_captured=False)
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'scene.json'
        # A generated unit cube keeps editor tests independent of optional downloads.
        from stl import mesh, Mode
        from mini3d.editor import PROJECT
        source = mesh.Mesh.from_file(str(PROJECT / 'model/06_stl_cube/cube.STL'), mode=Mode.BINARY)
        low, high = source.vectors.min(axis=(0, 1)), source.vectors.max(axis=(0, 1))
        source.vectors[:] = (source.vectors - (low + high) / 2) / (high - low)
        fixture = Path(self.temporary.name) / 'unit_cube.stl'
        source.save(str(fixture), mode=Mode.BINARY)
        self.box_index = len(self.app.assets)
        self.app.assets.append(dict(name='Unit cube', path=str(fixture)))

    def tearDown(self):
        self.temporary.cleanup()

    def add_box(self, position=(0, 0, 0)):
        return self.app.add_asset(self.box_index, position)

    def assert_camera_equal(self, actual, expected):
        self.assertEqual(set(actual), set(expected))
        for key in expected:
            np.testing.assert_allclose(actual[key], expected[key], err_msg=key)

    def test_add_and_duplicate_share_mesh_but_transform_independently(self):
        original = self.add_box()
        original.pos[:] = [1, 2, 3]
        original.rot[:] = [.2, -.3, .4]
        original.scale[:] = [2, .5, 3]
        duplicate = self.app.duplicate_selected()
        self.assertEqual(len(self.app.scene.root_entities), 2)
        self.assertIs(self.app.selection, duplicate)
        self.assertIs(self.app.viewer.selected_entity, duplicate)
        self.assertNotEqual(original.name, duplicate.name)
        for first, second in zip(model_nodes(original), model_nodes(duplicate)):
            self.assertIsNot(first, second)
            self.assertIs(first.model, second.model)
        np.testing.assert_allclose(duplicate.pos, [1, 2, 3])
        np.testing.assert_allclose(duplicate.rot, [.2, -.3, .4])
        np.testing.assert_allclose(duplicate.scale, [2, .5, 3])
        duplicate.pos[0] = 90
        duplicate.rot[1] = 1
        duplicate.scale[2] = 9
        np.testing.assert_allclose(original.pos, [1, 2, 3])
        np.testing.assert_allclose(original.rot, [.2, -.3, .4])
        np.testing.assert_allclose(original.scale, [2, .5, 3])

    def test_delete_clears_selection_and_preserves_other_instance(self):
        original = self.add_box()
        self.app.duplicate_selected()
        self.app.delete_selected()
        self.assertEqual(self.app.scene.root_entities, [original])
        self.assertIsNone(self.app.selection)
        self.assertIsNone(self.app.viewer.selected_entity)
        self.app.delete_selected()
        self.assertEqual(self.app.scene.root_entities, [original])

    def test_save_load_preserves_instances_and_camera(self):
        original = self.add_box()
        original.name = 'Box custom name'
        original.pos[:] = [1.25, -2.5, 3.75]
        original.rot[:] = [.15, -.25, .35]
        original.scale[:] = [2, .5, 3]
        original.visible = False
        second = self.app.duplicate_selected()
        second.name = 'Visible copy'
        second.visible = True
        second.pos[:] = [-4, 5, 6]
        controller = self.app.viewer.controller
        controller.target[:] = [3, -4, 5]
        controller.distance, controller.yaw, controller.pitch = 18, .75, -.35
        controller.camera.fov_y = 48
        controller.update()
        expected_camera = controller.snapshot()
        self.app.render_mode, self.app.show_grid = 'Wireframe', False
        self.app.save_scene(self.path)
        loaded = Editor(800, 600)
        loaded.load_scene(self.path)
        first, second = loaded.scene.root_entities
        self.assertEqual(first.name, 'Box custom name')
        self.assertEqual(second.name, 'Visible copy')
        self.assertFalse(first.visible)
        self.assertTrue(second.visible)
        np.testing.assert_allclose(first.pos, [1.25, -2.5, 3.75])
        np.testing.assert_allclose(first.rot, [.15, -.25, .35])
        np.testing.assert_allclose(first.scale, [2, .5, 3])
        np.testing.assert_allclose(second.pos, [-4, 5, 6])
        self.assertIs(model_nodes(first)[0].model, model_nodes(second)[0].model)
        self.assertEqual(loaded.render_mode, 'Wireframe')
        self.assertFalse(loaded.show_grid)
        self.assert_camera_equal(loaded.viewer.controller.snapshot(), expected_camera)
        loaded.viewer.controller.orbit(50, 20)
        loaded.reset_camera()
        self.assert_camera_equal(loaded.viewer.controller.snapshot(), expected_camera)

    def test_invalid_scene_leaves_existing_scene_and_camera_intact(self):
        original = self.add_box()
        self.app.save_scene(self.path)
        valid = json.loads(self.path.read_text(encoding='utf8'))
        bad_documents = []
        for field, value in [('position', [1, 2]), ('scale', [1, 0, 1]),
                             ('rotation', [0, float('nan'), 0])]:
            data = json.loads(json.dumps(valid))
            data['objects'][0][field] = value
            bad_documents.append(data)
        bad_camera = json.loads(json.dumps(valid))
        bad_camera['camera']['target'] = [1, 2]
        bad_documents.append(bad_camera)
        missing_asset = json.loads(json.dumps(valid))
        missing_asset['objects'][0]['asset'] = str(Path(self.temporary.name) / 'missing.glb')
        bad_documents.append(missing_asset)
        expected_camera = self.app.viewer.controller.snapshot()
        for data in bad_documents:
            with self.subTest(document=data):
                self.path.write_text(json.dumps(data), encoding='utf8')
                with self.assertRaises((ValueError, OSError)):
                    self.app.load_scene(self.path)
                self.assertEqual(self.app.scene.root_entities, [original])
                self.assertIs(self.app.selection, original)
                self.assert_camera_equal(self.app.viewer.controller.snapshot(), expected_camera)

    def test_invalid_camera_lens_cannot_replace_scene(self):
        original = self.add_box()
        self.app.save_scene(self.path)
        data = json.loads(self.path.read_text(encoding='utf8'))
        data['camera']['fov_y'] = 0
        self.path.write_text(json.dumps(data), encoding='utf8')
        expected_camera = self.app.viewer.controller.snapshot()
        with self.assertRaises(ValueError):
            self.app.load_scene(self.path)
        self.assertEqual(self.app.scene.root_entities, [original])
        self.assertIs(self.app.selection, original)
        self.assert_camera_equal(self.app.viewer.controller.snapshot(), expected_camera)

    def test_captured_keyboard_cannot_change_tools_or_delete(self):
        original = self.add_box()
        self.app.tool = 'select'
        self.ui.keyboard_captured = True
        for key in (pygame.K_g, pygame.K_r, pygame.K_DELETE):
            self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0), self.ui)
            self.assertEqual(self.app.tool, 'select')
            self.assertEqual(self.app.scene.root_entities, [original])
        self.ui.keyboard_captured = False
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, mod=0), self.ui)
        self.assertEqual(self.app.tool, 'move')
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0), self.ui)
        self.assertEqual(self.app.tool, 'rotate')

    def test_click_outside_viewport_preserves_selection(self):
        original = self.add_box()
        self.ui.viewport_hovered = False
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20), button=1), self.ui)
        self.assertIs(self.app.selection, original)

    def test_queued_outside_click_ignored_even_if_pointer_now_hovers_viewport(self):
        original = self.add_box()
        self.app.tool = 'select'
        self.ui.viewport_hovered = True
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20), button=1), self.ui)
        self.assertIs(self.app.selection, original)

    def test_drop_on_ground_preserves_camera_distance(self):
        camera = self.app.viewer.camera
        camera.position, camera.rotation = [0, 0, 10], np.eye(3)
        before = self.app.viewer.controller.distance
        dropped = self.app.drop_asset(self.box_index, self.center)
        np.testing.assert_allclose(dropped.pos, [0, 0, .5])  # Bounds Bottom, not pivot.
        self.assertEqual(self.app.viewer.controller.distance, before)

    def test_drop_on_existing_surface_uses_surface_hit(self):
        self.add_box()
        camera = self.app.viewer.camera
        camera.position, camera.rotation = [0, 0, 10], np.eye(3)
        dropped = self.app.drop_asset(self.box_index, self.center)
        np.testing.assert_allclose(dropped.pos, [0, 0, 1], atol=1e-6)

    def test_drop_without_forward_ground_hit_uses_target(self):
        self.app.viewer.controller.target[:] = [3, 4, 5]
        camera = self.app.viewer.camera
        camera.position = [0, 0, 10]
        camera.look_at([0, 0, 20])
        dropped = self.app.drop_asset(self.box_index, self.center)
        np.testing.assert_allclose(dropped.pos, [3, 4, 5.5])

    def prepare_gizmo(self, tool):
        root = self.add_box()
        root.rot[:] = [.1, -.2, .3]
        root.scale[:] = [2, .5, 3]
        self.app.tool = tool
        camera = self.app.viewer.camera
        camera.position = [6, -8, 7]
        camera.look_at([0, 0, 0])
        self.app.gizmo.geometry(self.app.viewport_rect)
        before = (root.pos.copy(), root.rot.copy(), root.scale.copy())
        return root, before

    def assert_cancel_restored(self, root, before):
        self.app.gizmo.finish(cancel=True)
        for actual, expected in zip((root.pos, root.rot, root.scale), before):
            np.testing.assert_allclose(actual, expected)
        self.assertIsNone(self.app.gizmo.drag)

    def test_move_axis_drag_changes_position_and_cancel_restores(self):
        root, before = self.prepare_gizmo('move')
        _, points = self.app.gizmo.handles[0]
        center, end = map(np.asarray, points)
        start = center + .8 * (end - center)
        self.assertTrue(self.app.gizmo.begin(start, self.app.viewport_rect))
        self.app.gizmo.update(start + .4 * (end - center))
        self.assertGreater(root.pos[0], before[0][0])
        np.testing.assert_allclose(root.pos[1:], before[0][1:])
        self.assert_cancel_restored(root, before)

    def test_scale_axis_drag_changes_one_component_and_cancel_restores(self):
        self.app.transform_space = 'local'
        root, before = self.prepare_gizmo('scale')
        _, points = self.app.gizmo.handles[1]
        center, end = map(np.asarray, points)
        start = center + .8 * (end - center)
        self.assertTrue(self.app.gizmo.begin(start, self.app.viewport_rect))
        self.app.gizmo.update(start + .4 * (end - center))
        self.assertGreater(root.scale[1], before[2][1])
        np.testing.assert_allclose(root.scale[[0, 2]], before[2][[0, 2]])
        self.assert_cancel_restored(root, before)

    def test_rotation_ring_drag_changes_orientation_and_cancel_restores(self):
        root, before = self.prepare_gizmo('rotate')
        _, points = self.app.gizmo.handles[2]
        self.assertTrue(self.app.gizmo.begin(points[8], self.app.viewport_rect))
        self.app.gizmo.update(points[16])
        self.assertFalse(np.allclose(rotation_xyz(root.rot), rotation_xyz(before[1])))
        self.assert_cancel_restored(root, before)

    def test_editor_viewer_cannot_consume_legacy_mouse_or_keyboard_bindings(self):
        before = self.app.viewer.controller.snapshot()
        for event in (
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=self.center),
            pygame.event.Event(pygame.MOUSEMOTION, rel=(50, 30), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEWHEEL, y=2),
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, mod=0),
        ):
            self.assertFalse(self.app.viewer.handle_event(event))
        self.assert_camera_equal(self.app.viewer.controller.snapshot(), before)

    def test_left_selection_drag_does_not_orbit(self):
        self.add_box()
        self.app.tool = 'select'
        before = self.app.viewer.controller.snapshot()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=self.center), self.ui)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(520, 370), rel=(20, 20), buttons=(1, 0, 0)), self.ui)
        self.assert_camera_equal(self.app.viewer.controller.snapshot(), before)

    def test_ui_capture_blocks_click_wheel_and_an_existing_orbit(self):
        original = self.add_box()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2, pos=self.center), self.ui)
        before = self.app.viewer.controller.snapshot()
        self.ui.mouse_captured = True
        for event in (
            pygame.event.Event(pygame.MOUSEMOTION, pos=self.center, rel=(30, 20), buttons=(0, 1, 0)),
            pygame.event.Event(pygame.MOUSEWHEEL, y=2),
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=self.center),
        ):
            self.app.handle_event(event, self.ui)
        self.assertIs(self.app.selection, original)
        self.assertFalse(self.app._orbiting)
        self.assert_camera_equal(self.app.viewer.controller.snapshot(), before)

    def test_gizmo_and_camera_cannot_own_the_same_gesture(self):
        root, before = self.prepare_gizmo('move')
        _, points = self.app.gizmo.handles[0]
        center, end = map(np.asarray, points)
        start = center + .8 * (end - center)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start), self.ui)
        self.assertIsNotNone(self.app.gizmo.drag)
        camera = self.app.viewer.controller.snapshot()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2, pos=start), self.ui)
        self.assertFalse(self.app._orbiting)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=start + (20, 0), rel=(20, 0), buttons=(1, 1, 0)), self.ui)
        self.assertFalse(np.allclose(root.pos, before[0]))
        self.assert_camera_equal(self.app.viewer.controller.snapshot(), camera)
        position = root.pos.copy()
        self.ui.mouse_captured = True
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=start + (40, 0), rel=(20, 0), buttons=(1, 0, 0)), self.ui)
        np.testing.assert_allclose(root.pos, position)
        self.assertIsNotNone(self.app.gizmo.drag)

    def begin_moved_gizmo(self):
        root, before = self.prepare_gizmo('move')
        self.app.commands.clear_history()
        _, points = self.app.gizmo.handles[0]
        center, end = map(np.asarray, points)
        start = center + .8 * (end - center)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start), self.ui)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=start + (20, 0),
                             rel=(20, 0), buttons=(1, 0, 0)), self.ui)
        self.assertFalse(np.allclose(root.pos, before[0]))
        self.ui.mouse_captured = True
        self.ui.viewport_hovered = False
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(20, 20),
                             rel=(-100, 0), buttons=(1, 0, 0)), self.ui)
        self.assertIsNotNone(self.app.gizmo.drag)
        self.assertEqual(self.app.commands.undo_count, 0)
        return root, before

    def test_gizmo_cross_panel_escape_restores_pose_and_history(self):
        root, before = self.begin_moved_gizmo()
        self.ui.keyboard_captured = True
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0), self.ui)
        for actual, expected in zip((root.pos, root.rot, root.scale), before):
            np.testing.assert_array_equal(actual, expected)
        self.assertFalse(self.app.commands.active_transaction)
        self.assertEqual(self.app.commands.undo_count, 0)

    def test_gizmo_cross_panel_release_commits_once_and_undo_redo_restore(self):
        root, before = self.begin_moved_gizmo()
        moved = root.pos.copy()
        for _ in range(2):
            self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(20, 20)), self.ui)
        self.assertIsNone(self.app.gizmo.drag)
        self.assertFalse(self.app.commands.active_transaction)
        self.assertEqual(self.app.commands.undo_count, 1)
        self.app.undo()
        np.testing.assert_array_equal(root.pos, before[0])
        self.app.redo()
        np.testing.assert_array_equal(root.pos, moved)

    def test_gizmo_missing_release_over_panel_ends_gesture(self):
        self.begin_moved_gizmo()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(20, 20),
                             rel=(0, 0), buttons=(0, 0, 0)), self.ui)
        self.assertIsNone(self.app.gizmo.drag)
        self.assertFalse(self.app.commands.active_transaction)
        self.assertEqual(self.app.commands.undo_count, 1)

    def test_gizmo_modal_and_focus_loss_keep_existing_commit_policy(self):
        for mode in ('modal', 'focus'):
            with self.subTest(mode=mode):
                self.ui.modal_open = False
                self.ui.mouse_captured = False
                self.ui.viewport_hovered = True
                self.begin_moved_gizmo()
                if mode == 'modal':
                    self.ui.modal_open = True
                    event = pygame.event.Event(pygame.MOUSEWHEEL, y=1)
                else:
                    event = pygame.event.Event(pygame.WINDOWFOCUSLOST)
                self.app.handle_event(event, self.ui)
                self.assertIsNone(self.app.gizmo.drag)
                self.assertFalse(self.app.commands.active_transaction)
                self.assertEqual(self.app.commands.undo_count, 1)

    def test_middle_shift_pan_and_wheel_have_separate_effects(self):
        before = self.app.viewer.controller.snapshot()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2, pos=self.center), self.ui)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=self.center, rel=(25, 12), buttons=(0, 1, 0), mod=pygame.KMOD_SHIFT), self.ui)
        after = self.app.viewer.controller.snapshot()
        self.assertFalse(np.allclose(before['target'], after['target']))
        self.assertEqual(before['yaw'], after['yaw'])
        self.assertEqual(before['pitch'], after['pitch'])
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=2), self.ui)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1), self.ui)
        self.assertLess(self.app.viewer.controller.distance, after['distance'])

    def test_lost_focus_or_missing_button_release_clears_orbit(self):
        for event in (pygame.event.Event(pygame.WINDOWFOCUSLOST),
                      pygame.event.Event(pygame.MOUSEMOTION, pos=self.center, rel=(20, 20), buttons=(0, 0, 0))):
            self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2, pos=self.center), self.ui)
            self.app.handle_event(event, self.ui)
            self.assertFalse(self.app._orbiting)


if __name__ == '__main__':
    unittest.main()
