"""Placement rules use actual geometry, independent of OpenGL and Editor UI."""
import unittest

import numpy as np

from mini3d.camera import Camera
from mini3d.picking import pick_entity
from mini3d.placement import (SurfaceHit, compute_placement, create_ground,
                             geometry_bounds, raycast_surface)
from mini3d.scene import Entity, Mesh, Scene, rotation_xyz
from mini3d.placement_plane import PlacementPlane


RECT = (0, 0, 800, 600)
CENTER = (400, 300)


def triangle():
    return Entity(Mesh([[-2, -2, 0], [2, -2, 0], [0, 2, 0]], [[0, 1, 2]]))


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.scene.placement_plane = PlacementPlane(size=20)
        self.camera = Camera(position=(0, 0, 10), near=.1, far=100)

    def test_plane_is_not_geometry_and_explicit_ground_is_selectable(self):
        ground = create_ground(20)
        self.assertEqual(len(ground.model.indices), 2)
        self.assertIsNone(ground.entity_id)
        self.assertFalse(ground.locked)
        self.assertIsNone(ground.asset_path)
        self.assertIsNotNone(ground.model.material)
        hit = raycast_surface(self.scene, self.camera, CENTER, RECT)
        self.assertIsNone(hit.entity)
        np.testing.assert_allclose(hit.position, [0, 0, 0])
        np.testing.assert_allclose(hit.normal, [0, 0, 1])
        self.assertEqual(pick_entity(self.scene, self.camera, CENTER, RECT), (None, None))
        self.assertEqual(self.scene.get_flat_render_list(), [])
        self.scene.add(ground)
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], ground)
        self.assertIs(raycast_surface(self.scene, self.camera, CENTER, RECT).entity, ground)

    def test_finite_ground_and_fallback(self):
        self.camera.position = [30, 0, 10]
        self.assertIsNone(raycast_surface(self.scene, self.camera, CENTER, RECT))
        hit = raycast_surface(self.scene, self.camera, CENTER, RECT, fallback=[3, 4, 5])
        self.assertIsNone(hit.entity)
        np.testing.assert_allclose(hit.position, [3, 4, 5])
        self.scene.placement_plane.enabled = False
        self.camera.position = [0, 0, 10]
        self.assertIsNone(raycast_surface(self.scene, self.camera, CENTER, RECT))

    def test_locked_surface_remains_raycastable_but_is_not_selectable(self):
        root = triangle()
        root.pos[2] = 3
        root.locked = True
        self.scene.add(root)
        self.assertEqual(pick_entity(self.scene, self.camera, CENTER, RECT), (None, None))
        hit = raycast_surface(self.scene, self.camera, CENTER, RECT)
        self.assertIs(hit.entity, root)
        np.testing.assert_allclose(hit.position, [0, 0, 3])
        root.locked = False
        self.assertIs(pick_entity(self.scene, self.camera, CENTER, RECT)[0], root)

    def test_models_have_priority_and_excluding_self_reaches_ground(self):
        root = triangle()
        root.pos[2] = -1
        root.entity_id = 'ent_123456'
        self.scene.add(root)
        self.assertIs(raycast_surface(self.scene, self.camera, CENTER, RECT).entity, root)
        for exclude in (root, root.entity_id, [root], [root.entity_id]):
            self.assertIsNone(raycast_surface(self.scene, self.camera, CENTER, RECT, exclude).entity)

    def test_world_normal_with_nonuniform_mirrored_slope(self):
        root = triangle()
        root.rot[:] = [.3, .2, .5]
        root.scale[:] = [-2, .5, 3]
        self.scene.add(root)
        hit = raycast_surface(self.scene, self.camera, CENTER, RECT)
        expected = rotation_xyz(root.rot)[:, 2]
        np.testing.assert_allclose(hit.normal, expected, atol=1e-7)
        self.assertAlmostEqual(hit.distance, 10)

    def test_bounds_anchor_uses_exact_vertices_with_nested_transform(self):
        root = Entity(matrix=np.array([[1, 0, 0, 3], [0, 1, 0, 4],
                                      [0, 0, 1, 5], [0, 0, 0, 1]]))
        child = triangle()
        child.pos[:] = [.5, -.5, 2]
        child.rot[:] = [.2, .1, .4]
        child.scale[:] = [2, .3, 1]
        root.add_child(child)
        root.pos[:] = [30, 20, 10]
        root.rot[:] = [.4, -.6, .7]
        root.scale[:] = [-2, 3, .5]
        root.update_transform()
        before = child.world_matrix.copy()
        original = child.model.vertices.copy()
        hit = SurfaceHit([8, 9, 10], [0, 0, 1])
        position, rotation = compute_placement(root, hit, anchor='bounds_bottom')
        np.testing.assert_array_equal(child.model.vertices, original)
        np.testing.assert_array_equal(child.world_matrix, before)
        np.testing.assert_array_equal(root.pos, [30, 20, 10])
        bounds = geometry_bounds(root, position, rotation)
        exact = (before @ original.T).T[:, :3]
        np.testing.assert_allclose(geometry_bounds(root)[0], exact.min(axis=0), atol=1e-7)
        np.testing.assert_allclose(geometry_bounds(root)[1], exact.max(axis=0), atol=1e-7)
        np.testing.assert_allclose((bounds[0][:2] + bounds[1][:2]) * .5, hit.position[:2], atol=1e-7)
        self.assertAlmostEqual(bounds[0][2], hit.position[2])

    def test_character_keeps_yaw_and_world_up_on_sloped_surface(self):
        root = triangle()
        root.placement_type = 'character'
        root.rot[:] = [.2, -.3, .9]
        hit = SurfaceHit([1, 2, 3], [.4, .2, 1])
        position, rotation = compute_placement(root, hit)
        np.testing.assert_allclose(rotation, [0, 0, .9])
        np.testing.assert_allclose(rotation_xyz(rotation)[:, 2], [0, 0, 1])
        self.assertAlmostEqual(geometry_bounds(root, position, rotation)[0][2], 3)
        np.testing.assert_allclose(root.rot, [.2, -.3, .9])

    def test_prop_preserves_rotation_and_pivot_anchor(self):
        root = triangle()
        root.placement_type = 'prop'
        root.rot[:] = [.4, .5, .6]
        position, rotation = compute_placement(root, SurfaceHit([4, 5, 6], [1, 0, 1]), anchor='pivot')
        np.testing.assert_allclose(position, [4, 5, 6])
        np.testing.assert_allclose(rotation, root.rot)
        position[0] = 90
        self.assertEqual(root.pos[0], 0)

    def test_hidden_instance_keeps_the_same_geometric_anchor(self):
        root = Entity()
        child = triangle()
        child.pos[2] = -3
        root.add_child(child)
        hit = SurfaceHit([1, 2, 4], [0, 0, 1])
        before = compute_placement(root, hit)
        root.visible = child.visible = False
        after = compute_placement(root, hit)
        np.testing.assert_allclose(after, before)
        self.assertEqual(after[0][2], 7)

    def test_empty_bounds_and_invalid_parameters(self):
        root = Entity()
        hit = SurfaceHit([1, 2, 3], [0, 0, 2])
        np.testing.assert_allclose(compute_placement(root, hit)[0], [1, 2, 3])
        self.assertIsNone(geometry_bounds(root))
        with self.assertRaises(ValueError):
            compute_placement(root, hit, anchor='vertex')
        with self.assertRaises(NotImplementedError):
            compute_placement(root, hit, align_normal=True)
        with self.assertRaises(ValueError):
            create_ground(-1)
        with self.assertRaises(ValueError):
            SurfaceHit([0, 0, 0], [0, 0, 0])


if __name__ == '__main__':
    unittest.main()
