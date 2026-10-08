"""Real ray/triangle surface gestures, without a rendering context."""
import unittest

import numpy as np

from mini3d.camera import Camera
from mini3d.commands import PlacementCommands
from mini3d.placement import create_ground, geometry_bounds
from mini3d.scene import Entity, Mesh, Scene
from mini3d.surface_drag import SurfaceDrag


RECT = (0, 0, 800, 600)


class SurfaceDragTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.scene.ground = create_ground(20)
        self.entity = self.scene.add(Entity(Mesh(
            [[-1, -1, -2], [1, -1, -2], [0, 1, 1]], [[0, 1, 2]])))
        self.entity.pos[:] = [2, 3, 8]
        self.entity.rot[:] = [.2, -.4, .8]
        self.entity.placement_type = 'character'
        self.scene.update()
        self.camera = Camera(position=(0, 0, 10), near=.1, far=100)
        self.commands = PlacementCommands(self.scene, None)

    def test_one_hundred_updates_one_history_and_redo(self):
        before_pos, before_rot = self.entity.pos.copy(), self.entity.rot.copy()
        mesh, vertices = self.entity.model, self.entity.model.vertices.copy()
        drag = SurfaceDrag(self.commands, self.entity.entity_id)
        for x in np.linspace(320, 480, 100):
            self.assertTrue(drag.update(self.camera, (x, 300), RECT))
        after = self.entity.pos.copy()
        self.assertEqual(self.commands.undo_count, 0)
        self.assertTrue(drag.active)
        self.assertAlmostEqual(geometry_bounds(self.entity)[0][2], 0)
        np.testing.assert_allclose(self.entity.rot, [0, 0, .8])
        drag.finish()
        self.assertFalse(drag.active)
        self.assertEqual(self.commands.undo_count, 1)
        self.commands.undo()
        np.testing.assert_array_equal(self.entity.pos, before_pos)
        np.testing.assert_array_equal(self.entity.rot, before_rot)
        self.commands.redo()
        np.testing.assert_array_equal(self.entity.pos, after)
        self.assertIs(self.entity.model, mesh)
        np.testing.assert_array_equal(mesh.vertices, vertices)

    def test_escape_restores_entire_pose_without_history(self):
        before = [value.copy() for value in (self.entity.pos, self.entity.rot, self.entity.scale)]
        drag = SurfaceDrag(self.commands, self.entity)
        drag.update(self.camera, (400, 300), RECT)
        drag.finish(cancel=True)
        for actual, expected in zip((self.entity.pos, self.entity.rot, self.entity.scale), before):
            np.testing.assert_array_equal(actual, expected)
        self.assertEqual(self.commands.undo_count, 0)
        self.assertFalse(self.commands.active_transaction)

    def test_no_hit_preserves_last_valid_position(self):
        drag = SurfaceDrag(self.commands, self.entity)
        drag.update(self.camera, (400, 300), RECT)
        valid = self.entity.pos.copy()
        self.camera.position = (100, 100, 10)
        self.assertFalse(drag.update(self.camera, (400, 300), RECT))
        np.testing.assert_array_equal(self.entity.pos, valid)
        drag.finish()

    def test_locked_surface_and_pivot_anchor(self):
        table = Entity(Mesh([[-3, -3, 0], [3, -3, 0], [0, 3, 0]], [[0, 1, 2]]))
        table.pos[2] = 3
        table.locked = True
        self.scene.add(table)
        self.entity.placement_anchor = 'pivot'
        drag = SurfaceDrag(self.commands, self.entity)
        self.assertTrue(drag.update(self.camera, (400, 300), RECT))
        np.testing.assert_allclose(self.entity.pos, [0, 0, 3])
        self.assertTrue(table.locked)
        drag.finish()

    def test_self_is_excluded_from_ray(self):
        self.entity.pos[:] = [0, 0, 4]
        self.entity.rot[:] = 0
        self.entity.placement_anchor = 'pivot'
        self.scene.update()
        drag = SurfaceDrag(self.commands, self.entity)
        drag.update(self.camera, (400, 300), RECT)
        np.testing.assert_allclose(self.entity.pos, [0, 0, 0])
        drag.finish()

    def test_locked_instance_cannot_begin(self):
        self.entity.locked = True
        with self.assertRaises(ValueError):
            SurfaceDrag(self.commands, self.entity)
        self.assertFalse(self.commands.active_transaction)

    def test_later_lock_is_not_rolled_back_by_escape_or_update(self):
        for escape in (True, False):
            self.entity.locked = False
            drag = SurfaceDrag(self.commands, self.entity)
            drag.update(self.camera, (400, 300), RECT)
            self.commands.lock(self.entity)
            if escape:
                drag.finish(cancel=True)
            else:
                self.assertFalse(drag.update(self.camera, (420, 300), RECT))
            self.assertTrue(self.entity.locked)
            self.assertFalse(drag.active)
            self.assertFalse(self.commands.active_transaction)

    def test_stale_gesture_cannot_cancel_a_later_transaction(self):
        drag = SurfaceDrag(self.commands, self.entity)
        self.commands.commit_transaction()
        self.commands.begin_transaction('Later operation')
        self.commands.set_transform(self.entity, position=[9, 8, 7])
        drag.finish(cancel=True)
        self.assertTrue(self.commands.active_transaction)
        np.testing.assert_array_equal(self.entity.pos, [9, 8, 7])
        self.commands.commit_transaction()


if __name__ == '__main__':
    unittest.main()
