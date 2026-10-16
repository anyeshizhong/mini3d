"""Shared shadow preparation preserves coverage and reacts to public edits."""
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.camera import Camera
from mini3d.scene import Entity, Mesh, Scene
from mini3d.scene_snapshot import SceneSnapshot
from mini3d.shadow_fit import _corners, _prepare_box, receiver_matrix
from mini3d.shadow_map import _shadow_input_key, light_matrix


class ShadowPreparationTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.parent = Entity()
        self.scene.add(self.parent)
        self.mesh = Mesh(_corners(([-.6, -.5, 0], [.6, .5, 3])), [[0, 1, 2]])
        self.mesh.material = {'alphaMode': 'OPAQUE'}
        self.buildings = []
        for index in range(7):
            entity = Entity(self.mesh)
            entity.pos[:] = [3 * (index - 3), index % 2, 0]
            entity.rot[:] = [.03 * index, -.1, .12 * index]
            entity.scale[:] = [-1 if index % 2 else 1, 1.4, .6 + .1 * index]
            self.parent.add_child(entity)
            self.buildings.append(entity)
        floor = Mesh(_corners(([-1, -1, 0], [1, 1, 0])), [[0, 1, 2]])
        floor.material = {'extras': {'photographicGround': True}}
        self.ground = Entity(floor)
        self.ground.scale[:] = [300, 300, 1]
        self.scene.add(self.ground)
        self.scene.update()
        self.geometry = SceneSnapshot().refresh(self.scene)
        self.cache = {}
        self.camera = Camera([7, -9, 6], near=.01, far=500)
        self.camera.look_at([0, 0, 1])

    def compare_fit(self, light):
        entities = self.scene.get_flat_render_list()
        expected = receiver_matrix(entities, light, self.camera, 2048, aspect=16/9)
        actual = receiver_matrix(entities, light, self.camera, 2048, aspect=16/9,
                                 geometry_cache=self.cache, prepared=self.geometry)
        self.assertIsNotNone(expected)
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)

    def test_moving_camera_low_sun_mirrored_and_offscreen_geometry(self):
        for position in ([7, -9, 6], [-8, 7, 2], [0, -3, 1.1]):
            self.camera.position[:] = position
            self.camera.look_at([0, 0, 1])
            for light in ([1, 0, .03], [-3, -2, 3], [0, 0, 1], [1, 0, 0], [2, -1, -1]):
                self.compare_fit(light)

    def test_static_geometry_reuses_arrays_and_inverse_preparation(self):
        self.compare_fit([-3, -2, 3])
        bank = self.cache['_prepared_receivers']
        arrays = bank.arrays
        records = bank.records[:]
        with patch('mini3d.shadow_fit._prepare_box', side_effect=AssertionError('static geometry rebuilt')):
            self.camera.position[:] = [-8, -7, 3]
            self.camera.look_at([0, 0, 1])
            self.compare_fit([-3, -2, 3])
        for before, after in zip(arrays, bank.arrays):
            self.assertIs(before, after)
        self.assertTrue(all(a is b for a, b in zip(records, bank.records)))

    def test_only_following_ground_rebuilds_when_camera_plane_moves(self):
        self.compare_fit([-3, -2, 3])
        records = self.cache['_prepared_receivers'].records[:]
        self.ground.pos[:] = [90, -70, 0]
        self.ground.scale[:] = [600, 600, 1]
        self.scene.update()
        self.geometry.refresh(self.scene)
        with patch('mini3d.shadow_fit._prepare_box', wraps=_prepare_box) as prepare:
            self.compare_fit([-3, -2, 3])
            self.assertEqual(prepare.call_count, 1)
        current = self.cache['_prepared_receivers'].records
        self.assertTrue(all(a is b for a, b in zip(records[:-1], current[:-1])))

    def test_parent_mesh_bounds_visibility_and_ground_classification_edits(self):
        self.compare_fit([-3, -2, 3])
        edits = [lambda: self.parent.pos.__setitem__(0, 2),
                 lambda: self.mesh.bounds[1].__setitem__(2, 7),
                 lambda: setattr(self.buildings[2], 'visible', False),
                 lambda: self.ground.model.material['extras'].__setitem__('photographicGround', False)]
        for edit in edits:
            edit()
            self.scene.update()
            self.geometry.refresh(self.scene)
            self.compare_fit([1, .2, .12])

    def test_cutout_changes_invalidate_shadow_key(self):
        entities = self.scene.get_flat_render_list()
        previous = _shadow_input_key(entities, self.geometry)
        self.mesh.material.update(alphaMode='MASK', alphaCutoff=.7,
                                  textures={'baseColor': {'image': object(), 'sampler': {}}})
        self.geometry.refresh(self.scene)
        current = _shadow_input_key(entities, self.geometry)
        self.assertNotEqual(previous, current)
        self.mesh.material['textures']['baseColor']['sampler']['wrapS'] = 33071
        self.geometry.refresh(self.scene)
        self.assertNotEqual(current, _shadow_input_key(entities, self.geometry))

    def test_whole_scene_fallback_matches_legacy_endpoint_corners(self):
        entities = self.scene.get_flat_render_list()
        for light in ([1, 0, 0], [0, 1, 0], [1, -2, 3]):
            np.testing.assert_allclose(light_matrix(entities, light),
                                       light_matrix(entities, light, prepared=self.geometry),
                                       rtol=1e-14, atol=1e-14)


if __name__ == '__main__':
    unittest.main()
