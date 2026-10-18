"""Sky/sun geometry, atomic persistence and non-editing ground regressions."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch
from mini3d.atmosphere import (atmosphere_state, sun_angles, sun_color,
                               prepare_photographic_scene)
from mini3d.camera import Camera
from mini3d.placement import geometry_bounds


class AtmosphereTests(unittest.TestCase):
    def test_invalid_combined_update_preserves_settings_and_sun(self):
        api=Mini3DAPI(); api.sunset_preset()
        before=api.get_scene_state()
        for key, value in (('enabled',1),('ground','yes'),('haze',-1),
                ('sun_temperature',1999),('exposure_ev',float('nan')),
                ('ground_scale',0),('azimuth',True),('elevation',90.1),('ground_z',float('inf'))):
            with self.assertRaises(ValueError):
                api.set_atmosphere(**{key:value,'azimuth':False if key=='azimuth' else 20})
            self.assertEqual(api.get_scene_state(),before)
        state=api.get_atmosphere();state['ground']=False
        self.assertTrue(api.get_atmosphere()['ground'])
        with api.transaction('placing'):
            with self.assertRaises(ValueError):api.set_atmosphere(enabled=False)
            with self.assertRaises(ValueError):api.sunset_preset()
        self.assertFalse(dispatch(api,{'command':'transaction','args':{'commands':[
            {'command':'set_atmosphere','args':{'ground':False}}]}})['ok'])

    def test_direction_shadow_projection_and_temperature_are_physical(self):
        api=Mini3DAPI();api.sunset_preset();api.set_atmosphere(azimuth=-90,elevation=9)
        direction=np.asarray(api.get_lighting()['direction'])
        self.assertAlmostEqual(np.linalg.norm(direction),1.)
        self.assertAlmostEqual(sun_angles(api._app.scene)['elevation'],9.,places=6)
        # Intersect the ray away from the sun with Z=0: shadow travels +Y.
        height=2.;shadow=-height*direction[:2]/direction[2]
        self.assertAlmostEqual(shadow[0],0.,places=10)
        self.assertAlmostEqual(shadow[1],height/math.tan(math.radians(9)))
        warm,cool=sun_color(2500),sun_color(8000)
        self.assertGreater(warm[0]/warm[2],cool[0]/cool[2])
        api.set_atmosphere(exposure_ev=1)
        np.testing.assert_array_equal(api.get_lighting()['direction'],direction)

    def test_roundtrip_builtin_camera_sky_and_old_scene_reset(self):
        api=Mini3DAPI();entity=api.spawn('builtin:roman-soldier');api.sunset_preset()
        api.set_atmosphere(azimuth=-90,elevation=9,ground_z=-.02,exposure_ev=.5)
        api.create_shot_camera(position=(3,-5,2),target=(0,0,1),focal_mm=50,aspect='3:2')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scene.json';api.save_scene(path)
            document=json.loads(path.read_text());fresh=Mini3DAPI();fresh.load_scene(path)
            self.assertEqual(fresh.get_atmosphere(),api.get_atmosphere())
            self.assertEqual(fresh.get_shot_camera(),api.get_shot_camera())
            self.assertEqual(fresh.list_entities()[0]['asset_path'],'builtin:roman-soldier')
            expected=fresh.get_scene_state()
            for invalid in (None,[],{'enabled':None},{'haze':-1},{'unknown':5}):
                bad=copy.deepcopy(document);bad['atmosphere']=invalid
                path.write_text(json.dumps(bad))
                with self.assertRaises((ValueError,TypeError)):fresh.load_scene(path)
                self.assertEqual(fresh.get_scene_state(),expected)
            del document['atmosphere'];path.write_text(json.dumps(document));fresh.load_scene(path)
            self.assertFalse(fresh.get_atmosphere()['enabled'])
            self.assertFalse(fresh.get_atmosphere()['ground'])

    def test_ground_covers_clipping_volume_and_never_mutates_saved_roots(self):
        api=Mini3DAPI();api.spawn('builtin:roman-soldier');api.sunset_preset()
        scene=api._app.scene;roots=list(scene.root_entities)
        camera=Camera((1000,-2000,2),far=80)
        clean,ground=prepare_photographic_scene(scene,camera)
        self.assertEqual(scene.root_entities,roots)
        self.assertEqual(clean.root_entities,roots+[ground])
        lo,hi=geometry_bounds(ground)
        self.assertTrue((lo[:2] <= camera.position[:2]-camera.far).all())
        self.assertTrue((hi[:2] >= camera.position[:2]+camera.far).all())
        original_image=ground.model.material['textures']['baseColor']['image']
        camera.position=(1100,3000,3)
        next_scene,next_ground=prepare_photographic_scene(scene,camera,ground)
        self.assertIs(next_ground,ground)
        self.assertIs(ground.model.material['textures']['baseColor']['image'],original_image)
        self.assertEqual(scene.root_entities,roots)
        api.set_atmosphere(ground=False)
        self.assertIs(prepare_photographic_scene(scene,camera,ground)[0],scene)

    def test_roman_street_has_a_photographic_floor_below_its_authored_paving(self):
        api = Mini3DAPI()
        api.load_scene(Path(__file__).resolve().parents[1] / 'examples/roman_street/street.json')
        settings = api.get_atmosphere()
        self.assertTrue(settings['ground'])
        roads = [root for root in api._app.scene.root_entities
                 if root.asset_path == 'builtin:roman-road']
        self.assertTrue(roads)
        # The render-only floor must not Z-fight with the authored road slab.
        for road in roads:
            self.assertLess(settings['ground_z'], geometry_bounds(road)[0][2] - .01)
        roots = list(api._app.scene.root_entities)
        rendered, ground = prepare_photographic_scene(api._app.scene, api._app.shot_camera)
        self.assertEqual(api._app.scene.root_entities, roots)
        self.assertEqual(rendered.root_entities, roots + [ground])

    def test_hdr_and_ground_switches_validate_atomically_and_roundtrip(self):
        api=Mini3DAPI();api.sunset_preset()
        api.set_atmosphere(sky_texture='sunset',ground_texture='gravel',sun_size=.53,
                          sky_intensity=.7,tone_mapping='filmic')
        before=api.get_scene_state()
        for kwargs in ({'sky_texture':'missing-sky.hdr'},{'sky_texture':3},
                {'ground_texture':'unknown'},{'tone_mapping':'unknown'},
                {'sun_size':float('nan')},{'sky_intensity':-1}):
            with self.assertRaises((ValueError,OSError)):
                api.set_atmosphere(azimuth=20,**kwargs)
            self.assertEqual(api.get_scene_state(),before)
        camera=Camera((0,-5,2),far=65)
        _,ground=prepare_photographic_scene(api._app.scene,camera)
        photo=ground.model.material
        self.assertIn('metallicRoughness',photo['textures'])
        self.assertIn('occlusion',photo['textures'])
        api.set_atmosphere(ground_texture='procedural')
        _,same=prepare_photographic_scene(api._app.scene,camera,ground)
        self.assertIs(ground,same);self.assertIsNot(ground.model.material,photo)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scene.json';api.save_scene(path)
            fresh=Mini3DAPI();fresh.load_scene(path)
            self.assertEqual(fresh.get_atmosphere(),api.get_atmosphere())

    def test_real_sky_rotation_preserves_solar_direction_for_all_views(self):
        from mini3d.photo_environment import load_sky,sky_rotation
        from mini3d.lighting import scene_light_direction
        sun=load_sky('sunset')[2]
        api=Mini3DAPI()
        for azimuth,elevation in ((-170,2),(-90,9),(25,35),(180,80)):
            api.set_atmosphere(azimuth=azimuth,elevation=elevation)
            direction=scene_light_direction(api._app.scene)
            rotation=sky_rotation('sunset',direction)
            np.testing.assert_allclose(rotation@direction,sun,atol=1e-7)
            np.testing.assert_allclose(rotation.T@rotation,np.eye(3),atol=1e-7)
            self.assertAlmostEqual(np.linalg.det(rotation),1.)

    def test_hdr_reader_rejects_truncated_and_oversized_files(self):
        from mini3d.hdr import read_hdr
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.hdr'
            for data in (b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 8192 +X 16384\n',
                    b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 2 +X 8\n'):
                path.write_bytes(data)
                with self.assertRaises(ValueError):read_hdr(path)

    def test_builtin_model_shares_resources_and_needs_no_download(self):
        api=Mini3DAPI();a=api._app.cache.load('builtin:roman-soldier').instantiate()
        b=api._app.cache.load('builtin:roman-soldier').instantiate()
        self.assertIs(a.children[0].model,b.children[0].model)
        lo,hi=geometry_bounds(a)
        self.assertGreater(hi[2]-lo[2],2.3)
        self.assertGreater(len(a.children),100)
        self.assertEqual(a.placement_type,'character')


if __name__=='__main__':unittest.main()
