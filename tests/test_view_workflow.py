"""A photo/editor handoff retains framing and settings, with working navigation."""
import unittest
from types import SimpleNamespace
import numpy as np
import pygame
from mini3d.api import Mini3DAPI


class ViewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.api = Mini3DAPI()
        self.app = self.api._app
        self.addCleanup(self.app.model_dialog.close)
        self.api.spawn('builtin:roman-soldier')
        self.api.create_shot_camera(position=[3,-4,2], target=[0,0,1], focal_mm=50, far=100,
                                    f_number=1.4, dof_enabled=True)
        self.api.set_photo_color(7400, 'Warm')
        self.api.set_antialiasing(4)
        self.api.set_view('Camera')

    def test_switch_to_editor_and_back_keeps_projection_and_photo_settings(self):
        original = self.api.get_shot_camera()
        history = self.api.get_scene_state()['history']
        self.api.set_view('Editor')
        editor = self.app.viewer.camera
        np.testing.assert_allclose(editor.position, original['position'])
        np.testing.assert_allclose(editor.rotation, original['rotation'])
        self.assertEqual(editor.fov_y, original['fov_y'])
        self.app.viewer.update_clipping()
        self.assertGreaterEqual(editor.far, original['far'])
        self.api.set_view('Camera')
        current = self.api.get_shot_camera()
        for key in ('position','rotation','fov_y'):
            np.testing.assert_allclose(current[key], original[key], atol=1e-12)
        for key in ('samples','f_number','white_balance_kelvin','color_preset','dof_enabled'):
            self.assertEqual(current[key], original[key])
        self.assertEqual(history, self.api.get_scene_state()['history'])

    def test_wheel_in_photo_view_enters_editing_and_preview_commits_the_new_pose(self):
        original = self.api.get_shot_camera()
        ui = SimpleNamespace(viewport_hovered=True, mouse_captured=False, modal_open=False,
                             asset_dragging=False, keyboard_captured=False)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=1), ui)
        self.assertFalse(self.app.camera_view)
        new_position = self.app.viewer.camera.position.copy()
        self.assertFalse(np.allclose(new_position, original['position']))
        self.api.set_view('Camera')
        np.testing.assert_allclose(self.app.shot_camera.position, new_position)
        self.assertEqual(self.app.shot_camera.f_number, 1.4)

    def test_lens_and_aspect_controls_change_the_camera_currently_being_edited(self):
        self.api.set_view('Editor')
        self.api.set_view_lens(85)
        edit_fov = self.app.viewer.camera.fov_y
        self.assertNotEqual(edit_fov, self.app.shot_camera.fov_y)
        self.api.set_view_aspect('1:1')
        self.api.set_view('Camera')
        self.assertAlmostEqual(self.app.shot_camera.focal_mm, 85)
        self.assertEqual(self.app.shot_camera.aspect_name, '1:1')
        self.assertEqual(self.app.shot_camera.white_balance_kelvin, 7400)

    def test_explicit_api_camera_creation_is_not_overwritten_by_pending_editor_pose(self):
        self.api.set_view('Editor')
        requested = self.api.create_shot_camera(position=[5,-6,3], target=[0,0,1], focal_mm=35)
        self.api.set_view('Camera')
        self.assertEqual(self.api.get_shot_camera(), requested)

    def test_explicit_api_focus_is_not_overwritten_by_the_photo_handoff(self):
        entity_id = self.api.list_entities()[0]['entity_id']
        self.api.focus_entity(entity_id)
        np.testing.assert_allclose(self.app.viewer.controller.target,
            np.mean(list(self.api.get_entity(entity_id,True)['bounds'].values()),axis=0))


if __name__ == '__main__':
    unittest.main()
