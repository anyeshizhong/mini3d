"""Shot AA API validation and backward-compatible Scene v3 persistence."""
import json
from pathlib import Path
import tempfile
import unittest

from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch
from mini3d.shot_camera import ShotCamera


class ShotAntialiasingTests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()
        self.api.create_shot_camera(position=[3, -5, 3], target=[0, 0, 1])

    def test_save_load_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scene.json'
            result = dispatch(self.api, dict(command='set_antialiasing', args=dict(samples=4)))
            self.assertTrue(result['ok'], result)
            self.api.save_scene(path)
            fresh = Mini3DAPI()
            self.assertEqual(fresh.load_scene(path)['shot_camera']['samples'], 4)
            document = json.loads(path.read_text())
            del document['shot_camera']['samples']
            path.write_text(json.dumps(document))
            self.assertEqual(fresh.load_scene(path)['shot_camera']['samples'], 1)
            self.assertEqual(fresh.set_antialiasing()['samples'], 1)

    def test_invalid_values_are_atomic_and_transactions_disallow_camera_change(self):
        self.api.set_antialiasing(4)
        before = self.api.get_shot_camera()
        for value in (True, None, 0, 2, 8, 4.0, '4', [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.api.set_antialiasing(value)
                with self.assertRaises(ValueError):
                    ShotCamera.from_dict(dict(before, samples=value))
                self.assertEqual(before, self.api.get_shot_camera())
        with self.api.transaction():
            with self.assertRaises(ValueError):
                self.api.set_antialiasing(1)
        self.assertFalse(dispatch(self.api, dict(command='transaction', args=dict(commands=[
            dict(command='set_antialiasing', args=dict(samples=1))])))['ok'])
        with self.assertRaisesRegex(ValueError, 'Shot Camera'):
            Mini3DAPI().set_antialiasing(4)


if __name__ == '__main__':
    unittest.main()
