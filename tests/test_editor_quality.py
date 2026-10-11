"""Regressions for tiny-focus precision and retained live viewport invalidation."""
import unittest
import numpy as np
from mini3d.editor import Editor
from mini3d.scene import Entity, Mesh
from mini3d.geometry import make_box
from mini3d.viewport_cache import viewport_key
from mini3d.shadow_map import light_matrix
from mini3d.shot_camera import ShotCamera


def box(size=1):
    return Entity(Mesh(*make_box(size, size, size)))


class EditorQualityTests(unittest.TestCase):
    def test_tiny_focus_then_dolly_with_crossing_ground_retains_depth_precision(self):
        for scale in (1e-5, 1, 1e5):
            app = Editor()
            avocado = app.scene.add(box(.06*scale))
            floor = app.scene.add(box(100*scale))
            floor.scale[2] = 0
            app.viewer.focus(avocado)
            app.viewer.controller.zoom(-35)
            distance = app.viewer.controller.distance
            self.assertGreaterEqual(app.viewer.camera.near, distance*9e-4)
            self.assertLess(app.viewer.camera.near, distance*.01 + 1e-12)
            # Nearby real geometry must still be retained even when ground
            # crosses the eye and would otherwise hide the closest depth.
            tiny = app.scene.add(box(distance*1e-5))
            tiny.pos[:] = app.viewer.camera.position + app.viewer.camera.forward*distance*1e-4
            app.viewer.update_clipping()
            self.assertLess(app.viewer.camera.near, distance*1e-4)

    def test_editor_and_shot_shadow_fit_use_identical_camera_and_aspect(self):
        app = Editor()
        subject = app.scene.add(box())
        floor = app.scene.add(Entity(Mesh(*make_box(200, 200, 0))))
        app.viewer.focus(subject)
        app.scene.update()
        camera = app.viewer.camera
        camera.far = 10
        shot = ShotCamera(camera)
        entities = app.scene.get_flat_render_list()
        editor_matrix = light_matrix(entities, [-1, -.35, .3], camera, 2048, shot.aspect)
        shot_matrix = light_matrix(entities, [-1, -.35, .3], shot, 2048)
        np.testing.assert_allclose(editor_matrix, shot_matrix)
        global_matrix = light_matrix(entities, [-1, -.35, .3])
        self.assertGreater(np.linalg.norm(editor_matrix[0,:3]), np.linalg.norm(global_matrix[0,:3])*10)

    def test_transform_cache_tracks_inplace_edits_extra_basis_and_reparenting(self):
        app = Editor()
        first, second, child = Entity(), Entity(), box()
        app.scene.add(first)
        app.scene.add(second)
        first.add_child(child)
        app.scene.update()
        original = child.world_matrix.copy()
        first.pos[0] = 3
        child.extra_local[2,3] = 4
        app.scene.update()
        np.testing.assert_allclose(child.world_matrix[:3,3], [3,0,4])
        second.pos[1] = 5
        second.add_child(child)
        app.scene.update()
        np.testing.assert_allclose(child.world_matrix[:3,3], [0,5,4])
        child.extra_local[2,3] = 0
        child.pos[1] = -5
        app.scene.update()
        np.testing.assert_allclose(child.world_matrix, original)
        child.local_matrix[0,3] = 100
        child.world_matrix[2,3] = 100
        app.scene.update()
        np.testing.assert_allclose(child.world_matrix, original)

    def test_retained_view_invalidates_real_scene_changes_including_undo(self):
        app = Editor()
        subject = app.commands.spawn('builtin:ground')
        def key():
            app.scene.update()
            return viewport_key(app, (800,600), False, 'REALISTIC')
        baseline = key()
        self.assertEqual(key(), baseline)
        app.commands.set_transform(subject, position=[1,0,0])
        self.assertNotEqual(key(), baseline)
        app.commands.undo()
        self.assertEqual(key(), baseline)
        app.scene.light_dir[0] += .1
        lighting = key()
        self.assertNotEqual(lighting, baseline)
        app.viewer.controller.orbit(10,2)
        camera = key()
        self.assertNotEqual(camera, lighting)
        app.select(subject)
        selection = key()
        self.assertNotEqual(selection, camera)
        subject.model.material['pbrMetallicRoughness']['roughnessFactor'] = .2
        self.assertNotEqual(key(), selection)
        subject.visible = False
        hidden = key()
        self.assertNotEqual(hidden, selection)
        app.scene.root_entities.remove(subject)
        app.scene.clean_selection()
        app.sync_selection()
        self.assertNotEqual(key(), hidden)


if __name__ == '__main__':
    unittest.main()
