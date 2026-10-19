"""CPU-only regression checks for the LAB-01 heightfield core."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = ROOT / "experiments" / "world-surroundings" / "heightfield.py"
SPEC = importlib.util.spec_from_file_location("world_surroundings_heightfield", MODULE_PATH)
heightfield_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(heightfield_module)
Heightfield = heightfield_module.Heightfield


def _area_weighted_normals_add_at(vertices, indices):
    """Pre-optimization scatter retained as a numerical regression oracle."""
    points = np.asarray(vertices, dtype=np.float64)
    triangles = points[indices]
    faces = np.cross(triangles[:, 1] - triangles[:, 0],
                     triangles[:, 2] - triangles[:, 0])
    accumulated = np.zeros((len(points), 3), dtype=np.float64)
    for corner in range(3):
        np.add.at(accumulated, indices[:, corner], faces)
    lengths = np.linalg.norm(accumulated, axis=1)
    if not np.isfinite(lengths).all() or np.any(lengths <= 0.0):
        raise ValueError("heightfield geometry produced invalid vertex normals")
    return (accumulated / lengths[:, None]).astype(np.float32)


class HeightfieldTests(unittest.TestCase):
    def test_flat_geometry_counts_and_mesh_contract(self):
        terrain = Heightfield.flat(rows=3, cols=4, height=2.5,
                                   origin=(-2.0, -1.0), size=(6.0, 4.0))
        arrays = terrain.mesh_arrays()
        mesh = terrain.to_mesh(material={"kind": "terrain"})

        self.assertEqual(terrain.stats(), {
            "rows": 3, "cols": 4, "vertices": 12, "cells": 6, "triangles": 12,
        })
        self.assertEqual(arrays["vertices"].dtype, np.float32)
        self.assertEqual(arrays["indices"].dtype, np.uint32)
        self.assertEqual(arrays["normals"].dtype, np.float32)
        self.assertEqual(arrays["uvs"].dtype, np.float32)
        self.assertEqual(arrays["vertices"].shape, (12, 3))
        self.assertEqual(arrays["indices"].shape, (12, 3))
        self.assertTrue(np.all(arrays["vertices"][:, 2] == np.float32(2.5)))
        self.assertTrue(np.allclose(arrays["normals"], (0.0, 0.0, 1.0)))
        self.assertTrue(np.allclose(mesh.vertex_normals, (0.0, 0.0, 1.0)))
        self.assertEqual(mesh.material, {"kind": "terrain"})
        self.assertTrue(np.array_equal(mesh.vertices[:, :3], arrays["vertices"]))
        self.assertTrue(np.array_equal(mesh.indices, arrays["indices"]))
        self.assertTrue(np.all(mesh.texcoords >= 0.0))
        self.assertTrue(np.all(mesh.texcoords <= 1.0))

        faces = arrays["vertices"][arrays["indices"]]
        cross = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        self.assertTrue(np.all(cross[:, 2] > 0.0))

    def test_height_samples_are_owned_float64_and_cannot_be_reenabled_for_writing(self):
        source = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
        terrain = Heightfield(source)
        source[0, 0] = 99.0

        self.assertEqual(terrain.heights.dtype, np.float64)
        self.assertEqual(float(terrain.heights[0, 0]), 0.0)
        with self.assertRaises(ValueError):
            terrain.heights[0, 0] = -1.0
        with self.assertRaises(ValueError):
            terrain.heights.setflags(write=True)

    def test_constructor_validates_shape_finiteness_and_float32_geometry(self):
        invalid_cases = [
            (np.array([0.0, 1.0]), {}, "rows"),
            (np.zeros((1, 2)), {}, "rows"),
            (np.zeros((2, 1)), {}, "columns"),
            (np.array([[0.0, np.nan], [1.0, 2.0]]), {}, "finite samples"),
            (np.array([[0.0, 1e40], [1.0, 2.0]]), {}, "float32 heights"),
            (np.zeros((2, 2)), {"origin": (np.inf, 0.0)}, "finite origin"),
            (np.zeros((2, 2)), {"size": (0.0, 1.0)}, "positive size"),
            (np.zeros((2, 2)), {"size": (np.nan, 1.0)}, "finite size"),
            (np.zeros((2, 2)), {"origin": (1e39, 0.0)}, "float32 origin"),
            (np.zeros((2, 3)), {"origin": (1e8, 0.0), "size": (1.0, 1.0)},
             "collapsed x grid"),
        ]
        for samples, kwargs, label in invalid_cases:
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    Heightfield(samples, **kwargs)

    def test_asymmetric_slope_queries_match_each_emitted_triangle(self):
        terrain = Heightfield([[0.0, 2.0], [1.0, 6.0]],
                              origin=(0.0, 0.0), size=(1.0, 1.0))

        first = terrain.query_surface(0.75, 0.25)
        self.assertTrue(first["hit"])
        self.assertAlmostEqual(first["height"], 2.5)
        self.assertEqual(first["cell"], [0, 0])
        self.assertEqual(first["triangle"], 0)
        self.assertTrue(np.allclose(first["normal"],
                                    np.array([-2.0, -4.0, 1.0]) /
                                    np.linalg.norm([-2.0, -4.0, 1.0])))

        second = terrain.query_surface(0.25, 0.75)
        self.assertTrue(second["hit"])
        self.assertAlmostEqual(second["height"], 2.0)
        self.assertEqual(second["cell"], [0, 0])
        self.assertEqual(second["triangle"], 1)
        self.assertTrue(np.allclose(second["normal"],
                                    np.array([-5.0, -1.0, 1.0]) /
                                    np.linalg.norm([-5.0, -1.0, 1.0])))

        diagonal = terrain.query_surface(0.5, 0.5)
        self.assertEqual(diagonal["triangle"], 0)
        self.assertAlmostEqual(diagonal["height"], 3.0)

    def test_saddle_query_is_piecewise_planar_not_bilinear(self):
        terrain = Heightfield([[0.0, 1.0], [1.0, 0.0]],
                              origin=(0.0, 0.0), size=(1.0, 1.0))
        center = terrain.query_surface(0.5, 0.5)
        self.assertEqual(center["triangle"], 0)
        self.assertAlmostEqual(center["height"], 0.0)
        self.assertNotAlmostEqual(center["height"], 0.5)

        off_diagonal = terrain.query_surface(0.75, 0.25)
        self.assertAlmostEqual(off_diagonal["height"], 0.5)
        self.assertEqual(off_diagonal["triangle"], 0)

    def test_grid_lines_boundaries_and_outside_points(self):
        terrain = Heightfield([[0.0, 1.0, 2.0],
                               [3.0, 4.0, 5.0],
                               [6.0, 7.0, 8.0]],
                              origin=(-1.0, -2.0), size=(4.0, 6.0))
        arrays = terrain.mesh_arrays()
        points = arrays["vertices"].reshape(3, 3, 3)

        for row, col in ((0, 0), (0, 2), (2, 0), (2, 2), (1, 1)):
            x, y, z = points[row, col]
            result = terrain.query_surface(float(x), float(y))
            with self.subTest(vertex=(row, col)):
                self.assertTrue(result["hit"])
                self.assertAlmostEqual(result["height"], float(z))

        # Interior grid lines are assigned to their positive-side cell.
        self.assertEqual(terrain.query_surface(1.0, 1.0)["cell"], [1, 1])
        # The maximum boundary stays in the final cell.
        self.assertEqual(terrain.query_surface(3.0, 4.0)["cell"], [1, 1])
        self.assertFalse(terrain.query_surface(-1.0001, 0.0)["hit"])
        self.assertFalse(terrain.query_surface(0.0, 4.0001)["hit"])

    def test_nonfinite_or_nonnumeric_query_coordinates_raise_value_error(self):
        terrain = Heightfield.flat(rows=2, cols=2)
        for x, y in ((np.nan, 0.0), (0.0, np.inf), (-np.inf, 0.0), ("bad", 0.0)):
            with self.subTest(point=(x, y)):
                with self.assertRaises(ValueError):
                    terrain.query_surface(x, y)

    def test_queries_follow_float32_mesh_bounds_and_vertex_coordinates(self):
        terrain = Heightfield([[0.0, 0.5], [1.0, 1.5]],
                              origin=(-1.00000004, -2.00000004),
                              size=(2.00000003, 4.00000003))
        arrays = terrain.mesh_arrays()
        mesh = terrain.to_mesh()
        vertices = arrays["vertices"].reshape(2, 2, 3)
        self.assertTrue(np.array_equal(mesh.vertices[:, :3], arrays["vertices"]))
        self.assertEqual(terrain.bounds[0][0], float(vertices[0, 0, 0]))
        self.assertEqual(terrain.bounds[1][1], float(vertices[1, 1, 1]))

        for row in range(2):
            for col in range(2):
                x, y, z = vertices[row, col]
                result = terrain.query_surface(float(x), float(y))
                self.assertTrue(result["hit"])
                self.assertAlmostEqual(result["height"], float(z))
        # The input origin rounds inward to float32, so the ideal float64 edge
        # is outside the canonical mesh domain.
        if terrain.bounds[0][0] > terrain.origin[0]:
            self.assertFalse(terrain.query_surface(terrain.origin[0],
                                                   terrain.bounds[1][0])["hit"])

    def test_at_least_twenty_queries_match_independent_triangle_ray_hits(self):
        samples = np.array([
            [0.0, 1.5, -0.5, 2.0, 3.0, 0.0],
            [2.0, -1.0, 4.0, 1.0, -2.0, 1.0],
            [1.0, 3.0, 0.0, -1.5, 2.5, 4.0],
            [-2.0, 0.5, 2.0, 5.0, 1.0, -1.0],
            [3.5, -0.5, 1.0, 2.0, 0.0, 2.5],
        ])
        terrain = Heightfield(samples, origin=(-2.3, -1.7), size=(4.1, 3.8))
        mesh = terrain.to_mesh()

        from mini3d.picking import _triangle_hit

        points = terrain.mesh_arrays()["vertices"].reshape(terrain.rows, terrain.cols, 3)
        maximum = float(points[..., 2].max()) + 25.0
        queries = []
        # Every sample vertex checks the exact mesh bounds and shared edges.
        queries.extend((float(points[row, col, 0]), float(points[row, col, 1]))
                       for row in range(terrain.rows) for col in range(terrain.cols))
        # One point in each triangle gives both halves of every cell coverage.
        for row in range(terrain.rows - 1):
            for col in range(terrain.cols - 1):
                x0, x1 = points[row, col, 0], points[row, col + 1, 0]
                y0, y1 = points[row, col, 1], points[row + 1, col, 1]
                queries.append((float(x0 + 0.75 * (x1 - x0)),
                                float(y0 + 0.25 * (y1 - y0))))
                queries.append((float(x0 + 0.25 * (x1 - x0)),
                                float(y0 + 0.75 * (y1 - y0))))

        self.assertGreaterEqual(len(queries), 20)
        for index, (x, y) in enumerate(queries):
            result = terrain.query_surface(x, y)
            ray = _triangle_hit(mesh, np.array([x, y, maximum]),
                                np.array([0.0, 0.0, -1.0]), 0.0, np.inf)
            with self.subTest(query=index, point=(x, y)):
                self.assertTrue(result["hit"])
                self.assertIsNotNone(ray)
                self.assertAlmostEqual(result["height"], maximum - ray[0], places=5)

    def test_chunks_cover_cells_once_and_reuse_global_seam_normals(self):
        terrain = Heightfield([
            [0, 1, 0, 2, 1, 3, 0],
            [2, 3, 1, 4, 0, 5, 2],
            [1, 4, 2, 6, 2, 4, 1],
            [3, 0, 5, 1, 7, 2, 6],
            [2, 5, 1, 8, 0, 6, 3],
            [4, 1, 7, 2, 5, 3, 9],
        ], origin=(-3.0, -2.0), size=(6.0, 5.0))
        material = {"surface": "soil"}
        chunks = terrain.iter_mesh_chunks(material, chunk_cells=2)
        arrays = terrain.mesh_arrays()
        global_vertices = arrays["vertices"].reshape(terrain.rows, terrain.cols, 3)
        global_mesh = terrain.to_mesh(material)
        global_normals = global_mesh.vertex_normals.reshape(terrain.rows, terrain.cols, 3)

        self.assertEqual([(chunk["row_start"], chunk["col_start"]) for chunk in chunks], [
            (0, 0), (0, 2), (0, 4),
            (2, 0), (2, 2), (2, 4),
            (4, 0), (4, 2), (4, 4),
        ])
        self.assertTrue(all(chunk["mesh"].material is material for chunk in chunks))

        coverage = np.zeros((terrain.rows - 1, terrain.cols - 1), dtype=np.int32)
        for chunk in chunks:
            row_start, col_start = chunk["row_start"], chunk["col_start"]
            row_end, col_end = chunk["row_end"], chunk["col_end"]
            coverage[row_start:row_end, col_start:col_end] += 1
            mesh = chunk["mesh"]
            local_rows = row_end - row_start + 1
            local_cols = col_end - col_start + 1
            actual_vertices = mesh.vertices[:, :3].reshape(local_rows, local_cols, 3)
            actual_normals = mesh.vertex_normals.reshape(local_rows, local_cols, 3)
            expected_vertices = global_vertices[row_start:row_end + 1,
                                                col_start:col_end + 1]
            expected_normals = global_normals[row_start:row_end + 1,
                                              col_start:col_end + 1]
            self.assertTrue(np.array_equal(actual_vertices, expected_vertices))
            self.assertTrue(np.array_equal(actual_normals, expected_normals))
            self.assertEqual(len(mesh.indices), 2 * (local_rows - 1) * (local_cols - 1))
            self.assertEqual(chunk["triangle_count"], len(mesh.indices))
        self.assertTrue(np.all(coverage == 1))

        # Adjacent chunks contain identical vertices and smoothed normals on
        # their shared vertical and horizontal edges.
        by_start = {(chunk["row_start"], chunk["col_start"]): chunk for chunk in chunks}
        for row_start in (0, 2, 4):
            for col_start in (0, 2):
                left = by_start[(row_start, col_start)]["mesh"]
                right = by_start[(row_start, col_start + 2)]["mesh"]
                left_rows = left.vertices[:, :3].reshape(-1, 3, 3)
                right_rows = right.vertices[:, :3].reshape(-1, 3, 3)
                left_normals = left.vertex_normals.reshape(-1, 3, 3)
                right_normals = right.vertex_normals.reshape(-1, 3, 3)
                self.assertTrue(np.array_equal(left_rows[:, -1], right_rows[:, 0]))
                self.assertTrue(np.array_equal(left_normals[:, -1], right_normals[:, 0]))
        for row_start in (0, 2):
            for col_start in (0, 2, 4):
                upper = by_start[(row_start, col_start)]["mesh"]
                lower = by_start[(row_start + 2, col_start)]["mesh"]
                upper_row_count = by_start[(row_start, col_start)]["row_end"] - row_start + 1
                lower_start = row_start + 2
                lower_row_count = by_start[(lower_start, col_start)]["row_end"] - lower_start + 1
                upper_rows = upper.vertices[:, :3].reshape(upper_row_count, -1, 3)
                lower_rows = lower.vertices[:, :3].reshape(lower_row_count, -1, 3)
                upper_normals = upper.vertex_normals.reshape(upper_row_count, -1, 3)
                lower_normals = lower.vertex_normals.reshape(lower_row_count, -1, 3)
                self.assertTrue(np.array_equal(upper_rows[-1], lower_rows[0]))
                self.assertTrue(np.array_equal(upper_normals[-1], lower_normals[0]))

    def test_chunk_validation_order_and_deterministic_outputs(self):
        terrain = Heightfield.flat(rows=5, cols=4)
        first = terrain.iter_mesh_chunks(chunk_cells=2)
        second = terrain.iter_mesh_chunks(chunk_cells=2)
        self.assertEqual([(c["row_start"], c["col_start"], c["row_end"], c["col_end"])
                          for c in first],
                         [(0, 0, 2, 2), (0, 2, 2, 3),
                          (2, 0, 4, 2), (2, 2, 4, 3)])
        for one, two in zip(first, second):
            self.assertTrue(np.array_equal(one["mesh"].vertices, two["mesh"].vertices))
            self.assertTrue(np.array_equal(one["mesh"].indices, two["mesh"].indices))
            self.assertTrue(np.array_equal(one["mesh"].vertex_normals,
                                           two["mesh"].vertex_normals))
        with self.assertRaises(ValueError):
            terrain.iter_mesh_chunks(chunk_cells=0)
        with self.assertRaises(ValueError):
            terrain.iter_mesh_chunks(chunk_cells=1.5)

    def test_repeated_inputs_produce_identical_arrays_and_query_results(self):
        samples = np.array([[0.0, 0.5, 2.0], [1.0, 4.0, -1.0], [3.0, 2.0, 5.0]])
        terrains = [Heightfield(samples, origin=(-4.1, 0.3), size=(5.7, 8.2))
                    for _ in range(2)]
        arrays = [terrain.mesh_arrays() for terrain in terrains]
        for name in ("vertices", "indices", "normals", "uvs"):
            self.assertTrue(np.array_equal(arrays[0][name], arrays[1][name]))
        query_point = (0.123, 3.987)
        self.assertEqual(terrains[0].query_surface(*query_point),
                         terrains[1].query_surface(*query_point))

    def test_bincount_normals_match_corner_major_add_at_bitwise_on_random_meshes(self):
        cases = ((2, 2, 11, 1.0), (5, 8, 17, 1e-3),
                 (65, 65, 23, 1.0), (65, 65, 31, 1e6),
                 (257, 257, 29, 1.0), (257, 257, 37, 1e20))
        for rows, cols, seed, height_scale in cases:
            with self.subTest(shape=(rows, cols), height_scale=height_scale):
                rng = np.random.default_rng(seed)
                grid_x, grid_y = np.meshgrid(np.arange(cols, dtype=np.float32),
                                             np.arange(rows, dtype=np.float32))
                vertices = np.empty((rows, cols, 3), dtype=np.float32)
                vertices[..., 0] = grid_x + rng.normal(
                    0.0, 0.01, size=(rows, cols)).astype(np.float32)
                vertices[..., 1] = grid_y + rng.normal(
                    0.0, 0.01, size=(rows, cols)).astype(np.float32)
                vertices[..., 2] = rng.normal(
                    0.0, height_scale, size=(rows, cols)).astype(np.float32)
                flat_vertices = vertices.reshape(-1, 3)
                indices = heightfield_module._grid_indices(rows, cols)

                expected = _area_weighted_normals_add_at(flat_vertices, indices)
                actual = heightfield_module._area_weighted_normals(
                    flat_vertices, indices)

                self.assertEqual(actual.dtype, np.float32)
                self.assertEqual(actual.shape, expected.shape)
                self.assertEqual(actual.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
