"""API works without an Editor UI or OpenGL context; results are detached data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from stl import mesh, Mode
from mini3d.api import Mini3DAPI
from mini3d.editor import PROJECT


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.asset = self.directory / 'unit.stl'
        source = mesh.Mesh.from_file(str(PROJECT / 'model/06_stl_cube/cube.STL'), mode=Mode.BINARY)
        low, high = source.vectors.min(axis=(0, 1)), source.vectors.max(axis=(0, 1))
        source.vectors[:] = (source.vectors - (low + high) / 2) / (high - low)
        source.save(str(self.asset), mode=Mode.BINARY)
        self.api = Mini3DAPI()

    def tearDown(self):
        self.temp.cleanup()

    def spawn(self, **kwargs):
        return self.api.spawn(str(self.asset), **kwargs)

    def test_observation_is_json_safe_detached_and_stable_id_based(self):
        a, b = self.spawn(name='same'), self.spawn(name='same')
        self.assertNotEqual(a['entity_id'], b['entity_id'])
        a['position'][0] = 999
        self.assertEqual(self.api.get_entity(a['entity_id'])['position'][0], 0)
        group = self.api.create_group([a['entity_id'], b['entity_id']], name='pair')
        group['member_ids'].clear()
        self.assertEqual(len(self.api.get_group(group['group_id'])['member_ids']), 2)
        json.dumps(self.api.get_scene_state(include_bounds=True), allow_nan=False)
        with self.assertRaises(ValueError):
            self.api.get_entity('same')
        with self.assertRaises(ValueError):
            self.api.get_group('missing')
        with self.assertRaises(ValueError):
            self.api.get_entity(object())

    def test_placement_delegates_and_ground_is_idempotent_and_finite(self):
        root = self.spawn(rotation=[.2, .3, .7], scale=[2, 1, 3], placement_type='character')
        entity_id = root['entity_id']
        with patch.object(self.api._commands, 'place_on_surface', wraps=self.api._commands.place_on_surface) as call:
            placed = self.api.place_on_ground(entity_id, x=3, y=4)
            self.assertEqual(call.call_count, 1)
        bounds = self.api.get_entity(entity_id, include_bounds=True)['bounds']
        self.assertAlmostEqual(bounds['minimum'][2], 0)
        self.assertEqual(placed['rotation'][:2], [0, 0])
        np.testing.assert_array_equal(self.api.place_on_ground(entity_id)['position'], placed['position'])
        self.api.place_at(entity_id, [3, 4, 7])
        self.assertAlmostEqual(self.api.get_entity(entity_id, True)['bounds']['minimum'][2], 7)
        pivot = self.api.place_at(entity_id, [1, 2, 3], anchor='pivot')
        self.assertEqual(pivot['position'], [1, 2, 3])
        with self.assertRaises(ValueError):
            self.api.place_on_ground(entity_id, x=1001)

    def test_duplicate_lock_delete_and_undo_reuse_commands(self):
        entity_id = self.spawn()['entity_id']
        self.api.lock(entity_id)
        with self.assertRaises(ValueError):
            self.api.set_transform(entity_id, position=[1, 0, 0])
        with self.assertRaises(ValueError):
            self.api.delete(entity_id)
        duplicate = self.api.duplicate(entity_id)
        self.assertFalse(duplicate['locked'])
        self.assertIs(self.api._entity(entity_id).model, self.api._entity(duplicate['entity_id']).model)
        self.api.unlock(entity_id)
        self.api.delete(duplicate['entity_id'])
        self.assertTrue(self.api.undo()['changed'])
        self.assertEqual(self.api.get_entity(duplicate['entity_id']), duplicate)
        self.assertTrue(self.api.redo()['changed'])
        self.assertEqual(len(self.api.list_entities()), 1)

    def test_transactions_batch_and_rollback_without_reusing_ids(self):
        with self.api.transaction('two instances'):
            first = self.spawn()
            second = self.spawn()
            self.api.set_transform(first['entity_id'], position=[1, 2, 3])
        self.assertEqual(self.api.get_scene_state()['history']['undo_count'], 1)
        self.api.undo()
        self.assertEqual(self.api.list_entities(), [])
        self.api.redo()
        with self.assertRaises(ValueError):
            with self.api.transaction():
                failed = self.spawn()
                self.api.set_transform(first['entity_id'], scale=[0, 1, 1])
        self.assertEqual(len(self.api.list_entities()), 2)
        self.assertGreater(int(self.spawn()['entity_id'][4:]), int(failed['entity_id'][4:]))

    def test_formation_transform_save_reload_and_camera(self):
        entity_id = self.spawn()['entity_id']
        self.api.place_on_ground(entity_id)
        group = self.api.create_rectangular_formation(entity_id, 5, 8, 1.2, 1.4)
        self.assertEqual(len(self.api.list_entities()), 40)
        self.assertEqual(len(set(group['member_ids'])), 40)
        self.api.undo()
        self.assertEqual(len(self.api.list_entities()), 1)
        self.api.redo()
        self.assertEqual(self.api.get_group(group['group_id']), group)
        self.api.lock(group['member_ids'][-1])
        locked = self.api.get_entity(group['member_ids'][-1])
        changed = self.api.transform_many(group['member_ids'], translation=[2, 3, 0], rotation=[0, 0, .4])
        self.assertEqual(len(changed), 39)
        self.assertEqual(self.api.get_entity(locked['entity_id']), locked)
        document = self.directory / 'scene.json'
        self.api.save_scene(document)
        fresh = Mini3DAPI()
        state = fresh.load_scene(document)
        self.assertEqual(state['entities'], self.api.list_entities())
        self.assertEqual(state['groups'], [group])
        self.assertEqual(state['history']['undo_count'], 0)
        camera = fresh.create_shot_camera(focal_mm=50, aspect='16:9')
        self.assertAlmostEqual(camera['focal_mm'], 50)
        self.assertEqual((camera['width'], camera['height']), (1920, 1080))
        with self.assertRaisesRegex(RuntimeError, 'OpenGL'):
            fresh.capture(self.directory / 'not-created.png')
        self.assertFalse((self.directory / 'not-created.png').exists())

    def test_invalid_load_and_camera_creation_leave_old_state(self):
        self.spawn()
        before = self.api.get_scene_state()
        bad = self.directory / 'bad.json'
        bad.write_text('{"version":99}')
        with self.assertRaises(ValueError):
            self.api.load_scene(bad)
        self.assertEqual(before, self.api.get_scene_state())
        old = self.api.create_shot_camera(position=[4, -5, 6], target=[0, 0, 0])
        with self.assertRaises(ValueError):
            self.api.create_shot_camera(focal_mm=999)
        self.assertEqual(self.api.get_shot_camera(), old)
        self.assertAlmostEqual(self.api.set_lens(85)['focal_mm'], 85)
        self.assertEqual(self.api.set_aspect('1:1')['width'], 1920)
        self.assertEqual(self.api.get_shot_camera()['height'], 1920)

    def test_capture_requires_current_context_even_with_a_renderer(self):
        api = Mini3DAPI(renderer=object())
        api.create_shot_camera(position=[3, -4, 5], target=[0, 0, 0])
        with patch('OpenGL.GL.glGetString', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'current OpenGL context'):
                api.capture(self.directory / 'missing-context.png')
        self.assertFalse((self.directory / 'missing-context.png').exists())

    def test_side_effects_cannot_silently_commit_an_active_transaction(self):
        entity_id = self.spawn()['entity_id']
        path = self.directory / 'forbidden.json'
        for action in (lambda: self.api.save_scene(path), lambda: self.api.load_scene(path),
                       self.api.create_shot_camera, lambda: self.api.set_lens(50),
                       lambda: self.api.capture(self.directory / 'forbidden.png'),
                       lambda: self.api.create_rectangular_formation(entity_id, 1, 2, 1, 1)):
            with self.subTest(action=action), self.assertRaises(ValueError):
                with self.api.transaction():
                    self.api.set_transform(entity_id, position=[4, 0, 0])
                    action()
            self.assertEqual(self.api.get_entity(entity_id)['position'], [0, 0, 0])
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
