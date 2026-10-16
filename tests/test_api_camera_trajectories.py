"""API-first deterministic camera motion; no window or GPU required."""
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch
from api_camera_trajectories import linear_path, orbit_path


class APICameraTrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()

    def test_orbit_moves_shot_through_json_dispatch_without_resetting_photography(self):
        self.api.create_shot_camera(position=[5, 0, 3], target=[0, 0, 1],
                                    focal_mm=85, aspect='3:2', near=.03, far=250)
        self.api.set_depth_of_field(enabled=True, focus_distance=5., f_number=2.0)
        self.api.set_photo_color(white_balance_kelvin=7600, preset='Warm')
        self.api.set_antialiasing(4)
        original = self.api.get_shot_camera()
        poses = list(orbit_path([0, 0, 1], radius=5, height=2, frames=17))
        for pose in poses:
            response = dispatch(self.api, dict(command='set_shot_camera_pose', args=pose))
            self.assertTrue(response['ok'], response)
            result = response['result']
            np.testing.assert_allclose(result['position'], pose['position'], atol=1e-10)
            for field in ('focal_mm', 'aspect', 'fov_y', 'near', 'far', 'samples',
                          'dof_enabled', 'focus_distance', 'f_number',
                          'white_balance_kelvin', 'color_preset'):
                self.assertEqual(result[field], original[field], field)
        np.testing.assert_allclose(self.api.get_shot_camera()['position'],
                                   poses[0]['position'], atol=1e-10)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orbit.scene.json'
            self.api.save_scene(path)
            restored = Mini3DAPI()
            restored.load_scene(path)
            self.assertEqual(restored.get_shot_camera(), self.api.get_shot_camera())

    def test_linear_dolly_updates_pose_and_allows_full_roll_rotation(self):
        self.api.create_shot_camera(position=[7, 9, 13], target=[0, 0, 0])
        poses = list(linear_path([7, 9, 13], [6, 7.5, 10],
                                 [0, 0, 0], [0, 1, 0], frames=5))
        self.assertEqual(poses[0]['position'], [7., 9., 13.])
        self.assertEqual(poses[-1]['target'], [0., 1., 0.])
        for pose in poses:
            self.api.set_shot_camera_pose(**pose)
        np.testing.assert_allclose(self.api.get_shot_camera()['position'], [6, 7.5, 10])
        # Explicit 3x3 orientation supports 6-DoF tracks, including roll.
        rotation = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        changed = self.api.set_shot_camera_pose(position=[3, 4, 5], rotation=rotation)
        np.testing.assert_allclose(changed['rotation'], rotation)
        self.assertEqual(changed['position'], [3., 4., 5.])

    def test_invalid_camera_pose_is_atomic_and_rejected_by_dispatch(self):
        missing = dispatch(self.api, dict(command='set_shot_camera_pose',
                                          args=dict(position=[1, 2, 3], target=[0, 0, 0])))
        self.assertFalse(missing['ok'])
        self.api.create_shot_camera(position=[5, 0, 2], target=[0, 0, 1])
        baseline = self.api.get_shot_camera()
        bad = [
            dict(position=[5, 0, 2]),
            dict(position=[5, 0, 2], target=[0, 0, 1], rotation=np.eye(3).tolist()),
            dict(position=[0, 0, 1], target=[0, 0, 1]),
            dict(position=[float('nan'), 0, 0], target=[0, 0, 1]),
            dict(position=[5, 0, 2], rotation=[[1, 0, 0]] * 3),
            dict(position=[5, 0, 2], rotation=[[1, 0], [0, 1]]),
        ]
        for args in bad:
            with self.subTest(args=args):
                result = dispatch(self.api, dict(command='set_shot_camera_pose', args=args))
                self.assertFalse(result['ok'], result)
                self.assertEqual(self.api.get_shot_camera(), baseline)
        with self.api.transaction('placement'):
            with self.assertRaises(ValueError):
                self.api.set_shot_camera_pose(position=[4, 0, 2], target=[0, 0, 1])
        self.assertEqual(self.api.get_shot_camera(), baseline)

    def test_world_focus_marker_tracks_pose_and_clears_if_behind(self):
        self.api.create_shot_camera(position=[5, 0, 2], target=[0, 0, 1])
        self.api.focus_at([0, 0, 1])
        moved = self.api.set_shot_camera_pose(position=[6, 0, 3], target=[0, 0, 1])
        self.assertEqual(moved['focus_point'], [0., 0., 1.])
        self.assertAlmostEqual(moved['focus_distance'], math.sqrt(40), places=8)
        reversed_pose = self.api.set_shot_camera_pose(position=[6, 0, 3], target=[12, 0, 5])
        self.assertIsNone(reversed_pose['focus_point'])
        self.assertEqual(reversed_pose['focus_distance'], moved['focus_distance'])

    def test_trajectory_parameters_validate_before_yielding_frames(self):
        with self.assertRaises(ValueError):
            list(orbit_path([0, 0, 0], 0, 1, 10))
        with self.assertRaises(ValueError):
            list(orbit_path([0, 0, 0], 2, 1, 1))
        with self.assertRaises(ValueError):
            list(linear_path([0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0], 1))


if __name__ == '__main__':
    unittest.main()
