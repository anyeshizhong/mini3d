#!/usr/bin/env python3
"""Exercise the native Shot renderer on a real Pompeii scene and GL context."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# This smoke must fail at the native boundary instead of accepting Python fallback.
os.environ["MINI3D_PHOTO_BACKEND"] = "native"
os.environ["MINI3D_REQUIRE_NATIVE_PHOTO"] = "1"


def stage(message):
    print("STEP " + message, flush=True)


def rgb_top_down(target, size, gl, read_rgb):
    old_read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    old_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))
    try:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        raw = read_rgb(0, 0, size[0], size[1])
        return np.frombuffer(raw, dtype=np.uint8).reshape(size[1], size[0], 3)[::-1].copy()
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, old_read)
        gl.glReadBuffer(old_buffer)


def depth_buffer(target, size, gl):
    old_read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    old_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))
    try:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        raw = gl.glReadPixels(0, 0, size[0], size[1], gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)
        if isinstance(raw, (bytes, bytearray, memoryview)):
            values = np.frombuffer(raw, dtype=np.float32)
        else:
            values = np.asarray(raw, dtype=np.float32).reshape(-1)
        if values.size != size[0] * size[1]:
            raise AssertionError("Resolved depth readback has the wrong size")
        return values.reshape(size[1], size[0]).copy()
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, old_read)
        gl.glReadBuffer(old_buffer)


def visible_world_z(depth, camera, size):
    height, width = depth.shape
    rows, columns = np.nonzero(depth < 1.0 - 1e-7)
    if not len(rows):
        return np.empty(0, dtype=np.float64)
    ndc_x = (columns.astype(np.float64) + 0.5) * (2.0 / width) - 1.0
    ndc_y = (rows.astype(np.float64) + 0.5) * (2.0 / height) - 1.0
    ndc_z = depth[rows, columns].astype(np.float64) * 2.0 - 1.0
    clip = np.column_stack((ndc_x, ndc_y, ndc_z, np.ones(len(rows))))
    camera_points = clip @ np.linalg.inv(camera.projection_matrix(size[0] / size[1])).T
    camera_points /= camera_points[:, 3, None]
    world_points = camera_points @ np.linalg.inv(camera.view_matrix).T
    return world_points[:, 2] / world_points[:, 3]


def load_png_rgb(path, pygame):
    surface = pygame.image.load(str(path))
    return pygame.surfarray.array3d(surface).transpose(1, 0, 2).copy()


def no_gl_errors(gl, label):
    errors = []
    while True:
        error = int(gl.glGetError())
        if error == gl.GL_NO_ERROR:
            break
        errors.append("0x{:04x}".format(error))
    if errors:
        raise AssertionError("OpenGL error after {}: {}".format(label, ", ".join(errors)))


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "steps": [], "output": str(output.resolve())}

    def done(message):
        report["steps"].append(message)
        stage(message)

    renderer = target = api = None
    try:
        from OpenGL import GL as gl
        import pygame
        from mini3d.api import Mini3DAPI
        from mini3d.gl_renderer import GLRenderer
        from mini3d.render_target import RenderTarget
        from mini3d.shot_camera import render_scene_view
        from mini3d.gl_state import read_rgb
        from tools.capture_sunset import desktop_context

        context = desktop_context()
        context.__enter__()
        try:
            renderer = GLRenderer(960, 540)
            renderer.render_mode = "REALISTIC"
            target = RenderTarget()
            api = Mini3DAPI(renderer=renderer)
            scene_file = ROOT / "examples" / "pompeii" / "district.json"
            api.load_scene(scene_file)
            scene = api._app.scene
            scene.update()
            shot = api._app.shot_camera
            if shot is None:
                raise AssertionError("Pompeii scene did not load its Shot Camera")
            shot.position = [1.0, -10.0, 1.7]
            shot.look_at([0.0, 20.0, 3.0])
            shot.near, shot.far = 0.0012, 100.0
            shot.set_aspect("16:9")
            shot.set_lens(24.0)
            shot.set_samples(4)
            shot.set_depth_of_field(enabled=False)
            original_shot = shot.to_dict()
            if (not np.isclose(shot.focal_mm, 24.0, atol=1e-10) or
                    shot.aspect_name != "16:9" or shot.samples != 4 or
                    shot.near != 0.0012 or shot.far != 100.0):
                raise AssertionError("Shot Camera did not accept the requested native-walk setup")
            done("loaded Pompeii district and configured original walk Shot Camera")
            no_gl_errors(gl, "setup")

            preview_size = (960, 540)

            def render(size=preview_size, samples=None):
                scene.update()
                render_scene_view(scene, shot, renderer, target, size,
                                  shot.samples if samples is None else samples)
                stats = renderer.render_stats
                if stats.get("backend") != "native-photo":
                    raise AssertionError("Shot used {} instead of native-photo".format(
                        stats.get("backend", "an unknown renderer")))
                no_gl_errors(gl, "native render {}x{} / {}x".format(size[0], size[1],
                                                                    shot.samples if samples is None else samples))
                return stats

            stats = render()
            effective_near = float(target.render_camera.near)
            if effective_near <= original_shot["near"]:
                raise AssertionError("Native conservative near did not exceed the legacy Shot near")
            if shot.to_dict() != original_shot:
                raise AssertionError("Rendering mutated the Shot Camera")
            first_pixels = rgb_top_down(target, preview_size, gl, read_rgb)
            first_depth = depth_buffer(target, preview_size, gl)
            if not np.isfinite(first_depth).all() or not np.any(first_depth < 1.0 - 1e-7):
                raise AssertionError("Native render produced an empty depth buffer")
            sky_pixels = int(np.count_nonzero(first_depth >= 1.0 - 1e-7))
            world_z = visible_world_z(first_depth, target.render_camera, preview_size)
            ground_z = float(api.get_atmosphere()["ground_z"])
            ground_pixels = int(np.count_nonzero(np.abs(world_z - ground_z) < 0.04))
            model_pixels = int(np.count_nonzero(world_z > ground_z + 0.5))
            if sky_pixels < 100 or ground_pixels < 100 or model_pixels < 100:
                raise AssertionError("Expected visible sky/ground/model; counts={}".format(
                    {"sky": sky_pixels, "ground": ground_pixels, "model": model_pixels}))
            if int(stats.get("color_triangles", 0)) <= 0:
                raise AssertionError("Native scene submitted no color triangles")
            report["initial_frame"] = dict(
                backend=stats["backend"], effective_near=effective_near,
                legacy_near=original_shot["near"], sky_pixels=sky_pixels,
                ground_pixels=ground_pixels, model_pixels=model_pixels,
                color_triangles=int(stats["color_triangles"]),
                depth_min=float(first_depth.min()), depth_max=float(first_depth.max()))
            done("native backend rendered geometry, sky, ground and adjusted only target near")

            native = renderer.native_photo
            if native.handle is None:
                raise AssertionError("Native renderer did not create a context handle")
            initial_handle = native.handle
            initial_builds = native.bundle_builds
            initial_updates = native.parameter_updates
            moved = np.array([0.35, 0.0, 0.0])
            shot.position = shot.position + moved
            shot.look_at(np.array([0.0, 20.0, 3.0]) + moved)
            moved_snapshot = shot.to_dict()
            render()
            if native.bundle_builds != initial_builds:
                raise AssertionError("Camera movement rebuilt the native scene bundle")
            if shot.to_dict() != moved_snapshot:
                raise AssertionError("Native camera motion mutated Shot parameters")
            camera_pixels = rgb_top_down(target, preview_size, gl, read_rgb)
            done("camera motion reused the same native bundle")

            builds_before_color = native.bundle_builds
            updates_before_color = native.parameter_updates
            api.set_photo_color(8200.0, "Warm")
            api.set_atmosphere(exposure_ev=0.7)
            color_snapshot = shot.to_dict()
            render()
            color_pixels = rgb_top_down(target, preview_size, gl, read_rgb)
            color_delta = int(np.count_nonzero(np.any(camera_pixels != color_pixels, axis=2)))
            if native.bundle_builds != builds_before_color:
                raise AssertionError("White balance / exposure rebuilt the native scene bundle")
            if native.parameter_updates <= updates_before_color:
                raise AssertionError("White balance / exposure did not update native parameters")
            if color_delta < 100:
                raise AssertionError("White balance / exposure did not change rendered pixels")
            if shot.to_dict() != color_snapshot:
                raise AssertionError("Color or exposure update mutated unrelated Shot fields")
            report["color_update"] = dict(pixel_changed=color_delta,
                bundle_builds=native.bundle_builds, parameter_updates=native.parameter_updates)
            done("white balance and exposure updated parameters without rebuilding assets")

            api.set_antialiasing(1)
            builds_before_resize = native.bundle_builds
            resize_handle = native.handle
            render((800, 450), 1)
            api.set_antialiasing(4)
            render((800, 450), 4)
            if native.handle != resize_handle or native.bundle_builds != builds_before_resize:
                raise AssertionError("Resize or AA 1x/4x switch replaced the native scene bundle")
            api.set_antialiasing(4)
            render(preview_size, 4)
            done("size and 1x/4x AA changes reused the native handle and bundle")

            full_size = shot.size
            if full_size != (1920, 1080):
                raise AssertionError("16:9 Shot Camera did not resolve to 1920x1080")
            render(full_size, 4)
            preview_path = output / "preview.png"
            capture_path = output / "capture.png"
            preview_pixels = rgb_top_down(target, full_size, gl, read_rgb)
            pygame.image.save(pygame.image.fromstring(preview_pixels.tobytes(), full_size,
                                                       "RGB", False), str(preview_path))
            preview_shot = shot.to_dict()
            api.capture(capture_path)
            captured_pixels = load_png_rgb(capture_path, pygame)
            if captured_pixels.shape != preview_pixels.shape or not np.array_equal(captured_pixels, preview_pixels):
                difference = int(np.count_nonzero(np.any(captured_pixels != preview_pixels, axis=2)))
                raise AssertionError("API.capture differs from same-size native preview in {} pixels".format(difference))
            if shot.to_dict() != preview_shot:
                raise AssertionError("API.capture mutated the Shot Camera")
            if native.handle != resize_handle or native.bundle_builds != builds_before_resize:
                raise AssertionError("Full-resolution capture rebuilt the native scene bundle")
            report["capture"] = dict(size=list(full_size), exact_rgb_match=True,
                                     bundle_builds=native.bundle_builds,
                                     parameter_updates=native.parameter_updates)
            done("1920x1080 API.capture PNG exactly matches same-size native preview")

            # A newly added built-in module and a later transform each change
            # native geometry resources and must visibly affect the next frame.
            render(preview_size, 4)
            before_add = rgb_top_down(target, preview_size, gl, read_rgb)
            builds_before_add = native.bundle_builds
            added = api.spawn("builtin:roman-column", name="Native photo smoke column",
                              position=[1.0, 1.0, 0.0], placement_type="prop", anchor="pivot")
            scene.update()
            render(preview_size, 4)
            after_add = rgb_top_down(target, preview_size, gl, read_rgb)
            add_delta = int(np.count_nonzero(np.any(before_add != after_add, axis=2)))
            if native.bundle_builds <= builds_before_add or add_delta < 100:
                raise AssertionError("Adding a built-in module failed to rebuild or change the frame")
            builds_before_transform = native.bundle_builds
            before_transform = after_add
            api.set_transform(added["entity_id"], position=[-3.0, 8.0, 0.0])
            scene.update()
            render(preview_size, 4)
            after_transform = rgb_top_down(target, preview_size, gl, read_rgb)
            transform_delta = int(np.count_nonzero(np.any(before_transform != after_transform, axis=2)))
            if native.bundle_builds <= builds_before_transform or transform_delta < 100:
                raise AssertionError("Transform edit failed to rebuild or change the frame")
            report["geometry_edits"] = dict(add_pixel_changed=add_delta,
                transform_pixel_changed=transform_delta,
                bundle_builds=native.bundle_builds)
            done("adding and transforming a built-in module rebuilt assets and changed pixels")

            native.close()
            if native.handle is not None:
                raise AssertionError("First native close did not clear the handle")
            native.close()
            done("native context close is idempotent")
            no_gl_errors(gl, "final smoke")
            report["gl_error"] = 0
            report["native_frames"] = native.frames
            report["native_handle_reused_before_geometry_edits"] = True
            report["passed"] = True
        finally:
            try:
                if target is not None:
                    target.close()
                if renderer is not None:
                    renderer.close()
            finally:
                context.__exit__(*sys.exc_info())
    except BaseException as exc:
        report["passed"] = False
        report["error"] = "{}: {}".format(type(exc).__name__, exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        stage("report written: " + str((output / "report.json").resolve()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="directory for report and preview/capture PNGs")
    run(parser.parse_args().output.expanduser().resolve())


if __name__ == "__main__":
    main()
