"""Real-GL smoke test for the experimental SUR-00 frame statistics API.

Run serially with a newly built terrain_lab DLL and a SUR-00 v1 bundle. This
creates one hidden GL 3.3 context and does not build or alter any source bundle.
"""
import argparse
import ctypes as C
import json
import math
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "experiments" / "world-surroundings"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from sculpt_native import NativeTerrain


FIELDS = (
    "input_near", "color_near", "color_draws", "shadow_draws",
    "color_triangles", "shadow_triangles",
    "near_shadow_depth_span", "far_shadow_depth_span",
)
INTEGER_FIELDS = {
    "color_draws", "shadow_draws", "color_triangles", "shadow_triangles",
}


def require(report, label, condition, detail=None):
    if not condition:
        raise AssertionError(label if detail is None else f"{label}: {detail}")
    report["checks"].append(label)


def read_error(native):
    return (native.dll.lab_error() or b"unknown terrain_lab error").decode(
        "utf-8", "replace")


def raw_frame_stats(native, handle, output, capacity):
    result = native._frame_stats(handle, output, capacity)
    return int(result), read_error(native) if result != 1 else ""


def validate_stats(report, stats, label):
    require(report, label + " field names", set(stats) == set(FIELDS), sorted(stats))
    require(report, label + " finite values",
            all(math.isfinite(float(value)) for value in stats.values()))
    require(report, label + " count types",
            all(type(stats[name]) is int for name in INTEGER_FIELDS))
    require(report, label + " near/depth types",
            all(type(stats[name]) is float for name in set(FIELDS) - INTEGER_FIELDS))
    require(report, label + " nonnegative counts",
            all(stats[name] >= 0 for name in INTEGER_FIELDS))


def run(args):
    output = args.output.resolve()
    report = {
        "stage": "SUR-00 native frame stats smoke",
        "passed": False,
        "library": str(args.library.resolve()),
        "bundle": str(args.bundle.resolve()),
        "output": str(output),
        "checks": [],
    }
    pg = None
    native = None
    try:
        require(report, "library exists", args.library.is_file(), str(args.library))
        require(report, "bundle has scene and camera frames",
                (args.bundle / "scene.bin").is_file() and
                (args.bundle / "frames.bin").is_file(), str(args.bundle))
        output.mkdir(parents=True, exist_ok=True)

        import pygame as pg
        from OpenGL import GL

        pg.display.init()
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION, 3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION, 3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK,
                                    pg.GL_CONTEXT_PROFILE_CORE)
        require(report, "Pygame supports a hidden window", hasattr(pg, "HIDDEN"))
        pg.display.set_mode((1081, 662), pg.OPENGL | pg.DOUBLEBUF | pg.HIDDEN,
                            vsync=0)
        version_bytes = GL.glGetString(GL.GL_VERSION)
        require(report, "OpenGL context reports a version", version_bytes is not None)
        version = version_bytes.decode("ascii", "replace")
        major, minor = (int(part) for part in version.split()[0].split(".")[:2])
        require(report, "OpenGL context is at least 3.3", (major, minor) >= (3, 3), version)
        report["opengl"] = {
            "version": version,
            "vendor": GL.glGetString(GL.GL_VENDOR).decode("utf-8", "replace"),
            "renderer": GL.glGetString(GL.GL_RENDERER).decode("utf-8", "replace"),
        }

        native = NativeTerrain(args.library, args.bundle)
        require(report, "DLL exports optional frame stats", native._frame_stats is not None)
        before = native.stats()
        report["initial_stats"] = before

        try:
            native.frame_stats()
        except RuntimeError as error:
            require(report, "frame stats reject access before render",
                    "until a frame has been rendered" in str(error), str(error))
            report["pre_render_error"] = str(error)
        else:
            raise AssertionError("frame_stats returned data before the first render")

        aerial_frame = 3  # fixed_views() order in the SUR-00 frame bank
        native.render(aerial_frame)
        aerial = native.frame_stats()
        validate_stats(report, aerial, "aerial render")
        require(report, "aerial near values are plausible",
                0.0 < aerial["input_near"] < 1.0 <= aerial["color_near"] < 1_000_000.0,
                {key: aerial[key] for key in ("input_near", "color_near")})
        require(report, "active aerial shadow spans are plausible",
                0.0 < aerial["near_shadow_depth_span"] < 1_000_000.0 and
                0.0 < aerial["far_shadow_depth_span"] < 1_000_000.0,
                {key: aerial[key] for key in
                 ("near_shadow_depth_span", "far_shadow_depth_span")})
        require(report, "aerial frame has color geometry",
                aerial["color_draws"] > 0 and aerial["color_triangles"] > 0)
        report["aerial_frame"] = aerial_frame
        report["aerial_stats"] = aerial

        output_buffer = (C.c_double * len(FIELDS))()
        invalid_calls = []
        cases = (
            ("null handle", None, output_buffer, len(FIELDS), "handle is null"),
            ("short capacity", native.handle, output_buffer, len(FIELDS) - 1,
             "output buffer is too small"),
            ("null output", native.handle, None, len(FIELDS), "output pointer is null"),
        )
        for label, handle, buffer, capacity, message in cases:
            result, error = raw_frame_stats(native, handle, buffer, capacity)
            require(report, label + " is rejected", result == 0 and message in error,
                    {"result": result, "error": error})
            invalid_calls.append({"case": label, "result": result, "error": error})
            require(report, label + " preserves the saved snapshot",
                    native.frame_stats() == aerial)
        report["invalid_calls"] = invalid_calls

        thread_result = []

        def call_stats_from_foreign_thread():
            foreign_output = (C.c_double * len(FIELDS))()
            result = native._frame_stats(native.handle, foreign_output, len(FIELDS))
            thread_result.append({"result": int(result), "error": read_error(native)})

        worker = threading.Thread(target=call_stats_from_foreign_thread,
                                  name="terrain-lab-wrong-thread")
        worker.start()
        worker.join()
        require(report, "foreign-thread frame stats are rejected",
                len(thread_result) == 1 and thread_result[0]["result"] == 0 and
                "another thread" in thread_result[0]["error"], thread_result)
        require(report, "foreign-thread call preserves the saved snapshot",
                native.frame_stats() == aerial)
        report["foreign_thread_call"] = thread_result[0]

        native.render(0)
        ordinary_walk = native.frame_stats()
        validate_stats(report, ordinary_walk, "ordinary walk render")
        native.render(aerial_frame)
        stale_snapshot = native.frame_stats()
        require(report, "capture refresh uses a distinguishable frame",
                stale_snapshot["color_near"] != ordinary_walk["color_near"],
                {"aerial_color_near": stale_snapshot["color_near"],
                 "walk_color_near": ordinary_walk["color_near"]})

        capture_stem = output / "capture-refresh"
        native.capture(capture_stem, frame=0)
        capture_stats = native.frame_stats()
        for field in ("input_near", "color_near", "color_draws", "color_triangles"):
            require(report, "capture render matches ordinary render: " + field,
                    capture_stats[field] == ordinary_walk[field],
                    {"ordinary": ordinary_walk[field], "capture": capture_stats[field]})
        report["ordinary_walk_stats"] = ordinary_walk
        report["capture_render_stats"] = capture_stats
        report["capture_stem"] = str(capture_stem)

        after = native.stats()
        report["final_stats"] = after
        resource_keys = ("shader_compiles", "updates", "uploaded_bytes",
                         "texture_updates", "texture_uploaded_bytes")
        resource_changes = {
            key: {"before": before[key], "after": after[key]}
            for key in resource_keys if before[key] != after[key]
        }
        require(report, "renders and capture add no explicit updates or shader compiles",
                not resource_changes, resource_changes)

    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if native is not None and native.handle:
            try:
                native.close()
                report["native_handle_closed"] = True
            except Exception as error:
                report["native_handle_closed"] = False
                report["cleanup_error"] = f"{type(error).__name__}: {error}"
        if pg is not None:
            try:
                pg.display.quit()
                pg.quit()
            except Exception as error:
                report["cleanup_error"] = f"{type(error).__name__}: {error}"

    report["passed"] = "error" not in report and "cleanup_error" not in report
    report_path = output / "frame_stats_smoke.json"
    output.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(report_path),
                      "checks": len(report["checks"])}, indent=2))
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
