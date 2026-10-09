"""Lighting V1: public API, dispatcher, atomic validation and v3 persistence."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch, dispatch_json
from mini3d.editor import PROJECT
from mini3d.editor_ui import EditorUI
from mini3d.lighting import scene_light_direction


class LightingAPITests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()

    def test_partial_updates_none_and_detached_snapshots(self):
        initial = self.api.get_lighting()
        self.assertEqual(self.api.set_lighting(), initial)
        result = self.api.set_lighting(direction=[3, -4, 0])
        self.assertEqual(result, dict(initial, direction=[3., -4., 0.]))
        self.assertEqual(self.api.set_lighting(diffuse=2), dict(result, diffuse=2.))
        self.assertEqual(self.api.set_lighting(ambient=0)['ambient'], 0.)
        self.assertEqual(self.api.set_lighting(mode='Scene')['mode'], 'Scene')
        result['direction'][0] = 99
        self.assertEqual(self.api.get_lighting()['direction'], [3., -4., 0.])
        snapshot = self.api.get_scene_state()
        self.assertEqual(snapshot['lighting'], self.api.get_lighting())
        snapshot['lighting']['direction'][1] = 99
        self.assertEqual(self.api.get_lighting()['direction'], [3., -4., 0.])
        json.dumps(self.api.get_scene_state(), allow_nan=False)

    def test_numpy_direction_is_copied_and_normalized_only_for_rendering(self):
        source = np.array([3., -4., 0.])
        self.api.set_lighting(direction=source)
        source[:] = 0
        self.assertEqual(self.api.get_lighting()['direction'], [3., -4., 0.])
        np.testing.assert_allclose(scene_light_direction(self.api._app.scene), [.6, -.8, 0])
        for magnitude in (1e-300, 1e300):
            self.api.set_lighting(direction=[magnitude, 0, 0])
            np.testing.assert_array_equal(scene_light_direction(self.api._app.scene), [1, 0, 0])

    def test_every_invalid_parameter_rejects_whole_update(self):
        invalid = {
            'mode': ['', 'scene', 'Other', 0, False, [], {}],
            'direction': [[0, 0, 0], [1, 2], [1, 2, 3, 4], [[1, 2, 3]],
                          [float('nan'), 0, 1], [1, float('inf'), 0], [True, 0, 1],
                          ['1', 2, 3], [1j, 0, 1], 5, '123'],
            'diffuse': [-1, float('nan'), float('inf'), '2', True, [], 1j, 10**400],
            'ambient': [-.1, float('nan'), float('-inf'), '0', False, {}, 1j],
        }
        before = self.api.get_scene_state()
        for name, values in invalid.items():
            for value in values:
                with self.subTest(parameter=name, value=value):
                    changes = dict(mode='Scene', direction=[1, 2, 3], diffuse=4., ambient=.1)
                    changes[name] = value
                    with self.assertRaises(ValueError):
                        self.api.set_lighting(**changes)
                    self.assertEqual(self.api.get_scene_state(), before)

    def test_camera_pose_and_focal_length_leave_lighting_unchanged(self):
        expected = self.api.set_lighting(mode='Scene', direction=[2, -5, 3], diffuse=.7, ambient=.2)
        for position, target in (([4, -6, 4], [0, 0, 0]), ([7, -3, 3], [0, 0, 0]),
                                 ([7.4, -3, 3], [.2, .1, 0])):
            self.api.create_shot_camera(position=position, target=target)
            self.api.set_lens(85)
            self.api.set_aspect('1:1')
            self.assertEqual(self.api.get_lighting(), expected)

    def test_changes_preserve_placement_undo_and_redo_history(self):
        item = self.api.spawn(PROJECT/'model/06_stl_cube/cube.STL')
        self.api.set_transform(item['entity_id'], position=[1, 2, 3])
        self.api.undo()
        history = self.api.get_scene_state()['history']
        light = self.api.set_lighting(diffuse=3)
        self.assertEqual(self.api.get_scene_state()['history'], history)
        self.api.redo()
        self.assertEqual(self.api.get_entity(item['entity_id'])['position'], [1., 2., 3.])
        self.assertEqual(self.api.get_lighting(), light)

    def test_transaction_allows_queries_but_rejects_lighting_writes_and_rolls_back(self):
        item = self.api.spawn(PROJECT/'model/06_stl_cube/cube.STL')
        before = self.api.get_scene_state()
        with self.assertRaisesRegex(ValueError, 'placement transaction'):
            with self.api.transaction():
                self.api.set_transform(item['entity_id'], position=[4, 0, 0])
                self.assertEqual(self.api.get_lighting(), before['lighting'])
                self.api.set_lighting(ambient=.5)
        self.assertEqual(self.api.get_scene_state(), before)

    def test_dispatch_whitelist_partial_updates_and_errors(self):
        result = json.loads(dispatch_json(self.api,
            '{"command":"set_lighting","args":{"mode":"Scene","direction":[0,0,9],"ambient":0}}'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(dispatch(self.api, {'command': 'get_lighting'})['result'], result['result'])
        before = self.api.get_lighting()
        self.assertEqual(dispatch(self.api, dict(command='set_lighting', args=dict(mode=None)))['result'], before)
        for args in (dict(diffuse=-1), dict(direction=[0, 0, 0]), dict(intensity=2)):
            self.assertFalse(dispatch(self.api, dict(command='set_lighting', args=args))['ok'])
            self.assertEqual(self.api.get_lighting(), before)
        for text in ('{"command":"set_lighting","args":{"ambient":NaN}}',
                     '{"command":"set_lighting","args":{"diffuse":1e400}}'):
            self.assertFalse(json.loads(dispatch_json(self.api, text))['ok'])
            self.assertEqual(self.api.get_lighting(), before)

    def test_json_batch_rejects_write_before_any_placement_runs(self):
        item = self.api.spawn(PROJECT/'model/06_stl_cube/cube.STL')
        before = self.api.get_scene_state()
        result = dispatch(self.api, dict(command='transaction', args=dict(commands=[
            dict(command='set_transform', args=dict(entity_id=item['entity_id'], position=[4, 0, 0])),
            dict(command='set_lighting', args=dict(diffuse=2))])))
        self.assertFalse(result['ok'])
        self.assertEqual(self.api.get_scene_state(), before)
        query = dispatch(self.api, dict(command='transaction', args=dict(commands=[dict(command='get_lighting')])))
        self.assertTrue(query['ok'], query)
        self.assertEqual(query['result'], [before['lighting']])

    def test_v3_round_trip_and_v1_v2_v3_legacy_defaults(self):
        expected = self.api.set_lighting(mode='Scene', direction=[2, -8, 3], diffuse=2.5, ambient=.04)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scene.json'
            self.api.save_scene(path)
            document = json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(document['version'], 3)
            self.assertEqual(document['lighting']['light_dir'], expected['direction'])
            fresh = Mini3DAPI()
            self.assertEqual(fresh.load_scene(path)['lighting'], expected)
            del document['lighting']
            for version in (1, 2, 3):
                document['version'] = version
                path.write_text(json.dumps(document), encoding='utf8')
                self.assertEqual(fresh.load_scene(path)['lighting'], Mini3DAPI().get_lighting())

    def test_invalid_saved_lighting_leaves_entire_scene_unchanged(self):
        self.api.spawn(PROJECT/'model/06_stl_cube/cube.STL')
        self.api.set_lighting(mode='Scene', direction=[2, 4, -1])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scene.json'
            self.api.save_scene(path)
            document = json.loads(path.read_text(encoding='utf8'))
            before = self.api.get_scene_state()
            for light in (dict(mode=None), dict(light_dir=None), dict(light_dir=[0, 0, 0]),
                          dict(diffuse='2'), dict(ambient=-1), [], None):
                document['lighting'] = light
                path.write_text(json.dumps(document), encoding='utf8')
                with self.assertRaises(ValueError):
                    self.api.load_scene(path)
                self.assertEqual(self.api.get_scene_state(), before)

    def test_editor_controls_share_atomic_validation_and_error_feedback(self):
        ui = EditorUI.__new__(EditorUI)
        ui.app = self.api._app
        ui.lighting_error = ''
        before = self.api.get_lighting()
        ui._apply_lighting(mode='Scene', direction=[0, 0, 0], diffuse=2)
        self.assertEqual(self.api.get_lighting(), before)
        self.assertIn('nonzero', ui.lighting_error)
        ui._apply_lighting(mode='Scene', direction=[2, 3, 0], diffuse=2)
        self.assertEqual(ui.lighting_error, '')
        self.assertEqual(self.api.get_lighting()['direction'], [2., 3., 0.])
        self.assertEqual(self.api.get_lighting()['mode'], 'Scene')


if __name__ == '__main__':
    unittest.main()
