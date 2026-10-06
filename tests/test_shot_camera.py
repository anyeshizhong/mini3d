import math
from types import SimpleNamespace
import unittest

import numpy as np
import pygame

from mini3d.camera import Camera
from mini3d.editor import Editor
from mini3d.shot_camera import ShotCamera


class ShotCameraTests(unittest.TestCase):
    def test_copy_pose_and_lens_are_independent(self):
        view = Camera(position=[3, -4, 5], fov_y=47, near=.02, far=123)
        view.look_at([0, 0, 0])
        shot = ShotCamera(view)
        np.testing.assert_allclose(shot.view_matrix, view.view_matrix)
        self.assertEqual((shot.fov_y, shot.near, shot.far), (47, .02, 123))
        before = shot.view_matrix.copy()
        view.position = [8, 9, 10]
        view.look_at([0, 0, 0])
        view.fov_y = 60
        np.testing.assert_allclose(shot.view_matrix, before)
        self.assertEqual(shot.fov_y, 47)

    def test_focal_presets_and_aspects_preserve_pose_and_focal_length(self):
        shot = ShotCamera(Camera())
        before = shot.view_matrix.copy()
        for focal in (24, 35, 50, 85):
            shot.set_lens(focal)
            for name in ShotCamera.ASPECTS:
                shot.set_aspect(name)
                self.assertAlmostEqual(shot.focal_mm, focal)
                self.assertAlmostEqual(shot.fov_y, math.degrees(2 * math.atan(36 / (2 * shot.aspect * focal))))
                np.testing.assert_allclose(shot.view_matrix, before)
                self.assertTrue(np.isfinite(shot.projection_matrix(shot.aspect)).all())

    def test_fit_rect_centers_and_never_exceeds_available_viewport(self):
        shot = ShotCamera(Camera())
        for name in ShotCamera.ASPECTS:
            shot.set_aspect(name)
            x, y, w, h = shot.fit_rect((100, 80, 650, 450))
            self.assertGreaterEqual(x, 100)
            self.assertGreaterEqual(y, 80)
            self.assertLessEqual(x + w, 750)
            self.assertLessEqual(y + h, 530)
            self.assertLess(abs(w / h - shot.aspect), .005)

    def test_editor_navigation_and_photo_preview_do_not_move_shot(self):
        app = Editor()
        app.create_camera_from_view()
        shot_before = app.shot_camera.view_matrix.copy()
        app.viewer.controller.orbit(100, 20)
        np.testing.assert_allclose(app.shot_camera.view_matrix, shot_before)
        editor_before = app.viewer.camera.view_matrix.copy()
        app.set_camera_view(True)
        ui = SimpleNamespace()
        for event in (pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2, pos=(200, 200)),
                      pygame.event.Event(pygame.MOUSEMOTION, rel=(20, 10), buttons=(0, 1, 0)),
                      pygame.event.Event(pygame.MOUSEWHEEL, y=2),
                      pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f, mod=0)):
            app.handle_event(event, ui)
        np.testing.assert_allclose(app.viewer.camera.view_matrix, editor_before)
        np.testing.assert_allclose(app.shot_camera.view_matrix, shot_before)
        app.set_camera_view(False)
        np.testing.assert_allclose(app.viewer.camera.view_matrix, editor_before)

    def test_capture_and_camera_view_require_explicit_camera_creation(self):
        app = Editor()
        for command in (app.request_capture, lambda: app.set_camera_view(True),
                        lambda: app.set_shot_lens(50), lambda: app.set_shot_aspect('1:1')):
            with self.assertRaises(ValueError):
                command()
        self.assertFalse(app.capture_requested)
        app.create_camera_from_view()
        app.request_capture()
        self.assertTrue(app.capture_requested)


if __name__ == '__main__':
    unittest.main()
