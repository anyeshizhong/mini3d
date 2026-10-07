"""Gizmo command transactions and world/local behavior, without a GL window."""
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.commands import PlacementCommands
from mini3d.editor_tools import TransformGizmo
from mini3d.scene import Entity, Scene, rotation_xyz
from mini3d.viewer import Viewer


class PlacementGizmoTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.entity = self.scene.add(Entity(name="Rotated instance"))
        self.entity.rot = np.array([.2, -.3, .7])
        self.commands = PlacementCommands(self.scene, None)
        self.viewer = Viewer(self.scene, 800, 600, input_enabled=False)
        self.viewer.camera.position = [6, -8, 7]
        self.viewer.camera.look_at([0, 0, 0])
        self.app = SimpleNamespace(selection=self.entity, viewer=self.viewer,
                                   tool="move", transform_space="world", commands=self.commands)
        self.gizmo = TransformGizmo(self.app)
        self.rect = (0, 0, 800, 600)

    def start_axis(self, axis=0):
        self.gizmo.geometry(self.rect)
        center, end = map(np.asarray, self.gizmo.handles[axis][1])
        start = center + .85 * (end - center)
        self.assertTrue(self.gizmo.begin(start, self.rect))
        self.assertEqual(self.gizmo.drag['axis'], axis)
        return start, end - center

    def test_local_axes_follow_rotation_and_move_along_local_x(self):
        self.gizmo.geometry(self.rect)
        world_x = np.asarray(self.gizmo.handles[0][1][1])
        self.app.transform_space = "local"
        self.gizmo.geometry(self.rect)
        self.assertFalse(np.allclose(world_x, self.gizmo.handles[0][1][1]))
        start, direction = self.start_axis()
        self.gizmo.update(start + .4 * direction)
        expected_direction = rotation_xyz(self.entity.rot)[:, 0]
        np.testing.assert_allclose(self.entity.pos / np.linalg.norm(self.entity.pos), expected_direction)
        self.gizmo.finish()

    def test_many_drag_updates_record_one_undo_and_redo(self):
        start, direction = self.start_axis()
        for amount in np.linspace(.02, .5, 25):
            self.gizmo.update(start + amount * direction)
        final = self.entity.pos.copy()
        self.assertEqual(self.commands.undo_count, 0)
        self.gizmo.finish()
        self.assertEqual(self.commands.undo_count, 1)
        self.commands.undo()
        np.testing.assert_allclose(self.entity.pos, [0, 0, 0])
        self.commands.redo()
        np.testing.assert_allclose(self.entity.pos, final)

    def test_cancel_restores_transform_without_history(self):
        start, direction = self.start_axis()
        self.gizmo.update(start + direction)
        self.gizmo.finish(cancel=True)
        np.testing.assert_allclose(self.entity.pos, [0, 0, 0])
        self.assertEqual(self.commands.undo_count, 0)
        self.assertFalse(self.commands.active_transaction)

    def test_locked_entity_has_no_handles_and_cannot_start(self):
        self.commands.lock(self.entity)
        self.assertIsNone(self.gizmo.geometry(self.rect))
        self.assertFalse(self.gizmo.begin((400, 300), self.rect))
        self.assertEqual(self.gizmo.handles, [])
        self.assertFalse(self.commands.active_transaction)

    def test_local_scale_changes_only_chosen_component(self):
        self.app.tool, self.app.transform_space = "scale", "local"
        start, direction = self.start_axis(1)
        self.gizmo.update(start + .4 * direction)
        self.assertGreater(self.entity.scale[1], 1)
        np.testing.assert_allclose(self.entity.scale[[0, 2]], [1, 1])
        self.gizmo.finish()

    def test_world_scale_projects_without_introducing_shear(self):
        self.entity.rot = np.array([0, 0, math.pi / 4])
        self.app.tool = "scale"
        start, direction = self.start_axis(0)
        self.gizmo.update(start + .4 * direction)
        self.assertGreater(self.entity.scale[0], 1)
        self.assertAlmostEqual(self.entity.scale[0], self.entity.scale[1])
        self.assertEqual(self.entity.scale[2], 1)
        self.gizmo.finish()

    def test_rotation_uses_local_or_world_composition(self):
        self.app.tool = "rotate"
        start_rotation = self.entity.rot.copy()
        results = []
        for space in ("world", "local"):
            self.app.transform_space = space
            self.gizmo.geometry(self.rect)
            point = self.gizmo.handles[0][1][8]
            # Edge-on rings use the same pixel-delta fallback in both modes;
            # verify matrix composition independently of ray-plane geometry.
            with patch('mini3d.editor_tools.plane_point', return_value=None):
                self.assertTrue(self.gizmo.begin(point, self.rect))
                self.assertEqual(self.gizmo.drag['axis'], 0)
                self.gizmo.update(np.asarray(point) + [30, 0])
            results.append(rotation_xyz(self.entity.rot))
            delta = rotation_xyz([.3, 0, 0])
            expected = (delta @ rotation_xyz(start_rotation) if space == "world" else
                        rotation_xyz(start_rotation) @ delta)
            np.testing.assert_allclose(results[-1], expected, atol=1e-12)
            self.gizmo.finish(cancel=True)
        self.assertFalse(np.allclose(*results))


if __name__ == '__main__':
    unittest.main()
