"""Roman arch mortar geometry must close masonry joints without blocking the arch.

No OpenGL context: inspect the actual generated model and test whether an
orthographic sight line through a voussoir joint intersects its mortar backing.
"""
import math
import unittest

import numpy as np

from mini3d.roman_assets import create_roman_asset


def _front_back_triangles(mesh, y):
    points = np.asarray(mesh.vertices, dtype=float)
    triangles = points[np.asarray(mesh.indices, dtype=int)]
    triangles = triangles[np.all(np.isclose(triangles[:, :, 1], y, atol=1e-7), axis=1)]
    return triangles[:, :, [0, 2]]


def _inside_triangle(point, triangle, tolerance=1e-7):
    a, b, c = triangle
    transform = np.stack((b-a, c-a), axis=1)
    determinant = np.linalg.det(transform)
    if abs(determinant) < 1e-10:
        return False
    u, v = np.linalg.solve(transform, np.asarray(point, dtype=float)-a)
    return u >= -tolerance and v >= -tolerance and u + v <= 1 + tolerance


def _covered(triangles, point):
    return any(_inside_triangle(point, triangle) for triangle in triangles)


class RomanArchIntegrityTests(unittest.TestCase):
    def test_all_arch_joints_have_front_and_back_mortar_backing(self):
        arch = create_roman_asset('builtin:roman-arch')
        mortar = next(part.model for part in arch.children if part.name == 'Mortar')
        front = _front_back_triangles(mortar, -.63)
        back = _front_back_triangles(mortar, .63)
        self.assertGreater(len(front), 0)
        self.assertGreater(len(back), 0)
        # Every intentionally gapped radial joint must be backed, including
        # the first and last visible joints near the springing points.
        for i in range(1, 18):
            angle = i * math.pi / 18
            point = (3.44 * math.cos(angle), 3.0 + 3.44 * math.sin(angle))
            with self.subTest(joint=i):
                self.assertTrue(_covered(front, point), 'Front joint exposes background')
                self.assertTrue(_covered(back, point), 'Back joint exposes background')

    def test_real_arch_opening_stays_open(self):
        arch = create_roman_asset('builtin:roman-arch')
        mortar = next(part.model for part in arch.children if part.name == 'Mortar')
        front = _front_back_triangles(mortar, -.63)
        back = _front_back_triangles(mortar, .63)
        for point in ((0., 4.0), (0., 5.0), (0., 6.0)):
            with self.subTest(point=point):
                self.assertFalse(_covered(front, point))
                self.assertFalse(_covered(back, point))


if __name__ == '__main__':
    unittest.main()
