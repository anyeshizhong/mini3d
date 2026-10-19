"""CPU regressions for LAB-02B real terrain maps and texture baking."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from material_maps import MaterialMaps, shader_source, weight_rgba
from mini3d.material_shaders import FRAGMENT_SHADER


def make_asset_set(folder, colors, normals, roughness, tile_widths=None):
    """Write a tiny-description fixture using full-sized constant RGB maps."""
    folder.mkdir(parents=True, exist_ok=True)
    tile_widths = tile_widths or (1.3, 2.4, 2.0)
    records = {}
    for layer_index, layer in enumerate(("soil", "rock", "grass")):
        layer_dir = folder / layer
        layer_dir.mkdir()
        maps = {
            "diff.png": colors[layer_index],
            "nor_gl.png": normals[layer_index],
            "rough.png": (roughness[layer_index],) * 3,
        }
        for filename, color in maps.items():
            pixels = np.empty((256, 256, 3), dtype=np.uint8)
            pixels[...] = color
            path = layer_dir / filename
            Image.fromarray(pixels, "RGB").save(path, format="PNG")
            records["%s/%s" % (layer, filename)] = {
                "tile_metres": tile_widths[layer_index],
                "bundled_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": [256, 256],
                "channels": "RGB8",
            }
    (folder / "manifest.json").write_text(json.dumps({
        "license": "CC0-1.0", "maps": records,
    }), encoding="utf-8")


class MaterialMapsTests(unittest.TestCase):
    def test_real_manifest_hashes_and_three_tile_atlas_layout(self):
        maps = MaterialMaps()
        atlas = maps.atlas_maps()
        self.assertEqual(maps.tile_metres, (1.3, 2.4, 2.0))
        self.assertEqual(set(atlas), {"baseColor", "normal", "metallicRoughness"})
        for value in atlas.values():
            self.assertEqual(value.shape, (511, 768, 4))
            self.assertEqual(value.dtype, np.uint8)
            self.assertTrue(value.flags.writeable)
            self.assertTrue(np.all(value[..., 3] == 255))

        manifest = json.loads((EXPERIMENT_DIR / "assets/materials/manifest.json").read_text(
            encoding="utf-8"))
        for layer_index, layer in enumerate(("soil", "rock", "grass")):
            x0, x1 = layer_index * 256, (layer_index + 1) * 256
            with Image.open(EXPERIMENT_DIR / "assets/materials" / layer / "diff.png") as image:
                original_color = np.asarray(image)
            with Image.open(EXPERIMENT_DIR / "assets/materials" / layer / "nor_gl.png") as image:
                original_normal = np.asarray(image)
            with Image.open(EXPERIMENT_DIR / "assets/materials" / layer / "rough.png") as image:
                original_rough = np.asarray(image)
            self.assertTrue(np.array_equal(atlas["baseColor"][:256, x0:x1, :3], original_color))
            self.assertTrue(np.array_equal(atlas["normal"][:256, x0:x1, :3], original_normal))
            mr = atlas["metallicRoughness"][:256, x0:x1]
            self.assertTrue(np.all(mr[..., 0] == 255))
            self.assertTrue(np.array_equal(mr[..., 1], original_rough[..., 0]))
            self.assertTrue(np.all(mr[..., 2] == 0))
            for filename in ("diff.png", "nor_gl.png", "rough.png"):
                self.assertIn("bundled_sha256", manifest["maps"][layer + "/" + filename])

        atlas["baseColor"][0, 0, 0] ^= np.uint8(255)
        self.assertFalse(np.array_equal(atlas["baseColor"], maps.atlas_maps()["baseColor"]))

    def test_manifest_hash_mismatch_is_rejected(self):
        source = EXPERIMENT_DIR / "assets/materials"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "materials"
            import shutil
            shutil.copytree(source, destination)
            tampered = destination / "soil/diff.png"
            tampered.write_bytes(tampered.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                MaterialMaps(destination)

    def test_rgba_weight_quantization_and_zero_fallback(self):
        values = np.array([[[0.5, 0.25, 0.25], [0.0, 0.0, 0.0]]], dtype=np.float32)
        packed = weight_rgba(values)
        self.assertEqual(packed.dtype, np.uint8)
        self.assertEqual(packed.shape, (1, 2, 4))
        self.assertTrue(packed.flags.writeable)
        self.assertEqual(tuple(packed[0, 0]), (128, 64, 64, 255))
        self.assertEqual(tuple(packed[0, 1]), (255, 0, 0, 255))

    def test_bake_mixes_srgb_in_linear_space_and_packs_roughness(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "materials"
            make_asset_set(folder,
                           colors=((255, 0, 0), (0, 255, 0), (0, 0, 255)),
                           normals=((204, 128, 230), (51, 128, 230), (128, 128, 255)),
                           roughness=(0, 255, 64))
            maps = MaterialMaps(folder, origin=(0, 0), size=(2, 2))
            weights = np.empty((2, 2, 3), dtype=np.float32)
            weights[...] = (0.5, 0.5, 0.0)
            baked = maps.bake(weights)
            self.assertEqual(set(baked), {"baseColor", "normal", "metallicRoughness"})
            self.assertTrue(all(array.shape == (2, 2, 4) and array.dtype == np.uint8
                                and array.flags.writeable for array in baked.values()))
            # A half red / half green linear-light mix encodes to sRGB 188/188.
            self.assertEqual(tuple(baked["baseColor"][0, 0]), (188, 188, 0, 255))
            # The opposite x normals nearly cancel; the surviving vector is normalized.
            self.assertTrue(np.all(np.abs(baked["normal"][..., :2].astype(int) - 128) <= 1))
            self.assertTrue(np.all(baked["normal"][..., 2] >= 254))
            mr = baked["metallicRoughness"]
            self.assertTrue(np.all(mr[..., 0] == 255))
            self.assertTrue(np.all(mr[..., 1] == 128))
            self.assertTrue(np.all(mr[..., 2] == 0))
            self.assertTrue(np.all(mr[..., 3] == 255))

    def test_periodic_world_sampling_and_dirty_rect_match_full_crop(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "materials"
            # A horizontal ramp makes the two world-space tile endpoints
            # directly comparable; the tile width is exactly one world extent.
            records = {}
            for layer in ("soil", "rock", "grass"):
                layer_dir = folder / layer
                layer_dir.mkdir(parents=True)
                x = np.arange(256, dtype=np.uint8)
                ramp = np.broadcast_to(x[None, :, None], (256, 256, 3)).copy()
                for filename, pixels in (("diff.png", ramp),
                                         ("nor_gl.png", np.full((256, 256, 3), 128, np.uint8)),
                                         ("rough.png", np.full((256, 256, 3), 90, np.uint8))):
                    path = layer_dir / filename
                    Image.fromarray(pixels, "RGB").save(path, format="PNG")
                    records[layer + "/" + filename] = {
                        "tile_metres": 1.0, "bundled_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size": [256, 256], "channels": "RGB8",
                    }
            folder.mkdir(exist_ok=True)
            (folder / "manifest.json").write_text(json.dumps({"license": "CC0-1.0", "maps": records}),
                                                    encoding="utf-8")
            maps = MaterialMaps(folder, origin=(0, 0), size=(1, 1))
            weights = np.zeros((9, 11, 3), dtype=np.float32)
            weights[..., 0] = 1.0
            full = maps.bake(weights)
            # origin and end sample the same point on the repeating 1m tile.
            self.assertTrue(np.array_equal(full["baseColor"][:, 0], full["baseColor"][:, -1]))
            rect = (2, 3, 8, 10)
            partial = maps.bake(weights, rect=rect)
            for key in full:
                self.assertTrue(np.array_equal(partial[key], full[key][2:8, 3:10]), key)

    def test_bake_rejects_unnormalized_and_invalid_rect_inputs(self):
        maps = MaterialMaps()
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            maps.bake(np.full((2, 2, 3), 0.2, dtype=np.float32))
        valid = np.zeros((2, 2, 3), dtype=np.float32)
        valid[..., 0] = 1.0
        with self.assertRaisesRegex(ValueError, "half-open"):
            maps.bake(valid, rect=(0, 0, 2))
        with self.assertRaisesRegex(ValueError, "in-bounds"):
            maps.bake(valid, rect=(0, 0, 3, 1))

    def test_bundle_shader_variants_are_guarded_and_keep_ordinary_material_path(self):
        for scheme in ("layered", "baked"):
            result = shader_source(FRAGMENT_SHADER, scheme, origin=(-4, -3), size=(8, 6))
            self.assertIn("return hasAO ? worldPosition.xy", result)
            self.assertIn("vec2(-4.0, -3.0)", result)
            self.assertIn("vec2(8.0, 6.0)", result)
            self.assertIn("hasAO ? labNormal()", result)
            self.assertIn("float ao = 1.0;", result)
            self.assertIn("texture(normalMap, surfaceUV()).xyz", result)
            self.assertIn("metal = 0.0;", result)
        layered = shader_source(FRAGMENT_SHADER, "layered")
        self.assertIn("labLayerLOD", layered)
        self.assertIn("vec2(768.0, 511.0)", layered)
        self.assertIn("vec3 weights = texture(aoMap, labWeightUV()).rgb", layered)
        self.assertIn("weights / total : vec3(1.0, 0.0, 0.0)", layered)
        baked = shader_source(FRAGMENT_SHADER, "baked")
        self.assertIn("texture(baseMap, labBaseUV())", baked)
        self.assertIn("coordinate * vec2(dimensions - ivec2(1)) + vec2(0.5)", baked)
        self.assertNotIn("texture(aoMap, labWeightUV())", baked)
        with self.assertRaises(ValueError):
            shader_source(FRAGMENT_SHADER, "other")
        surface = "vec2 surfaceUV() { return photographicGround ? worldPosition.xy*groundScale : uv; }"
        with self.assertRaisesRegex(ValueError, "expected exactly one surfaceUV"):
            shader_source(FRAGMENT_SHADER + "\n" + surface, "layered")

    def test_prefilter_averages_checker_in_linear_light_without_layer_bleed(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "materials"
            make_asset_set(folder, colors=((0, 0, 0), (0, 255, 0), (0, 0, 255)),
                           normals=((128, 128, 255),) * 3, roughness=(64, 128, 192),
                           tile_widths=(1., 1., 1.))
            checker = (np.indices((256, 256)).sum(axis=0) % 2 * 255).astype(np.uint8)
            path = folder / 'soil/diff.png'
            Image.fromarray(np.repeat(checker[..., None], 3, axis=2), 'RGB').save(path)
            manifest_path = folder / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['maps']['soil/diff.png']['bundled_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            maps = MaterialMaps(folder, origin=(0., 0.), size=(256., 256.))
            atlas = maps.atlas_maps()['baseColor']
            self.assertEqual(tuple(atlas[510, 0]), (188, 188, 188, 255))
            self.assertEqual(tuple(atlas[510, 256]), (0, 255, 0, 255))
            self.assertEqual(tuple(atlas[510, 512]), (0, 0, 255, 255))
            weights = np.zeros((2, 2, 3), np.float32)
            weights[..., 0] = 1.
            baked = maps.bake(weights)
            self.assertTrue(np.all(baked['baseColor'][..., :3] == 188))
            self.assertTrue(np.all(baked['metallicRoughness'][..., 1] == 64))


if __name__ == "__main__":
    unittest.main()
