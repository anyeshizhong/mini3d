"""Directional shadow projection and public controls, without a GL context."""
import json
from itertools import product
from pathlib import Path
import tempfile
import unittest
import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch
from mini3d.geometry import make_box
from mini3d.scene import Entity, Mesh, Scene
from mini3d.shadow_map import light_matrix


class ShadowTests(unittest.TestCase):
    def test_fit_rotated_hierarchy_and_scales(self):
        vertices, indices = make_box(2, 3, 4)
        for scale in (1e-5, 1, 1e5):
            scene = Scene()
            parent = Entity()
            parent.pos[:] = np.array([3,-5,7])*scale
            parent.scale[:] = scale
            parent.rot[:] = [.3,.2,-.7]
            child = Entity(Mesh(vertices,indices))
            child.pos[:] = [100,0,0]
            child.scale[:] = [-2,.3,4]
            parent.add_child(child)
            scene.add(parent)
            scene.update()
            for direction in ((1,0,0),(0,0,1),(0,1,0),(1,-2,3)):
                matrix = light_matrix(scene.get_flat_render_list(),direction)
                corners = np.array(list(product(*zip(*child.model.bounds))))
                world = corners @ child.world_matrix[:3,:3].T + child.world_matrix[:3,3]
                clip = world @ matrix[:3,:3].T + matrix[:3,3]
                self.assertTrue(np.isfinite(clip).all())
                self.assertLess(np.abs(clip).max(),1)

    def test_light_direction_sign_and_camera_independence(self):
        scene = Scene()
        v,i = make_box(2,2,2)
        scene.add(Entity(Mesh(v,i)))
        scene.update()
        matrix = light_matrix(scene.get_flat_render_list(),(0,0,1))
        self.assertLess((matrix @ [0,0,1,1])[2], (matrix @ [0,0,-1,1])[2])
        api = Mini3DAPI()
        api._app.viewer.controller.orbit(90,30)
        api._app.viewer.controller.pan(40,20,600)
        np.testing.assert_array_equal(matrix,light_matrix(scene.get_flat_render_list(),(0,0,1)))

    def test_empty_hidden_and_cached_bounds(self):
        scene = Scene()
        v,i = make_box(1,1,1)
        entity = Entity(Mesh(v,i))
        scene.add(entity)
        scene.update()
        entity.model.vertices = None  # depth fitting must never touch vertices
        self.assertIsNotNone(light_matrix(scene.get_flat_render_list(),(1,2,3)))
        entity.visible = False
        self.assertIsNone(light_matrix(scene.get_flat_render_list(),(1,2,3)))

    def test_atomic_controls_and_dispatch(self):
        api = Mini3DAPI()
        old = api.get_shadows()
        self.assertFalse(old['enabled'])
        for args in ({'resolution':1023},{'resolution':True},{'bias':float('nan')},
                     {'bias':-.1},{'pcf':1},{'enabled':'yes'}):
            with self.assertRaises(ValueError):
                api.set_shadows(**dict({'enabled':True},**args))
            self.assertEqual(api.get_shadows(),old)
        result = dispatch(api,dict(command='set_shadows',args=dict(enabled=True,resolution=512,bias=.001,pcf=False)))
        self.assertTrue(result['ok'])
        self.assertEqual(api.get_scene_state()['shadows'],result['result'])
        with api.transaction('test'):
            with self.assertRaises(ValueError):
                api.set_shadows(enabled=False)
        self.assertFalse(dispatch(api,dict(command='transaction',args=dict(commands=[dict(command='set_shadows',args=dict(enabled=False))])))['ok'])

    def test_v3_roundtrip_legacy_default_and_invalid_load(self):
        api = Mini3DAPI()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scene.json'
            expected = api.set_shadows(enabled=True,resolution=2048,bias=.002,pcf=False)
            api.save_scene(str(path))
            api.set_shadows(enabled=False)
            api.load_scene(str(path))
            self.assertEqual(api.get_shadows(),expected)
            doc = json.loads(path.read_text(encoding='utf8'))
            doc['shadows']['bias'] = -1
            path.write_text(json.dumps(doc),encoding='utf8')
            with self.assertRaises(ValueError):
                api.load_scene(str(path))
            self.assertEqual(api.get_shadows(),expected)
            del doc['shadows']
            path.write_text(json.dumps(doc),encoding='utf8')
            api.load_scene(str(path))
            self.assertFalse(api.get_shadows()['enabled'])


if __name__ == '__main__':
    unittest.main()
