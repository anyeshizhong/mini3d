"""CPU regressions for replayable World Surroundings sculpt gestures."""
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from heightfield import Heightfield
from sculpt import HistoryBudgetExceeded, SculptSession


def unit_grid(values):
    values = np.asarray(values, dtype=np.float64)
    return Heightfield(values, origin=(0.0, 0.0),
                       size=(values.shape[1] - 1, values.shape[0] - 1))


class SculptTests(unittest.TestCase):
    def test_raise_and_lower_use_seconds_weighted_by_smooth_circle_falloff(self):
        terrain = Heightfield.flat(rows=5, cols=5, origin=(0.0, 0.0),
                                   size=(4.0, 4.0))
        session = SculptSession(terrain)
        session.begin_stroke("raise", radius=2.0, strength=2.0)
        changed = session.dab(2.0, 2.0, amount=0.5)

        self.assertEqual(changed, (1, 1, 4, 4))
        self.assertAlmostEqual(session.terrain.heights[2, 2], 1.0)
        self.assertAlmostEqual(session.terrain.heights[2, 3], 0.5)
        self.assertEqual(session.terrain.heights[2, 4], 0.0)
        patch = session.end_stroke()
        self.assertEqual(patch.mode, "raise")
        self.assertEqual(patch.dirty_rect, (1, 1, 4, 4))
        self.assertEqual(patch.before.shape, (3, 3))
        self.assertEqual(patch.byte_size, 3 * 3 * 2 * 8)
        self.assertEqual(session.undo_count, 1)

        session.begin_stroke("lower", radius=2.0, strength=2.0)
        session.dab(2.0, 2.0, amount=0.5)
        self.assertAlmostEqual(session.terrain.heights[2, 2], 0.0)
        lower_patch = session.end_stroke()
        self.assertEqual(lower_patch.mode, "lower")
        self.assertEqual(session.undo_count, 2)

    def test_raise_lower_flatten_and_smooth_are_time_partition_invariant(self):
        source = np.arange(49, dtype=np.float64).reshape(7, 7) / 7.0
        for mode in ("raise", "lower", "flatten", "smooth"):
            with self.subTest(mode=mode):
                kwargs = {"target_height": 2.75} if mode == "flatten" else {}
                whole = SculptSession(unit_grid(source))
                split = SculptSession(unit_grid(source))
                whole.begin_stroke(mode, radius=2.25, strength=1.7, **kwargs)
                split.begin_stroke(mode, radius=2.25, strength=1.7, **kwargs)
                whole.dab(3.0, 3.0, amount=1.0)
                for _ in range(8):
                    split.dab(3.0, 3.0, amount=0.125)
                whole.end_stroke()
                split.end_stroke()
                self.assertTrue(np.allclose(whole.terrain.heights,
                                            split.terrain.heights,
                                            rtol=0.0, atol=1e-12))

    def test_smooth_uses_clamped_three_by_three_stroke_start_window(self):
        terrain = unit_grid(np.arange(9, dtype=np.float64).reshape(3, 3))
        session = SculptSession(terrain)
        session.begin_stroke("smooth", radius=0.5, strength=100.0)
        self.assertEqual(session.dab(0.0, 0.0, amount=1.0), (0, 0, 1, 1))

        # Edge replication yields [0,0,1; 0,0,1; 3,3,4], with mean 4/3.
        self.assertAlmostEqual(session.terrain.heights[0, 0], 4.0 / 3.0)
        self.assertTrue(np.array_equal(session.terrain.heights[1:, :],
                                       terrain.heights[1:, :]))

    def test_flatten_freezes_surface_target_at_first_effective_dab(self):
        terrain = unit_grid([[0, 0, 0], [0, 10, 0], [0, 0, 0]])
        session = SculptSession(terrain)
        session.begin_stroke("flatten", radius=0.1, strength=10.0)

        # The first point already lies at its target, but still freezes 10 m.
        self.assertIsNone(session.dab(1.0, 1.0, amount=1.0))
        self.assertEqual(session.revision, 0)
        session.dab(2.0, 1.0, amount=1.0)
        self.assertGreater(session.terrain.heights[1, 2], 9.9)
        self.assertEqual(session.end_stroke().mode, "flatten")

    def test_boundary_hits_work_but_outside_centers_do_not_modify(self):
        terrain = Heightfield.flat(rows=3, cols=3, origin=(0.0, 0.0),
                                   size=(2.0, 2.0))
        session = SculptSession(terrain)
        session.begin_stroke("raise", radius=1.0, strength=1.0)
        self.assertIsNone(session.dab(-0.01, 0.0, amount=1.0))
        self.assertIs(session.terrain, terrain)
        self.assertEqual(session.revision, 0)
        self.assertIsNone(session.end_stroke())
        self.assertEqual(session.undo_count, 0)

        session.begin_stroke("raise", radius=0.1, strength=1.0)
        self.assertEqual(session.dab(0.0, 0.0, amount=1.0), (0, 0, 1, 1))
        self.assertEqual(session.terrain.heights[0, 0], 1.0)
        session.end_stroke()

    def test_invalid_dab_is_atomic_and_cancel_restores_exact_heightfield(self):
        initial = unit_grid(np.arange(25, dtype=np.float64).reshape(5, 5) / 4.0)
        session = SculptSession(initial)
        session.begin_stroke("raise", radius=1.1, strength=0.75)
        dirty = session.dab(2.0, 2.0, amount=0.5)
        preview = session.terrain.heights.copy()
        preview_revision = session.revision

        for args in ((np.nan, 2.0, 1.0), (2.0, np.inf, 1.0),
                     (2.0, 2.0, -0.1), (2.0, 2.0, np.inf)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    session.dab(*args)
                self.assertTrue(np.array_equal(session.terrain.heights, preview))
                self.assertEqual(session.revision, preview_revision)
                self.assertTrue(session.active)

        cancel_rect = session.cancel_stroke()
        self.assertEqual(cancel_rect, dirty)
        self.assertTrue(np.array_equal(session.terrain.heights, initial.heights))
        self.assertEqual(session.revision, preview_revision + 1)
        self.assertFalse(session.active)

    def test_invalid_begin_and_unrepresentable_preview_leave_session_unchanged(self):
        terrain = Heightfield.flat(rows=3, cols=3, origin=(0.0, 0.0),
                                   size=(2.0, 2.0))
        session = SculptSession(terrain)
        for args, kwargs in ((("bad", 1.0, 1.0), {}),
                             (("raise", 0.0, 1.0), {}),
                             (("raise", 1.0, -1.0), {}),
                             (("raise", 1.0, 1.0), {"target_height": 2.0}),
                             (("flatten", 1.0, 1.0), {"target_height": np.nan})):
            with self.subTest(args=args, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    session.begin_stroke(*args, **kwargs)
                self.assertFalse(session.active)
                self.assertEqual(session.revision, 0)
                self.assertIs(session.terrain, terrain)

        near_float32_limit = np.zeros((3, 3), dtype=np.float64)
        near_float32_limit[1, 1] = 3.0e38
        terrain = unit_grid(near_float32_limit)
        session = SculptSession(terrain)
        session.begin_stroke("raise", radius=0.1, strength=1.0e38)
        with self.assertRaises(ValueError):
            session.dab(1.0, 1.0, amount=1.0)
        self.assertTrue(np.array_equal(session.terrain.heights, terrain.heights))
        self.assertEqual(session.revision, 0)
        self.assertTrue(session.active)
        self.assertIsNone(session.cancel_stroke())

    def test_cancel_undo_redo_are_exact_and_revision_is_monotonic(self):
        initial = unit_grid(np.arange(49, dtype=np.float64).reshape(7, 7) / 5.0)
        session = SculptSession(initial)

        session.begin_stroke("raise", radius=1.1, strength=0.5)
        first_dirty = session.dab(3.0, 3.0, amount=0.5)
        session.dab(4.0, 3.0, amount=0.25)
        preview_revision = session.revision
        cancelled_rect = session.cancel_stroke()
        self.assertEqual(cancelled_rect, (2, 2, 5, 6))
        self.assertIsNotNone(first_dirty)
        self.assertTrue(np.array_equal(session.terrain.heights, initial.heights))
        self.assertEqual(session.revision, preview_revision + 1)

        session.begin_stroke("lower", radius=1.1, strength=0.5)
        session.dab(2.0, 2.0, amount=0.5)
        patch = session.end_stroke()
        committed = session.terrain.heights.copy()
        committed_revision = session.revision
        self.assertEqual(session.undo_count, 1)

        self.assertEqual(session.undo(), patch.dirty_rect)
        self.assertTrue(np.array_equal(session.terrain.heights, initial.heights))
        self.assertEqual(session.revision, committed_revision + 1)
        self.assertEqual(session.redo(), patch.dirty_rect)
        self.assertTrue(np.array_equal(session.terrain.heights, committed))
        self.assertEqual(session.revision, committed_revision + 2)
        self.assertEqual(session.history_bytes, patch.byte_size)

    def test_noop_gestures_do_not_create_history_or_clear_redo(self):
        terrain = Heightfield.flat(rows=3, cols=3, origin=(0.0, 0.0),
                                   size=(2.0, 2.0))
        empty = SculptSession(terrain, history_budget_bytes=0)
        empty.begin_stroke("raise", radius=1.0, strength=1.0)
        self.assertIsNone(empty.dab(1.0, 1.0, amount=0.0))
        self.assertIsNone(empty.dab(-2.0, 1.0, amount=1.0))
        self.assertIsNone(empty.end_stroke())
        self.assertEqual(empty.history_bytes, 0)
        self.assertEqual(empty.undo_count, 0)
        self.assertEqual(empty.revision, 0)

        session = SculptSession(terrain)
        session.begin_stroke("raise", radius=0.1, strength=1.0)
        session.dab(1.0, 1.0, amount=1.0)
        session.end_stroke()
        session.undo()
        self.assertEqual(session.redo_count, 1)
        session.begin_stroke("raise", radius=1.0, strength=1.0)
        self.assertIsNone(session.dab(-1.0, -1.0, amount=1.0))
        self.assertIsNone(session.end_stroke())
        self.assertEqual(session.redo_count, 1)
        self.assertIsNotNone(session.redo())

    def test_region_history_budget_rejects_new_diff_and_preserves_prior_history(self):
        initial = Heightfield.flat(rows=5, cols=5, origin=(0.0, 0.0),
                                   size=(4.0, 4.0))
        session = SculptSession(initial, history_budget_bytes=32)
        session.begin_stroke("raise", radius=0.1, strength=1.0)
        session.dab(2.0, 2.0, amount=1.0)
        first_patch = session.end_stroke()
        self.assertEqual(first_patch.byte_size, 16)
        after_first = session.terrain.heights.copy()

        session.begin_stroke("raise", radius=0.1, strength=1.0)
        session.dab(3.0, 3.0, amount=1.0)
        session.end_stroke()
        after_second = session.terrain.heights.copy()
        session.undo()
        self.assertTrue(np.array_equal(session.terrain.heights, after_first))
        self.assertEqual(session.undo_count, 1)
        self.assertEqual(session.redo_count, 1)
        self.assertEqual(session.history_bytes, 32)
        revision_before_rejected_stroke = session.revision

        session.begin_stroke("raise", radius=1.1, strength=1.0)
        session.dab(0.0, 0.0, amount=1.0)
        with self.assertRaises(HistoryBudgetExceeded) as raised:
            session.end_stroke()

        self.assertEqual(raised.exception.required_bytes, 80)
        self.assertEqual(raised.exception.budget_bytes, 32)
        self.assertEqual(raised.exception.patch_bytes, 64)
        self.assertEqual(raised.exception.dirty_rect, (0, 0, 2, 2))
        self.assertTrue(np.array_equal(session.terrain.heights, after_first))
        self.assertEqual(session.revision, revision_before_rejected_stroke + 2)
        self.assertFalse(session.active)
        self.assertEqual(session.undo_count, 1)
        self.assertEqual(session.redo_count, 1)
        self.assertEqual(session.history_bytes, 32)
        self.assertEqual(session.redo(), (3, 3, 4, 4))
        self.assertTrue(np.array_equal(session.terrain.heights, after_second))
        self.assertEqual(session.undo(), (3, 3, 4, 4))
        self.assertTrue(np.array_equal(session.terrain.heights, after_first))
        self.assertEqual(session.undo(), first_patch.dirty_rect)
        self.assertTrue(np.array_equal(session.terrain.heights, initial.heights))


if __name__ == "__main__":
    unittest.main()
