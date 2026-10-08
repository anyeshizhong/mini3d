"""Acceptance geometry using local assets; missing optional assets skip cleanly."""
from pathlib import Path
import unittest

import numpy as np

from mini3d.camera import Camera
from mini3d.gltf_loader import AssetCache
from mini3d.picking import pick_entity
from mini3d.placement import (SurfaceHit, compute_placement, create_ground,
                             geometry_bounds, raycast_surface)
from mini3d.scene import Scene, rotation_xyz


PROJECT = Path(__file__).resolve().parents[1]
ASSETS = {'roman': '05_roman_soldier/roman_legionnaire.glb',
          'table': '03_side_table/side_table.glb',
          'box': '01_box/Box.glb', 'bottle': '02_water_bottle/WaterBottle.glb'}
RECT = (0, 0, 800, 600)
CENTER = (400, 300)


class ExistingAssetPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = AssetCache()

    def asset(self, name):
        path = PROJECT / 'model' / ASSETS[name]
        if not path.exists():
            self.skipTest('Optional local asset unavailable: ' + str(path))
        return self.cache.load(path).instantiate()

    def scene(self):
        scene = Scene()
        return scene

    def assert_anchored(self, entity, hit):
        position, rotation = compute_placement(entity, hit)
        minimum, maximum = geometry_bounds(entity, position, rotation)
        self.assertAlmostEqual(minimum[2], hit.position[2], places=7)
        np.testing.assert_allclose((minimum[:2] + maximum[:2]) / 2, hit.position[:2], atol=1e-7)
        return position, rotation

    def test_roman_feet_ground_then_rotated_upright_on_real_table(self):
        scene = self.scene()
        camera = Camera(position=(0, 0, 50), far=1000)
        roman = self.asset('roman')
        roman.placement_type = 'character'
        ground_hit = raycast_surface(scene, camera, CENTER, RECT)
        self.assertIsNone(ground_hit.entity)
        roman.pos, roman.rot = self.assert_anchored(roman, ground_hit)
        scene.add(roman)
        # Native assets use different units; enlarge the existing table for a
        # useful support surface without modifying either imported mesh.
        table = self.asset('table')
        table.scale[:] = 50
        table.pos, table.rot = compute_placement(table, SurfaceHit([0, 0, 0], [0, 0, 1]))
        table.locked = True
        scene.add(table)
        table_hit = raycast_surface(scene, camera, CENTER, RECT, exclude=roman)
        self.assertIs(table_hit.entity, table)
        self.assertGreater(table_hit.position[2], 37)
        roman.rot[:] = [.2, -.5, 1.1]
        roman.pos, roman.rot = self.assert_anchored(roman, table_hit)
        np.testing.assert_allclose(rotation_xyz(roman.rot)[:, 2], [0, 0, 1], atol=1e-12)
        self.assertAlmostEqual(roman.rot[2], 1.1)
        scene.root_entities.remove(roman)
        self.assertEqual(pick_entity(scene, camera, CENTER, RECT), (None, None))
        self.assertIs(raycast_surface(scene, camera, CENTER, RECT).entity, table)

    def test_box_and_bottle_ground_and_real_table_surface(self):
        scene = self.scene()
        camera = Camera(position=(0, 0, 5))
        ground_hit = raycast_surface(scene, camera, CENTER, RECT)
        table = self.asset('table')
        table.pos, table.rot = compute_placement(table, ground_hit)
        scene.add(table)
        table_hit = raycast_surface(scene, camera, CENTER, RECT)
        self.assertIs(table_hit.entity, table)
        self.assertGreater(table_hit.position[2], .75)
        for name in ('box', 'bottle'):
            with self.subTest(asset=name):
                root = self.asset(name)
                root.rot[2] = .67
                root.scale[:] = [.7, 1.1, 1.3]
                self.assert_anchored(root, ground_hit)
                self.assert_anchored(root, table_hit)


if __name__ == '__main__':
    unittest.main()
