"""Exact selection stays correct across viewport offsets and scene transforms."""
import unittest

import numpy as np

from mini3d.camera import Camera
from mini3d.picking import ground_hit, pick_entity, project_point, screen_ray
from mini3d.scene import Entity, Mesh, Scene


RECT = (120, 70, 800, 600)
CENTER = (520, 370)


def triangle():
    return Mesh([[-2, -2, 0], [2, -2, 0], [0, 2, 0]], [[0, 1, 2]])


class PickingTests(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(position=(0, 0, 10), near=.1, far=100)
        self.scene = Scene()

    def add_triangle(self, z=0):
        root = Entity(name='Instance')
        root.pos[2] = z
        root.add_child(Entity(model=triangle(), name='Primitive'))
        self.scene.add(root)
        return root

    def test_screen_ray_and_projection_with_viewport_offset(self):
        origin, direction = screen_ray(self.camera, CENTER, RECT)
        np.testing.assert_allclose(origin, [0, 0, 10])
        np.testing.assert_allclose(direction, [0, 0, -1])
        screen = project_point(self.camera, [1, 1, 0], RECT)
        self.assertGreater(screen[0], CENTER[0])
        self.assertLess(screen[1], CENTER[1])
        np.testing.assert_allclose(ground_hit(screen_ray(self.camera, screen, RECT)), [1, 1, 0], atol=1e-12)

    def test_nearest_triangle_wins_in_any_scene_order(self):
        far = self.add_triangle(0)
        near = self.add_triangle(4)
        selected, point = pick_entity(self.scene, self.camera, CENTER, RECT)
        self.assertIs(selected, near)
        np.testing.assert_allclose(point, [0, 0, 4])
        self.scene.root_entities[:] = [near, far]
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], near)

    def test_aabb_gap_does_not_hide_triangle_behind(self):
        gap = Mesh([[-2, -1, 0], [-1, -1, 0], [-1, 1, 0],
                    [1, -1, 0], [2, -1, 0], [1, 1, 0]], [[0, 1, 2], [3, 4, 5]])
        hole = Entity(model=gap)
        hole.pos[2] = 4
        self.scene.add(hole)
        solid = self.add_triangle()
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], solid)
        self.scene.root_entities.remove(solid)
        self.assertEqual(pick_entity(self.scene, self.camera, CENTER, RECT), (None, None))

    def test_nonuniform_scale_preserves_world_distance_order(self):
        near = self.add_triangle(5)
        near.scale[:] = [4, .5, 100]
        far = self.add_triangle(0)
        far.scale[:] = [1, 1, .01]
        selected, point = pick_entity(self.scene, self.camera, CENTER, RECT)
        self.assertIs(selected, near)
        np.testing.assert_allclose(point, [0, 0, 5])

    def test_nested_rotated_instance_returns_root_and_world_hit(self):
        root = self.add_triangle()
        root.pos[:] = [3, -1, 2]
        root.rot[:] = [.4, .2, .6]
        root.scale[:] = [2, .5, 3]
        child = root.children[0]
        child.extra_local[:3, 3] = [1, 2, -1]
        self.scene.update()
        centroid = np.mean(child.model.vertices[:, :3], axis=0)
        expected = (child.world_matrix @ np.append(centroid, 1))[:3]
        self.camera.position = expected + [0, 0, 10]
        selected, hit = pick_entity(self.scene, self.camera, project_point(self.camera, expected, RECT), RECT)
        self.assertIs(selected, root)
        np.testing.assert_allclose(hit, expected, atol=1e-7)

    def test_visibility_inherits_from_parent(self):
        far = self.add_triangle()
        near = self.add_triangle(4)
        near.visible = False
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], far)
        near.visible = True
        near.children[0].visible = False
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], far)
        far.visible = False
        self.assertEqual(pick_entity(self.scene, self.camera, CENTER, RECT), (None, None))

    def test_behind_eye_and_outside_clip_range_are_ignored(self):
        self.add_triangle(20)
        self.add_triangle(9.95)
        self.add_triangle(-100)
        self.assertEqual(pick_entity(self.scene, self.camera, CENTER, RECT), (None, None))
        self.assertIsNone(project_point(self.camera, [0, 0, 20], RECT))
        self.assertIsNone(project_point(self.camera, [0, 0, 10], RECT))

    def test_click_outside_viewport_cannot_select(self):
        self.add_triangle()
        self.assertEqual(pick_entity(self.scene, self.camera, (119, 370), RECT), (None, None))
        self.assertEqual(pick_entity(self.scene, self.camera, (920, 370), RECT), (None, None))

    def test_singular_instance_is_skipped(self):
        root = self.add_triangle()
        root.scale[2] = 0
        self.assertEqual(pick_entity(self.scene, self.camera, CENTER, RECT), (None, None))

    def test_mirrored_scale_remains_pickable(self):
        root = self.add_triangle()
        root.scale[0] = -2
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], root)

    def test_ground_intersection_rejects_parallel_and_backward(self):
        self.assertIsNone(ground_hit(([0, 0, 10], [1, 0, 0])))
        self.assertIsNone(ground_hit(([0, 0, 10], [0, 0, 1])))
        np.testing.assert_allclose(ground_hit(([0, 0, 10], [0, 0, -2])), [0, 0, 0])

    def test_invalid_viewport_rejected(self):
        with self.assertRaises(ValueError):
            screen_ray(self.camera, CENTER, (0, 0, 0, 600))


if __name__ == '__main__':
    unittest.main()
