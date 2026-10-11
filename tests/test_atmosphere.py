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
                ('ground_scale',0),('azimuth',True),('elevation',90),('ground_z',float('inf'))):
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

    def test_builtin_model_shares_resources_and_needs_no_download(self):
        api=Mini3DAPI();a=api._app.cache.load('builtin:roman-soldier').instantiate()
        b=api._app.cache.load('builtin:roman-soldier').instantiate()
        self.assertIs(a.children[0].model,b.children[0].model)
        lo,hi=geometry_bounds(a)
        self.assertGreater(hi[2]-lo[2],2.3)
        self.assertGreater(len(a.children),100)
        self.assertEqual(a.placement_type,'character')


if __name__=='__main__':unittest.main()
