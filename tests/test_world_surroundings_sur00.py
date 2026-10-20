"""SUR-00 backdrop and bundle accounting contracts, without a GL context."""
from pathlib import Path
import io
import struct
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/world-surroundings'))
sys.path.insert(0,str(ROOT))
from run_surroundings import (backdrop_shader,cube_cameras,add_backdrop,texture_inventory,
                              validate_backdrop_far)
from mini3d.material_shaders import FRAGMENT_SHADER
from mini3d.scene import Scene


class SurroundingsRunnerTests(unittest.TestCase):
    def test_short_far_cannot_silently_clip_the_b_background(self):
        for far in (2000.,4000.):
            with self.assertRaisesRegex(ValueError, 'requires far>=6000m'):
                validate_backdrop_far(['A','B','C'],far)
            validate_backdrop_far(['A','C'],far)
        validate_backdrop_far(['A','B','C'],8000.)

    def test_b_shader_uses_baked_display_color_once_and_keeps_pbr_body(self):
        patched=backdrop_shader(FRAGMENT_SHADER)
        self.assertIn('if (hasAO)',patched)
        self.assertIn('vec4 baked=texture(aoMap,uv)',patched)
        self.assertIn('if (baked.a<.5) discard;',patched)
        self.assertIn('fragColor=vec4(baked.rgb,1.);',patched)
        self.assertTrue(patched.endswith(FRAGMENT_SHADER.split('void main() {',1)[1]))
        with self.assertRaises(ValueError):
            backdrop_shader('source drift')

    def test_cube_faces_are_inward_and_do_not_become_shadow_casters(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'face.png'
            Image.fromarray(np.full((4,4,4),255,dtype=np.uint8)).save(path)
            scene=Scene(); anchor=[0.,0.,115.]
            cameras=cube_cameras(anchor,.1,8000.)
            self.assertEqual(len(cameras),6)
            np.testing.assert_allclose([c.forward for c in cameras],
                [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)],atol=1e-14)
            add_backdrop(scene,dict(anchor=anchor,faces=[dict(path=str(path))]*6))
            self.assertEqual(len(scene.root_entities),6)
            for entity in scene.root_entities:
                mesh=entity.model
                self.assertEqual(mesh.material['alphaMode'],'BLEND')
                self.assertEqual(set(mesh.material['textures']),{'occlusion'})
                triangle=mesh.vertices[mesh.indices[0],:3]
                normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
                self.assertGreater(float(normal @ (np.asarray(anchor)-triangle.mean(axis=0))),0.)
                self.assertEqual(mesh.texcoords[0].tolist(),[0.,1.])

    def test_texture_accounting_includes_faces_mips_and_source_float_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'scene.bin'
            raw=bytearray(b'SPQRN001'+struct.pack('<II',1,1))
            raw.extend(struct.pack('<8I',34067,32856,9729,9729,33071,33071,33071,2))
            for size in (2,1):
                raw.extend(struct.pack('<II',size,size))
                raw.extend(bytes(size*size*6*16))
            path.write_bytes(raw)
            result=texture_inventory(path)
            self.assertEqual(result['initial_float32_source_bytes'],480)
            self.assertEqual(result['known_storage_bytes'],120)
            self.assertEqual(result['unknown_internal_formats'],[])
            path.write_bytes(b'wrong format')
            with self.assertRaises(ValueError):
                texture_inventory(path)


if __name__=='__main__':
    unittest.main()
