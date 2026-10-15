"""Cache invalidation through public arrays, hierarchy, commands and scene IO."""
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.camera import Camera
from mini3d.geometry_cache import box_geometry, normal_transform
from mini3d.scene import Entity, Mesh, Scene, rotation_xyz
from mini3d.shadow_map import light_matrix
from mini3d.viewer import _world_boxes


class PerformanceCacheTests(unittest.TestCase):
    def test_boxes_follow_in_place_parent_bounds_and_mesh_replacement(self):
        mesh = Mesh(list(product((-1, 1), repeat=3)), [[0, 1, 2]])
        parent, child = Entity(), Entity(mesh)
        parent.add_child(child)
        scene = Scene(); scene.add(parent)
        for change in (lambda: None,
                       lambda: parent.pos.__setitem__(slice(None), [8, -2, 4]),
                       lambda: parent.scale.__setitem__(slice(None), [-2, .3, 1]),
                       lambda: child.rot.__setitem__(slice(None), [.2, .4, .9]),
                       lambda: mesh.bounds[1].__setitem__(0, 7),
                       lambda: setattr(child, 'model', Mesh([[0,0,0],[3,4,5]], [[0,1,0]]))):
            change(); scene.update()
            geometry = box_geometry(child)
            corners = np.array(list(product(*zip(*child.model.bounds))))
            expected = corners @ child.world_matrix[:3,:3].T + child.world_matrix[:3,3]
            np.testing.assert_array_equal(geometry[2], expected)
            np.testing.assert_allclose(geometry[3], [expected.min(0), expected.max(0)], atol=1e-12)
            self.assertIs(geometry, box_geometry(child))
        parent.visible = False
        self.assertEqual(list(_world_boxes(scene.root_entities, visible_only=True)), [])

    def test_invalid_boxes_are_never_culled_with_stale_data(self):
        entity = Entity(Mesh([[0,0,0],[1,1,1]], [[0,1,0]]))
        entity.update_transform()
        self.assertIsNotNone(box_geometry(entity))
        for invalid in (np.nan, np.inf):
            entity.model.bounds[1][0] = invalid
            self.assertIsNone(box_geometry(entity))
        entity.model.bounds[1][0] = 1
        entity.world_matrix[3,0] = .5
        self.assertIsNone(box_geometry(entity))
        entity.world_matrix[3,0] = 0
        self.assertIsNotNone(box_geometry(entity))

    def test_normals_reused_but_mirrors_and_flattened_objects_stay_correct(self):
        cache = {}
        for scale in ([2,.3,4], [-2,.3,4], [0,1,1]):
            matrix = np.eye(4, dtype=np.float32)
            matrix[:3,:3] = rotation_xyz([.2,.4,.9]) @ np.diag(scale)
            expected = np.linalg.pinv(matrix[:3,:3]).T
            with patch('numpy.linalg.pinv', wraps=np.linalg.pinv) as compute:
                normal, mirrored = normal_transform(matrix, cache)
                matrix[:3,3] += 5
                normal_transform(matrix, cache)
                self.assertEqual(compute.call_count, 1)
            np.testing.assert_array_equal(normal, expected)
            self.assertEqual(mirrored, np.linalg.det(matrix[:3,:3]) < 0)
        for i in range(300):
            normal_transform(np.diag([i+1., 1, 1, 1]), cache)
        self.assertLessEqual(len(cache), 256)

    def test_shadow_cache_revalidates_transforms_bounds_and_camera(self):
        api = Mini3DAPI(); api.create_roman_street(segments=2)
        scene = api._app.scene
        camera = Camera([9,-14,7], near=.05, far=100); camera.look_at([0,0,1])
        cache = {}
        for step in range(4):
            root = scene.root_entities[step]
            root.pos[0] += step
            root.scale[:] = [-1,.7,1.2]
            camera.position[0] += 1
            scene.update(); entities = scene.get_flat_render_list()
            # The scalar corner/edge oracle is tested separately; here compare
            # reused geometry against a fresh fit after every supported edit.
            cached = light_matrix(entities, [1,-2,3], camera, 2048, aspect=16/9, geometry_cache=cache)
            fresh = light_matrix(entities, [1,-2,3], camera, 2048, aspect=16/9)
            np.testing.assert_array_equal(cached, fresh)
        self.assertLessEqual(len(cache), 2048)

    def test_commands_undo_redo_reload_never_reuse_old_world_boxes(self):
        api = Mini3DAPI(); api.create_roman_street(segments=2)
        root = api._app.scene.root_entities[0]
        api._app.scene.update(); original = box_geometry(api._app.scene.get_flat_render_list()[0])[3].copy()
        api.set_transform(root.entity_id, position=[20,30,1])
        api._app.scene.update(); moved = box_geometry(api._app.scene.get_flat_render_list()[0])[3].copy()
        self.assertFalse(np.array_equal(moved, original))
        api.undo(); api._app.scene.update()
        np.testing.assert_array_equal(box_geometry(api._app.scene.get_flat_render_list()[0])[3], original)
        api.redo(); api._app.scene.update()
        np.testing.assert_array_equal(box_geometry(api._app.scene.get_flat_render_list()[0])[3], moved)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scene.json'; api.save_scene(path)
            api.load_scene(path); api._app.scene.update()
            np.testing.assert_array_equal(box_geometry(api._app.scene.get_flat_render_list()[0])[3], moved)


if __name__ == '__main__':
    unittest.main()
