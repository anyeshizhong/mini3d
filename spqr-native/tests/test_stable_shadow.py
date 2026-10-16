#!/usr/bin/env python3
"""Numerical checks for the stable near-cascade shadow ABI; no GL is used."""
import argparse
import ctypes
import json
from pathlib import Path
import struct
import sys

import numpy as np


SIGNS = np.asarray([
    [-1.0, -1.0, -1.0], [-1.0, -1.0, 1.0],
    [-1.0, 1.0, -1.0], [-1.0, 1.0, 1.0],
    [1.0, -1.0, -1.0], [1.0, -1.0, 1.0],
    [1.0, 1.0, -1.0], [1.0, 1.0, 1.0],
], dtype=np.float64)


def look_at(eye, target):
    eye, target = np.asarray(eye, dtype=np.float64), np.asarray(target, dtype=np.float64)
    forward = target - eye
    forward /= np.linalg.norm(forward)
    up = np.array([0.0, 0.0, 1.0])
    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-12:
        up = np.array([0.0, 1.0, 0.0])
        right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    corrected_up = np.cross(right, forward)
    view = np.eye(4, dtype=np.float64)
    view[0, :3], view[1, :3], view[2, :3] = right, corrected_up, -forward
    view[:3, 3] = -view[:3, :3] @ eye
    return view


def perspective(fov_y_degrees, aspect, near, far):
    f = 1.0 / np.tan(np.deg2rad(fov_y_degrees) * 0.5)
    return np.array([
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, -(far + near) / (far - near), -2.0 * far * near / (far - near)],
        [0.0, 0.0, -1.0, 0.0],
    ], dtype=np.float64)


def world_matrix(position, scale=(1.0, 1.0, 1.0), yaw_degrees=0.0):
    angle = np.deg2rad(yaw_degrees)
    c, s = np.cos(angle), np.sin(angle)
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]) @ np.diag(scale)
    matrix[:3, 3] = position
    return matrix


def load_library(path):
    lib = ctypes.CDLL(str(path))
    dp, up = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_uint32)
    lib.spqr_fit_stable_shadow.argtypes = [dp, dp, up, ctypes.c_uint32, dp, dp, dp,
                                           ctypes.c_uint32, ctypes.c_double,
                                           ctypes.c_double, dp]
    lib.spqr_fit_stable_shadow.restype = ctypes.c_int
    return lib


def fit(lib, boxes, direction, view, projection, resolution, near_distance, far_distance):
    bounds = np.ascontiguousarray([box[0] for box in boxes], dtype=np.float64).reshape(-1, 6)
    worlds = np.ascontiguousarray([box[1] for box in boxes], dtype=np.float64).reshape(-1, 16)
    flags = np.ascontiguousarray([1 if box[2] else 0 for box in boxes], dtype=np.uint32)
    direction = np.ascontiguousarray(direction, dtype=np.float64)
    view = np.ascontiguousarray(view, dtype=np.float64)
    projection = np.ascontiguousarray(projection, dtype=np.float64)
    output = np.zeros(16, dtype=np.float64)
    result = lib.spqr_fit_stable_shadow(
        bounds.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        worlds.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), len(boxes),
        direction.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        view.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        projection.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), resolution,
        near_distance, far_distance,
        output.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    if result != 1:
        raise AssertionError("stable shadow fit unexpectedly fell back")
    return output.reshape(4, 4)


def light_basis(direction):
    light = np.asarray(direction, dtype=np.float64)
    light /= np.linalg.norm(light)
    up = np.eye(3)[np.argmin(np.abs(light))]
    right = np.cross(up, light)
    right /= np.linalg.norm(right)
    return right, np.cross(light, right), light


def split_corners(view, projection, near_distance, far_distance):
    inverse_projection = np.linalg.inv(projection)
    inverse_view = np.linalg.inv(view)
    corners_camera = []
    corners_world = []
    for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        point = inverse_projection @ np.array([sx, sy, -1.0, 1.0])
        point = point[:3] / point[3]
        depth = -point[2]
        slope_x, slope_y = point[0] / depth, point[1] / depth
        for distance in (near_distance, far_distance):
            camera_point = np.array([slope_x * distance, slope_y * distance, -distance])
            world_h = inverse_view @ np.append(camera_point, 1.0)
            corners_camera.append(camera_point)
            corners_world.append(world_h[:3] / world_h[3])
    return np.asarray(corners_camera), np.asarray(corners_world)


def box_world_corners(bounds, world):
    local = (bounds[:3] + bounds[3:]) * 0.5 + SIGNS * ((bounds[3:] - bounds[:3]) * 0.5)
    return local @ world[:3, :3].T + world[:3, 3]


def transform_points(matrix, points):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def read_camera_frames(path):
    data = path.read_bytes()
    if data[:8] != b"SPQRF001":
        raise ValueError(f"bad frames header: {path}")
    count = struct.unpack_from("<I", data, 8)[0]
    offset = 12
    frames = []
    for _ in range(count):
        route_size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        route = data[offset:offset + route_size].decode("utf-8")
        offset += route_size
        t = struct.unpack_from("<d", data, offset)[0]
        offset += 8
        values = np.frombuffer(data, dtype="<f8", count=46, offset=offset).astype(np.float64)
        offset += 46 * 8
        frames.append({
            "route": route, "t": t,
            "view": values[12:28].reshape(4, 4),
            "projection": values[28:44].reshape(4, 4),
        })
    if offset != len(data):
        raise ValueError(f"unexpected trailing bytes in {path}")
    return frames


def verify_real_pompeii(lib, project, bundle, split_near=0.02, split_far=18.0, resolution=4096):
    sys.path.insert(0, str(project.resolve()))
    sys.path.insert(0, str((project / "tests").resolve()))
    from mini3d.api import Mini3DAPI
    from tools.build_pompeii import build_scene

    api = Mini3DAPI()
    build_scene(api)
    scene = api._app.scene
    scene.update()
    entities = scene.get_flat_render_list()
    valid = [entity for entity in entities if getattr(entity.model, "bounds", None) is not None]
    bounds = np.ascontiguousarray(
        [np.asarray(entity.model.bounds, dtype=np.float64).reshape(-1) for entity in valid], dtype=np.float64)
    worlds = np.ascontiguousarray(
        [np.asarray(entity.world_matrix, dtype=np.float64).reshape(-1) for entity in valid], dtype=np.float64)
    flags = np.ascontiguousarray([
        2 if np.linalg.det(np.asarray(entity.world_matrix, dtype=np.float64)[:3, :3]) < 0.0 else 0
        for entity in valid
    ], dtype=np.uint32)
    if not len(valid):
        raise AssertionError("Pompeii scene produced no bounded render entities")
    world_corners = np.concatenate([
        box_world_corners(np.asarray(entity.model.bounds, dtype=np.float64).reshape(6),
                          np.asarray(entity.world_matrix, dtype=np.float64))
        for entity in valid
    ], axis=0)

    metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    direction = np.asarray(metadata["lighting"]["direction_surface_to_light"], dtype=np.float64)
    frames = read_camera_frames(bundle / "frames.bin")
    route_counts = {route: sum(frame["route"] == route for frame in frames) for route in ("walk", "orbit")}
    if len(frames) != 288 or route_counts != {"walk": 144, "orbit": 144}:
        raise AssertionError(f"expected 288 camera frames (144 per route), got {len(frames)} / {route_counts}")

    double_ptr = ctypes.POINTER(ctypes.c_double)
    uint_ptr = ctypes.POINTER(ctypes.c_uint32)
    native = lib.spqr_fit_stable_shadow
    rows = []
    reference_xy_scale = None
    max_texel_error = 0.0
    max_split_xy = 0.0
    max_abs_caster_z = 0.0
    for index, frame in enumerate(frames):
        view = np.ascontiguousarray(frame["view"], dtype=np.float64)
        projection = np.ascontiguousarray(frame["projection"], dtype=np.float64)
        direction_arg = np.ascontiguousarray(direction, dtype=np.float64)
        output = np.zeros(16, dtype=np.float64)
        result = native(
            bounds.ctypes.data_as(double_ptr), worlds.ctypes.data_as(double_ptr),
            flags.ctypes.data_as(uint_ptr), len(valid),
            direction_arg.ctypes.data_as(double_ptr), view.ctypes.data_as(double_ptr),
            projection.ctypes.data_as(double_ptr), resolution, split_near, split_far,
            output.ctypes.data_as(double_ptr))
        if result != 1:
            raise AssertionError(f"stable shadow fit failed on {frame['route']} frame {index}")
        matrix = output.reshape(4, 4)
        xy_scale = np.linalg.norm(matrix[:2, :3], axis=1)
        if reference_xy_scale is None:
            reference_xy_scale = xy_scale
        elif not np.allclose(xy_scale, reference_xy_scale, rtol=1e-13, atol=0.0):
            raise AssertionError(f"XY world extent drifted on {frame['route']} frame {index}: {xy_scale}")

        texel_indices = matrix[:2, 3] * (resolution * 0.5)
        texel_error = np.abs(texel_indices - np.rint(texel_indices))
        local_texel_error = float(texel_error.max())
        max_texel_error = max(max_texel_error, local_texel_error)
        if local_texel_error > 2e-7:
            raise AssertionError(f"shadow center missed texel grid on {frame['route']} frame {index}: {local_texel_error}")

        _, split_world = split_corners(view, projection, split_near, split_far)
        split_clip = transform_points(matrix, split_world)
        local_split_xy = float(np.abs(split_clip[:, :2]).max())
        max_split_xy = max(max_split_xy, local_split_xy)
        if local_split_xy > 1.0 + 2e-12:
            raise AssertionError(f"split corner outside shadow XY on {frame['route']} frame {index}: {local_split_xy}")

        caster_z = world_corners @ matrix[2, :3] + matrix[2, 3]
        local_caster_z = float(np.abs(caster_z).max())
        max_abs_caster_z = max(max_abs_caster_z, local_caster_z)
        if local_caster_z > 1.0 + 2e-12:
            raise AssertionError(f"real Pompeii caster corner outside shadow depth on frame {index}: {local_caster_z}")

        rows.append({
            "route": frame["route"], "frame_index": index, "t": frame["t"],
            "xy_scale_x": float(xy_scale[0]), "xy_scale_y": float(xy_scale[1]),
            "texel_index_x": float(texel_indices[0]), "texel_index_y": float(texel_indices[1]),
            "max_split_corner_xy": local_split_xy, "max_abs_caster_z": local_caster_z,
        })

    return {
        "passed": True,
        "scene": "Pompeii",
        "bounded_render_entities": len(valid),
        "camera_samples": len(rows),
        "route_counts": route_counts,
        "split_near": split_near,
        "split_far": split_far,
        "resolution": resolution,
        "xy_scale_x": float(reference_xy_scale[0]),
        "xy_scale_y": float(reference_xy_scale[1]),
        "max_texel_index_error": max_texel_error,
        "max_split_corner_xy": max_split_xy,
        "max_abs_caster_z": max_abs_caster_z,
        "samples": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[1] / "assets")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    lib = load_library(args.library.resolve())

    eye = np.array([1.0, -30.0, 11.0])
    target = np.array([0.0, 12.0, 1.5])
    view = look_at(eye, target)
    projection = perspective(48.0, 1081.0 / 662.0, 0.1, 180.0)
    direction = np.array([0.44, -0.70, 0.56], dtype=np.float64)
    near_distance, far_distance, resolution = 0.1, 42.0, 2048
    camera_corners, frustum_corners = split_corners(view, projection, near_distance, far_distance)
    center_camera = np.array([0.0, 0.0, -(near_distance + far_distance) * 0.5])
    radius = np.ceil(np.linalg.norm(camera_corners - center_camera, axis=1).max())
    expected_side = 2.0 * radius / (1.0 - 4.0 / resolution)

    right, second, light = light_basis(direction)
    center_world = np.linalg.inv(view) @ np.append(center_camera, 1.0)
    center_world = center_world[:3] / center_world[3]
    offscreen_center = center_world + light * 250.0
    boxes = [
        (np.array([-2.0, -2.5, 0.0, 2.0, 2.5, 7.0]), world_matrix([0.0, -4.0, 0.0]), False),
        (np.array([-1.5, -2.0, 0.0, 1.5, 2.0, 6.0]),
         world_matrix([5.5, 8.0, 0.0], (1.4, 0.7, 1.2), 27.0), False),
        # This caster is outside the camera split, but shares XY with its center
        # in light space and must still be included by the global depth bounds.
        (np.array([-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]), world_matrix(offscreen_center), False),
    ]
    ground = (np.array([-1.0, -1.0, 0.0, 1.0, 1.0, 0.0]),
              world_matrix(center_world, (1000.0, 1000.0, 1.0)), True)

    matrix = fit(lib, boxes + [ground], direction, view, projection,
                 resolution, near_distance, far_distance)
    without_ground = fit(lib, boxes, direction, view, projection,
                         resolution, near_distance, far_distance)
    if not np.array_equal(matrix, without_ground):
        raise AssertionError("photographic ground changed stable caster bounds")

    row0_scale = np.linalg.norm(matrix[0, :3])
    row1_scale = np.linalg.norm(matrix[1, :3])
    actual_side = 2.0 / row0_scale
    if not np.isclose(actual_side, expected_side, rtol=1e-12, atol=1e-12):
        raise AssertionError((actual_side, expected_side))
    if actual_side * 0.5 - radius < 2.0 * actual_side / resolution - 1e-12:
        raise AssertionError("stable split volume has less than a two-texel guard")
    if not np.isclose(row0_scale, row1_scale, rtol=1e-14, atol=0.0):
        raise AssertionError("stable shadow XY extent is not square")
    split_clip = transform_points(matrix, frustum_corners)
    if np.any(np.abs(split_clip[:, :2]) > 1.0 + 1e-12):
        raise AssertionError("split frustum corner fell outside stable shadow XY")

    texel = actual_side / resolution
    center_x = float(np.dot(right, center_world))
    snapped_x = -matrix[0, 3] / row0_scale
    offset = center_x - snapped_x
    if abs(offset) > 1e-10:
        shift = -np.sign(offset) * min(0.2 * texel, max(1e-8 * texel, 0.25 * (0.5 * texel - abs(offset))))
    else:
        shift = 0.2 * texel
    eye_shifted, target_shifted = eye + right * shift, target + right * shift
    moved = fit(lib, boxes + [ground], direction, look_at(eye_shifted, target_shifted),
                projection, resolution, near_distance, far_distance)
    if abs(shift) >= texel or not np.array_equal(matrix[:2], moved[:2]):
        raise AssertionError("same-cell subtexel translation changed stable shadow XY")
    if not np.array_equal(matrix[2], moved[2]):
        raise AssertionError("camera translation changed global caster depth bounds")

    rotated_view = look_at(eye, eye + np.array([6.0, 41.0, -8.0]))
    rotated = fit(lib, boxes + [ground], direction, rotated_view, projection,
                  resolution, near_distance, far_distance)
    if not np.allclose(np.linalg.norm(rotated[:2, :3], axis=1),
                       [row0_scale, row1_scale], rtol=1e-14, atol=0.0):
        raise AssertionError("camera rotation changed split radius or XY extent")
    rotated_corners_camera, rotated_corners_world = split_corners(
        rotated_view, projection, near_distance, far_distance)
    _ = rotated_corners_camera
    if np.any(np.abs(transform_points(rotated, rotated_corners_world)[:, :2]) > 1.0 + 1e-12):
        raise AssertionError("rotated split frustum corner fell outside stable shadow XY")

    offscreen_corners = box_world_corners(boxes[2][0], boxes[2][1])
    offscreen_clip = transform_points(matrix, offscreen_corners)
    if not np.all(np.abs(offscreen_clip[:, 2]) <= 1.0 + 1e-12):
        raise AssertionError("offscreen caster exceeded conservative stable depth bounds")
    offscreen_view = transform_points(view, offscreen_corners)
    if np.all((-offscreen_view[:, 2] >= near_distance) & (-offscreen_view[:, 2] <= far_distance)):
        raise AssertionError("offscreen depth fixture unexpectedly lies in the camera split")

    print("PASS stable XY side / 1m radius rounding / split frustum coverage")
    print("PASS same-cell subtexel translation leaves XY matrix unchanged")
    print("PASS camera rotation keeps fixed split extent and covers corners")
    print("PASS ground is excluded and offscreen caster remains depth-covered")

    real = verify_real_pompeii(lib, args.project, args.bundle)
    real["library"] = str(args.library.resolve())
    real["library_kind"] = "provided build output; not the temporary test DLL"
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(real, indent=2), encoding="utf-8")
    print("PASS real Pompeii walk+orbit camera samples:", real["camera_samples"])
    print(json.dumps({key: value for key, value in real.items() if key != "samples"}, indent=2))


if __name__ == "__main__":
    main()
