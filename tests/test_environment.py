"""Fixed IBL resource conventions and API/persistence regression (no GL required)."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch
from mini3d.environment import load_environment


class EnvironmentTests(unittest.TestCase):
    def test_disabled_default_and_atomic_validation(self):
        api = Mini3DAPI()
        self.assertEqual(api.get_environment(), dict(enabled=False, intensity=.35))
        api.set_environment(enabled=True, intensity=.6)
        expected = api.get_environment()
        for value in (True, -1, float('nan'), float('inf'), 101, '1'):
            with self.assertRaises(ValueError): api.set_environment(enabled=False, intensity=value)
            self.assertEqual(api.get_environment(), expected)
        for value in (1, 'yes', np.bool_(True)):
            with self.assertRaises(ValueError): api.set_environment(enabled=value)
        snapshot = api.get_environment(); snapshot['enabled'] = False
        self.assertEqual(api.get_environment(), expected)
        with api.transaction('placement'):
            with self.assertRaises(ValueError): api.set_environment(enabled=False)

    def test_json_api_and_scene_roundtrip_legacy_atomic_load(self):
        api = Mini3DAPI()
        self.assertTrue(dispatch(api, dict(command='set_environment', args=dict(enabled=True, intensity=.45)))['ok'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'scene.json'
            api.save_scene(path)
            saved = json.loads(path.read_text('utf8'))
            fresh = Mini3DAPI(); fresh.load_scene(path)
            self.assertEqual(fresh.get_environment(), api.get_environment())
            before = fresh.get_scene_state()
            for value in (None, [], dict(enabled=None), dict(intensity=-1), dict(unknown=1)):
                bad = copy.deepcopy(saved); bad['environment'] = value
                path.write_text(json.dumps(bad), encoding='utf8')
                with self.assertRaises(ValueError): fresh.load_scene(path)
                self.assertEqual(fresh.get_scene_state(), before)
            for version in (1, 2, 3):
                legacy = copy.deepcopy(saved); del legacy['environment']; legacy['version'] = version
                path.write_text(json.dumps(legacy), encoding='utf8'); fresh.load_scene(path)
                self.assertEqual(fresh.get_environment(), dict(enabled=False, intensity=.35))

    def test_linear_hdr_mips_and_brdf_axis_convention(self):
        arrays = load_environment()
        self.assertEqual(sum(a.nbytes for a in arrays.values()), 3444724)
        self.assertGreater(float(arrays['specular_0'].max()), 100)  # HDR, not clamped/sRGB.
        peaks = [float(arrays['specular_'+str(i)].max()) for i in range(9)]
        self.assertTrue(all(b < a for a,b in zip(peaks, peaks[1:])))
        lut = arrays['brdf']
        self.assertLess(float(lut[0,-1,1]), .001)  # x=NdotV, y=roughness, row0=GL bottom.
        self.assertGreater(float(lut[0,-1,0]), .95)
        self.assertGreater(float(lut[0,0,1]), .9)
        self.assertLess(float(lut[-1,-1,0]), .4)


if __name__ == '__main__': unittest.main()
