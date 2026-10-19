"""CPU-only tests for lossless heightmap PNG import."""

import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from heightmap_io import load_heightmap, read_heightmap, save_heightmap  # noqa: E402


class HeightmapIOTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _save(self, samples, bit_depth=8, name="height.png"):
        path = self.root / name
        save_heightmap(path, samples, bit_depth)
        return path

    def test_uint16_adjacent_samples_survive_pillow_without_8_bit_truncation(self):
        samples = np.array([[32768, 32769, 65534, 65535],
                            [1, 257, 513, 1025]], dtype=np.uint16)
        path = self._save(samples, 16)

        decoded = read_heightmap(path)
        self.assertEqual(decoded["bit_depth"], 16)
        self.assertEqual(decoded["shape"], (2, 4))
        self.assertEqual(decoded["samples"].dtype, np.uint16)
        np.testing.assert_array_equal(decoded["samples"], samples)
        self.assertEqual(decoded["input_sha256"],
                         hashlib.sha256(path.read_bytes()).hexdigest())

        field = load_heightmap(path, base_z=-2.0, height_range=6.0)
        expected = -2.0 + samples.astype(np.float64) / 65535.0 * 6.0
        np.testing.assert_array_equal(field.heights, expected)
        self.assertGreater(float(field.heights[0, 1] - field.heights[0, 0]), 0.0)

    def test_low_dynamic_range_samples_are_not_normalized_to_each_image(self):
        samples = np.array([[2, 4, 6], [1, 3, 5]], dtype=np.uint8)
        field = load_heightmap(self._save(samples), height_range=6.0)
        expected = samples.astype(np.float64) / 255.0 * 6.0
        np.testing.assert_array_equal(field.heights, expected)
        self.assertLess(float(field.heights.max()), 1.0)

    def test_rectangular_rows_keep_origin_orientation_and_flip_only_on_request(self):
        samples = np.array([[0, 25, 200], [255, 125, 50]], dtype=np.uint8)
        path = self._save(samples)
        common = {"size": (12.0, 6.0), "origin": (10.0, -4.0),
                  "base_z": 1.5, "height_range": 2.0}
        normal = load_heightmap(path, **common)
        flipped = load_heightmap(path, flip_y=True, **common)

        expected = 1.5 + samples.astype(np.float64) / 255.0 * 2.0
        np.testing.assert_array_equal(normal.heights, expected)
        np.testing.assert_array_equal(flipped.heights, expected[::-1, :])
        self.assertEqual((normal.rows, normal.cols), (2, 3))
        self.assertEqual(normal.origin, (10.0, -4.0))
        self.assertEqual(normal.size, (12.0, 6.0))
        self.assertAlmostEqual(normal.query_surface(10.0, -4.0)["height"],
                               float(expected[0, 0]))
        self.assertAlmostEqual(normal.query_surface(10.0, 2.0)["height"],
                               float(expected[-1, 0]))

    def test_png_signature_dimensions_bit_depth_color_type_and_sample_budget_are_checked(self):
        path = self._save(np.arange(6, dtype=np.uint8).reshape(2, 3))
        with self.assertRaisesRegex(ValueError, "max_samples"):
            read_heightmap(path, max_samples=5)

        tiny = self.root / "one-pixel-wide.png"
        Image.fromarray(np.array([[0], [1]], dtype=np.uint8)).save(tiny)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            read_heightmap(tiny)

        bad_signature = self.root / "bad-signature.png"
        bad_signature.write_bytes(b"not a png")
        with self.assertRaisesRegex(ValueError, "PNG"):
            read_heightmap(bad_signature)

        # A valid-looking, over-budget IHDR must be rejected before Pillow is
        # asked to verify its intentionally absent IDAT data or bad CRC.
        header_only = self.root / "over-budget-header.png"
        ihdr = struct.pack(">IIBBBBB", 3, 2, 8, 0, 0, 0, 0)
        header_only.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) +
                                b"IHDR" + ihdr + b"\x00\x00\x00\x00")
        with self.assertRaisesRegex(ValueError, "max_samples"):
            read_heightmap(header_only, max_samples=5)

    def test_rgb_alpha_and_palette_pngs_are_rejected(self):
        images = {
            "rgb": Image.new("RGB", (2, 2), (1, 2, 3)),
            "rgba": Image.new("RGBA", (2, 2), (1, 2, 3, 4)),
            "gray-alpha": Image.new("LA", (2, 2), (1, 2)),
            "palette": Image.new("P", (2, 2)),
        }
        for name, image in images.items():
            with self.subTest(mode=name):
                path = self.root / (name + ".png")
                image.save(path, format="PNG")
                with self.assertRaisesRegex(ValueError, "single-channel grayscale"):
                    read_heightmap(path)

    def test_grayscale_trns_transparency_is_rejected_at_both_bit_depths(self):
        fixtures = (
            (8, np.array([[0, 1], [2, 3]], dtype=np.uint8), 2),
            (16, np.array([[0, 1], [2, 3]], dtype=np.uint16), 2),
        )
        for bit_depth, samples, transparent_sample in fixtures:
            with self.subTest(bit_depth=bit_depth):
                original = self._save(samples, bit_depth,
                                      "plain-%s.png" % bit_depth).read_bytes()
                trns_data = struct.pack(">H", transparent_sample)
                trns_body = b"tRNS" + trns_data
                trns_chunk = (struct.pack(">I", len(trns_data)) + trns_body +
                              struct.pack(">I", zlib.crc32(trns_body) & 0xFFFFFFFF))
                path = self.root / ("transparent-%s.png" % bit_depth)
                path.write_bytes(original[:33] + trns_chunk + original[33:])

                with self.assertRaisesRegex(ValueError, "transparency"):
                    read_heightmap(path)

    def test_srgb_and_gamma_metadata_do_not_change_gray_samples(self):
        samples = np.array([[0, 1, 127], [128, 254, 255]], dtype=np.uint8)
        original = self._save(samples).read_bytes()

        def chunk(name, payload):
            body = name + payload
            return (struct.pack(">I", len(payload)) + body +
                    struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        metadata = chunk(b"gAMA", struct.pack(">I", 45455)) + chunk(b"sRGB", b"\x00")
        path = self.root / "gamma-srgb.png"
        path.write_bytes(original[:33] + metadata + original[33:])

        decoded = read_heightmap(path)
        np.testing.assert_array_equal(decoded["samples"], samples)

    def test_truncated_and_corrupt_png_data_are_rejected(self):
        valid = self._save(np.array([[0, 10], [20, 30]], dtype=np.uint8))
        data = valid.read_bytes()
        truncated = self.root / "truncated.png"
        truncated.write_bytes(data[:-12])
        with self.assertRaises(ValueError):
            read_heightmap(truncated)

        corrupted = self.root / "corrupted.png"
        changed = bytearray(data)
        changed[-5] ^= 0x01
        corrupted.write_bytes(changed)
        with self.assertRaises(ValueError):
            read_heightmap(corrupted)

    def test_invalid_parameters_and_missing_file_raise_clear_errors(self):
        valid = self._save(np.array([[0, 1], [2, 3]], dtype=np.uint8))
        invalid_calls = [
            {"size": (0.0, 1.0)},
            {"size": (float("inf"), 1.0)},
            {"origin": (float("nan"), 0.0)},
            {"base_z": float("nan")},
            {"height_range": float("inf")},
            {"height_range": -1.0},
            {"flip_y": 1},
            {"max_samples": 0},
            {"max_samples": 1.5},
        ]
        for kwargs in invalid_calls:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    load_heightmap(valid, **kwargs)

        with self.assertRaises(FileNotFoundError):
            read_heightmap(self.root / "missing.png")

    def test_fixture_writer_is_repeatable_and_validates_before_replacing_output(self):
        fixtures = (
            (8, np.array([[0, 1, 255], [128, 254, 17]], dtype=np.uint8)),
            (16, np.array([[0, 1, 257], [32768, 65534, 65535]], dtype=np.uint16)),
        )
        for bit_depth, samples in fixtures:
            with self.subTest(bit_depth=bit_depth):
                first = self._save(samples, bit_depth, "first-%s.png" % bit_depth).read_bytes()
                second = self._save(samples, bit_depth, "second-%s.png" % bit_depth).read_bytes()
                self.assertEqual(first, second)
                self.assertEqual(struct.unpack_from(">IIBBBBB", first, 16),
                                 (3, 2, bit_depth, 0, 0, 0, 0))

        protected = self.root / "protected.png"
        protected.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            save_heightmap(protected, np.array([[0, 256], [1, 2]]), 8)
        self.assertEqual(protected.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
