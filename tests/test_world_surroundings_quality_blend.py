"""Numerical regressions for independent three-layer height blending."""

from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from quality_blend import blend_weights


class QualityBlendTests(unittest.TestCase):
    def test_strength_zero_returns_normalized_authored_weights_and_soil_fallback(self):
        painted_weights = np.array([
            [2.0, 3.0, 5.0],
            [0.0, 0.0, 0.0],
            [1.0e308, 1.0e308, 0.0],
        ], dtype=np.float64)
        heights = np.array([
            [1.0, 0.0, 0.5],
            [0.0, 1.0, 1.0],
            [0.2, 0.8, 0.4],
        ], dtype=np.float64)
        original = painted_weights.copy()
        expected = np.array([
            [0.2, 0.3, 0.5],
            [1.0, 0.0, 0.0],
            [0.5, 0.5, 0.0],
        ], dtype=np.float64)

        for method in ("depth", "power"):
            with self.subTest(method=method):
                result = blend_weights(painted_weights, heights, method=method,
                                       strength=0.0)
                self.assertEqual(result.dtype, np.float64)
                np.testing.assert_array_equal(result, expected)
        np.testing.assert_array_equal(painted_weights, original)

    def test_depth_matches_three_layer_positive_residual(self):
        weights = np.array([0.2, 0.5, 0.3], dtype=np.float64)
        heights = np.array([0.15, 0.65, 0.3], dtype=np.float64)
        width = 0.2

        scores = weights + heights
        residual = np.maximum(scores - np.max(scores) + width, 0.0) * weights
        expected = residual / residual.sum()
        result = blend_weights(weights, heights, method="depth", width=width)

        np.testing.assert_allclose(result, expected, rtol=0.0, atol=1e-15)
        self.assertAlmostEqual(float(result.sum()), 1.0)

    def test_power_matches_log_score_and_prefers_the_higher_material_height(self):
        weights = np.array([0.45, 0.4, 0.15], dtype=np.float64)
        heights = np.array([0.1, 0.9, 0.4], dtype=np.float64)
        sharpness = 8.0

        log_scores = sharpness * np.log(weights + heights) + np.log(weights)
        shifted = np.exp(log_scores - np.max(log_scores))
        expected = shifted / shifted.sum()
        result = blend_weights(weights, heights, method="power",
                               sharpness=sharpness)

        np.testing.assert_allclose(result, expected, rtol=0.0, atol=1e-15)
        self.assertGreater(result[1], weights[1])

    def test_equal_depth_heights_still_sharpen_the_largest_authored_weight(self):
        weights = np.array([0.6, 0.3, 0.1], dtype=np.float64)
        heights = np.full(3, 0.4, dtype=np.float64)

        result = blend_weights(weights, heights, method="depth", width=0.2)

        # With equal heights, score = height + p; the 0.3 score gap exceeds
        # width, so the positive-residual candidate is one-hot.
        np.testing.assert_array_equal(result, np.array([1.0, 0.0, 0.0]))
        self.assertFalse(np.array_equal(result, weights))

    def test_zero_weight_layers_remain_absent_and_pure_layers_do_not_bleed(self):
        pure = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 7.0, 0.0],
            [0.0, 0.0, 4.0],
        ], dtype=np.float64)
        heights = np.array([
            [0.0, 1.0, 1.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
        ], dtype=np.float64)
        mixed_without_soil = np.array([0.0, 0.8, 0.2], dtype=np.float64)
        high_zero_layer = np.array([1.0, 0.4, 0.2], dtype=np.float64)

        for method in ("depth", "power"):
            with self.subTest(method=method):
                result = blend_weights(pure, heights, method=method)
                np.testing.assert_array_equal(result, np.eye(3))
                mixed = blend_weights(mixed_without_soil, high_zero_layer,
                                      method=method)
                self.assertEqual(float(mixed[0]), 0.0)
                self.assertAlmostEqual(float(mixed.sum()), 1.0)
                empty = blend_weights(np.zeros(3), np.array([0.0, 1.0, 1.0]),
                                      method=method)
                np.testing.assert_array_equal(empty, np.array([1.0, 0.0, 0.0]))

    def test_depth_is_continuous_at_a_residual_cutoff(self):
        width = 0.2
        epsilon = 1.0e-7
        height = np.full(3, 0.35, dtype=np.float64)

        def candidate(score_gap):
            weights = np.array([(1.0 + score_gap) / 2.0,
                                (1.0 - score_gap) / 2.0, 0.0])
            return blend_weights(weights, height, method="depth", width=width)

        below = candidate(width - epsilon)
        at = candidate(width)
        above = candidate(width + epsilon)
        self.assertLess(np.max(np.abs(below - at)), 3.0e-6)
        self.assertLess(np.max(np.abs(above - at)), 1.0e-12)

    def test_both_methods_are_permutation_equivariant_for_nonzero_triples(self):
        rng = np.random.default_rng(20261019)
        weights = rng.uniform(0.01, 1.0, size=(4, 5, 3))
        heights = rng.uniform(0.0, 1.0, size=(4, 5, 3))
        near_zero_weights = np.array([0.4999995, 0.4999995, 1.0e-6])
        near_zero_heights = np.array([0.0, 0.0, 1.0])
        permutations = ((2, 0, 1), (1, 2, 0))

        for method in ("depth", "power"):
            with self.subTest(method=method):
                for case_weights, case_heights in (
                        (weights, heights),
                        (near_zero_weights, near_zero_heights)):
                    result = blend_weights(case_weights, case_heights,
                                           method=method)
                    for permutation in permutations:
                        permuted = blend_weights(case_weights[..., permutation],
                                                  case_heights[..., permutation],
                                                  method=method)
                        np.testing.assert_allclose(
                            permuted, result[..., permutation],
                            rtol=0.0, atol=2e-15)

    def test_depth_near_zero_high_height_layer_cannot_take_over(self):
        weights = np.array([0.4999995, 0.4999995, 1.0e-6])
        heights = np.array([0.0, 0.0, 1.0])
        strength = 0.75
        authored = weights / weights.sum()

        result = blend_weights(weights, heights, method="depth",
                               strength=strength, width=0.35)
        expected = np.array([
            0.25 * authored[0] + 0.75 * 0.5,
            0.25 * authored[1] + 0.75 * 0.5,
            0.25 * authored[2],
        ])

        np.testing.assert_allclose(result, expected, rtol=0.0, atol=2e-15)
        self.assertLess(float(result[2]), 1.0e-6)

    def test_depth_high_height_layer_varies_continuously_as_its_weight_approaches_zero(self):
        heights = np.array([0.0, 0.0, 1.0])
        strength = 0.75
        weights_to_check = (1.0e-12, 1.0e-10, 1.0e-8, 1.0e-6, 1.0e-4)
        zero_result = blend_weights(np.array([0.5, 0.5, 0.0]), heights,
                                    method="depth", strength=strength,
                                    width=0.35)
        results = []

        for tiny_weight in weights_to_check:
            weights = np.array([(1.0 - tiny_weight) * 0.5,
                                (1.0 - tiny_weight) * 0.5,
                                tiny_weight])
            result = blend_weights(weights, heights, method="depth",
                                   strength=strength, width=0.35)
            expected_third = (1.0 - strength) * tiny_weight
            self.assertAlmostEqual(float(result[2]), expected_third, delta=2e-15)
            self.assertLess(np.max(np.abs(result - zero_result)), 3.0e-5)
            results.append(result)

        for earlier, later in zip(results, results[1:]):
            self.assertLess(np.max(np.abs(later - earlier)), 3.0e-5)

    def test_broadcast_heights_and_blending_leave_painted_weights_unchanged(self):
        painted_weights = np.array([
            [0.7, 0.2, 0.1],
            [0.15, 0.55, 0.3],
        ], dtype=np.float64)
        original = painted_weights.copy()
        layer_heights = np.array([0.1, 0.8, 0.4], dtype=np.float64)

        for method in ("depth", "power"):
            with self.subTest(method=method):
                result = blend_weights(painted_weights, layer_heights,
                                       method=method, strength=0.5)
                self.assertEqual(result.shape, painted_weights.shape)
                self.assertTrue(np.all(np.isfinite(result)))
                np.testing.assert_allclose(result.sum(axis=-1), 1.0,
                                           rtol=0.0, atol=2e-15)
                self.assertTrue(np.all(result >= 0.0))
        np.testing.assert_array_equal(painted_weights, original)

    def test_strength_is_a_linear_mix_of_authored_and_candidate_weights(self):
        painted_weights = np.array([0.45, 0.4, 0.15], dtype=np.float64)
        heights = np.array([0.1, 0.9, 0.4], dtype=np.float64)
        strength = 0.35

        for method in ("depth", "power"):
            with self.subTest(method=method):
                authored = blend_weights(painted_weights, heights, method=method,
                                         strength=0.0)
                candidate = blend_weights(painted_weights, heights, method=method,
                                          strength=1.0)
                actual = blend_weights(painted_weights, heights, method=method,
                                       strength=strength)
                expected = authored * (1.0 - strength) + candidate * strength
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-15)

    def test_both_methods_are_continuous_as_a_layer_weight_approaches_zero(self):
        heights = np.array([0.9, 0.4, 0.1], dtype=np.float64)
        zero_weight = np.array([0.0, 0.6, 0.4], dtype=np.float64)
        tiny_weight = np.array([1.0e-9, 0.6, 0.4], dtype=np.float64)

        for method in ("depth", "power"):
            with self.subTest(method=method):
                at_zero = blend_weights(zero_weight, heights, method=method)
                near_zero = blend_weights(tiny_weight, heights, method=method)
                self.assertLess(np.max(np.abs(at_zero - near_zero)), 2.0e-8)

    def test_extreme_finite_values_stay_finite_and_normalized(self):
        smallest = np.nextafter(np.float64(0.0), np.float64(1.0))
        largest = np.finfo(np.float64).max
        weights = np.array([
            [largest, largest / 2.0, smallest],
            [smallest, 2.0 * smallest, smallest],
            [0.0, 0.8, 0.2],
        ], dtype=np.float64)
        heights = np.array([
            [0.0, 1.0, 0.5],
            [1.0, 0.0, 0.5],
            [1.0, 0.0, 0.0],
        ], dtype=np.float64)

        for method in ("depth", "power"):
            with self.subTest(method=method):
                result = blend_weights(weights, heights, method=method,
                                       sharpness=1.0e308)
                self.assertTrue(np.all(np.isfinite(result)))
                self.assertTrue(np.all(result >= 0.0))
                np.testing.assert_allclose(result.sum(axis=-1), 1.0,
                                           rtol=0.0, atol=2e-15)

    def test_subnormal_depth_width_does_not_activate_zero_weight_layers(self):
        smallest = np.nextafter(np.float64(0.0), np.float64(1.0))
        weights = np.array([0.0, 0.8, 0.2], dtype=np.float64)
        heights = np.array([1.0, 0.0, 0.0], dtype=np.float64)

        result = blend_weights(weights, heights, method="depth", width=smallest)

        self.assertTrue(np.all(np.isfinite(result)))
        self.assertEqual(float(result[0]), 0.0)
        np.testing.assert_array_equal(result, np.array([0.0, 1.0, 0.0]))

    def test_large_finite_depth_width_stays_stable(self):
        weights = np.array([0.2, 0.3, 0.5], dtype=np.float64)
        heights = np.array([0.0, 1.0, 0.25], dtype=np.float64)

        result = blend_weights(weights, heights, method="depth",
                               width=np.finfo(np.float64).max)

        self.assertTrue(np.all(np.isfinite(result)))
        np.testing.assert_allclose(result, weights, rtol=0.0, atol=2e-16)

    def test_invalid_scalar_parameters_are_rejected(self):
        weights = np.array([0.2, 0.3, 0.5])
        heights = np.array([0.2, 0.3, 0.5])
        invalid = (
            ({"strength": True},),
            ({"strength": -0.01},),
            ({"strength": 1.01},),
            ({"strength": np.nan},),
            ({"strength": np.inf},),
            ({"width": False},),
            ({"width": 0.0},),
            ({"width": -0.01},),
            ({"width": np.inf},),
            ({"sharpness": np.bool_(True)},),
            ({"sharpness": -0.01},),
            ({"sharpness": np.nan},),
            ({"sharpness": np.inf},),
            ({"method": "pairwise"},),
            ({"method": True},),
        )
        for (kwargs,) in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    blend_weights(weights, heights, **kwargs)

    def test_invalid_weight_and_height_inputs_are_rejected(self):
        valid = np.array([0.2, 0.3, 0.5])
        invalid_inputs = (
            (np.array([True, False, True]), np.array([0.0, 0.5, 1.0])),
            (np.array([0.2, -0.1, 0.9]), np.array([0.0, 0.5, 1.0])),
            (np.array([0.2, np.nan, 0.8]), np.array([0.0, 0.5, 1.0])),
            (np.array([0.2, 0.3, 0.5]), np.array([0.0, 0.5, np.inf])),
            (valid, np.array([-0.01, 0.5, 1.0])),
            (valid, np.array([0.0, 0.5, 1.01])),
            (np.ones((2, 2)), np.ones((2, 2))),
            (np.ones((2, 3)), np.ones((4, 3))),
        )
        for weights, heights in invalid_inputs:
            with self.subTest(weights=weights, heights=heights):
                with self.assertRaises(ValueError):
                    blend_weights(weights, heights)


if __name__ == "__main__":
    unittest.main()
