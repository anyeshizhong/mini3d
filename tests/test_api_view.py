"""Shared visible camera control, validation, and query/write round trips."""
import json
import unittest

import numpy as np

from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch, BATCH_METHODS, READ_METHODS
from mini3d.editor_ui import EditorUI


class ViewAPITests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()
        self.app = self.api._app
        self.addCleanup(self.app.model_dialog.close)
        self.entity = self.api.spawn('builtin:roman-soldier')
        self.ui = EditorUI.__new__(EditorUI)
        self.ui.app = self.app

    def test_workspace_is_shared_in_both_directions_and_view_switch_is_explicit(self):
        self.api.set_workspace('Lighting')
        self.assertEqual(self.ui.workspace, 'Lighting')
        self.assertFalse(self.ui.assets_visible)
        self.ui._choose_workspace('Shot')
        self.assertEqual(self.api.get_view_state()['workspace'], 'Shot')
        self.assertIsNone(self.app.shot_camera)
        before = self.api.get_view_state()
        with self.assertRaises(ValueError):
            self.api.set_view('Camera')
        self.assertEqual(before, self.api.get_view_state())
        self.api.create_shot_camera()
        state = self.api.set_view('Camera')
        self.assertEqual(state['active_camera'], self.api.get_shot_camera())
        self.assertTrue(self.app.camera_view)
        self.ui._choose_workspace('Arrange')
        self.assertEqual(self.api.get_view_state()['view'], 'Editor')
        self.assertTrue(self.ui.assets_visible)

    def test_scale_then_focus_moves_the_displayed_editor_not_the_shot_and_keeps_history(self):
        self.api.frame_all()
        self.api.create_camera_from_view()
        shot = self.api.get_shot_camera()
        self.api.set_view('Camera')
        initial_distance = self.app.viewer.controller.distance
        self.api.set_transform(self.entity['entity_id'], scale=[.01]*3)
        history = self.api.get_scene_state()['history']
        state = self.api.focus_entity(self.entity['entity_id'])
        self.assertEqual(state['view'], 'Editor')
        self.assertEqual(state['selected_ids'], [self.entity['entity_id']])
        self.assertLess(self.app.viewer.controller.distance, initial_distance / 10)
        self.assertEqual(state['active_camera']['position'], self.app.viewer.camera.position.tolist())
        self.assertEqual(shot, self.api.get_shot_camera())
        self.assertEqual(history, self.api.get_scene_state()['history'])
        self.api.undo()
        self.assertEqual(self.api.get_entity(self.entity['entity_id'])['scale'], [1, 1, 1])

    def test_pose_and_copy_use_the_real_view_and_navigation_remains_valid(self):
        state = self.api.set_editor_camera(position=[2, -3, 1], target=[0, 0, .5], fov_y=45)
        np.testing.assert_allclose(state['active_camera']['position'], [2, -3, 1])
        self.api.set_workspace('Shot')
        shot = self.api.create_camera_from_view()
        np.testing.assert_allclose(shot['position'], self.app.viewer.camera.position)
        np.testing.assert_allclose(shot['rotation'], self.app.viewer.camera.rotation)
        self.assertEqual(shot['fov_y'], 45)
        self.app.viewer.controller.orbit(10, 5)
        self.assertNotEqual(self.api.get_editor_camera()['position'], shot['position'])
        self.assertEqual(self.api.get_shot_camera(), shot)
        self.api.set_editor_view('top')
        np.testing.assert_allclose(self.app.viewer.camera.forward, [0, 0, -1], atol=1e-12)

    def test_invalid_mutations_and_placement_batches_leave_view_and_history_unchanged(self):
        self.api.frame_all()
        before = self.api.get_view_state()
        history = self.api.get_scene_state()['history']
        cases = [('set_workspace', dict(workspace='unknown')),
                 ('set_view', dict(view='unknown')),
                 ('focus_entity', dict(entity_id='missing')),
                 ('set_editor_view', dict(preset='unknown')),
                 ('set_editor_camera', dict(position=[0,0,0], target=[0,0,0])),
                 ('set_editor_camera', dict(position=[1,2,3], target=[0,0,0], fov_y=180)),
                 ('set_editor_camera', dict(position=[1,2], target=[0,0,0])),
                 ('select_entities', dict(entity_ids=['missing']))]
        for command, args in cases:
            with self.subTest(command=command, args=args):
                self.assertFalse(dispatch(self.api, dict(command=command, args=args))['ok'])
                self.assertEqual(before, self.api.get_view_state())
                self.assertEqual(history, self.api.get_scene_state()['history'])
        for command in ('set_view', 'set_workspace', 'select_entities', 'frame_all',
                        'focus_entity', 'set_editor_view', 'set_editor_camera', 'create_camera_from_view'):
            self.assertNotIn(command, BATCH_METHODS)
        self.assertIn('get_view_state', READ_METHODS)
        with self.api.transaction():
            for command, args in [('frame_all', {}), ('set_workspace', {'workspace':'Shot'})]:
                self.assertFalse(dispatch(self.api, dict(command=command, args=args))['ok'])

    def test_no_window_is_not_reported_as_a_displayed_frame_and_snapshots_are_detached(self):
        result = dispatch(self.api, dict(command='get_view_state'))
        self.assertTrue(result['ok'])
        state = result['result']
        self.assertIsNone(state['displayed_frame'])
        self.assertFalse(state['view_matches_displayed_frame'])
        json.dumps(state, allow_nan=False)
        state['active_camera']['position'][0] = 1e6
        self.assertNotEqual(self.app.viewer.camera.position[0], 1e6)

    def test_lens_values_from_query_can_be_written_back(self):
        for lens in (24, 35, 50, 85):
            first = self.api.create_shot_camera(focal_mm=lens)
            second = self.api.create_shot_camera(focal_mm=first['focal_mm'])
            self.assertAlmostEqual(first['focal_mm'], second['focal_mm'])
            self.api.set_lens(second['focal_mm'])
        before = self.api.get_shot_camera()
        for bad in (49.9, True, '50', float('nan')):
            with self.assertRaises(ValueError):
                self.api.set_lens(bad)
            self.assertEqual(before, self.api.get_shot_camera())


if __name__ == '__main__':
    unittest.main()
