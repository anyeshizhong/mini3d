"""Lens physics, atomic updates, legacy saves, IPC whitelist and cache changes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch, BATCH_METHODS
from mini3d.camera import Camera
from mini3d.shot_camera import ShotCamera
from mini3d.viewport_cache import viewport_key


class DepthOfFieldTests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()
        self.api.create_shot_camera(position=[0, 0, 0], target=[0, 0, -2], focal_mm=85)
        self.shot = self.api._app.shot_camera

    def test_thin_lens_zero_focus_sign_and_aperture_ratio(self):
        self.shot.set_depth_of_field(True, 2, 1.4)
        self.assertEqual(float(self.shot.circle_of_confusion(2)), 0)
        self.assertLess(float(self.shot.circle_of_confusion(1)), 0)
        self.assertGreater(float(self.shot.circle_of_confusion(8)), 0)
        wide = float(self.shot.circle_of_confusion(8))
        self.shot.set_depth_of_field(f_number=2.8)
        self.assertAlmostEqual(float(self.shot.circle_of_confusion(8)), wide / 2)
        self.assertAlmostEqual(float(self.shot.circle_of_confusion(8, width=960)), wide / 4)
        self.assertAlmostEqual(wide, 1920*.085**2*(8-2)/(2*1.4*.036*8*(2-.085)))

    def test_invalid_settings_are_atomic(self):
        original = self.shot.to_dict()
        for kwargs in ({'enabled': 1}, {'focus_distance': True}, {'focus_distance': .01},
                       {'focus_distance': float('nan')}, {'f_number': 0}, {'f_number': '2'},
                       {'f_number': float('inf')}, {'enabled': True, 'focus_distance': 2, 'f_number': -1}):
            with self.assertRaises(ValueError):
                self.shot.set_depth_of_field(**kwargs)
            self.assertEqual(self.shot.to_dict(), original)

    def test_focus_is_view_depth_and_does_not_change_pose(self):
        original = self.shot.view_matrix.copy()
        self.api.focus_at([2, 3, -4])
        self.assertEqual(self.shot.focus_distance, 4)
        np.testing.assert_array_equal(self.shot.view_matrix, original)
        for point in ([0, 0, 2], [0, 0, 0], [0, float('nan'), -2], [True, 0, -2], [0, 0]):
            with self.assertRaises(ValueError):
                self.api.focus_at(point)
            self.assertEqual(self.shot.focus_distance, 4)

    def test_scene_and_dispatch_round_trip_and_legacy_defaults(self):
        result = dispatch(self.api, {'command': 'set_depth_of_field', 'args': {
            'enabled': True, 'focus_distance': 3.5, 'f_number': 1.4}})
        self.assertTrue(result['ok'], result)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scene.json'
            self.api.save_scene(path)
            fresh = Mini3DAPI()
            self.assertEqual(fresh.load_scene(path)['shot_camera'], self.api.get_shot_camera())
            document = json.loads(path.read_text())
            for key in ('dof_enabled', 'focus_distance', 'f_number'):
                del document['shot_camera'][key]
            path.write_text(json.dumps(document))
            camera = fresh.load_scene(path)['shot_camera']
            self.assertFalse(camera['dof_enabled'])
            self.assertEqual((camera['focus_distance'], camera['f_number']), (5, 2.8))
            invalid = copy.deepcopy(document)
            invalid['shot_camera']['f_number'] = -2
            path.write_text(json.dumps(invalid))
            before = fresh.get_scene_state()
            with self.assertRaises(ValueError):
                fresh.load_scene(path)
            self.assertEqual(fresh.get_scene_state(), before)
        for method in ('set_depth_of_field', 'focus_at', 'focus_on'):
            self.assertNotIn(method, BATCH_METHODS)

    def test_focus_selected_bounds_and_viewport_cache_invalidation(self):
        entity = self.api.spawn('builtin:ground', position=[0, 0, -3], scale=[.1, .1, .1])
        self.api.focus_on(entity['entity_id'])
        self.assertEqual(self.shot.focus_distance, 3)
        app = self.api._app
        app.set_camera_view(True)
        before = viewport_key(app, (640, 360), True, 'REALISTIC')
        self.api.set_depth_of_field(True, 4, 1.4)
        after = viewport_key(app, (640, 360), True, 'REALISTIC')
        self.assertNotEqual(before, after)
        app.select(app.scene.find_by_id(entity['entity_id']))
        app.focus_shot_selection()
        self.assertEqual(self.shot.focus_distance, 3)

    def test_no_camera_and_failed_creation_do_not_replace_state(self):
        fresh = Mini3DAPI()
        with self.assertRaises(ValueError):
            fresh.set_depth_of_field(True)
        old = self.api.get_shot_camera()
        with self.assertRaises(ValueError):
            self.api.create_shot_camera(position=[1, 0, 0], target=[0, 0, 0], f_number=0)
        self.assertEqual(old, self.api.get_shot_camera())


if __name__ == '__main__':
    unittest.main()
