"""Scene geometry, display guides and placement queries have separate lifetimes."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.camera import Camera
from mini3d.editor import Editor
from mini3d.placement import create_ground, geometry_bounds, raycast_surface
from mini3d.placement_plane import PlacementPlane
from mini3d.picking import pick_entity
from mini3d.scene import Entity, Mesh

RECT, CENTER = (0, 0, 800, 600), (400, 300)


class GroundSeparationTests(unittest.TestCase):
    def test_default_and_legacy_helper_never_enter_render_list(self):
        app = Editor()
        self.assertIsNone(app.scene.ground)
        self.assertEqual(app.scene.get_flat_render_list(), [])
        app.scene.ground = create_ground()  # Stale helper reference is harmless.
        self.assertEqual(app.scene.get_flat_render_list(), [])
        self.assertEqual(app.scene.root_entities, [])

    def test_grid_does_not_control_plane_and_mesh_hits_have_priority(self):
        app = Editor()
        camera = Camera(position=[0, 0, 10])
        for visible in (True, False):
            app.show_grid = app.scene.show_grid = visible
            hit = raycast_surface(app.scene, camera, CENTER, RECT)
            np.testing.assert_allclose(hit.position, [0,0,0])
            self.assertIsNone(hit.entity)
            self.assertEqual(pick_entity(app.scene, camera, CENTER, RECT), (None,None))
        # A real surface below the fallback plane still takes priority.
        root = app.commands.spawn('builtin:ground', position=[0,0,-2])
        app.commands.lock(root)
        self.assertIs(raycast_surface(app.scene,camera,CENTER,RECT).entity,root)
        self.assertEqual(pick_entity(app.scene,camera,CENTER,RECT),(None,None))
        app.commands.unlock(root)
        self.assertIs(pick_entity(app.scene,camera,CENTER,RECT)[0],root)

    def test_plane_parallel_behind_outside_and_explicit_fallback(self):
        app = Editor()
        plane = PlacementPlane(z=2,size=20)
        self.assertIsNone(plane.intersect([0,0,3],[1,0,0]))
        self.assertIsNone(plane.intersect([0,0,3],[0,0,1]))
        self.assertIsNone(plane.intersect([11,0,3],[0,0,-1]))
        point, distance = plane.intersect([0,0,3],[0,0,-1])
        np.testing.assert_array_equal(point,[0,0,2])
        self.assertEqual(distance,1)
        app.scene.placement_plane = plane
        camera = Camera(position=[11,0,3])
        hit = raycast_surface(app.scene,camera,CENTER,RECT,fallback=[4,5,6])
        np.testing.assert_array_equal(hit.position,[4,5,6])
        with self.assertRaises(ValueError):
            PlacementPlane(z=float('nan'))

    def test_offset_pivot_character_feet_on_locked_steps(self):
        app = Editor()
        # A nested mesh with an offset local origin, to catch pivot-as-foot bugs.
        soldier = Entity(matrix=np.array([[1,0,0,3],[0,1,0,4],[0,0,1,-7],[0,0,0,1]],float))
        child = Entity(Mesh([[0,0,0],[1,0,0],[0,1,2]],[[0,1,2]]))
        soldier.add_child(child)
        soldier.placement_type = 'character'
        soldier.rot[:] = [.4,.2,.7]
        soldier.scale[:] = [.3,.5,.8]
        app.scene.add(soldier)
        vertices = child.model.vertices.copy()
        steps = [app.commands.spawn('builtin:ground', position=[x,0,z], scale=[.1,.1,1])
                 for x,z in ((-2,1),(0,2),(2,3))]
        for step in steps:
            app.commands.lock(step)
            camera = Camera(position=[step.pos[0],0,10])
            hit = raycast_surface(app.scene,camera,CENTER,RECT,exclude=soldier)
            self.assertIs(hit.entity,step)
            app.commands.place_on_surface(soldier,hit)
            low, high = geometry_bounds(soldier)
            self.assertAlmostEqual(low[2],step.pos[2])
            np.testing.assert_allclose((low[:2]+high[:2])/2,hit.position[:2],atol=1e-12)
            np.testing.assert_allclose(soldier.rot,[0,0,.7])
        np.testing.assert_array_equal(child.model.vertices,vertices)

    def test_explicit_ground_uses_commands_ids_history_and_persistence(self):
        api = Mini3DAPI()
        original = api.spawn('builtin:ground', name='My ground', position=[1,2,-3], scale=[2,3,1])
        other = api.duplicate(original['entity_id'])
        self.assertNotEqual(original['entity_id'],other['entity_id'])
        api.delete(other['entity_id'])
        api.undo()
        api.redo()
        api.lock(original['entity_id'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'scene.json'
            api.save_scene(path)
            restored = Mini3DAPI()
            restored.load_scene(path)
            self.assertEqual(restored.list_entities(),api.list_entities())
            self.assertEqual(len(restored._app.scene.get_flat_render_list()),1)
            self.assertIsNone(restored._app.scene.ground)

    def test_old_scene_flags_do_not_resurrect_ground_or_disable_placement(self):
        app = Editor()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'scene.json'
            app.save_scene(path)
            original = json.loads(path.read_text(encoding='utf8'))
            for version in (1,2,3):
                for visible in (True,False):
                    document = dict(original,version=version,ground_visible=visible)
                    document.pop('placement_plane',None)
                    path.write_text(json.dumps(document),encoding='utf8')
                    app.load_scene(path)
                    self.assertEqual(app.scene.get_flat_render_list(),[])
                    self.assertIsNone(app.scene.ground)
                    self.assertTrue(app.scene.placement_plane.enabled)
            app.scene.placement_plane = PlacementPlane(z=5,size=30)
            app.show_grid = False
            app.save_scene(path)
            app.load_scene(path)
            self.assertFalse(app.show_grid)
            self.assertEqual(app.scene.placement_plane.to_dict(),dict(z=5.,size=30.,enabled=True))
            document = json.loads(path.read_text(encoding='utf8'))
            self.assertNotIn('ground_visible',document)


if __name__ == '__main__':
    unittest.main()
