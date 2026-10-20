import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from surroundings_scene import DEFAULT_CONFIG, build_scene, terrain_height
import surroundings_scene


def _root_named(scene, name):
    return next(entity for entity in scene.root_entities if entity.name == name)


class SurroundingsSceneTests(unittest.TestCase):
    def test_default_config_and_query_are_json_safe_and_broadcast(self):
        json.dumps(DEFAULT_CONFIG, allow_nan=False)
        scalar = terrain_height(0.0, 0.0)
        self.assertIsInstance(scalar, float)
        self.assertAlmostEqual(scalar, DEFAULT_CONFIG["city"]["plateau_z"] -
                               DEFAULT_CONFIG["terrain"]["surface_clearance"], places=5)

        x = np.asarray([[-200.0], [0.0], [200.0]])
        y = np.asarray([-200.0, 0.0, 200.0])
        values = terrain_height(x, y)
        self.assertEqual(values.shape, (3, 3))
        self.assertTrue(np.isfinite(values).all())

    def test_a_and_c_share_city_terrain_and_exit_with_far_geometry_only_in_c(self):
        scene_a, meta_a = build_scene("A")
        scene_c, meta_c = build_scene("C")

        self.assertEqual(meta_a["config_sha256"], meta_c["config_sha256"])
        self.assertEqual(meta_a["entity_names"]["city"], meta_c["entity_names"]["city"])
        self.assertEqual(meta_a["far_entities"], [])
        self.assertEqual(meta_c["far_entities"], ["SUR Far Mountains"])
        self.assertIsNone(meta_a["entity_names"]["far_mountains"])
        self.assertEqual(meta_c["entity_names"]["far_mountains"], "SUR Far Mountains")

        for name in ("SUR Common Terrain", "SUR Static Exit Road"):
            mesh_a = _root_named(scene_a, name).model
            mesh_c = _root_named(scene_c, name).model
            np.testing.assert_array_equal(mesh_a.vertices, mesh_c.vertices)
            np.testing.assert_array_equal(mesh_a.indices, mesh_c.indices)
            np.testing.assert_array_equal(mesh_a.vertex_normals, mesh_c.vertex_normals)

        common_a = [entity for entity in scene_a.root_entities
                    if entity.name != "SUR Far Mountains"]
        common_c = [entity for entity in scene_c.root_entities
                    if entity.name != "SUR Far Mountains"]
        self.assertEqual([entity.name for entity in common_a], [entity.name for entity in common_c])
        for first, second in zip(common_a, common_c):
            np.testing.assert_array_equal(first.pos, second.pos)
            np.testing.assert_array_equal(first.rot, second.rot)

        mountain = _root_named(scene_c, "SUR Far Mountains").model
        self.assertGreater(float(mountain.vertices[:, 2].max()), 300.0)
        self.assertGreater(meta_c["geometry"]["far_mountains"]["triangles"], 0)

    def test_all_emitted_meshes_are_finite_and_camera_area_has_ground(self):
        scene, metadata = build_scene("C")
        render_nodes = scene.get_flat_render_list()
        self.assertGreater(len(render_nodes), 0)
        for entity in render_nodes:
            mesh = entity.model
            self.assertTrue(np.isfinite(mesh.vertices).all(), entity.name)
            self.assertTrue(np.isfinite(mesh.vertex_normals).all(), entity.name)
            self.assertGreater(len(mesh.indices), 0, entity.name)
            if entity.name in ("SUR Common Terrain", "SUR Static Exit Road", "SUR Far Mountains"):
                self.assertTrue(np.all(np.linalg.norm(mesh.vertex_normals, axis=1) > 0.99), entity.name)

        bounds = metadata["geography"]["terrain_xy_bounds"]
        camera_bounds = metadata["geography"]["camera_xy_bounds"]
        self.assertLessEqual(bounds[0][0], camera_bounds[0][0])
        self.assertGreaterEqual(bounds[0][1], camera_bounds[0][1])
        self.assertLessEqual(bounds[1][0], camera_bounds[1][0])
        self.assertGreaterEqual(bounds[1][1], camera_bounds[1][1])
        samples = terrain_height(
            np.asarray([-200.0, -200.0, 200.0, 200.0]),
            np.asarray([-200.0, 200.0, -200.0, 200.0]),
        )
        self.assertTrue(np.isfinite(samples).all())

    def test_far_mountain_keeps_only_elevated_faces_and_compacts_vertices(self):
        scene, _ = build_scene("C")
        mountain = _root_named(scene, "SUR Far Mountains").model
        common_height = terrain_height(mountain.vertices[:, 0], mountain.vertices[:, 1])
        clearance = mountain.vertices[:, 2].astype(np.float64) - common_height
        triangle_clearance = clearance[mountain.indices]

        self.assertTrue(np.all(np.max(triangle_clearance, axis=1) > 0.01))
        self.assertGreaterEqual(float(clearance.min()), -1e-5)
        self.assertAlmostEqual(float(clearance.min()), 0.0, places=5)
        np.testing.assert_array_equal(
            np.unique(mountain.indices), np.arange(len(mountain.vertices), dtype=np.uint32))
        self.assertTrue(np.isfinite(mountain.vertex_normals).all())

    def test_grid_sample_and_vertex_budgets_reject_before_large_arrays(self):
        tiny_step = surroundings_scene._merge_config({"grid": {"inner_step": 0.01}})
        with patch.object(surroundings_scene.np, "linspace",
                          side_effect=AssertionError("axis samples allocated before budget check")) as linspace:
            with self.assertRaisesRegex(ValueError, "too many terrain samples"):
                surroundings_scene._build_axes(tiny_step)
            linspace.assert_not_called()

        dense_grid = surroundings_scene._merge_config({
            "grid": {"inner_step": 8.0, "mid_step": 14.0,
                     "far_step": 14.0, "outer_step": 14.0}
        })
        config_key = surroundings_scene._config_json(dense_grid)
        with patch.object(surroundings_scene.np, "meshgrid",
                          side_effect=AssertionError("terrain grid allocated before vertex check")) as meshgrid:
            with self.assertRaisesRegex(ValueError, "terrain vertex budget"):
                surroundings_scene._ground_data_cached(config_key)
            meshgrid.assert_not_called()

    def test_ridge_and_valley_control_points_are_bounded(self):
        too_many_ridge_controls = [[index * 10.0, 0.0, 300.0] for index in range(33)]
        with self.assertRaisesRegex(ValueError, "ridge.controls must contain"):
            surroundings_scene._merge_config({"ridge": {"controls": too_many_ridge_controls}})

        too_many_valley_points = [[0.0, -float(index)] for index in range(33)]
        with self.assertRaisesRegex(ValueError, "valley.centerline must contain"):
            surroundings_scene._merge_config({"valley": {"centerline": too_many_valley_points}})

    def test_exit_road_vertices_follow_the_common_triangle_surface(self):
        scene, metadata = build_scene("A")
        road = _root_named(scene, "SUR Static Exit Road").model
        vertices = road.vertices[:, :3]
        expected = terrain_height(vertices[:, 0], vertices[:, 1]) + metadata["geometry"]["exit_road"]["surface_lift"]
        np.testing.assert_allclose(vertices[:, 2], expected, rtol=0.0, atol=1e-4)

    def test_exit_road_triangle_interiors_keep_small_positive_ground_clearance(self):
        scene, _ = build_scene("A")
        road = _root_named(scene, "SUR Static Exit Road").model
        triangles = road.vertices[road.indices, :3]  # Mesh vertices include homogeneous W.
        weights = np.asarray([(a / 10.0, b / 10.0, 1.0 - (a + b) / 10.0)
                              for a in range(11) for b in range(11 - a)])
        samples = np.einsum("sv,tvc->tsc", weights, triangles).reshape(-1, 3)
        clearance = samples[:, 2] - terrain_height(samples[:, 0], samples[:, 1])
        # 66 barycentric probes per road triangle catch both clipping through
        # terrain cell boundaries and excessive lifting between edge stations.
        self.assertGreater(float(clearance.min()), 0.0)
        self.assertLess(float(clearance.max()), 0.04)

    def test_invalid_variant_config_and_non_finite_query_are_rejected(self):
        with self.assertRaises(ValueError):
            build_scene("B")
        with self.assertRaises(ValueError):
            build_scene("A", config={"ridge": {"unknown": 1}})
        with self.assertRaises(ValueError):
            terrain_height(np.nan, 0.0)
        with self.assertRaises(ValueError):
            terrain_height(0.0, 9001.0)


if __name__ == "__main__":
    unittest.main()
