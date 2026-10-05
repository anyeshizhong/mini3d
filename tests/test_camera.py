"""Camera navigation regressions; run without an OpenGL window.

    F:/gymenv/python.exe -B -m unittest discover -s tests -v
"""

import itertools
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pygame

from mini3d.camera import Camera
from mini3d.cpu_renderer import Renderer
from mini3d.orbit_controller import OrbitController
from mini3d.viewer import Viewer, world_bounds


def corners(minimum, maximum):
    return np.array(list(itertools.product(*zip(minimum, maximum))))


def ndc(camera, points, aspect):
    homogeneous = np.column_stack((np.atleast_2d(points), np.ones(len(np.atleast_2d(points)))))
    clip = homogeneous @ (camera.projection_matrix(aspect) @ camera.view_matrix).T
    return clip[:, :3] / clip[:, 3:4], clip[:, 3]


class CameraTests(unittest.TestCase):
    def test_view_maps_eye_to_origin_and_target_to_negative_z(self):
        camera = Camera(position=(8, -3, 6))
        target = np.array((1, 2, -1))
        camera.look_at(target)
        np.testing.assert_allclose(camera.view_matrix @ [8, -3, 6, 1], [0, 0, 0, 1], atol=1e-10)
        view_target = camera.view_matrix @ np.append(target, 1)
        np.testing.assert_allclose(view_target[:2], [0, 0], atol=1e-10)
        self.assertAlmostEqual(view_target[2], -np.linalg.norm(target - camera.position))
        rotation = camera.view_matrix[:3, :3]
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-10)
        self.assertAlmostEqual(np.linalg.det(rotation), 1.0)

    def test_projection_maps_near_and_far_to_opengl_depth_limits(self):
        camera = Camera(position=(0, 0, 0), near=0.025, far=730)
        projected, w = ndc(camera, [[0, 0, -camera.near], [0, 0, -camera.far]], 1.5)
        np.testing.assert_allclose(projected[:, 2], [-1, 1], atol=1e-10)
        self.assertTrue(np.all(w > 0))

    def test_resize_keeps_vertical_fov_and_square_pixels(self):
        camera = Camera(position=(0, 0, 0))
        projected = []
        for width, height in [(800, 600), (1600, 600), (600, 1000)]:
            points, _ = ndc(camera, [[1, 0, -10], [0, 1, -10]], width / height)
            pixel_x = points[0, 0] * width / 2
            pixel_y = points[1, 1] * height / 2
            self.assertAlmostEqual(pixel_x, pixel_y)
            projected.append(points)
        self.assertAlmostEqual(projected[0][1, 1], projected[1][1, 1])
        self.assertAlmostEqual(projected[0][0, 0], projected[1][0, 0] * 2)

    def test_look_at_world_up_pole_remains_finite(self):
        for position in [(0, 0, 10), (0, 0, -10)]:
            with self.subTest(position=position):
                camera = Camera(position=position)
                camera.look_at((0, 0, 0))
                self.assertTrue(np.all(np.isfinite(camera.view_matrix)))
                self.assertAlmostEqual(np.linalg.det(camera.view_matrix[:3, :3]), 1.0)


class OrbitControllerTests(unittest.TestCase):
    def make_controller(self, **kwargs):
        camera = Camera()
        return camera, OrbitController(camera, **kwargs)

    def test_presets_have_exact_axes_and_consistent_handedness(self):
        camera, controller = self.make_controller(target=(4, 5, 6), distance=20)
        directions = {
            "front": (1, 0, 0), "back": (-1, 0, 0),
            "right": (0, 1, 0), "left": (0, -1, 0),
            "top": (0, 0, 1), "bottom": (0, 0, -1),
        }
        for name, direction in directions.items():
            with self.subTest(view=name):
                controller.set_view(name)
                np.testing.assert_allclose((camera.position - controller.target) / controller.distance,
                                           direction, atol=1e-12)
                np.testing.assert_allclose(camera.forward, -np.array(direction), atol=1e-12)
                self.assertAlmostEqual(np.linalg.det(camera.rotation), 1)
                projected, _ = ndc(camera, [controller.target], 1)
                np.testing.assert_allclose(projected[0, :2], [0, 0], atol=1e-12)

    def test_front_projects_positive_y_right_and_positive_z_up(self):
        camera, controller = self.make_controller()
        controller.set_view("front")
        points, _ = ndc(camera, [[0, 1, 0], [0, 0, 1]], 1)
        self.assertGreater(points[0, 0], 0)
        self.assertGreater(points[1, 1], 0)

    def test_top_is_exact_and_drag_from_pole_does_not_flip(self):
        camera, controller = self.make_controller()
        controller.set_view("top")
        np.testing.assert_allclose(camera.up, [-1, 0, 0], atol=1e-12)
        old_right = camera.right.copy()
        controller.orbit(0, -1)
        self.assertGreater(np.dot(old_right, camera.right), 0.999)
        self.assertTrue(np.all(np.isfinite(camera.view_matrix)))

    def test_pitch_clamps_before_upside_down_even_for_huge_drag(self):
        camera, controller = self.make_controller()
        for dy in [1e6, -1e6]:
            controller.orbit(0, dy)
            self.assertLessEqual(abs(controller.pitch), math.radians(89.5) + 1e-12)
            self.assertGreater(camera.up[2], 0)
            self.assertTrue(np.all(np.isfinite(camera.view_matrix)))

    def test_pan_moves_scene_by_requested_pixels_in_screen_space(self):
        camera, controller = self.make_controller(target=(2, -4, 5), yaw=0.7, pitch=0.6)
        stationary_point = controller.target.copy()
        before_eye = camera.position.copy()
        before_target = controller.target.copy()
        before, _ = ndc(camera, [stationary_point], 800 / 600)
        controller.pan(45, -27, 600)
        after, _ = ndc(camera, [stationary_point], 800 / 600)
        pixel_delta = (after[0, :2] - before[0, :2]) * [400, -300]
        np.testing.assert_allclose(pixel_delta, [45, -27], atol=1e-9)
        np.testing.assert_allclose(camera.position - before_eye, controller.target - before_target,
                                   atol=1e-10)

    def test_pan_sensitivity_scales_with_distance(self):
        displacements = []
        for distance in [0.01, 1, 100]:
            _, controller = self.make_controller(distance=distance)
            start = controller.target.copy()
            controller.pan(12, 30, 600)
            displacements.append((controller.target - start) / distance)
        np.testing.assert_allclose(displacements, np.tile(displacements[0], (3, 1)), atol=1e-12)

    def test_zoom_ratio_is_scale_independent_and_reversible(self):
        ratios = []
        for distance in [0.01, 1, 100]:
            camera, controller = self.make_controller(distance=distance)
            target = controller.target.copy()
            controller.zoom(1)
            self.assertLess(controller.distance, distance)
            ratios.append(controller.distance / distance)
            np.testing.assert_allclose(controller.target, target)
            self.assertAlmostEqual(np.linalg.norm(camera.position - target), controller.distance)
            controller.zoom(-1)
            self.assertAlmostEqual(controller.distance, distance)
        np.testing.assert_allclose(ratios, [ratios[0]] * 3)

    def test_zoom_extremes_remain_finite_and_positive(self):
        camera, controller = self.make_controller()
        for delta in [1e6, -1e6]:
            controller.zoom(delta)
            self.assertTrue(np.isfinite(controller.distance))
            self.assertGreater(controller.distance, 0)
            self.assertGreaterEqual(controller.distance, controller.min_distance)
            self.assertLessEqual(controller.distance, controller.max_distance)
            self.assertTrue(np.all(np.isfinite(camera.view_matrix)))

    def test_focus_fits_all_corners_at_multiple_scales_aspects_and_views(self):
        for scale, aspect, view in itertools.product(
                [0.00001, 0.01, 2, 50, 100000], [0.25, 1, 4], ["front", "top", None]):
            with self.subTest(scale=scale, aspect=aspect, view=view):
                camera, controller = self.make_controller(yaw=0.73, pitch=0.41)
                if view:
                    controller.set_view(view)
                center = np.array([2, -3, 5]) * scale
                extent = np.array([1, 3, 0.5]) * scale
                minimum, maximum = center - extent, center + extent
                controller.focus_bounds(minimum, maximum, aspect)
                projected, w = ndc(camera, corners(minimum, maximum), aspect)
                self.assertTrue(np.all(w > 0))
                self.assertTrue(np.all(np.abs(projected) <= 1 + 1e-9), projected)
                np.testing.assert_allclose(controller.target, center, atol=1e-10)
                self.assertGreater(camera.near, 0)
                self.assertGreater(camera.far, camera.near)

    def test_focus_zero_size_point_still_produces_valid_camera(self):
        camera, controller = self.make_controller()
        controller.focus_bounds((4, 5, 6), (4, 5, 6), 1)
        projected, w = ndc(camera, [[4, 5, 6]], 1)
        self.assertTrue(np.all(np.isfinite(projected)))
        self.assertTrue(np.all(np.abs(projected) <= 1))
        self.assertGreater(w[0], 0)

    def test_focus_preserves_useful_depth_precision_across_scales(self):
        for scale in [1e-5, 1, 1e5]:
            with self.subTest(scale=scale):
                camera, controller = self.make_controller()
                controller.focus_bounds(np.array([-1, -2, -3]) * scale,
                                        np.array([1, 2, 3]) * scale, 4 / 3)
                # A framed object should not spend almost all depth precision
                # on a near plane many orders of magnitude before the model.
                self.assertGreaterEqual(camera.near / controller.distance, 0.001)
                self.assertLess(camera.far / camera.near, 1000)
                self.assertLess(camera.near, controller.distance)
                self.assertGreater(camera.far, controller.distance)

    def test_snapshot_restore_recovers_complete_view_after_navigation(self):
        camera, controller = self.make_controller()
        controller.focus_bounds((-1, -2, -3), (3, 4, 5), 1.3)
        original_view = camera.view_matrix.copy()
        original_projection = camera.projection_matrix(1.3).copy()
        state = controller.snapshot()
        controller.orbit(100, -60)
        controller.pan(25, 30, 600)
        controller.zoom(4)
        camera.fov_y = 35
        controller.restore(state)
        np.testing.assert_allclose(camera.view_matrix, original_view, atol=1e-10)
        np.testing.assert_allclose(camera.projection_matrix(1.3), original_projection, atol=1e-10)


class CpuRendererTests(unittest.TestCase):
    @staticmethod
    def scene_with_triangle(depth):
        mesh = SimpleNamespace(
            vertices=np.array([[1, 1, depth, 1], [3, 1, depth, 1], [1, 3, depth, 1]]),
            indices=np.array([[0, 1, 2]]),
            colors=np.array([[255, 0, 0]]),
            vertex_normals=np.tile([0, 0, 1], (3, 1)),
        )
        entity = SimpleNamespace(model=mesh, world_matrix=np.eye(4), isaxes=False)
        return SimpleNamespace(get_flat_render_list=lambda: [entity],
                               light_dir=np.array([0, 0, 1]), ambient=1, diffuse=0)

    def test_new_camera_draws_positive_x_y_in_upper_right(self):
        camera = Camera(position=(0, 0, 0), near=1, far=20)
        self.assertFalse(hasattr(camera, "fov"))
        surface = pygame.Surface((200, 200))
        surface.fill((0, 0, 0))
        Renderer(surface).render(self.scene_with_triangle(-10), camera)
        # In OpenGL coordinates +X is screen-right and +Y is screen-up.
        self.assertEqual(surface.get_at((125, 70))[:3], (255, 0, 0))
        self.assertEqual(surface.get_at((125, 130))[:3], (0, 0, 0))
        self.assertEqual(surface.get_at((75, 70))[:3], (0, 0, 0))

    def test_near_far_and_behind_camera_triangles_are_rejected(self):
        camera = Camera(position=(0, 0, 0), near=1, far=20)
        surface = pygame.Surface((200, 200))
        for depth in [-0.5, -30, 10]:
            with self.subTest(depth=depth):
                surface.fill((0, 0, 0))
                Renderer(surface).render(self.scene_with_triangle(depth), camera)
                self.assertFalse(np.any(pygame.surfarray.array3d(surface)))


class ViewerTests(unittest.TestCase):
    @staticmethod
    def mesh_entity(minimum=(-1, -1, -1), maximum=(1, 1, 1), transform=None, children=()):
        return SimpleNamespace(
            model=SimpleNamespace(vertices=corners(minimum, maximum)),
            world_matrix=np.eye(4) if transform is None else transform,
            children=list(children),
        )

    def make_scene(self, entities):
        return SimpleNamespace(root_entities=entities, update=lambda: None)

    def test_world_bounds_include_transformed_descendants_of_empty_container(self):
        # A nonuniformly scaled box, rotated 90 degrees about Z and translated.
        transform = np.array([[0, -3, 0, 10], [2, 0, 0, -5], [0, 0, .5, 7], [0, 0, 0, 1]])
        child = self.mesh_entity((-1, -2, -4), (1, 2, 4), transform)
        parent = SimpleNamespace(model=None, children=[child])
        minimum, maximum = world_bounds([parent])
        np.testing.assert_allclose(minimum, [4, -7, 5])
        np.testing.assert_allclose(maximum, [16, -3, 9])

    def test_focus_refreshes_transforms_and_home_frames_scene(self):
        entity = self.mesh_entity()
        distant = self.mesh_entity((99, -1, -1), (101, 1, 1))
        scene = self.make_scene([entity, distant])
        viewer = Viewer(scene, 600, 800)
        np.testing.assert_allclose(viewer.controller.target, [50, 0, 0])

        def update():
            entity.world_matrix[0, 3] = 8

        scene.update = update
        viewer.selected_entity = entity
        viewer.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
        np.testing.assert_allclose(viewer.controller.target, [8, 0, 0])
        viewer.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_HOME))
        np.testing.assert_allclose(viewer.controller.target, [54, 0, 0])
        projected, w = ndc(viewer.camera, corners(*world_bounds(scene.root_entities)), viewer.aspect)
        self.assertTrue(np.all(w > 0))
        self.assertTrue(np.all(np.abs(projected) <= 1))

    def test_empty_scene_and_mesh_are_safe_to_frame(self):
        empty = self.mesh_entity()
        empty.model.vertices = np.empty((0, 4))
        scene = self.make_scene([empty])
        viewer = Viewer(scene, 800, 600)
        self.assertIsNone(world_bounds(scene.root_entities))
        self.assertFalse(viewer.frame_all())
        self.assertFalse(viewer.focus(empty))
        self.assertFalse(viewer.focus(None))
        self.assertTrue(np.all(np.isfinite(viewer.camera.view_matrix)))

    def test_resize_event_and_minimized_window_keep_projection_valid(self):
        viewer = Viewer(self.make_scene([]), 800, 600)
        old_projection = viewer.camera.projection_matrix(viewer.aspect)
        viewer.handle_event(pygame.event.Event(pygame.VIDEORESIZE, w=1600, h=600))
        new_projection = viewer.camera.projection_matrix(viewer.aspect)
        self.assertAlmostEqual(old_projection[0, 0], new_projection[0, 0] * 2)
        self.assertAlmostEqual(old_projection[1, 1], new_projection[1, 1])
        viewer.resize(0, 0)
        self.assertTrue(np.all(np.isfinite(viewer.camera.projection_matrix(viewer.aspect))))

    def test_drag_stops_after_release_or_window_focus_loss(self):
        viewer = Viewer(self.make_scene([]), 800, 600)
        with patch("pygame.key.get_mods", return_value=0):
            for end_event in [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1),
                              pygame.event.Event(pygame.WINDOWFOCUSLOST)]:
                viewer.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1))
                viewer.handle_event(pygame.event.Event(pygame.MOUSEMOTION, rel=(20, 10), buttons=(1, 0, 0)))
                viewer.handle_event(end_event)
                view = viewer.camera.view_matrix.copy()
                viewer.handle_event(pygame.event.Event(pygame.MOUSEMOTION, rel=(50, 20), buttons=(0, 0, 0)))
                np.testing.assert_allclose(viewer.camera.view_matrix, view)

    def test_shift_drag_pans_and_r_restores_startup_frame(self):
        viewer = Viewer(self.make_scene([self.mesh_entity()]), 800, 600)
        initial_view = viewer.camera.view_matrix.copy()
        initial_target = viewer.controller.target.copy()
        initial_forward = viewer.camera.forward.copy()
        with patch("pygame.key.get_mods", return_value=pygame.KMOD_SHIFT):
            viewer.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1))
            viewer.handle_event(pygame.event.Event(pygame.MOUSEMOTION, rel=(50, 20), buttons=(1, 0, 0)))
        self.assertFalse(np.allclose(initial_target, viewer.controller.target))
        np.testing.assert_allclose(viewer.camera.forward, initial_forward)
        viewer.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=2))
        viewer.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r))
        np.testing.assert_allclose(viewer.camera.view_matrix, initial_view)


if __name__ == "__main__":
    unittest.main()
