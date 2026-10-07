"""STL import, hard edges and editor persistence without an OpenGL window."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
from stl import Mode, mesh

from mini3d.editor import Editor
from mini3d.gltf_loader import AssetCache
from mini3d.picking import pick_entity
from mini3d.stl_loader import load_stl


class StlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / '模型.STL'
        self.triangles = np.array([[[10, 20, 30], [12, 20, 30], [10, 23, 30]],
                                   [[10, 20, 30], [10, 20, 34], [12, 20, 30]]], np.float32)

    def tearDown(self):
        self.temporary.cleanup()

    def write_stl(self, mode=Mode.BINARY, triangles=None):
        triangles = self.triangles if triangles is None else triangles
        source = mesh.Mesh(np.zeros(len(triangles), dtype=mesh.Mesh.dtype))
        source.vectors[:] = triangles
        source.save(str(self.path), mode=mode)

    def test_ascii_and_binary_preserve_native_coordinates_and_hard_normals(self):
        for mode in (Mode.ASCII, Mode.BINARY):
            with self.subTest(mode=mode):
                self.write_stl(mode)
                root = load_stl(self.path).instantiate()
                model = root.model
                np.testing.assert_allclose(model.vertices[:, :3], self.triangles.reshape(-1, 3))
                np.testing.assert_allclose(root.extra_local, np.eye(4))
                np.testing.assert_allclose(model.vertex_normals[:3], [[0, 0, 1]] * 3)
                np.testing.assert_allclose(model.vertex_normals[3:], [[0, 1, 0]] * 3)
                self.assertIsNotNone(model.material)

    def test_cache_and_instances_share_mesh_but_not_transforms(self):
        self.write_stl()
        cache = AssetCache()
        asset = cache.load(self.path)
        self.assertIs(asset, cache.load(self.path))
        first, second = asset.instantiate(), asset.instantiate()
        self.assertIs(first.model, second.model)
        first.pos[0] = 99
        self.assertEqual(second.pos[0], 0)

    def test_import_pick_duplicate_and_save_load(self):
        self.write_stl()
        app = Editor(800, 600)
        original = app.import_asset(self.path)
        # Look directly down at the center of the first triangle.
        app.viewer.camera.position = np.array([10.5, 20.5, 40]) + original.pos
        app.viewer.camera.rotation = np.eye(3)
        app.viewer.camera.near, app.viewer.camera.far = .01, 1000
        selected, _ = pick_entity(app.scene, app.viewer.camera, (400, 300), (0, 0, 800, 600))
        self.assertIs(selected, original)
        duplicate = app.duplicate_selected()
        app.commands.set_transform(duplicate, position=[2, 3, 4])
        scene_path = Path(self.temporary.name) / 'scene.json'
        app.save_scene(scene_path)
        restored = Editor()
        restored.load_scene(scene_path)
        first, second = restored.scene.root_entities
        self.assertIs(first.model, second.model)
        np.testing.assert_allclose(second.pos, [2, 3, 4])
        self.assertEqual(first.asset_path, str(self.path.resolve()))

    def test_bad_stl_does_not_change_existing_scene_or_library(self):
        app = Editor()
        original = app.add_asset(0)
        assets_before = list(app.assets)
        for triangles in (np.zeros((0, 3, 3)), np.zeros((1, 3, 3))):
            self.write_stl(triangles=triangles)
            with self.assertRaises(ValueError):
                app.import_asset(self.path)
            self.assertEqual(app.scene.root_entities, [original])
            self.assertEqual(app.assets, assets_before)


if __name__ == '__main__':
    unittest.main()
