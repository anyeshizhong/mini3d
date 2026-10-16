#!/usr/bin/env python3
"""Exercise native Shot rendering through the real editor frame loop."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback
import traceback

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["MINI3D_PHOTO_BACKEND"] = "native"
os.environ["MINI3D_REQUIRE_NATIVE_PHOTO"] = "1"


def png_info(path, pygame):
    if not path.is_file():
        raise AssertionError("Expected PNG was not written: {}".format(path))
    surface = pygame.image.load(str(path))
    pixels = pygame.surfarray.array3d(surface)
    nonblack = int(np.count_nonzero(np.any(pixels > 2, axis=2)))
    if nonblack < 100:
        raise AssertionError("PNG is empty or nearly black: {}".format(path))
    return dict(path=str(path.resolve()), size=list(surface.get_size()), nonblack_pixels=nonblack)


def drain_gl_errors(gl):
    errors = []
    while True:
        code = int(gl.glGetError())
        if code == gl.GL_NO_ERROR:
            return errors
        errors.append("0x{:04x}".format(code))


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "frames": [], "actions": {}, "output": str(output.resolve())}
    original_draw = original_flip = None
    editor_ui_class = pygame = None
    holder = {"draw_index": 0, "frame_index": None, "app": None}
    shot_path = output / "native-shot.png"
    editor_path = output / "editor.png"

    try:
        import pygame as pygame_module
        from OpenGL import GL as gl
        from mini3d.editor import Editor
        from mini3d.editor_runtime import run as run_editor
        from mini3d.editor_ui import EditorUI

        pygame = pygame_module
        editor_ui_class = EditorUI
        original_draw = EditorUI.draw
        original_flip = pygame.display.flip

        def probed_draw(ui, width, height, texture_id):
            frame_index = holder["draw_index"]
            holder["draw_index"] += 1
            holder["frame_index"] = frame_index
            holder["app"] = ui.app
            api = ui.app.api

            if frame_index == 1:
                if ui.app.displayed_frame is None:
                    raise AssertionError("API.screenshot requires the completed frame 0")
                report["actions"]["frame1_capture"] = api.capture(shot_path)
                report["actions"]["frame1_screenshot"] = api.screenshot(editor_path)
            elif frame_index == 2:
                api.set_photo_color(7200.0, "Warm")
                report["actions"]["frame2"] = "set_photo_color(7200, Warm)"
            elif frame_index == 4:
                api.set_depth_of_field(enabled=True, focus_distance=10.0, f_number=8.0)
                report["actions"]["frame4"] = "enable DOF at 10m / f8"
            elif frame_index == 6:
                api.reset_photo_color()
                api.set_depth_of_field(enabled=False)
                report["actions"]["frame6"] = "reset color and disable DOF"
            elif frame_index == 8:
                api.set_workspace("Arrange")
                api.set_view("Editor")
                report["actions"]["frame8"] = "Arrange workspace / Editor view"
            elif frame_index == 10:
                api.set_view("Camera")
                report["actions"]["frame10"] = "return to Camera view"

            return original_draw(ui, width, height, texture_id)

        def probed_flip():
            original_flip()
            app = holder["app"]
            frame_index = holder["frame_index"]
            if app is None or frame_index is None:
                raise AssertionError("Editor frame flipped without its UI draw probe")
            renderer = app.api._renderer
            stats = dict(renderer.render_stats)
            native = getattr(renderer, "native_photo", None)
            state = dict(
                frame=frame_index,
                displayed_frame_id=(app.displayed_frame or {}).get("frame_id"),
                workspace=app.workspace,
                camera_view=bool(app.camera_view),
                backend=stats.get("backend"),
                viewport_redrawn=stats.get("viewport_redrawn"),
                native_frames=getattr(native, "frames", None),
                native_bundle_builds=getattr(native, "bundle_builds", None),
                native_parameter_updates=getattr(native, "parameter_updates", None),
                effective_near=stats.get("effective_near"),
                samples=stats.get("samples"),
                width=stats.get("width"),
                height=stats.get("height"),
                gl_errors=drain_gl_errors(gl),
            )
            report["frames"].append(state)
            print("FRAME {} {}".format(frame_index, json.dumps(state, sort_keys=True)), flush=True)
            if state["gl_errors"]:
                raise AssertionError("OpenGL errors after frame {}: {}".format(
                    frame_index, state["gl_errors"]))
            if frame_index in (0, 1):
                if app.workspace != "Shot" or not app.camera_view or state["backend"] != "native-photo":
                    raise AssertionError("Initial Shot viewport did not use the native-photo backend")
            if frame_index == 8 and (app.workspace != "Arrange" or app.camera_view):
                raise AssertionError("Arrange/Editor transition did not reach the legacy editor viewport")
            if frame_index == 10 and (app.workspace != "Shot" or not app.camera_view or
                                      state["backend"] != "native-photo"):
                raise AssertionError("Returning to Camera did not restore native Shot rendering")

        EditorUI.draw = probed_draw
        pygame.display.flip = probed_flip
        scene_path = ROOT / "examples" / "pompeii" / "native-photo.json"
        print("START editor_runtime.run: 12 hidden frames, native backend required", flush=True)
        run_editor(Editor, initial_asset=None, frames=12, hidden=True, ipc=False,
                   scene_path=scene_path)

        if len(report["frames"]) != 12:
            raise AssertionError("Expected 12 completed editor frames, got {}".format(
                len(report["frames"])))
        if not any(frame.get("native_frames") for frame in report["frames"]):
            raise AssertionError("Editor loop produced no native renderer frames")
        arrange = [frame for frame in report["frames"]
                   if frame["workspace"] == "Arrange" and not frame["camera_view"]]
        if not arrange:
            raise AssertionError("No completed Arrange/Editor frame was observed")
        camera_frames = [frame for frame in report["frames"]
                         if frame["frame"] >= 10 and frame["camera_view"]]
        if not camera_frames or camera_frames[0].get("backend") != "native-photo":
            raise AssertionError("Native Shot backend did not resume after Arrange")
        if not all(key in report["actions"] for key in
                   ("frame1_capture", "frame1_screenshot", "frame2", "frame4", "frame6", "frame8", "frame10")):
            raise AssertionError("One or more scheduled editor actions did not run")

        report["pngs"] = {
            "native_shot": png_info(shot_path, pygame),
            "editor": png_info(editor_path, pygame),
        }
        if report["pngs"]["native_shot"]["size"] != [1920, 1080]:
            raise AssertionError("Native Shot capture is not 1920x1080")
        report["constraints"] = {
            "real_editor_runtime": True,
            "native_backend_required": True,
            "synthetic_ui_or_os_input": False,
            "completed_frames": len(report["frames"]),
            "arrange_frame_count": len(arrange),
            "return_to_native_frame": camera_frames[0]["frame"],
            "gl_errors": 0,
        }
        report["passed"] = True
    except BaseException as exc:
        report["passed"] = False
        report["error"] = "{}: {}".format(type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        if editor_ui_class is not None and original_draw is not None:
            editor_ui_class.draw = original_draw
        if pygame is not None and original_flip is not None:
            pygame.display.flip = original_flip
        path = output / "report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("REPORT " + str(path.resolve()), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="directory for report and PNGs")
    run(parser.parse_args().output.expanduser().resolve())


if __name__ == "__main__":
    main()
