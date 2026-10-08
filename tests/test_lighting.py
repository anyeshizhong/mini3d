"""Lighting contract tests without a GL context; GPU pixels: lighting_smoke.py."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import numpy as np
from mini3d.camera import Camera
from mini3d.editor import Editor
from mini3d.gl_renderer import GLRenderer
from mini3d.lighting import scene_light_direction
from mini3d.material_renderer import MaterialRenderer
from mini3d.scene import Scene, rotation_xyz
from mini3d.shot_camera import ShotCamera, render_shot


class LightingTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.scene.lighting_mode = 'Scene'
        self.scene.light_dir = np.array([2., -3., 4.])
        self.camera = Camera()
        self.material = MaterialRenderer.__new__(MaterialRenderer)
        self.uniforms = {}
        for method in ('_vec3', '_float', '_int'):
            setattr(self.material, method, lambda name, value: self.uniforms.update({name: value}))

    def test_camera_translation_and_rotation_never_transform_scene_light(self):
        original = self.scene.light_dir.copy()
        expected = original / np.linalg.norm(original)
        for position, angles in (((0, 0, 5), (0, 0, 0)),
                                 ((100, -90, 60), (.7, 1.2, -.4)),
                                 ((-2, 3, -4), (1.4, -.9, 2.1))):
            self.camera.position = position
            self.camera.rotation = rotation_xyz(angles)
            self.material._lighting(self.scene, self.camera)
            np.testing.assert_allclose(self.uniforms['light0'], expected, atol=1e-7)
            np.testing.assert_array_equal(self.scene.light_dir, original)
            self.assertTrue(self.uniforms['sceneLighting'])
            self.assertEqual(self.uniforms['lightIntensity'], self.scene.diffuse)
            self.assertEqual(self.uniforms['ambientIntensity'], self.scene.ambient)
            self.assertNotIn('light1', self.uniforms)

    def test_scene_lighting_does_not_read_camera_pose(self):
        self.material._lighting(self.scene, object())
        np.testing.assert_allclose(self.uniforms['light0'], scene_light_direction(self.scene))

    def test_studio_preserves_camera_relative_preview_and_switches_back(self):
        self.scene.lighting_mode = 'Studio'
        self.material._lighting(self.scene, self.camera)
        first = self.uniforms['light0'].copy()
        self.camera.rotation = rotation_xyz((.5, .7, 1.2))
        self.material._lighting(self.scene, self.camera)
        self.assertFalse(np.allclose(first, self.uniforms['light0']))
        self.assertFalse(self.uniforms['sceneLighting'])
        self.assertIn('light2', self.uniforms)
        self.scene.lighting_mode = 'Scene'
        self.material._lighting(self.scene, self.camera)
        self.assertTrue(self.uniforms['sceneLighting'])
        np.testing.assert_allclose(self.uniforms['light0'], scene_light_direction(self.scene))

    def test_plain_realistic_and_toon_upload_same_direction_as_pbr(self):
        import mini3d.gl_renderer as module
        renderer = GLRenderer.__new__(GLRenderer)
        for name in ('program', 'locView', 'locProj', 'locLdir', 'locAmb', 'locDif',
                     'toon_program', 'toon_locView', 'toon_locProj', 'toon_locLdir',
                     'toon_locAmb', 'toon_locDif', 'toon_locCamPos'):
            setattr(renderer, name, name)
        self.material._lighting(self.scene, self.camera)
        for method in ('_render_realistic_pass', '_render_toon_pass'):
            with patch.object(module, 'glUseProgram'), patch.object(module, 'glUniformMatrix4fv'), \
                    patch.object(module, 'glUniform1f'), patch.object(module, 'glUniform3f') as upload:
                args = ([], self.camera.view_matrix, np.eye(4), self.scene)
                getattr(renderer, method)(*args, *([self.camera.position] if 'toon' in method else []))
                np.testing.assert_allclose(upload.call_args_list[0][0][1:], self.uniforms['light0'])

    def test_direction_validation_and_normalization_do_not_mutate_scene(self):
        for vector in ([0, 0, 0], [1, 2], [1, np.nan, 2], [np.inf, 1, 2]):
            self.scene.light_dir = vector
            with self.assertRaises(ValueError):
                scene_light_direction(self.scene)
        for vector in ([1e300, 0, 0], [1e-300, 0, 0], [9, 0, 0]):
            self.scene.light_dir = vector
            np.testing.assert_array_equal(scene_light_direction(self.scene), [1, 0, 0])
            self.assertEqual(self.scene.light_dir, vector)

    def test_shot_overrides_studio_on_copy_even_when_rendering_fails(self):
        self.scene.lighting_mode = 'Studio'
        shot = ShotCamera(self.camera)
        renderer, target = Mock(), Mock()
        renderer.render.side_effect = RuntimeError('intentional render failure')
        with patch('OpenGL.GL.glDisable'), patch('OpenGL.GL.glDepthMask'):
            with self.assertRaises(RuntimeError):
                render_shot(self.scene, shot, renderer, target)
        clean, camera = renderer.render.call_args[0]
        self.assertIs(camera, shot)
        self.assertIsNot(clean, self.scene)
        self.assertEqual(clean.lighting_mode, 'Scene')
        self.assertEqual(clean.render_mode, 'Lit')
        self.assertEqual(self.scene.lighting_mode, 'Studio')
        np.testing.assert_array_equal(clean.light_dir, self.scene.light_dir)

    def test_lighting_round_trip_and_legacy_scene_defaults(self):
        app = Editor()
        app.scene.lighting_mode = 'Scene'
        app.scene.light_dir = np.array([-2, 3, .5])
        app.scene.ambient, app.scene.diffuse = .15, 1.8
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scene.json'
            app.save_scene(path)
            restored = Editor()
            restored.load_scene(path)
            self.assertEqual(restored.scene.lighting_mode, 'Scene')
            np.testing.assert_array_equal(restored.scene.light_dir, app.scene.light_dir)
            self.assertEqual((restored.scene.ambient, restored.scene.diffuse), (.15, 1.8))
            data = json.loads(path.read_text(encoding='utf8'))
            del data['lighting']
            path.write_text(json.dumps(data), encoding='utf8')
            restored.load_scene(path)
            self.assertEqual(restored.scene.lighting_mode, 'Studio')
            np.testing.assert_array_equal(restored.scene.light_dir, Scene().light_dir)

    def test_bad_saved_lighting_does_not_replace_live_scene(self):
        app = Editor()
        before = app.scene.light_dir.copy()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scene.json'
            app.save_scene(path)
            data = json.loads(path.read_text(encoding='utf8'))
            for invalid in (dict(mode='Other'), dict(light_dir=[0, 0, 0]),
                            dict(ambient=-1), dict(diffuse=float('nan'))):
                data['lighting'] = invalid
                path.write_text(json.dumps(data), encoding='utf8')
                with self.assertRaises(ValueError):
                    app.load_scene(path)
                np.testing.assert_array_equal(app.scene.light_dir, before)


if __name__ == '__main__':
    unittest.main()
