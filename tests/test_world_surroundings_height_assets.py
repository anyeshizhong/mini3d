import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

import prepare_quality_assets as height_assets


class HeightAssetPreparationTests(unittest.TestCase):
    def test_area_mean_preserves_numeric_range_without_normalization(self):
        source = np.empty((8, 8), dtype=np.uint16)
        source[:4, :4] = 1000
        source[:4, 4:] = 2000
        source[4:, :4] = 3000
        source[4:, 4:] = 4000

        result, details = height_assets.downsample_area(source, target_size=(2, 2))

        np.testing.assert_array_equal(result, [[1000, 2000], [3000, 4000]])
        self.assertEqual(details["min"], 1000)
        self.assertEqual(details["max"], 4000)
        self.assertEqual(details["resampling"], "arithmetic 4x4 area mean, rounded half-up to uint16")

    def test_half_code_area_average_rounds_up_and_reports_error(self):
        source = np.full((4, 4), 1234, dtype=np.uint16)
        source.flat[:8] += 1

        result, details = height_assets.downsample_area(source, target_size=(1, 1))

        self.assertEqual(int(result[0, 0]), 1235)
        self.assertEqual(details["area_mean_rounding_error_lsb"]["max_absolute"], 0.5)

    def test_8bit_png_maps_to_uint16_codes_without_gamma_conversion(self):
        source = np.zeros((1024, 1024), dtype=np.uint8)
        source[0, :4] = [0, 1, 128, 255]
        png_info = PngInfo()
        png_info.add(b"gAMA", struct.pack(">I", 45455))
        encoded = tempfile.SpooledTemporaryFile()
        Image.fromarray(source).save(encoded, format="PNG", pnginfo=png_info)
        encoded.seek(0)

        samples, metadata = height_assets.decode_displacement_png(encoded.read())

        np.testing.assert_array_equal(samples[0, :4], [0, 257, 32896, 65535])
        self.assertEqual(metadata["bit_depth"], 8)
        self.assertIn("gAMA", metadata["ignored_color_chunks"])
        self.assertEqual(metadata["source_range"]["minimum_code"], 0)
        self.assertEqual(metadata["source_range"]["maximum_code"], 255)
        self.assertEqual(metadata["min"], 0)
        self.assertEqual(metadata["max"], 65535)

    def test_bundled_height_maps_match_manifest_and_uint16_png_contract(self):
        directory = EXPERIMENT / "assets" / "material-heights"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["license"], "CC0-1.0")
        self.assertEqual(set(manifest["maps"]), {"soil.png", "rock.png", "grass.png"})
        for name, record in manifest["maps"].items():
            raw = (directory / name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["bundled_sha256"])
            width, height, bit_depth, color_type = struct.unpack_from(">IIBB", raw, 16)
            self.assertEqual((width, height, bit_depth, color_type), (256, 256, 16, 0))
            with Image.open(directory / name) as image:
                image.load()
                values = np.asarray(image).astype(np.uint16)
            self.assertEqual(values.shape, (256, 256))
            self.assertEqual(int(values.min()), record["bundled_min"])
            self.assertEqual(int(values.max()), record["bundled_max"])

    def test_failed_directory_promotion_restores_previous_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "material-heights"
            staging = root / "material-heights.stage"
            destination.mkdir()
            staging.mkdir()
            (destination / "soil.png").write_bytes(b"old height")
            (destination / "manifest.json").write_text("old manifest", encoding="utf-8")
            (staging / "soil.png").write_bytes(b"new height")
            (staging / "manifest.json").write_text("new manifest", encoding="utf-8")
            real_replace = os.replace

            def fail_staging_promotion(source, target):
                if Path(source) == staging:
                    raise OSError("injected promotion failure")
                return real_replace(source, target)

            with self.assertRaisesRegex(OSError, "injected promotion failure"):
                height_assets.promote_staging(staging, destination, replace=fail_staging_promotion)

            self.assertEqual((destination / "soil.png").read_bytes(), b"old height")
            self.assertEqual((destination / "manifest.json").read_text(encoding="utf-8"), "old manifest")
            self.assertTrue(staging.exists())

    def test_promotion_refuses_to_replace_unknown_user_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "material-heights"
            staging = root / "material-heights.stage"
            destination.mkdir()
            staging.mkdir()
            user_file = destination / "user-note.txt"
            user_file.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unrecognized files"):
                height_assets.promote_staging(staging, destination)

            self.assertEqual(user_file.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
