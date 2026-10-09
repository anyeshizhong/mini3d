"""Issue #3: framing a small object must not clip the rest of the scene."""
import unittest
from pathlib import Path
import tempfile

import numpy as np
from mini3d.geometry import make_box
from mini3d.scene import Scene, Entity, Mesh
from mini3d.viewer import Viewer
from mini3d.viewer import world_bounds
from mini3d.camera import Camera
from mini3d.orbit_controller import OrbitController
from mini3d.editor import Editor
from mini3d.api import Mini3DAPI


def box(size=1, position=(0, 0, 0)):
    vertices, indices = make_box(size, size, size)
    entity = Entity(Mesh(vertices, indices))
    entity.pos[:] = position
    return entity


class SceneClippingTests(unittest.TestCase):
    def assert_covered(self, viewer):
        # Independent actual vertex depths, not the production box helper.
        scene, camera = viewer.scene, viewer.camera
        scene.update()
        for entity in scene.get_flat_render_list():
            depths = -(entity.model.vertices @ entity.world_matrix.T @ camera.view_matrix.T)[:, 2]
            if depths.max() <= 0:
                continue
            self.assertGreater(camera.far, depths.max())
            if depths.min() > 0:
                self.assertLess(camera.near, depths.min())
        self.assertGreater(camera.near, 0)
        self.assertGreater(camera.far, camera.near)

    def test_focus_small_preserves_framing_but_covers_distant_geometry(self):
        scene = Scene()
        small = scene.add(box(.01))
        distant = scene.add(box(2, (-20, 0, 0)))
        viewer = Viewer(scene, 800, 600)
        viewer.controller.set_view('front')
        viewer.focus(small)
        camera = viewer.camera
        np.testing.assert_allclose(viewer.controller.target, small.pos)
        self.assertLess(viewer.controller.distance, .1)
        point = np.append(distant.pos, 1)
        clip = camera.projection_matrix(viewer.aspect) @ camera.view_matrix @ point
        # This point really is inside the lateral field of view, not offscreen.
        self.assertLess(np.max(np.abs(clip[:2]/clip[3])), 1)
        depth = -(camera.view_matrix @ point)[2]
        self.assertGreater(camera.far, depth, 'Focus small incorrectly clips the distant model')

    def test_focus_pose_and_framing_match_original_controller_across_scales(self):
        for scale in (1e-5, 1, 1e5):
            scene = Scene()
            small = scene.add(box(.01*scale))
            scene.add(box(2*scale, (-20*scale, 0, 0)))
            viewer = Viewer(scene, 800, 600)
            original = OrbitController(Camera())
            original.focus_bounds(*world_bounds([small]), aspect=viewer.aspect)
            viewer.focus(small)
            np.testing.assert_allclose(viewer.camera.view_matrix, original.camera.view_matrix)
            np.testing.assert_allclose(viewer.controller.target, original.target)
            self.assertEqual(viewer.controller.distance, original.distance)
            self.assertEqual(viewer.controller._bounds_radius, original._bounds_radius)
            self.assert_covered(viewer)

    def test_orbit_pan_zoom_and_presets_refresh_the_scene_interval(self):
        scene = Scene()
        small = scene.add(box(.01))
        scene.add(box(2, (-20, 0, 0)))
        viewer = Viewer(scene, 800, 600)
        viewer.focus(small)
        for operation in (lambda: viewer.controller.orbit(80, 20),
                          lambda: viewer.controller.pan(100, 40, 600),
                          lambda: viewer.controller.zoom(-30),
                          lambda: viewer.set_view('back'), viewer.reset_camera, viewer.frame_all):
            operation()
            self.assert_covered(viewer)

    def test_scene_mutations_visibility_hierarchy_and_shared_meshes(self):
        app = Editor()
        small = app.scene.add(box(.01))
        app.select(small)
        app.focus_selected()
        original_distance = app.viewer.controller.distance
        parent = app.scene.add(Entity(name='parent'))
        child = box(1, (-20, 3, 2))
        parent.add_child(child)
        parent.rot[:] = [.2, -.3, .8]
        parent.scale[:] = [1, 2, 3]
        parent.pos[:] = [-25, 2, 1]
        app.viewer.update_clipping()
        self.assert_covered(app.viewer)
        broad_far = app.viewer.camera.far
        parent.visible = False
        app.viewer.update_clipping()
        self.assertLess(app.viewer.camera.far, broad_far)
        parent.visible = True
        duplicate = app.commands.duplicate(parent)
        self.assertIs(duplicate.children[0].model, child.model)
        app.commands.set_transform(duplicate, position=[-100, 0, 0], rotation=[.7, .2, -.3], scale=[2, 3, 4])
        app.viewer.update_clipping()
        self.assert_covered(app.viewer)
        far_with_duplicate = app.viewer.camera.far
        app.commands.delete(duplicate)
        app.viewer.update_clipping()
        self.assertLess(app.viewer.camera.far, far_with_duplicate)
        self.assertEqual(app.viewer.controller.distance, original_distance)
        app.commands.undo()
        app.viewer.update_clipping()
        self.assert_covered(app.viewer)

    def test_near_includes_foreground_geometry_without_enormous_far(self):
        scene = Scene()
        scene.add(box(2))
        viewer = Viewer(scene, 800, 600)
        near_original = viewer.camera.near
        tiny = scene.add(box(near_original*.05,
            viewer.camera.position+viewer.camera.forward*(near_original*.2)))
        viewer.update_clipping()
        self.assertLess(viewer.camera.near, near_original*.2)
        self.assert_covered(viewer)
        tiny.visible = False
        viewer.update_clipping()
        self.assertEqual(viewer.camera.near, near_original)
        self.assertLess(viewer.camera.far/viewer.camera.near, 1000)

    def test_boxes_behind_eye_and_hidden_descendants_do_not_expand_far(self):
        scene = Scene()
        scene.add(box())
        viewer = Viewer(scene, 800, 600)
        far = viewer.camera.far
        behind = scene.add(box(1, viewer.camera.position-viewer.camera.forward*1e6))
        hidden = box(100, (-1e8, 0, 0))
        hidden.visible = False
        behind.add_child(hidden)
        viewer.update_clipping()
        self.assertEqual(viewer.camera.far, far)
        crossing = scene.add(box(.1, viewer.camera.position))
        viewer.update_clipping()
        self.assertGreater(viewer.camera.near, 0)
        self.assertTrue(np.isfinite(viewer.camera.projection_matrix(viewer.aspect)).all())

    def test_repeated_navigation_uses_cached_boxes_not_mesh_vertices(self):
        scene = Scene()
        entity = scene.add(box())
        viewer = Viewer(scene, 800, 600)
        class UnreadableVertices:
            def __array__(self, *args, **kwargs):
                raise AssertionError('Per-frame geometry scan is forbidden')
        entity.model.vertices = UnreadableVertices()
        for i in range(10):
            viewer.controller.orbit(i, 2)
            viewer.update_clipping()
            world_bounds(scene.root_entities)

    def test_load_recomputes_live_clipping_and_preserves_explicit_shot_planes(self):
        api = Mini3DAPI()
        small = api.spawn('builtin:ground', scale=[.001]*3)
        api.spawn('builtin:ground', position=[-30, 0, 0], scale=[2]*3)
        app = api._app
        app.select(app.scene.find_by_id(small['entity_id']))
        app.focus_selected()
        shot = api.create_shot_camera(position=[2, -3, 4], target=[0, 0, 0], near=.7, far=7)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scene.json'
            api.save_scene(path)
            api.load_scene(path)
            self.assert_covered(app.viewer)
            app.viewer.controller.orbit(30, 10)
            app.viewer.update_clipping()
            self.assertEqual(api.get_shot_camera(), shot)


if __name__ == '__main__':
    unittest.main()
