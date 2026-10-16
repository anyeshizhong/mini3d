import unittest
from types import SimpleNamespace

import numpy as np
import pygame

from mini3d.camera import Camera
from mini3d.editor import Editor
from mini3d.orbit_controller import OrbitController
from mini3d.shot_camera import ShotCamera


class PhotoNavigationTests(unittest.TestCase):
    def app(self, workspace='Shot'):
        app = Editor()
        camera = Camera([1, -10, 1.7], fov_y=45, near=.01, far=100)
        camera.look_at([1, 20, 1.7])
        app.shot_camera = ShotCamera(camera)
        app.shot_camera.focus_distance = 30
        app.workspace = workspace
        app.viewport_rect = (0, 0, 800, 600)
        app.set_camera_view(True)
        return app

    def ui(self, **changes):
        fields = dict(viewport_hovered=True, modal_open=False, mouse_captured=False,
                      asset_dragging=False, keyboard_captured=False)
        fields.update(changes)
        return SimpleNamespace(**fields)

    def wheel(self, app, y=1, mod=0, **ui):
        app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=y, mod=mod), self.ui(**ui))

    def test_photo_can_pass_original_focus_target_and_reach_far_house(self):
        app = self.app()
        saved_shot = app.shot_camera.to_dict()
        for _ in range(45):
            self.wheel(app)
        np.testing.assert_allclose(app.viewer.camera.position, [1, 35, 1.7], atol=1e-12)
        np.testing.assert_allclose(app.viewer.controller.target, [1, 65, 1.7], atol=1e-12)
        self.assertAlmostEqual(app.viewer.controller.distance, 30)
        self.assertEqual(app.shot_camera.to_dict(), saved_shot)
        app.set_camera_view(True)
        np.testing.assert_allclose(app.shot_camera.position, [1, 35, 1.7], atol=1e-12)
        self.assertEqual(app.shot_camera.fov_y, saved_shot['fov_y'])

    def test_fast_fine_and_reverse_steps(self):
        app = self.app()
        self.wheel(app, mod=pygame.KMOD_SHIFT)
        self.assertAlmostEqual(app.viewer.camera.position[1], -5)
        self.wheel(app, mod=pygame.KMOD_CTRL)
        self.assertAlmostEqual(app.viewer.camera.position[1], -4.9)
        self.wheel(app, y=-1, mod=pygame.KMOD_CTRL)
        self.wheel(app, y=-1, mod=pygame.KMOD_SHIFT)
        np.testing.assert_allclose(app.viewer.camera.position, [1, -10, 1.7], atol=1e-12)

    def test_ui_capture_modal_and_nonviewport_block_movement(self):
        for flags in (dict(mouse_captured=True), dict(modal_open=True),
                      dict(asset_dragging=True), dict(viewport_hovered=False)):
            app = self.app()
            shot = app.shot_camera.to_dict()
            self.wheel(app, **flags)
            self.assertTrue(app.camera_view)
            self.assertEqual(app.shot_camera.to_dict(), shot)

    def test_arrange_preserves_original_orbit_zoom(self):
        app = self.app('Arrange')
        self.wheel(app)
        np.testing.assert_allclose(app.viewer.controller.target, [1, 20, 1.7], atol=1e-12)
        self.assertLess(app.viewer.controller.distance, 30)

    def test_dolly_preserves_roll_lens_distance_and_rejects_nonfinite(self):
        camera = Camera()
        controller = OrbitController(camera, distance=.01)
        roll = np.array([[0., -1, 0], [1, 0, 0], [0, 0, 1]])
        camera.rotation = camera.rotation @ roll
        rotation, fov, distance = camera.rotation, camera.fov_y, controller.distance
        eye, target = camera.position, controller.target.copy()
        forward = camera.forward
        controller.dolly(100)
        np.testing.assert_allclose(camera.position, eye + forward * 100)
        np.testing.assert_allclose(controller.target, target + forward * 100)
        np.testing.assert_array_equal(camera.rotation, rotation)
        self.assertEqual((camera.fov_y, controller.distance), (fov, distance))
        with self.assertRaises(ValueError):
            controller.dolly(float('nan'))


if __name__ == '__main__':
    unittest.main()
