"""CPU-only checks for the isolated LAB-00 SPQR fixture adapter."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = ROOT / "experiments" / "world-surroundings" / "baseline_scene.py"
SPEC = importlib.util.spec_from_file_location("world_surroundings_baseline", MODULE_PATH)
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def _material_color(mesh):
    return tuple(mesh.material["pbrMetallicRoughness"]["baseColorFactor"])


class BaselineSceneTests(unittest.TestCase):
    def test_ground_is_finite_ccw_z_up_rectangle(self):
        scene = baseline.create_baseline_scene()
        ground = scene.root_entities[0]
        points = ground.model.vertices[:, :3]
        self.assertEqual(ground.name, "Finite Ground")
        self.assertTrue(np.allclose(points[:, 2], 0.0))
        self.assertEqual(tuple(np.ptp(points[:, :2], axis=0)), baseline.GROUND_SIZE)
        self.assertTrue(np.allclose(ground.model.vertex_normals, (0.0, 0.0, 1.0)))

        triangles = points[ground.model.indices]
        face_normals = np.cross(triangles[:, 1] - triangles[:, 0],
                                triangles[:, 2] - triangles[:, 0])
        self.assertTrue(np.all(face_normals[:, 2] > 0.0))

    def test_markers_are_colored_upright_closed_meshes_at_asymmetric_positions(self):
        scene = baseline.create_baseline_scene()
        markers = scene.root_entities[1:]
        self.assertEqual(len(markers), 3)
        positions = np.asarray([entity.pos[:2] for entity in markers])
        self.assertEqual(len({tuple(row) for row in positions}), 3)
        self.assertGreater(abs(np.linalg.det(np.column_stack((positions[1] - positions[0],
                                                              positions[2] - positions[0])))), 1.0)
        self.assertEqual(len({_material_color(entity.model) for entity in markers}), 3)

        for entity in markers:
            mesh = entity.model
            points = mesh.vertices[:, :3]
            self.assertAlmostEqual(float(points[:, 2].min()), 0.0)
            self.assertGreater(float(points[:, 2].max()), 0.0)
            triangles = points[mesh.indices]
            face_normals = np.cross(triangles[:, 1] - triangles[:, 0],
                                    triangles[:, 2] - triangles[:, 0])
            vertex_normals = mesh.vertex_normals[mesh.indices[:, 0]]
            self.assertTrue(np.all(np.einsum("ij,ij->i", face_normals,
                                             vertex_normals) > 0.0))
            self.assertEqual(len(np.unique(mesh.indices)), len(points))

    def test_scene_rebuild_has_same_ids_geometry_materials_and_world_transforms(self):
        first = baseline.create_baseline_scene()
        second = baseline.create_baseline_scene()
        self.assertEqual([entity.entity_id for entity in first.root_entities],
                         [entity.entity_id for entity in second.root_entities])
        for left, right in zip(first.root_entities, second.root_entities):
            self.assertEqual(left.name, right.name)
            self.assertTrue(np.array_equal(left.pos, right.pos))
            self.assertTrue(np.array_equal(left.world_matrix, right.world_matrix))
            self.assertTrue(np.array_equal(left.model.vertices, right.model.vertices))
            self.assertTrue(np.array_equal(left.model.indices, right.model.indices))
            self.assertTrue(np.array_equal(left.model.vertex_normals,
                                           right.model.vertex_normals))
            self.assertEqual(left.model.material, right.model.material)
            self.assertFalse(left.model.material.get("textures"))
        self.assertEqual(first.lighting_mode, "Scene")
        self.assertTrue(first.shadows_enabled)
        self.assertGreater(float(first.light_dir[2]), 0.0)
        from mini3d.atmosphere import atmosphere_state
        atmosphere = atmosphere_state(first)
        self.assertTrue(atmosphere["enabled"])
        self.assertFalse(atmosphere["ground"])
        self.assertEqual(atmosphere["sky_texture"], "procedural")

    def test_camera_views_are_valid_z_up_poses_and_reject_unknown_names(self):
        cameras = [baseline.camera_for_view(view) for view in baseline.VIEW_NAMES]
        for camera in cameras:
            rotation = camera.rotation
            self.assertTrue(np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8))
            self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=8)
            self.assertLess(float(camera.forward[2]), 0.0)
        self.assertEqual(len({tuple(camera.position) for camera in cameras}), 3)
        with self.assertRaises(ValueError):
            baseline.camera_for_view("unknown")

    def test_frames_file_has_repeatable_static_orbit_with_24_plus_120_frames(self):
        camera = baseline.camera_for_view("oblique")
        with tempfile.TemporaryDirectory() as temp:
            first = baseline.write_frames(Path(temp) / "first", camera)
            second = baseline.write_frames(Path(temp) / "second", camera)
            data = first.read_bytes()
            self.assertEqual(data, second.read_bytes())

        self.assertEqual(data[:8], b"SPQRF001")
        self.assertEqual(struct.unpack_from("<I", data, 8)[0], 144)
        record_size = 385
        self.assertEqual(len(data), 12 + 144 * record_size)
        records = [data[12 + index * record_size:12 + (index + 1) * record_size]
                   for index in (0, baseline.CAPTURE_FRAME_INDEX, 143)]
        self.assertEqual(records[0], records[1])
        self.assertEqual(records[1], records[2])

        route_length = struct.unpack_from("<I", records[0], 0)[0]
        self.assertEqual(records[0][4:4 + route_length], b"orbit")
        self.assertEqual(struct.unpack_from("<d", records[0], 9)[0], 0.0)

        metadata = baseline._metadata("oblique", camera, {})
        self.assertEqual(metadata["contract"]["capture_frame_indices"],
                         {"orbit-0": 24, "orbit-mid": 84})
        self.assertIn("meter", metadata["contract"]["coordinates"]["world_unit"])


if __name__ == "__main__":
    unittest.main()
