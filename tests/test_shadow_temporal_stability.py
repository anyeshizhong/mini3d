"""Fixed world probes keep their shadow-texel phase during camera translation."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mini3d.camera import Camera
from mini3d.scene import Entity, Mesh
from mini3d.scene_snapshot import SceneSnapshot, OverlaySnapshot
from mini3d.shot_camera import ShotCamera
from mini3d.shadow_fit import _corners, _stabilize_bounds, receiver_matrix
from mini3d.shadow_map import (ShadowMap, _ShadowTemporalState, _uploaded_shadow_matrix,
                               _shadow_input_key, _shadow_fit_input_key)


def box(bounds):
    result = Entity(Mesh(_corners(bounds), [[0, 1, 2]]))
    result.update_transform()
    return result


def camera(offset=0):
    result = ShotCamera(Camera([7 + offset, 9, 13], near=.05, far=400))
    result.look_at([.6 + offset, .5, 0])
    result.set_lens(50)
    result.set_aspect('4:3')
    return result


class ShadowTemporalStabilityTests(unittest.TestCase):
    def setUp(self):
        self.entities = [box(([-100, -100, -.2], [100, 100, 0])),
                         box(([-.5, -.5, 0], [.5, .5, 2]))]

    def test_lateral_track_keeps_world_phase_and_depth_at_normal_and_low_sun(self):
        probe = np.array([1., 1., 0., 1.])
        for light in ([-3, -2, 3], [-3, -2, .8]):
            with self.subTest(light=light):
                state, matrices, baseline = {}, [], []
                for offset in np.linspace(0, .2, 121):
                    shot = camera(offset)
                    matrices.append(receiver_matrix(self.entities, light, shot, 1024,
                                                    stability=state))
                    # Replay the old unsnapped tight fit on the identical track.
                    with patch('mini3d.shadow_fit._stabilize_bounds',
                               side_effect=lambda lo, hi, *args: (lo, hi)):
                        baseline.append(receiver_matrix(self.entities, light, shot, 1024))
                matrices, baseline = np.array(matrices), np.array(baseline)
                before = np.diff((baseline @ probe)[:, :2] * 512, axis=0)
                self.assertGreater(float(np.max(np.abs(before - np.round(before)))), .04)
                # A moving integer texel grid preserves a fixed world's samples.
                steps = np.diff((matrices @ probe)[:, :2] * 512, axis=0)
                np.testing.assert_allclose(steps, np.round(steps), atol=1e-10)
                for matrix in matrices:
                    np.testing.assert_array_equal(matrix[:2, :3], matrices[0, :2, :3])
                    np.testing.assert_array_equal(matrix[2], matrices[0, 2])
                    self.assertTrue(np.all(np.abs((matrix @ probe)[:3]) < 1))
                # The local fit remains far smaller than the 200 m ground.
                self.assertLess(float((2 / np.linalg.norm(matrices[0, :2, :3], axis=1)).max()), 30)

    def test_snap_and_hysteresis_always_cover_requested_bounds_and_refit_on_zoom(self):
        state = {}
        for width, offset in ((10, 0), (10.1, .03), (9.9, .09), (20, 12), (2, 20)):
            lo, hi = np.array([offset, -width, -3]), np.array([offset + width, width, 4])
            fitted_lo, fitted_hi = _stabilize_bounds(lo, hi, np.eye(3), 1024, state)
            self.assertTrue(np.all(fitted_lo <= lo))
            self.assertTrue(np.all(fitted_hi >= hi))
            # Refitting on shrink prevents an earlier wide shot wasting texels.
            self.assertTrue(np.all((fitted_hi - fitted_lo)[:2] < (hi - lo)[:2] * 1.05))

    def test_xy_translation_keeps_pitch_and_does_not_start_scale_transition(self):
        state = _ShadowTemporalState()
        matrix = np.diag([.1, .2, -.1, 1.]).astype(np.float32)
        first = state.update(('scene', 1024), matrix, b'pose0')
        self.assertTrue(first['needs_draw'])
        self.assertEqual(first['current_layer'], 0)
        state.mark_rendered(first['depth_key'])

        moved = matrix.copy()
        moved[0, 3] = .015625
        moved[1, 3] = -.03125
        plan = state.update(('scene', 1024), moved, b'pose1')
        self.assertTrue(plan['needs_draw'])
        self.assertEqual(plan['current_layer'], 0)
        self.assertFalse(plan['transition'])
        self.assertEqual(plan['blend'], 1.)

    def test_scale_transition_keeps_old_layer_and_advances_on_distinct_poses_only(self):
        state = _ShadowTemporalState()
        old = np.diag([.1, .2, -.1, 1.]).astype(np.float32)
        initial = state.update(('scene', 1024), old, b'pose0')
        state.mark_rendered(initial['depth_key'])

        current = old.copy()
        current[0, 0] = .15
        current[2, 3] = .02
        start = state.update(('scene', 1024), current, b'pose1')
        self.assertTrue(start['transition'])
        self.assertEqual(start['current_layer'], 1)
        self.assertEqual(start['previous_layer'], 0)
        np.testing.assert_array_equal(start['previous_matrix'], old)
        self.assertEqual(start['blend'], 0.)
        state.mark_rendered(start['depth_key'])

        duplicate = state.update(('scene', 1024), current, b'pose1')
        self.assertEqual(duplicate['blend'], 0.)
        self.assertEqual(duplicate['current_layer'], 1)

        active_previous = start['previous_matrix'].copy()
        later = current.copy()
        later[0, 0] = .17
        changed_current = state.update(('scene', 1024), later, b'pose1')
        self.assertTrue(changed_current['transition'])
        self.assertEqual(changed_current['blend'], 0.)
        self.assertEqual(changed_current['current_layer'], 1)
        np.testing.assert_array_equal(changed_current['previous_matrix'], active_previous)
        state.mark_rendered(changed_current['depth_key'])

        # The first pose establishes alpha 0; seven further distinct poses
        # reach alpha 1. Repeated poses never move the fade.
        for index, pose in enumerate((b'pose2', b'pose3', b'pose4', b'pose5',
                                      b'pose6', b'pose7', b'pose8'), start=1):
            plan = state.update(('scene', 1024), later, pose)
            if index < 7:
                self.assertTrue(plan['transition'])
                self.assertAlmostEqual(plan['blend'], index / 7)
            else:
                self.assertFalse(plan['transition'])
                self.assertEqual(plan['blend'], 1.)

    def test_fit_input_change_invalidates_both_layers_and_cancels_fade(self):
        state = _ShadowTemporalState()
        old = np.diag([.1, .2, -.1, 1.]).astype(np.float32)
        first = state.update(('scene', 1024), old, b'pose0')
        state.mark_rendered(first['depth_key'])
        current = old.copy()
        current[0, 0] = .15
        faded = state.update(('scene', 1024), current, b'pose1')
        self.assertTrue(faded['transition'])
        state.mark_rendered(faded['depth_key'])
        # Resolution, light, lens, casters, or ground plane changes enter the
        # fit key and discard both cached layers as one invalidation.
        invalidated = state.update(('scene', 2048), current, b'pose2')
        self.assertTrue(invalidated['fit_changed'])
        self.assertTrue(invalidated['needs_draw'])
        self.assertFalse(invalidated['transition'])
        self.assertEqual(invalidated['current_layer'], 0)
        self.assertIsNone(state.previous_matrix)
        self.assertEqual(state.layer_keys, [None, None])

    def test_depth_cache_key_uses_the_uploaded_float32_matrix(self):
        state = _ShadowTemporalState()
        matrix = np.diag([.1, .2, -.1, 1.]).astype(np.float64)
        first = state.update(('scene', 1024), _uploaded_shadow_matrix(matrix), b'pose0')
        state.mark_rendered(first['depth_key'])
        near_same = matrix.copy()
        near_same[0, 3] = 1e-50
        plan = state.update(('scene', 1024), _uploaded_shadow_matrix(near_same), b'pose0')
        self.assertFalse(plan['needs_draw'])
        self.assertEqual(first['depth_key'], plan['depth_key'])

    def test_render_advances_new_pose_even_when_matrix_and_depth_are_reused(self):
        light = np.array([-3., -2., 3.])
        scene = SimpleNamespace(shadow_resolution=1024)
        first_pose = camera()
        next_pose = camera(.001)
        projection = np.asarray(first_pose.projection_matrix(first_pose.aspect)).tobytes()
        records = _shadow_input_key([])
        fit_key = (1024, light.tobytes(), projection, _shadow_fit_input_key([], None, light, records))
        matrix = np.diag([.1, .2, -.1, 1.]).astype(np.float32)
        scaled = matrix.copy()
        scaled[0, 0] = .15
        shadow = ShadowMap()
        shadow._fit_key = fit_key
        shadow._temporal.reset(fit_key)
        initial = shadow._temporal.update(fit_key, matrix, _uploaded_shadow_matrix(first_pose.view_matrix).tobytes())
        shadow._temporal.mark_rendered(initial['depth_key'])
        transition = shadow._temporal.update(fit_key, scaled, _uploaded_shadow_matrix(first_pose.view_matrix).tobytes())
        shadow._temporal.mark_rendered(transition['depth_key'])
        shadow.matrix = scaled.astype(np.float64)

        with patch('mini3d.shadow_map.scene_light_direction', return_value=light), \
             patch('mini3d.shadow_map.light_matrix', return_value=scaled), \
             patch('mini3d.gl_state.save_state', side_effect=AssertionError('unexpected GPU draw')):
            shadow.render([], scene, None, first_pose)
            self.assertEqual(shadow._temporal.transition_steps, 1)
            shadow.render([], scene, None, next_pose)
            self.assertEqual(shadow._temporal.transition_steps, 2)
            self.assertAlmostEqual(shadow._temporal.transition_steps - 1, 1)
            # Repeating the exact view takes the top-level key cache and freezes alpha.
            shadow.render([], scene, None, next_pose)
            self.assertEqual(shadow._temporal.transition_steps, 2)

    def test_following_ground_preserves_fit_key_but_plane_and_caster_edits_invalidate(self):
        ground = box(([-1, -1, 0], [1, 1, 0]))
        ground.model.material = {'extras': {'photographicGround': True}}
        base = SceneSnapshot().refresh_entities(self.entities)
        geometry = OverlaySnapshot().refresh(base, [ground])
        def fit_key(light=(-3, -2, 3)):
            entities = geometry.entities
            records = _shadow_input_key(entities, geometry)
            return _shadow_fit_input_key(entities, geometry, light, records)
        initial = fit_key()
        ground.pos[:] = [50, -20, 0]
        ground.scale[:] = [800, 800, 1]
        ground.update_transform()
        geometry.refresh(base, [ground])
        self.assertEqual(fit_key(), initial)
        ground.pos[2] = 2
        ground.update_transform()
        geometry.refresh(base, [ground])
        self.assertNotEqual(fit_key(), initial)
        plane_edit = fit_key()
        self.entities[1].model.bounds[1][2] += 2
        base.refresh_entities(self.entities)
        geometry.refresh(base, [ground])
        self.assertNotEqual(fit_key(), plane_edit)
        parallel = fit_key((1, 0, 0))
        ground.pos[0] += 5
        ground.update_transform()
        geometry.refresh(base, [ground])
        self.assertNotEqual(fit_key((1, 0, 0)), parallel)


if __name__ == '__main__':
    unittest.main()
