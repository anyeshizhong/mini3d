"""Scene v3 photography persistence, strict input validation and atomic load."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch_json
from mini3d.camera import Camera
from mini3d.editor import Editor, PROJECT
from mini3d.scene import rotation_xyz
from mini3d.shot_camera import ShotCamera


def editor_state(app):
    return json.loads(json.dumps(app.viewer.controller.snapshot(), default=lambda x: x.tolist()))


class ShotCameraPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'scene.json'
        self.api = Mini3DAPI()
        self.api.create_shot_camera(position=[7, -11, 9], target=[1, 2, 3],
                                    focal_mm=35, aspect='16:9', near=.05, far=300)

    def write(self, document):
        self.path.write_text(json.dumps(document), encoding='utf8')

    def document(self):
        self.api.save_scene(self.path)
        return json.loads(self.path.read_text(encoding='utf8'))

    def test_python_fresh_instance_round_trip_preserves_entire_scene(self):
        one = self.api.spawn(PROJECT / 'model/06_stl_cube/cube.STL', position=[3, 4, 5])
        two = self.api.duplicate(one['entity_id'])
        self.api.create_group([one['entity_id'], two['entity_id']], 'pair')
        self.api.set_lighting(mode='Scene', direction=[1, -1, 1.6], diffuse=2.5, ambient=.22)
        self.api.set_shadows(enabled=True, resolution=2048, bias=.0005, pcf=True)
        before = self.api.get_scene_state()
        editor_before = editor_state(self.api._app)
        shot = self.api._app.shot_camera
        view, projection = shot.view_matrix, shot.projection_matrix(shot.aspect)
        document = self.document()
        self.assertEqual(document['version'], 3)
        self.assertEqual(document['shot_camera'], shot.to_dict())
        del self.api
        fresh = Mini3DAPI()
        with patch.object(fresh, 'create_shot_camera', side_effect=AssertionError('must restore')):
            result = fresh.load_scene(self.path)
        for key in before.keys() - {'history'}:
            self.assertEqual(result[key], before[key], key)
        self.assertEqual(editor_state(fresh._app), editor_before)
        self.assertEqual(fresh._commands.undo_count, 0)
        np.testing.assert_array_equal(fresh._app.shot_camera.view_matrix, view)
        np.testing.assert_array_equal(fresh._app.shot_camera.projection_matrix(shot.aspect), projection)
        self.assertIsNot(fresh._app.shot_camera, fresh._app.viewer.camera)

    def test_json_save_load_get_without_camera_creation(self):
        def call(api, command, **args):
            response = json.loads(dispatch_json(api, json.dumps(dict(command=command, args=args))))
            self.assertTrue(response['ok'], response)
            return response['result']
        expected = call(self.api, 'get_shot_camera')
        self.assertEqual(call(self.api, 'save_scene', path=str(self.path))['version'], 3)
        fresh = Mini3DAPI()
        self.assertEqual(call(fresh, 'load_scene', path=str(self.path))['shot_camera'], expected)
        self.assertEqual(call(fresh, 'get_shot_camera'), expected)
        observed = fresh.get_shot_camera()
        observed['position'][0] = 999
        observed['rotation'][0][0] = 999
        self.assertEqual(fresh.get_shot_camera(), expected)

    def test_all_preset_lenses_and_aspects_round_trip_exactly(self):
        for focal in (24, 35, 50, 85):
            for aspect in ShotCamera.ASPECTS:
                with self.subTest(focal=focal, aspect=aspect):
                    self.api.set_aspect(aspect)
                    self.api.set_lens(focal)
                    expected = self.api.get_shot_camera()
                    self.api.save_scene(self.path)
                    fresh = Mini3DAPI()
                    fresh.load_scene(self.path)
                    self.assertEqual(fresh.get_shot_camera(), expected)

    def test_editor_view_nonpreset_fov_and_roll_are_not_reconstructed_from_target(self):
        app = Editor()
        app.viewer.camera.fov_y = 47.123456789
        app.viewer.camera.rotation = rotation_xyz([.17, -.25, .43])
        app.create_camera_from_view()
        app.shot_camera.set_aspect('4:3')
        expected = app.shot_camera.to_dict()
        app.save_scene(self.path)
        fresh = Editor()
        fresh.load_scene(self.path)
        self.assertEqual(fresh.shot_camera.to_dict(), expected)
        np.testing.assert_array_equal(fresh.shot_camera.view_matrix, app.shot_camera.view_matrix)

    def test_editor_navigation_view_switch_and_resave_preserve_shot(self):
        self.api.save_scene(self.path)
        fresh = Mini3DAPI()
        fresh.load_scene(self.path)
        expected = fresh.get_shot_camera()
        app = fresh._app
        before = editor_state(app)
        app.set_camera_view(True)
        app.set_camera_view(False)
        app.viewer.controller.orbit(100, 20)
        app.viewer.controller.pan(12, 8, 700)
        app.viewer.controller.zoom(-1)
        self.assertNotEqual(editor_state(app), before)
        app.set_camera_view(True)
        self.assertEqual(fresh.get_shot_camera(), expected)
        fresh.save_scene(self.path)
        self.assertEqual(Mini3DAPI().load_scene(self.path)['shot_camera'], expected)

    def test_missing_field_v1_v2_v3_clears_stale_camera_and_photo_state(self):
        document = self.document()
        del document['shot_camera']
        for version in (1, 2, 3):
            with self.subTest(version=version):
                document['version'] = version
                self.write(document)
                fresh = Mini3DAPI()
                self.assertIsNone(fresh.load_scene(self.path)['shot_camera'])
                fresh.create_shot_camera(position=[1, 2, 3], target=[0, 0, 0])
                fresh._app.set_camera_view(True)
                fresh._app.request_capture()
                fresh._app.last_capture = Path('old.png')
                self.assertIsNone(fresh.load_scene(self.path)['shot_camera'])
                self.assertFalse(fresh._app.camera_view)
                self.assertFalse(fresh._app.capture_requested)
                self.assertIsNone(fresh._app.last_capture)
                with self.assertRaisesRegex(ValueError, 'Shot Camera'):
                    fresh.capture(Path(self.temp.name) / 'unexpected.png')

    def test_null_round_trip_clears_existing_shot(self):
        empty = Mini3DAPI()
        empty.save_scene(self.path)
        self.assertIsNone(json.loads(self.path.read_text(encoding='utf8'))['shot_camera'])
        self.assertIsNone(self.api.load_scene(self.path)['shot_camera'])

    def test_successful_camera_replacement_clears_pending_capture(self):
        self.api.save_scene(self.path)
        self.api._app.set_camera_view(True)
        self.api._app.request_capture()
        self.api._app.last_capture = Path('old.png')
        expected = self.api.get_shot_camera()
        self.api.create_shot_camera(position=[4, 5, 6], target=[0, 0, 0], focal_mm=85)
        self.api.load_scene(self.path)
        self.assertEqual(self.api.get_shot_camera(), expected)
        self.assertTrue(self.api._app.camera_view)
        self.assertFalse(self.api._app.capture_requested)
        self.assertIsNone(self.api._app.last_capture)

    def test_invalid_camera_does_not_mutate_any_live_state(self):
        original = self.api.spawn(PROJECT / 'model/06_stl_cube/cube.STL', position=[3, 4, 5])
        self.api.duplicate(original['entity_id'])
        self.api.undo()  # Keep both undo and redo history to detect premature clearing.
        document = self.document()
        valid = document['shot_camera']
        candidates = [[], True, 12, 'camera', {}]
        for key in valid:
            missing = copy.deepcopy(valid)
            del missing[key]
            candidates.append(missing)
        bad_fields = {
            'position': [[1, 2], [[1, 2, 3]], [True, 2, 3], ['1', 2, 3], [None, 2, 3],
                         [float('nan'), 2, 3], [1e400, 2, 3], [10**400, 2, 3]],
            'rotation': [[0, 0, 0], np.zeros((3, 3)).tolist(), np.diag([1, 1, -1]).tolist(),
                         np.diag([1, 1, 2]).tolist(), [[1, .1, 0], [0, 1, 0], [0, 0, 1]],
                         [[True, 0, 0], [0, 1, 0], [0, 0, 1]],
                         [[float('nan'), 0, 0], [0, 1, 0], [0, 0, 1]]],
            'aspect': ['2:1', '', [], {}, 1, True],
            'focal_mm': [0, -35, 50, '35', True, float('inf'), float('nan'), 10**400],
            'fov_y': [0, 180, -1, 60, '30', True, float('inf'), float('nan')],
            'near': [0, -1, 300, 301, '0.05', True, float('inf'), float('nan')],
            'far': [0, -1, .01, .05, '300', True, float('inf'), float('nan')],
        }
        for key, values in bad_fields.items():
            for value in [None] + values:
                candidate = copy.deepcopy(valid)
                candidate[key] = value
                candidates.append(candidate)
        overflow = copy.deepcopy(valid)
        overflow.update(near=1e307, far=1e308)
        candidates.append(overflow)
        # Make the would-be loaded scene distinguishable from the live one.
        document['objects'][0]['position'] = [99, 88, 77]
        document['lighting']['ambient'] = .9
        document['shadows']['enabled'] = True
        document['camera']['yaw'] = 2.1
        app = self.api._app
        app.set_camera_view(True)
        app.request_capture()
        app.last_capture = Path('previous.png')
        state, editor = self.api.get_scene_state(), editor_state(app)
        shot, root, status = app.shot_camera, app.scene.root_entities[0], app.status
        for camera in candidates:
            with self.subTest(camera=camera):
                document['shot_camera'] = camera
                self.write(document)
                response = json.loads(dispatch_json(self.api, json.dumps(dict(
                    command='load_scene', args=dict(path=str(self.path))))))
                self.assertFalse(response['ok'], response)
                self.assertEqual(response['error']['type'], 'ValueError')
                self.assertEqual(self.api.get_scene_state(), state)
                self.assertEqual(editor_state(app), editor)
                self.assertIs(app.shot_camera, shot)
                self.assertIs(app.scene.root_entities[0], root)
                self.assertEqual(app.status, status)
                self.assertTrue(app.camera_view)
                self.assertTrue(app.capture_requested)
                self.assertEqual(app.last_capture, Path('previous.png'))
        self.assertTrue(self.api.redo()['changed'])

    def test_valid_shot_with_invalid_scene_does_not_replace_live_camera(self):
        document = self.document()
        document['shot_camera']['position'] = [9, 8, 7]
        document['camera']['fov_y'] = 0
        before = self.api.get_scene_state()
        self.write(document)
        with self.assertRaises(ValueError):
            self.api.load_scene(self.path)
        self.assertEqual(self.api.get_scene_state(), before)


if __name__ == '__main__':
    unittest.main()
