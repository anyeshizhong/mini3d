"""Height prefilter/packing invariants; original LAB-02B resources stay intact."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments/world-surroundings'))
from material_maps import MaterialMaps, shader_source
from quality_materials import QualityMaps, quality_shader
from mini3d.material_shaders import FRAGMENT_SHADER


def fixture(folder, eight_bit=False):
    records = {}
    for index, name in enumerate(('soil', 'rock', 'grass')):
        # Do not normalize the narrow source range to black/white.
        values = np.full((256, 256), (index+1)*10000, dtype=np.uint16)
        values[::2, ::2] += 4000
        path = folder/(name+'.png')
        Image.fromarray(values.astype(np.uint8) if eight_bit else values).save(path)
        records[name+'.png'] = dict(bundled_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   asset_id=('brown_mud_02', 'rock_face', 'leafy_grass')[index],
                                   tile_metres=(1.3, 2.4, 2.)[index])
    (folder/'manifest.json').write_text(json.dumps(dict(license='CC0-1.0', maps=records)), encoding='utf-8')


class QualityMaterialTests(unittest.TestCase):
    def test_linear_height_prefilter_and_channel_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); fixture(folder)
            quality = QualityMaps(folder); original = MaterialMaps().atlas_maps()
            atlas = quality.atlas_maps()
            np.testing.assert_array_equal(atlas['baseColor'][..., :3], original['baseColor'][..., :3])
            np.testing.assert_array_equal(atlas['normal'], original['normal'])
            np.testing.assert_array_equal(atlas['metallicRoughness'], original['metallicRoughness'])
            for i in range(3):
                expected = int(np.rint(((i+1)*10000.+1000.)/65535.*255.))
                self.assertEqual(int(atlas['baseColor'][510, i*256, 3]), expected)
                self.assertEqual(quality.height_levels[i][-1].shape, (1, 1))
                self.assertAlmostEqual(float(quality.height_levels[i][-1][0, 0]), ((i+1)*10000.+1000.)/65535.)
            self.assertTrue(np.all(MaterialMaps().atlas_maps()['baseColor'][..., 3] == 255))

    def test_corrupt_payload_and_wrong_bit_depth_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); fixture(folder)
            path = folder/'soil.png'; path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                QualityMaps(folder)
            fixture(folder, eight_bit=True)
            with self.assertRaisesRegex(ValueError, 'PNG16'):
                QualityMaps(folder)

    def test_quality_patch_refuses_source_drift_and_invalid_parameters(self):
        source = shader_source(FRAGMENT_SHADER, 'layered')
        for method in ('depth', 'power'):
            patched = quality_shader(source, method=method)
            self.assertIn('if (hasAO) qPrepare();', patched)
            self.assertIn('colorHeight.a', patched)
            self.assertIn('a.rgb = linearize', patched)
            self.assertIn('rough *= labRoughness()', patched)
            self.assertIn('metal = 0.0', patched)
        with self.assertRaises(ValueError):
            quality_shader(source.replace('void main() {', 'void main(){'))
        for options in (dict(strength=float('nan')), dict(width=0.), dict(strength=1.1), dict(method='unknown')):
            with self.assertRaises(ValueError):
                quality_shader(source, **options)


if __name__ == '__main__':
    unittest.main()
