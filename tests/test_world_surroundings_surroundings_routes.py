import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "world-surroundings"))

from mini3d.camera import Camera
import surroundings_routes as routes


FLAT = lambda x, y: 0.0


class SurroundingsRouteTests(unittest.TestCase):
    def assert_camera_basis(self, camera):
        rotation = camera.rotation
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-10)
        self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=10)
        np.testing.assert_allclose(camera.forward, -rotation[:, 2], atol=1e-12)

    def test_fixed_views_cover_street_exit_aerial_nadir_telephoto_edges_and_corners(self):
        views = routes.fixed_views(FLAT)
        expected = {
            "street", "exit", "exit_return", "aerial", "nadir", "telephoto",
            "edge_west", "edge_east", "edge_north", "edge_south",
            "corner_sw", "corner_se", "corner_ne", "corner_nw",
        }
        self.assertEqual(set(views), expected)

        for camera in views.values():
            self.assert_camera_basis(camera)
            self.assertTrue(routes.in_envelope(camera, FLAT))

        self.assertGreater(float(views["street"].forward[1]), 0.0)
        self.assertLess(float(views["exit"].forward[1]), 0.0)
        self.assertGreater(float(views["exit_return"].forward[1]), 0.0)
        np.testing.assert_allclose(views["nadir"].forward, (0.0, 0.0, -1.0), atol=1e-10)

        telephoto = views["telephoto"]
        expected_fov = math.degrees(2.0 * math.atan(24.0 / 170.0))
        self.assertAlmostEqual(telephoto.fov_y, expected_fov, places=12)
        record = routes.camera_record(telephoto)
        self.assertEqual(record["name"], "telephoto")
        self.assertEqual(record["lens"]["format"], "full_frame")
        self.assertEqual(record["lens"]["sensor_width_mm"], 36.0)
        self.assertEqual(record["lens"]["sensor_height_mm"], 24.0)
        self.assertEqual(record["lens"]["focal_length_mm"], 85.0)
        self.assertEqual(record["lens"]["fit_axis"], "vertical")
        self.assertAlmostEqual(record["lens"]["projected_width_mm"], 24.0 * record["aspect"])
        to_ridge = np.asarray((0.0, 900.0, 220.0)) - telephoto.position
        to_ridge /= np.linalg.norm(to_ridge)
        np.testing.assert_allclose(telephoto.forward, to_ridge, atol=1e-12)
        json.dumps(record)

    def test_all_routes_are_deterministic_continuous_and_inside_flat_envelope(self):
        names = ("outbound", "lateral", "ascent", "orbit", "boundary", "boundary_low")
        for name in names:
            with self.subTest(route=name):
                first = routes.route_frames(name, FLAT)
                second = routes.route_frames(name, FLAT)
                self.assertEqual(len(first), 120)
                self.assertEqual(
                    [routes.camera_record(camera) for camera in first],
                    [routes.camera_record(camera) for camera in second],
                )
                positions = np.asarray([camera.position for camera in first])
                steps = np.linalg.norm(np.diff(positions, axis=0), axis=1)
                self.assertLess(float(np.max(steps)), 30.0)
                self.assertTrue(all(routes.in_envelope(camera, FLAT) for camera in first))
                for camera in first:
                    self.assert_camera_basis(camera)

        lateral = routes.route_frames("lateral", FLAT)
        lateral_x = [camera.position[0] for camera in lateral]
        self.assertLessEqual(min(lateral_x), -190.0)
        self.assertGreaterEqual(max(lateral_x), 190.0)

        outbound = routes.route_frames("outbound", FLAT)
        outbound_positions = np.asarray([camera.position for camera in outbound])
        np.testing.assert_allclose(outbound_positions[[0, -1], 0], (0.0, 0.0), atol=1e-12)
        np.testing.assert_allclose(outbound_positions[[0, -1], 1], (15.0, -190.0), atol=1e-12)
        self.assertTrue(np.all(np.diff(outbound_positions[:, 1]) < 0.0))
        self.assertTrue(all(camera.forward[1] < 0.0 for camera in outbound))

        orbit = routes.route_frames("orbit", FLAT)
        np.testing.assert_allclose(orbit[0].position, orbit[-1].position, atol=1e-10)
        np.testing.assert_allclose(orbit[0].rotation, orbit[-1].rotation, atol=1e-10)

    def test_boundary_route_visits_all_four_exact_corners_at_120m_agl(self):
        boundary = routes.route_frames("boundary", FLAT)
        xy = {tuple(np.round(camera.position[:2], 8)) for camera in boundary}
        self.assertTrue({(-200.0, -200.0), (200.0, -200.0),
                         (200.0, 200.0), (-200.0, 200.0)}.issubset(xy))
        for camera in boundary:
            self.assertAlmostEqual(camera.position[2], 120.0, places=10)
            self.assertTrue(routes.in_envelope(camera, FLAT))

    def test_nonflat_ground_is_used_for_agl_checks(self):
        plane = lambda x, y: 0.03 * x - 0.02 * y + 7.0
        cameras = routes.route_frames("ascent", plane, samples=31)
        self.assertTrue(all(routes.in_envelope(camera, plane) for camera in cameras))
        self.assertAlmostEqual(cameras[0].position[2] - plane(140.0, -180.0), 1.7)
        self.assertAlmostEqual(cameras[-1].position[2] - plane(140.0, -180.0), 120.0)

        outside = Camera(position=(201.0, 0.0, 10.0))
        outside.look_at((0.0, 0.0, 0.0))
        self.assertFalse(routes.in_envelope(outside, FLAT))
        self.assertFalse(routes.in_envelope(cameras[0], lambda x, y: float("nan")))

    def test_frames_file_matches_native_spqrf001_static_walk_contract(self):
        cameras = routes.route_frames("outbound", FLAT, samples=3)
        with tempfile.TemporaryDirectory() as temp:
            output = routes.write_route_frames(Path(temp) / "frames.bin", cameras, aspect=1.0)
            data = output.read_bytes()

        self.assertEqual(data[:8], b"SPQRF001")
        self.assertEqual(struct.unpack_from("<I", data, 8)[0], len(cameras))
        # 'walk' is the parser-supported static label: each record is 384 bytes.
        self.assertEqual(len(data), 12 + len(cameras) * 384)
        offset = 12
        for index, camera in enumerate(cameras):
            route_length = struct.unpack_from("<I", data, offset)[0]
            self.assertEqual(route_length, 4)
            self.assertEqual(data[offset + 4:offset + 8], b"walk")
            t = struct.unpack_from("<d", data, offset + 8)[0]
            self.assertAlmostEqual(t, index / (len(cameras) - 1), places=12)
            projection = np.frombuffer(data, dtype="<f8", count=16, offset=offset + 240)
            np.testing.assert_allclose(
                projection.reshape(4, 4), camera.projection_matrix(1.0), atol=1e-12
            )
            near, far = struct.unpack_from("<dd", data, offset + 368)
            self.assertEqual(near, camera.near)
            self.assertEqual(far, camera.far)
            offset += 384

    def test_invalid_nan_parameters_and_empty_frame_sets_are_rejected(self):
        with self.assertRaises(ValueError):
            routes.fixed_views(FLAT, near=float("nan"))
        with self.assertRaises(ValueError):
            routes.route_frames("outbound", FLAT, far=float("inf"))
        with self.assertRaises(ValueError):
            routes.route_frames("boundary", FLAT, samples=float("nan"))
        with self.assertRaises(ValueError):
            routes.route_frames("unknown", FLAT)
        with self.assertRaises(ValueError):
            routes.route_frames([], FLAT)
        with self.assertRaises(ValueError):
            routes.write_route_frames("unused.bin", [])

        camera = routes.fixed_views(FLAT)["street"]
        camera.near = float("nan")
        with self.assertRaises(ValueError):
            routes.camera_record(camera)
        with self.assertRaises(ValueError):
            routes.camera_record(routes.fixed_views(FLAT)["street"], aspect=0.0)


if __name__ == "__main__":
    unittest.main()
