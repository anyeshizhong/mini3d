"""Multi Gizmo drives shared command deltas about the selection centre."""
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.commands import PlacementCommands
from mini3d.editor_tools import TransformGizmo
from mini3d.scene import Entity, Scene, rotation_xyz
from mini3d.viewer import Viewer


class MultiGizmoTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.first = self.scene.add(Entity(name='Same name'))
        self.second = self.scene.add(Entity(name='Same name'))
        self.first.pos[:] = [-2, 0, 0]
        self.second.pos[:] = [2, 0, 0]
        self.first.rot[:] = [.2, -.3, .7]
        self.second.rot[:] = [-.1, .4, -.2]
        self.commands = PlacementCommands(self.scene, None)
        self.viewer = Viewer(self.scene, 800, 600, input_enabled=False)
        self.viewer.camera.position = [6, -8, 7]
        self.viewer.camera.look_at([0, 0, 0])
        self.app = SimpleNamespace(selection=self.first, selected_entities=[self.first, self.second],
                                   editable_selection=[self.first, self.second], viewer=self.viewer,
                                   tool='move', transform_space='local', commands=self.commands)
        self.gizmo = TransformGizmo(self.app)
        self.rect = (0, 0, 800, 600)

    def start_axis(self, axis=0):
        self.gizmo.geometry(self.rect)
        center, end = map(np.asarray, self.gizmo.handles[axis][1])
        start = center + .85 * (end - center)
        self.assertTrue(self.gizmo.begin(start, self.rect))
        self.assertEqual(self.gizmo.drag['axis'], axis)
        return start, end - center

    def test_multi_forces_world_and_mean_pivot(self):
        origin, _, _ = self.gizmo.geometry(self.rect)
        np.testing.assert_array_equal(origin, [0, 0, 0])
        local_selected = np.asarray(self.gizmo.handles[0][1])
        self.app.transform_space = 'world'
        self.gizmo.geometry(self.rect)
        np.testing.assert_array_equal(local_selected, self.gizmo.handles[0][1])
        start, direction = self.start_axis()
        self.gizmo.update(start + .4 * direction)
        np.testing.assert_allclose(self.second.pos - self.first.pos, [4, 0, 0])
        np.testing.assert_allclose(self.first.pos[1:], [0, 0])
        self.assertGreater(self.first.pos[0], -2)
        self.gizmo.finish()

    def test_hidden_group_member_still_moves_and_contributes_to_center(self):
        self.second.visible = False
        origin, _, _ = self.gizmo.geometry(self.rect)
        np.testing.assert_array_equal(origin, [0, 0, 0])
        start, direction = self.start_axis()
        self.gizmo.update(start + .4 * direction)
        self.gizmo.finish()
        self.assertGreater(self.second.pos[0], 2)
        np.testing.assert_allclose(self.second.pos - self.first.pos, [4, 0, 0])

    def test_multi_drag_records_one_history_and_cancels_atomically(self):
        before = np.array([self.first.pos.copy(), self.second.pos.copy()])
        start, direction = self.start_axis()
        for amount in np.linspace(.01, .5, 50):
            self.gizmo.update(start + amount * direction)
        after = np.array([self.first.pos.copy(), self.second.pos.copy()])
        self.assertEqual(self.commands.undo_count, 0)
        self.gizmo.finish()
        self.assertEqual(self.commands.undo_count, 1)
        self.commands.undo()
        np.testing.assert_array_equal([self.first.pos, self.second.pos], before)
        self.commands.redo()
        np.testing.assert_array_equal([self.first.pos, self.second.pos], after)
        start, direction = self.start_axis()
        self.gizmo.update(start + direction)
        self.gizmo.finish(cancel=True)
        np.testing.assert_array_equal([self.first.pos, self.second.pos], after)
        self.assertEqual(self.commands.undo_count, 1)

    def test_multi_rotate_updates_positions_and_orientations(self):
        self.app.tool = 'rotate'
        initial = [(e.pos.copy(), e.rot.copy()) for e in (self.first, self.second)]
        self.gizmo.geometry(self.rect)
        point = self.gizmo.handles[2][1][8]
        with patch('mini3d.editor_tools.plane_point', return_value=None):
            self.assertTrue(self.gizmo.begin(point, self.rect))
            self.assertEqual(self.gizmo.drag['axis'], 2)
            self.gizmo.update(np.asarray(point) + [30, 0])
        delta = rotation_xyz([0, 0, .3])
        for entity, (pos, rot) in zip((self.first, self.second), initial):
            np.testing.assert_allclose(entity.pos, delta @ pos, atol=1e-12)
            np.testing.assert_allclose(rotation_xyz(entity.rot), delta @ rotation_xyz(rot), atol=1e-12)
        self.gizmo.finish()
        self.assertEqual(self.commands.undo_count, 1)

    def test_multi_uniform_scale_updates_spacing_and_instance_scales(self):
        self.app.tool = 'scale'
        _, center, _ = self.gizmo.geometry(self.rect)
        self.assertTrue(self.gizmo.begin(center, self.rect))
        self.gizmo.update(center + [30, 0])
        factor = math.exp(.3)
        np.testing.assert_allclose(self.first.pos, [-2 * factor, 0, 0])
        np.testing.assert_allclose(self.second.pos, [2 * factor, 0, 0])
        np.testing.assert_allclose(self.first.scale, np.full(3, factor))
        np.testing.assert_allclose(self.second.scale, np.full(3, factor))
        self.gizmo.finish()

    def test_axis_scale_uses_mean_pivot(self):
        self.app.tool = 'scale'
        start, direction = self.start_axis()
        self.gizmo.update(start + .4 * direction)
        factor = math.exp(.4)
        np.testing.assert_allclose(self.first.pos, [-2 * factor, 0, 0])
        np.testing.assert_allclose(self.second.pos, [2 * factor, 0, 0])
        self.gizmo.finish()

    def test_locked_primary_does_not_hide_other_editable_handles(self):
        self.first.locked = True
        origin, _, _ = self.gizmo.geometry(self.rect)
        np.testing.assert_array_equal(origin, self.second.pos)
        start, direction = self.start_axis()
        self.gizmo.update(start + .5 * direction)
        np.testing.assert_array_equal(self.first.pos, [-2, 0, 0])
        self.assertGreater(self.second.pos[0], 2)
        self.gizmo.finish()

    def test_member_locked_mid_drag_is_skipped_without_cancelling_other_members(self):
        start, direction = self.start_axis()
        self.commands.lock(self.first)
        self.gizmo.update(start + .4 * direction)
        np.testing.assert_array_equal(self.first.pos, [-2, 0, 0])
        self.assertGreater(self.second.pos[0], 2)
        self.gizmo.finish()
        self.assertTrue(self.first.locked)
        self.assertEqual(self.commands.undo_count, 1)

    def test_surface_tool_has_no_gizmo(self):
        self.app.tool = 'surface'
        self.assertIsNone(self.gizmo.geometry(self.rect))
        self.assertEqual(self.gizmo.handles, [])
        self.assertFalse(self.gizmo.begin((400, 300), self.rect))


if __name__ == '__main__':
    unittest.main()
