"""Back-face-culled sight lines through the actual procedural street geometry."""
import math
import tempfile
from pathlib import Path
import unittest

import numpy as np

from mini3d.api import Mini3DAPI
from mini3d.roman_assets import create_roman_asset


def triangles(root):
    result = []
    if root.model is not None:
        result.append(np.asarray(root.model.vertices, dtype=float)[:, :3][np.asarray(root.model.indices).reshape(-1, 3)])
    for child in root.children:
        result.extend(triangles(child))
    return result


def ray_hit(geometry, origin, direction):
    """Moller-Trumbore with the same outward-face culling as the renderer."""
    origin, direction = np.asarray(origin), np.asarray(direction)
    a, b, c = geometry.transpose(1, 0, 2)
    edge1, edge2 = b - a, c - a
    cross = np.cross(direction, edge2)
    determinant = np.einsum('ij,ij->i', edge1, cross)
    valid = determinant > 1e-9
    inverse = np.divide(1., determinant, out=np.zeros_like(determinant), where=valid)
    delta = origin - a
    u = np.einsum('ij,ij->i', delta, cross) * inverse
    q = np.cross(delta, edge1)
    v = (q @ direction) * inverse
    distance = np.einsum('ij,ij->i', edge2, q) * inverse
    return bool(np.any(valid & (u >= -1e-7) & (v >= -1e-7)
                       & (u + v <= 1. + 1e-7) & (distance > 1e-7)))


class RomanMasonryIntegrityTests(unittest.TestCase):
    def test_building_underside_has_one_red_surface_without_coplanar_overlap(self):
        for name in ('shop', 'shop-ochre', 'shop-rose', 'house', 'house-ochre', 'house-rose'):
            root = create_roman_asset('builtin:roman-' + name)
            caps = []
            for part in root.children:
                mesh = part.model
                indices = np.asarray(mesh.indices).reshape(-1, 3)
                points = np.asarray(mesh.vertices)[:, :3][indices]
                bottom = np.all(np.abs(points[:, :, 2]) < 1e-8, axis=1)
                if not bottom.any():
                    continue
                self.assertEqual(part.name, 'Terracotta', name)
                np.testing.assert_allclose(mesh.vertex_colors[indices[bottom], :3], .83)
                caps.extend(points[bottom])
            caps = np.asarray(caps)
            normals = np.cross(caps[:, 1] - caps[:, 0], caps[:, 2] - caps[:, 0])
            self.assertTrue(np.all(normals[:, 2] < 0), name)
            step_width = (1.08 if name.startswith('house') else 2.56) + .26
            # Area includes only the base and the exposed 6 cm door lip.
            self.assertAlmostEqual(float(-normals[:, 2].sum() / 2),
                                   3.94 * 4.88 + step_width * .06, places=5)
            xy = [(x, y) for x in np.linspace(-1.91, 1.89, 11)
                  for y in np.linspace(-2.39, 2.37, 13)]
            xy += [(x, y) for x in np.linspace(-.43, .39, 5) * step_width
                   for y in (-2.489, -2.471, -2.453)]
            for point in xy:
                hits = 0
                for triangle in caps[:, :, :2]:
                    a, b, c = triangle
                    u, v = np.linalg.solve(np.column_stack((b-a, c-a)), np.asarray(point)-a)
                    hits += int(u >= 0 and v >= 0 and u + v <= 1)
                self.assertEqual(hits, 1, (name, point))

    def test_arch_spandrels_block_side_views_with_culling(self):
        geometry = np.concatenate(triangles(create_roman_asset('builtin:roman-arch')))
        # Above the arch crown and below the cap: a wall, not a designed opening.
        for side in (-1, 1):
            for y in (-.55, 0., .55):
                with self.subTest(side=side, y=y):
                    self.assertTrue(ray_hit(geometry, (10. * side, y, 6.75), (-side, 0., 0.)))

    def test_arch_ring_to_spandrel_seam_blocks_front_and_back_views(self):
        geometry = np.concatenate(triangles(create_roman_asset('builtin:roman-arch')))
        # A dense sweep just inside the intended outer ring catches mismatched
        # polygonal circle approximations; checking only radial joints misses it.
        for angle in np.linspace(.02, math.pi - .02, 181):
            x, z = 3.674 * math.cos(angle), 3. + 3.674 * math.sin(angle)
            for side in (-1, 1):
                with self.subTest(angle=float(angle), side=side):
                    self.assertTrue(ray_hit(geometry, (x, 10. * side, z), (0., -side, 0.)))

    def test_open_arch_remains_open_from_multiple_directions(self):
        geometry = np.concatenate(triangles(create_roman_asset('builtin:roman-arch')))
        for origin, direction in [((0., -10., 4.), (0., 1., 0.)),
                                  ((0., 10., 4.), (0., -1., 0.)),
                                  ((-1., -10., 4.), (.1, 1., 0.)),
                                  ((1., 10., 4.), (-.1, -1., 0.))]:
            self.assertFalse(ray_hit(geometry, origin, direction))

    def test_building_shells_and_paving_are_opaque_from_oblique_views(self):
        for name in ('shop', 'shop-ochre', 'shop-rose', 'house', 'house-ochre', 'house-rose'):
            root = create_roman_asset('builtin:roman-' + name)
            geometry = np.concatenate(triangles(root))
            height = 5.8 if name.startswith('house') else 3.6
            targets = [(0., 0., height / 2), (0., 0., height + .5)]
            for target in targets:
                for origin in [(0., -10., 1.), (0., 10., 8.), (-10., 0., 1.),
                               (10., 0., 8.), (0., 0., 15.), (8., -8., 10.)]:
                    with self.subTest(asset=name, origin=origin, target=target):
                        self.assertTrue(ray_hit(geometry, origin, np.asarray(target) - origin))
        for name in ('road', 'sidewalk'):
            geometry = np.concatenate(triangles(create_roman_asset('builtin:roman-' + name)))
            for x in (-.5, 0., .5):
                for y in (-1.2, -.4, .4, 1.2):
                    self.assertTrue(ray_hit(geometry, (x, y, 10.), (0., 0., -1.)))

    def test_scene_v3_fresh_cache_rebuilds_identical_masonry(self):
        api = Mini3DAPI()
        fresh = Mini3DAPI()
        self.addCleanup(api._app.model_dialog.close)
        self.addCleanup(fresh._app.model_dialog.close)
        for name in ('arch', 'shop', 'house', 'road', 'sidewalk'):
            api.spawn('builtin:roman-' + name)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'masonry.json'
            api.save_scene(path)
            fresh.load_scene(path)
        before, after = api._app.scene.root_entities, fresh._app.scene.root_entities
        self.assertEqual(len(before), len(after))
        for first, second in zip(before, after):
            self.assertEqual(first.asset_path, second.asset_path)
            np.testing.assert_array_equal(np.concatenate(triangles(first)), np.concatenate(triangles(second)))


if __name__ == '__main__':
    unittest.main()
