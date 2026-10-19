"""CPU regressions for replayable World Surroundings material paint."""
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from paint import HistoryBudgetExceeded, PaintSession


def uniform_weights(rows, cols, values=(0.2, 0.3, 0.5)):
    result = np.empty((rows, cols, 3), dtype=np.float32)
    result[...] = values
    return result


class PaintTests(unittest.TestCase):
    def test_default_grid_is_immutable_float32_and_includes_world_endpoints(self):
        session = PaintSession(rows=3, cols=5, origin=(-1, -2), size=(4, 6))

        self.assertEqual(session.weights.shape, (3, 5, 3))
        self.assertEqual(session.weights.dtype, np.float32)
        self.assertTrue(np.all(session.weights[..., 0] == 1.0))
        self.assertTrue(np.all(session.weights[..., 1:] == 0.0))
        self.assertTrue(np.allclose(session.weights.sum(axis=2), 1.0))
        self.assertFalse(session.weights.flags.writeable)
        self.assertEqual((session.x_axis[0], session.x_axis[-1]), (-1.0, 3.0))
        self.assertEqual((session.y_axis[0], session.y_axis[-1]), (-2.0, 4.0))
        with self.assertRaises(ValueError):
            session.weights[0, 0, 0] = 0.0
        with self.assertRaises(ValueError):
            session.weights.setflags(write=True)

    def test_paint_uses_smoothstep_time_alpha_and_proportional_reduction(self):
        session = PaintSession(rows=5, cols=5, origin=(0, 0), size=(4, 4),
                               weights=uniform_weights(5, 5))
        session.begin_stroke("rock", radius=2.0, strength=2.0)
        dirty = session.dab(2.0, 2.0, amount=0.5)

        self.assertEqual(dirty, (1, 1, 4, 4))
        center_alpha = 1.0 - np.exp(-1.0)
        center = session.weights[2, 2]
        self.assertAlmostEqual(float(center[1]), 0.3 + center_alpha * 0.7,
                               places=6)
        self.assertAlmostEqual(float(center[0]), 0.2 * (1.0 - center_alpha),
                               places=6)
        self.assertAlmostEqual(float(center[2]), 0.5 * (1.0 - center_alpha),
                               places=6)

        # At distance one with radius two, smoothstep falloff is exactly 0.5.
        alpha = 1.0 - np.exp(-2.0 * 0.5 * 0.5)
        adjacent = session.weights[2, 3]
        self.assertAlmostEqual(float(adjacent[1]), 0.3 + alpha * 0.7,
                               places=6)
        self.assertTrue(np.allclose(session.weights.sum(axis=2), 1.0,
                                    atol=1.0e-7, rtol=0.0))
        patch = session.end_stroke()
        self.assertEqual(patch.dirty_rect, dirty)

    def test_paint_and_erase_are_invariant_to_time_partitioning(self):
        source = uniform_weights(7, 7)
        for erase in (False, True):
            with self.subTest(erase=erase):
                whole = PaintSession(rows=7, cols=7, origin=(0, 0),
                                     size=(6, 6), weights=source)
                split = PaintSession(rows=7, cols=7, origin=(0, 0),
                                     size=(6, 6), weights=source)
                whole.begin_stroke("grass", radius=2.25, strength=1.7,
                                   erase=erase)
                split.begin_stroke("grass", radius=2.25, strength=1.7,
                                   erase=erase)
                whole.dab(3.0, 3.0, amount=1.0)
                for _ in range(8):
                    split.dab(3.0, 3.0, amount=0.125)
                whole.end_stroke()
                split.end_stroke()
                self.assertTrue(np.allclose(whole.weights, split.weights,
                                            rtol=0.0, atol=2.0e-7))

    def test_boundary_dabs_work_and_outside_centers_do_not_modify(self):
        session = PaintSession(rows=3, cols=3, origin=(0, 0), size=(2, 2))
        initial = session.weights
        session.begin_stroke("rock", radius=0.1, strength=1.0)
        self.assertIsNone(session.dab(-0.01, 0.0, amount=1.0))
        self.assertIsNone(session.dab(2.01, 0.0, amount=1.0))
        self.assertIs(session.weights, initial)
        self.assertEqual(session.revision, 0)
        self.assertIsNone(session.end_stroke())

        session.begin_stroke("grass", radius=0.1, strength=1.0)
        self.assertEqual(session.dab(0.0, 0.0, amount=1.0), (0, 0, 1, 1))
        self.assertGreater(session.weights[0, 0, 2], 0.0)
        self.assertTrue(np.all(session.weights[1:, :, :] == initial[1:, :, :]))
        self.assertTrue(np.all(session.weights[:, 1:, :] == initial[:, 1:, :]))

    def test_erase_redistributes_by_existing_ratios_and_uses_empty_fallback(self):
        source = uniform_weights(3, 3)
        source[1, 1] = (0.0, 0.0, 1.0)
        fallback = PaintSession(rows=3, cols=3, origin=(0, 0), size=(2, 2),
                                weights=source)
        fallback.begin_stroke("grass", radius=0.1, strength=1000.0,
                              erase=True)
        fallback.dab(1.0, 1.0, amount=1.0)
        np.testing.assert_array_equal(fallback.weights[1, 1],
                                      np.array((0.5, 0.5, 0.0), dtype=np.float32))
        fallback.cancel_stroke()

        source[1, 1] = (0.6, 0.1, 0.3)
        proportional = PaintSession(rows=3, cols=3, origin=(0, 0),
                                    size=(2, 2), weights=source)
        proportional.begin_stroke("soil", radius=0.1, strength=1000.0,
                                  erase=True)
        proportional.dab(1.0, 1.0, amount=1.0)
        np.testing.assert_allclose(proportional.weights[1, 1],
                                   np.array((0.0, 0.25, 0.75), dtype=np.float32),
                                   atol=1.0e-7, rtol=0.0)

    def test_cancel_commit_undo_and_redo_restore_exact_weights(self):
        session = PaintSession(rows=7, cols=7, origin=(0, 0), size=(6, 6))
        initial = session.weights.copy()

        session.begin_stroke("rock", radius=1.1, strength=0.75)
        first_dirty = session.dab(3.0, 3.0, amount=0.5)
        preview = session.weights.copy()
        preview_revision = session.current_revision
        self.assertEqual(session.cancel_stroke(), first_dirty)
        np.testing.assert_array_equal(session.weights, initial)
        self.assertEqual(session.revision, preview_revision + 1)
        self.assertFalse(session.active)

        session.begin_stroke(1, radius=1.1, strength=0.75)
        dirty = session.dab(3.0, 3.0, amount=0.5)
        patch = session.end_stroke()
        committed = session.weights.copy()
        self.assertEqual(patch.mode, "paint")
        self.assertEqual(patch.layer, 1)
        self.assertEqual(patch.layer_name, "rock")
        self.assertEqual(patch.dirty_rect, dirty)
        self.assertEqual(patch.before.shape, (dirty[2] - dirty[0],
                                              dirty[3] - dirty[1], 3))
        self.assertEqual(patch.byte_size, patch.before.size * 2 * 4)
        self.assertFalse(patch.before.flags.writeable)
        with self.assertRaises(ValueError):
            patch.after[0, 0, 0] = 0.0

        committed_revision = session.revision
        self.assertEqual(session.undo(), patch.dirty_rect)
        np.testing.assert_array_equal(session.weights, initial)
        self.assertEqual(session.revision, committed_revision + 1)
        self.assertEqual(session.redo(), patch.dirty_rect)
        np.testing.assert_array_equal(session.weights, committed)
        self.assertEqual(session.revision, committed_revision + 2)
        self.assertEqual(session.history_bytes, patch.byte_size)

    def test_noop_strokes_do_not_create_history_or_clear_redo(self):
        session = PaintSession(rows=3, cols=3, origin=(0, 0), size=(2, 2),
                               history_budget_bytes=0)
        session.begin_stroke("rock", radius=0.1, strength=1.0)
        self.assertIsNone(session.dab(1.0, 1.0, amount=0.0))
        self.assertIsNone(session.dab(-1.0, -1.0, amount=1.0))
        self.assertIsNone(session.end_stroke())
        self.assertEqual(session.history_bytes, 0)
        self.assertEqual(session.undo_count, 0)
        self.assertEqual(session.revision, 0)

        session = PaintSession(rows=3, cols=3, origin=(0, 0), size=(2, 2))
        session.begin_stroke("rock", radius=0.1, strength=1.0)
        session.dab(1.0, 1.0, amount=1.0)
        session.end_stroke()
        session.undo()
        self.assertEqual(session.redo_count, 1)

        session.begin_stroke("grass", radius=1.0, strength=1.0)
        self.assertIsNone(session.dab(-1.0, -1.0, amount=1.0))
        self.assertIsNone(session.end_stroke())
        self.assertEqual(session.redo_count, 1)
        self.assertIsNotNone(session.redo())

    def test_over_budget_commit_rolls_back_and_preserves_existing_redo(self):
        session = PaintSession(rows=5, cols=5, origin=(0, 0), size=(4, 4),
                               history_budget_bytes=24)
        session.begin_stroke("rock", radius=0.1, strength=1.0)
        session.dab(2.0, 2.0, amount=1.0)
        first_patch = session.end_stroke()
        self.assertEqual(first_patch.byte_size, 24)
        after_first = session.weights.copy()
        session.undo()
        self.assertEqual(session.redo_count, 1)
        revision_before_rejected = session.revision

        session.begin_stroke("grass", radius=1.1, strength=1.0)
        session.dab(0.0, 0.0, amount=1.0)
        with self.assertRaises(HistoryBudgetExceeded) as raised:
            session.end_stroke()

        self.assertEqual(raised.exception.required_bytes, 96)
        self.assertEqual(raised.exception.patch_bytes, 96)
        self.assertEqual(raised.exception.budget_bytes, 24)
        self.assertEqual(raised.exception.dirty_rect, (0, 0, 2, 2))
        np.testing.assert_array_equal(session.weights, np.zeros_like(after_first) +
                                      np.array((1.0, 0.0, 0.0), dtype=np.float32))
        self.assertEqual(session.revision, revision_before_rejected + 2)
        self.assertFalse(session.active)
        self.assertEqual(session.undo_count, 0)
        self.assertEqual(session.redo_count, 1)
        self.assertEqual(session.history_bytes, first_patch.byte_size)
        self.assertIsNotNone(session.redo())
        np.testing.assert_array_equal(session.weights, after_first)

    def test_invalid_constructor_stroke_and_dab_inputs_are_atomic(self):
        for values in (
                np.full((2, 2, 3), -0.1, dtype=np.float32),
                np.full((2, 2, 3), np.nan, dtype=np.float32),
                np.full((2, 2, 3), 0.5, dtype=np.float32),
                np.ones((2, 2, 2), dtype=np.float32)):
            with self.subTest(values=values.shape):
                with self.assertRaises(ValueError):
                    PaintSession(rows=2, cols=2, weights=values)

        session = PaintSession(rows=3, cols=3, origin=(0, 0), size=(2, 2))
        for args, kwargs in ((('bad', 1.0, 1.0), {}),
                             ((3, 1.0, 1.0), {}),
                             ((0, 0.0, 1.0), {}),
                             ((0, 1.0, -1.0), {}),
                             ((0, 1.0, 1.0), {"erase": "true"})):
            with self.subTest(args=args, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    session.begin_stroke(*args, **kwargs)
                self.assertFalse(session.active)
                self.assertEqual(session.revision, 0)

        session.begin_stroke("rock", radius=1.1, strength=0.75)
        session.dab(1.0, 1.0, amount=0.5)
        preview = session.weights.copy()
        revision = session.revision
        for args in ((np.nan, 1.0, 1.0), (1.0, np.inf, 1.0),
                     (1.0, 1.0, -0.1), (1.0, 1.0, np.inf)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    session.dab(*args)
                np.testing.assert_array_equal(session.weights, preview)
                self.assertEqual(session.revision, revision)
                self.assertTrue(session.active)
        session.cancel_stroke()


if __name__ == "__main__":
    unittest.main()
