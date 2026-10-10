"""CPU visibility checks, independent eight-corner support oracle and mutations."""
from itertools import product
import unittest

import numpy as np
from mini3d.camera import Camera
from mini3d.scene import Entity, Mesh, Scene
from mini3d.render_plan import aabb_visible, build_render_plan, frustum_planes, world_bounds
from mini3d.shot_camera import ShotCamera


def box(bounds=((-1, -1, -1), (1, 1, 1)), material=None):
    return Entity(Mesh(list(product(*zip(*bounds))), [[0, 1, 2]], material=material))


class RenderPlanTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.camera = Camera([0, 0, 0], near=1, far=10, fov_y=90)

    def plan(self, camera=None, **kwargs):
        self.scene.update()
        return build_render_plan(self.scene, camera or self.camera, 100, 100, **kwargs)

    def add(self, position, bounds=((-1, -1, -1), (1, 1, 1)), material=None):
        entity = box(bounds, material)
        entity.pos[:] = position
        self.scene.add(entity)
        return entity

    def test_rejects_each_of_six_planes_and_behind_camera(self):
        for position in ((-20, 0, -5), (20, 0, -5), (0, -20, -5),
                         (0, 20, -5), (0, 0, 2), (0, 0, -12), (0, 0, 20)):
            self.add(position)
        plan = self.plan()
        self.assertEqual(plan.stats['entities_after'], 0)
        self.assertEqual(len(plan.shadow_candidates), 7)

    def test_partial_and_touching_near_far_and_sides_are_kept(self):
        for position in ((0, 0, 0), (0, 0, -11), (6, 0, -5), (0, 6, -5)):
            self.add(position)
        self.assertEqual(self.plan().stats['entities_after'], 4)

    def test_large_ground_and_enclosing_box_without_inside_corners(self):
        self.add([0, 0, -5], ((-100, -100, -.1), (100, 100, .1)))
        self.add([0, 0, -5], ((-100, -100, -100), (100, 100, 100)))
        self.assertEqual(self.plan().stats['entities_after'], 2)

    def test_parent_rotation_nonuniform_negative_scale_matches_corner_oracle(self):
        parent = Entity()
        parent.pos[:] = [5, 1, -6]
        parent.rot[:] = [.2, .5, 1.1]
        parent.scale[:] = [-2, .3, 1.5]
        child = box()
        child.pos[:] = [2, 0, 0]
        child.rot[:] = [.6, .3, .8]
        parent.add_child(child)
        self.scene.add(parent)
        self.scene.update()
        matrix = child.world_matrix.astype(np.float32)
        corners = np.array(list(product((-1, 1), repeat=3))) @ matrix[:3, :3].T + matrix[:3, 3]
        np.testing.assert_allclose(world_bounds(child.model, matrix),
                                   [corners.min(0), corners.max(0)])
        self.assertIs(self.plan().shadow_candidates[0], child)

    def test_batch_plane_support_matches_independent_corner_oracle(self):
        rng = np.random.RandomState(81)
        planes = frustum_planes(self.camera.view_matrix, self.camera.projection_matrix(1))
        lo = rng.uniform(-30, 30, (500, 3))
        hi = lo + rng.uniform(.1, 12, (500, 3))
        boxes = np.stack((lo, hi), axis=1)
        expected = []
        for bounds in boxes:
            corners = np.array(list(product(*zip(*bounds))))
            expected.append(np.all(np.max(corners @ planes[:, :3].T + planes[:, 3], axis=0) >= 0))
        np.testing.assert_array_equal(aabb_visible(boxes, planes), expected)

    def test_camera_pose_lens_aspect_and_shot_are_recomputed(self):
        self.add([8, 0, -5])
        self.assertEqual(self.plan().stats['entities_after'], 0)
        self.camera.fov_y = 140
        self.assertEqual(self.plan().stats['entities_after'], 1)
        self.camera.fov_y = 90
        self.assertEqual(build_render_plan(self.scene, self.camera, 300, 100).stats['entities_after'], 1)
        self.camera.position = [8, 0, 0]
        self.assertEqual(self.plan(ShotCamera(self.camera)).stats['entities_after'], 1)
        self.camera.look_at([30, 0, 0])
        self.assertEqual(self.plan().stats['entities_after'], 0)

    def test_transform_bounds_material_visibility_and_remove_have_no_stale_cache(self):
        entity = self.add([20, 0, -5])
        self.assertEqual(self.plan().stats['entities_after'], 0)
        entity.pos[:] = [0, 0, -5]
        self.assertEqual(self.plan().stats['entities_after'], 1)
        entity.model.material = {'alphaMode': 'BLEND'}
        self.assertEqual(len(self.plan().transparent), 1)
        entity.model = box(((-100, -1, -1), (100, 1, 1))).model
        entity.pos[:] = [20, 0, -5]
        self.assertEqual(self.plan().stats['entities_after'], 1)
        entity.visible = False
        self.assertEqual(len(self.plan().shadow_candidates), 0)
        entity.visible = True
        self.scene.root_entities.remove(entity)
        self.assertEqual(self.plan().stats['entities_before'], 0)

    def test_missing_invalid_bounds_and_projective_transform_are_retained(self):
        entity = self.add([20, 0, -5])
        for bounds in (None, [[np.nan]*3, [1]*3], [[2]*3, [1]*3]):
            entity.model.bounds = bounds
            self.assertEqual(self.plan().stats['entities_after'], 1)
        entity.model.bounds = [[-1]*3, [1]*3]
        entity.extra_local[3, 0] = .1
        self.assertEqual(self.plan().stats['entities_after'], 1)
        self.assertTrue(aabb_visible([[[-1]*3, [1]*3]], np.full((6, 4), np.nan))[0])

    def test_disabled_culling_draw_records_and_material_classification(self):
        opaque = self.add([20, 0, -5], material={'alphaMode': 'MASK'})
        blend = self.add([0, 0, -5], material={'alphaMode': 'BLEND'})
        self.add([0, 0, -5])
        plan = self.plan(culling=False)
        self.assertEqual(len(plan.imported), 2)
        self.assertEqual(len(plan.opaque), 2)
        self.assertEqual(plan.transparent[0].entity, blend)
        self.assertIs(plan.imported[0].model, opaque.model)
        np.testing.assert_array_equal(plan.imported[0].world_matrix, opaque.world_matrix.astype(np.float32))
        self.assertEqual(plan.stats['entities_culled'], 0)

    def test_outline_expansion_and_axes_keep_offscreen_legacy_helpers(self):
        entity = self.add([20, 0, -5])
        self.assertEqual(self.plan(legacy_mode='OUTLINE').stats['entities_after'], 1)
        entity.isaxes = True
        self.assertEqual(self.plan().stats['entities_after'], 1)

    def test_hidden_parent_excludes_children_from_both_passes(self):
        parent = Entity()
        parent.add_child(box())
        parent.visible = False
        self.scene.add(parent)
        self.assertEqual(self.plan().stats['entities_before'], 0)


if __name__ == '__main__':
    unittest.main()
