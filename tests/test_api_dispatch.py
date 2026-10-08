"""JSON whitelist, structured errors and atomic command batches."""
import json
import unittest
from unittest.mock import patch
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch, dispatch_json
from mini3d.editor import PROJECT


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()
        result = dispatch(self.api, dict(command='spawn', args=dict(
            asset_path=str(PROJECT / 'model/06_stl_cube/cube.STL'))))
        self.assertTrue(result['ok'], result)
        self.entity_id = result['result']['entity_id']

    def test_round_trip_and_query(self):
        result = json.loads(dispatch_json(self.api, json.dumps(dict(command='get_entity',
            args=dict(entity_id=self.entity_id)))))
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['entity_id'], self.entity_id)
        state = dispatch(self.api, dict(command='get_scene_state'))
        self.assertEqual(len(state['result']['entities']), 1)

    def test_whitelist_and_schema_reject_invalid_calls(self):
        for command in ({'command': '_entity'}, {'command': '__class__'}, {'command': 'close'},
                        {'command': 'undo', 'extra': True}, {'command': 'spawn'},
                        {'command': 'undo', 'args': []}, {'command': 'undo', 'args': {'x': 1}}, [], None):
            result = dispatch(self.api, command)
            self.assertFalse(result['ok'], command)
            self.assertIsInstance(result['error']['message'], str)
        for text in ('{', 'NaN', '{"command":"spawn","args":{"scale":NaN}}'):
            self.assertFalse(json.loads(dispatch_json(self.api, text))['ok'])

    def test_batch_rolls_back_on_failed_command_and_records_one_undo(self):
        args = dict(entity_id=self.entity_id, position=[1, 2, 3])
        bad = dict(command='transaction', args=dict(commands=[
            dict(command='set_transform', args=args),
            dict(command='delete', args=dict(entity_id='ent_missing'))]))
        before = self.api.get_entity(self.entity_id)
        self.assertFalse(dispatch(self.api, bad)['ok'])
        self.assertEqual(self.api.get_entity(self.entity_id), before)
        good = dict(command='transaction', args=dict(label='place', commands=[
            dict(command='set_transform', args=args),
            dict(command='lock', args=dict(entity_id=self.entity_id))]))
        self.assertTrue(dispatch(self.api, good)['ok'])
        self.api.undo()
        self.assertEqual(self.api.get_entity(self.entity_id), before)

    def test_batch_excludes_file_camera_nested_history_and_formation(self):
        for method in ('capture', 'save_scene', 'load_scene', 'create_shot_camera', 'undo', 'redo',
                       'transaction', 'create_rectangular_formation'):
            result = dispatch(self.api, dict(command='transaction', args=dict(commands=[dict(command=method)])))
            self.assertFalse(result['ok'])
            self.assertFalse(self.api.get_scene_state()['history']['active_transaction'])

    def test_missing_id_capture_and_bad_json_have_structured_errors(self):
        self.assertFalse(dispatch(self.api, dict(command='get_entity', args=dict(entity_id='missing')))['ok'])
        self.assertFalse(dispatch(self.api, dict(command='capture', args=dict(path='capture.png')))['ok'])
        self.assertFalse(json.loads(dispatch_json(self.api, 'null'))['ok'])

    def test_engine_errors_are_json_results(self):
        with patch.object(self.api, 'capture', side_effect=Exception('Driver error')):
            result = json.loads(dispatch_json(self.api, '{"command":"capture","args":{"path":"x.png"}}'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['message'], 'Driver error')


if __name__ == '__main__':
    unittest.main()
