"""Batched early-outs against the original scalar exact-intersection oracle."""
import unittest

import numpy as np
from mini3d.scene import rotation_xyz
from mini3d.shadow_fit import _corners, _planes, _intersection, _intersections


class ShadowFitBatchTests(unittest.TestCase):
    def compare(self, bounds, worlds, planes, clip_corners):
        bounds, worlds = np.asarray(bounds, float), np.asarray(worlds, float)
        corners = np.array([_corners(b) for b in bounds])
        transformed = np.array([c @ w[:3, :3].T + w[:3, 3] for c, w in zip(corners, worlds)])
        tolerances = np.maximum(np.max(np.abs(corners), axis=(1, 2)) * 1e-9, 1e-12)
        scalar = [_intersection(b, w, planes, clip_corners) for b, w in zip(bounds, worlds)]
        batch = _intersections(bounds, worlds, corners, transformed, tolerances, planes, clip_corners)
        scalar, batch = [p for p in scalar if len(p)], [p for p in batch if len(p)]
        self.assertEqual(len(scalar), len(batch))
        for before, after in zip(scalar, batch):
            np.testing.assert_array_equal(before, after)
        return batch

    def test_random_rotated_scaled_and_mirrored_boxes_match_scalar(self):
        rng = np.random.RandomState(26)
        bounds = np.tile([[-1, -.2, -.8], [1, .2, .8]], (150, 1, 1))
        worlds = np.tile(np.eye(4), (150, 1, 1))
        for world in worlds:
            scale = rng.uniform(.1, 3, 3) * rng.choice([-1, 1], 3)
            world[:3, :3] = rotation_xyz(rng.uniform(-3, 3, 3)) @ np.diag(scale)
            world[:3, 3] = rng.uniform(-4, 4, 3)
        clip = [[-2, -1, -2], [2, 1, 2]]
        self.compare(bounds, worlds, _planes(*np.asarray(clip)), _corners(clip))

    def test_contained_rejected_touching_and_crossing_without_enclosed_corners(self):
        bounds = [[[-.1, -.1, -.1], [.1, .1, .1]], [[5, 5, 5], [6, 6, 6]],
                  [[1, 0, 0], [2, 1, 1]], [[-.2, -3, -.2], [.2, 3, .2]]]
        clip = [[-3, -.2, -.2], [3, .2, .2]]
        points = self.compare(bounds, np.tile(np.eye(4), (4, 1, 1)),
                              _planes(*np.asarray(clip)), _corners(clip))
        self.assertEqual(len(points), 3)

    def test_mutations_use_current_values_at_each_call(self):
        bounds = np.tile([[-1., -1., -1.], [1., 1., 1.]], (2, 1, 1))
        worlds = np.tile(np.eye(4), (2, 1, 1))
        clip = [[-2, -2, -2], [2, 2, 2]]
        planes, clip_corners = _planes(*np.asarray(clip)), _corners(clip)
        self.compare(bounds, worlds, planes, clip_corners)
        worlds[0, :3, 3] += [10, 0, 0]
        worlds[1, :3, :3] = rotation_xyz([.4, .1, 1.2]) @ np.diag([-2, .4, 1])
        bounds[0, 0, 0] -= 12
        self.compare(bounds, worlds, planes, clip_corners)
        planes[:, 3] += 2
        self.compare(bounds, worlds, planes, clip_corners)

    def test_degenerate_plane_preserves_fallback_signal(self):
        with self.assertRaises(ValueError):
            self.compare([[[-1]*3, [1]*3]], [np.diag([0, 0, 0, 1])],
                         _planes(np.array([-2]*3), np.array([2]*3)), _corners([[-2]*3, [2]*3]))


if __name__ == '__main__':
    unittest.main()
