"""CPU tests for optional native World Surroundings frame statistics."""
import ctypes as C
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from sculpt_native import NativeTerrain


class StubFunction:
    def __init__(self, callback=lambda *args: 1):
        self.callback = callback
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def fake_library(frame_stats=None):
    names = (
        "lab_error", "lab_create", "lab_destroy", "lab_render",
        "lab_enable_gpu_timing", "lab_poll_gpu_timing", "lab_capture",
        "lab_capture_color", "lab_compile_count", "lab_mesh_count",
        "lab_entity_mesh_id", "lab_entity_texture_id", "lab_mesh_vertex_count",
        "lab_update_batch", "lab_read_mesh_vertices", "lab_texture_info",
        "lab_update_texture_batch", "lab_read_texture_rgba8", "lab_update_count",
        "lab_uploaded_bytes", "lab_texture_update_count",
        "lab_texture_uploaded_bytes", "lab_renderer_name", "lab_gl_version",
    )
    functions = {name: StubFunction() for name in names}
    functions["lab_error"] = StubFunction(lambda: b"stub error")
    functions["lab_create"] = StubFunction(lambda *args: C.c_void_p(1))
    if frame_stats is not None:
        functions["lab_frame_stats"] = StubFunction(frame_stats)
    return types.SimpleNamespace(**functions)


def make_native(library):
    with mock.patch.object(C, "CDLL", return_value=library):
        return NativeTerrain("stub.dll", "stub-bundle")


class NativeFrameStatsTests(unittest.TestCase):
    def test_stats_return_named_float_fields_and_integer_counts(self):
        expected = (0.1, 0.125, 4, 3, 120, 90, 18.25, 250.5)

        def fill_stats(_handle, output, capacity):
            self.assertEqual(capacity, 8)
            values = C.cast(output, C.POINTER(C.c_double))
            for index, value in enumerate(expected):
                values[index] = value
            return 1

        library = fake_library(fill_stats)
        native = make_native(library)

        stats = native.frame_stats()

        self.assertEqual(set(stats), {
            "input_near", "color_near", "color_draws", "shadow_draws",
            "color_triangles", "shadow_triangles", "near_shadow_depth_span",
            "far_shadow_depth_span",
        })
        for name in ("input_near", "color_near", "near_shadow_depth_span",
                     "far_shadow_depth_span"):
            self.assertIs(type(stats[name]), float)
        self.assertAlmostEqual(stats["input_near"], 0.1)
        self.assertEqual(stats["color_near"], 0.125)
        for name in ("color_draws", "shadow_draws", "color_triangles", "shadow_triangles"):
            self.assertIs(type(stats[name]), int)
        self.assertEqual(stats["color_triangles"], 120)
        self.assertEqual(stats["near_shadow_depth_span"], 18.25)

    def test_legacy_dll_loads_and_keeps_render_usable_without_optional_symbol(self):
        library = fake_library()
        native = make_native(library)

        native.render(frame=7)

        self.assertEqual(library.lab_render.calls[0][1], 7)
        with self.assertRaisesRegex(RuntimeError, "optional lab_frame_stats"):
            native.frame_stats()


if __name__ == "__main__":
    unittest.main()
