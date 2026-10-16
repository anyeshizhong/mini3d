#!/usr/bin/env python3
"""Numerical ABI comparison against the existing Python shadow fit."""
from __future__ import annotations

import argparse
import ctypes
from pathlib import Path
import sys
import warnings

import numpy as np


def look_at(eye, target):
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
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
    view[0, :3] = right
    view[1, :3] = corrected_up
    view[2, :3] = -forward
    view[0, 3] = -np.dot(right, eye)
    view[1, 3] = -np.dot(corrected_up, eye)
    view[2, 3] = np.dot(forward, eye)
    return view


class Camera:
    def __init__(self, eye, target, far=500.0, fov_y=48.0, aspect=16.0 / 9.0):
        self.eye = np.asarray(eye, dtype=np.float64)
        self.target = np.asarray(target, dtype=np.float64)
        self.aspect = float(aspect)
        self.near = 0.05
        self.far = float(far)
        self.fov_y = float(fov_y)
        self.view_matrix = look_at(self.eye, self.target)

    def projection_matrix(self, aspect):
        f = 1.0 / np.tan(np.deg2rad(self.fov_y) * 0.5)
        near, far = self.near, self.far
        return np.array([
            [f / aspect, 0.0, 0.0, 0.0],
            [0.0, f, 0.0, 0.0],
            [0.0, 0.0, -(far + near) / (far - near), -(2.0 * far * near) / (far - near)],
            [0.0, 0.0, -1.0, 0.0],
        ], dtype=np.float64)


class Mesh:
    def __init__(self, bounds, material=None):
        self.bounds = np.asarray(bounds, dtype=np.float64).reshape(2, 3)
        self.material = material


class Entity:
    def __init__(self, bounds, world, ground=False):
        material = {"extras": {"photographicGround": True}} if ground else None
        self.model = Mesh(bounds, material)
        self.world_matrix = np.asarray(world, dtype=np.float64).reshape(4, 4)


def transform(position, scale=(1.0, 1.0, 1.0), angles=(0.0, 0.0, 0.0)):
    x, y, z = np.deg2rad(np.asarray(angles, dtype=np.float64))
    cx, sx = np.cos(x), np.sin(x)
    cy, sy = np.cos(y), np.sin(y)
    cz, sz = np.cos(z), np.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rz @ ry @ rx @ np.diag(np.asarray(scale, dtype=np.float64))
    matrix[:3, 3] = np.asarray(position, dtype=np.float64)
    return matrix


def street_entities(center=(0.0, 0.0, 0.0), rotated=False):
    center = np.asarray(center, dtype=np.float64)
    entities = []
    bounds = np.array([[-1.9, -2.35, 0.0], [1.9, 2.35, 5.2]])
    for i in range(9):
        lane = -1.0 if i % 2 == 0 else 1.0
        distance = -2.0 + (i // 2) * 6.0
        pos = center + np.array([lane * 4.1, distance, 0.0])
        if rotated and i in (2, 6):
            scale = (1.7, 0.62, 1.25) if i == 2 else (-1.4, 0.8, 1.2)
            world = transform(pos, scale, (7.0, -11.0, 23.0 if i == 2 else -31.0))
        else:
            world = transform(pos, (1.0, 1.0, 1.0), (0.0, 0.0, 90.0 if lane > 0 else -90.0))
        entities.append(Entity(bounds, world))
    # A broad road box and a distant building ensure both receiver and caster
    # clipping see more than the camera-visible building set.
    entities.append(Entity([[-3.0, -8.0, -0.16], [3.0, 32.0, -0.04]],
                           transform(center + [0.0, 10.0, 0.0])))
    entities.append(Entity([[-2.0, -2.0, 0.0], [2.0, 2.0, 8.0]],
                           transform(center + [13.0, 42.0, 0.0], (1.4, 0.8, 1.2), (0, 0, 17))))
    return entities


def add_following_ground(entities, camera):
    size = 2.0 * camera.far
    world = transform([camera.eye[0], camera.eye[1], -0.14], (size, size, 1.0))
    entities.append(Entity([[-1.0, -1.0, 0.0], [1.0, 1.0, 0.0]], world, ground=True))


def cases():
    ordinary_camera = Camera([0.0, -19.0, 9.0], [0.0, 14.0, 1.5], far=320.0)
    ordinary = street_entities(rotated=True)
    yield "ordinary-and-rotated", ordinary, [0.4, -0.5, 0.8], ordinary_camera, 2048

    ground_camera = Camera([1.0, -23.0, 11.0], [0.0, 18.0, 1.4], far=350.0)
    ground = street_entities(rotated=True)
    add_following_ground(ground, ground_camera)
    yield "photographic-ground", ground, [0.4, -0.5, 0.8], ground_camera, 2048

    low_sun_camera = Camera([-4.0, -27.0, 8.0], [0.0, 17.0, 1.0], far=420.0)
    low_sun = street_entities(rotated=True)
    add_following_ground(low_sun, low_sun_camera)
    yield "low-sun-long-shadows", low_sun, [0.985, -0.06, 0.14], low_sun_camera, 2048

    center = np.array([15000.0, -12500.0, 6000.0])
    extreme_camera = Camera(center + [0.0, -180.0, 68.0], center + [0.0, 100.0, 1.0],
                            far=4000.0, fov_y=54.0)
    extreme = street_entities(center, rotated=True)
    add_following_ground(extreme, extreme_camera)
    yield "large-world-camera", extreme, [0.73, 0.19, 0.65], extreme_camera, 2048


def matrix_pointer(array):
    array = np.ascontiguousarray(array, dtype=np.float64)
    return array, array.ctypes.data_as(ctypes.POINTER(ctypes.c_double))


def invoke(lib, entities, direction, camera, resolution=2048, flags_override=None):
    boxes = np.asarray([e.model.bounds.reshape(-1) for e in entities], dtype=np.float64)
    worlds = np.asarray([e.world_matrix.reshape(-1) for e in entities], dtype=np.float64)
    flags = np.asarray([
        (1 if e.model.material and e.model.material.get("extras", {}).get("photographicGround") else 0)
        | (2 if np.linalg.det(e.world_matrix[:3, :3]) < 0.0 else 0)
        for e in entities
    ], dtype=np.uint32)
    if flags_override is not None:
        flags = flags_override
    dir_array, dir_ptr = matrix_pointer(direction)
    view_array, view_ptr = matrix_pointer(camera.view_matrix)
    projection_array, projection_ptr = matrix_pointer(camera.projection_matrix(camera.aspect))
    bounds_array = np.ascontiguousarray(boxes.reshape(-1))
    worlds_array = np.ascontiguousarray(worlds.reshape(-1))
    flags_array = np.ascontiguousarray(flags, dtype=np.uint32)
    out = np.full(16, 7.0, dtype=np.float64)
    result = lib.spqr_fit_shadow(
        bounds_array.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        worlds_array.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags_array.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)),
        len(entities), dir_ptr, view_ptr, projection_ptr, resolution,
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )
    # Keep ctypes-backed arrays alive through the call.
    _ = (dir_array, view_array, projection_array, bounds_array, worlds_array, flags_array)
    return bool(result), out.reshape(4, 4)


def load_library(path):
    lib = ctypes.CDLL(str(path))
    double_ptr = ctypes.POINTER(ctypes.c_double)
    uint_ptr = ctypes.POINTER(ctypes.c_uint32)
    lib.spqr_fit_shadow.argtypes = [double_ptr, double_ptr, uint_ptr, ctypes.c_uint32,
                                    double_ptr, double_ptr, double_ptr, ctypes.c_uint32, double_ptr]
    lib.spqr_fit_shadow.restype = ctypes.c_int
    return lib


def reference_fit(reference, entities, direction, camera, resolution):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            return reference(entities, np.asarray(direction, dtype=np.float64), camera, resolution)
        except (ValueError, np.linalg.LinAlgError, FloatingPointError, OverflowError):
            return None


def verify_valid_cases(lib, reference):
    results = []
    for name, entities, direction, camera, resolution in cases():
        expected = reference_fit(reference, entities, direction, camera, resolution)
        actual_ok, actual = invoke(lib, entities, direction, camera, resolution)
        if (expected is not None) != actual_ok:
            raise AssertionError(f"{name}: Python fit={expected is not None}, native fit={actual_ok}")
        if expected is None:
            raise AssertionError(f"{name}: fixture did not produce a reference fit")
        np.testing.assert_allclose(actual, expected, rtol=3e-8, atol=3e-9,
                                   err_msg=f"native shadow matrix differs for {name}")
        results.append((name, float(np.max(np.abs(actual - expected)))))
    return results


def verify_invalid_inputs(lib):
    _, entities, direction, camera, _ = next(iter(cases()))
    cases_to_check = [
        ("zero direction", entities, [0.0, 0.0, 0.0], camera, 2048),
        ("zero resolution", entities, direction, camera, 0),
        ("empty scene", [], direction, camera, 2048),
    ]
    singular = list(entities)
    singular[0] = Entity(entities[0].model.bounds, np.zeros((4, 4)))
    cases_to_check.append(("singular world", singular, direction, camera, 2048))
    reversed_bounds = list(entities)
    malformed = Entity([[2, 0, 0], [-2, 1, 1]], entities[0].world_matrix)
    reversed_bounds[0] = malformed
    cases_to_check.append(("reversed bounds", reversed_bounds, direction, camera, 2048))

    for name, entities_case, light, camera_case, resolution in cases_to_check:
        if not entities_case:
            # A non-null dummy buffer keeps the empty-count ABI path simple.
            entities_case = [Entity([[-1, -1, -1], [1, 1, 1]], np.eye(4))]
            empty = True
        else:
            empty = False
        if empty:
            out = np.full(16, 7.0, dtype=np.float64)
            double_ptr = ctypes.POINTER(ctypes.c_double)
            uint_ptr = ctypes.POINTER(ctypes.c_uint32)
            one = np.array([0.0, 0.0, 0.0], dtype=np.float64)
            view = np.ascontiguousarray(camera_case.view_matrix)
            projection = np.ascontiguousarray(camera_case.projection_matrix(camera_case.aspect))
            result = lib.spqr_fit_shadow(one.ctypes.data_as(double_ptr), one.ctypes.data_as(double_ptr),
                one.ctypes.data_as(uint_ptr), 0, one.ctypes.data_as(double_ptr),
                view.ctypes.data_as(double_ptr), projection.ctypes.data_as(double_ptr), resolution,
                out.ctypes.data_as(double_ptr))
            if result != 0 or np.any(out != 0.0):
                raise AssertionError("empty scene did not return conservative fallback")
            continue
        ok, output = invoke(lib, entities_case, light, camera_case, resolution)
        if ok or np.any(output != 0.0):
            raise AssertionError(f"{name}: invalid input did not return conservative fallback")

    # Reserved flag bits and null pointers are rejected at the ABI boundary.
    valid = list(entities)
    flags = np.full(len(valid), 4, dtype=np.uint32)
    ok, output = invoke(lib, valid, direction, camera, flags_override=flags)
    if ok or np.any(output != 0.0):
        raise AssertionError("reserved flags were not rejected")
    zero = np.zeros(16, dtype=np.float64)
    double_ptr = ctypes.POINTER(ctypes.c_double)
    uint_ptr = ctypes.POINTER(ctypes.c_uint32)
    result = lib.spqr_fit_shadow(None, None, None, 1, None, None, None, 2048,
                                 zero.ctypes.data_as(double_ptr))
    if result != 0 or np.any(zero != 0.0):
        raise AssertionError("null ABI input did not return conservative fallback")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path, help="compiled shadow_fit DLL/shared library")
    parser.add_argument("--project", required=True, type=Path, help="root of the existing Python mini3d package")
    args = parser.parse_args()
    project = args.project.resolve()
    if not (project / "mini3d" / "shadow_fit.py").is_file():
        parser.error(f"--project must contain mini3d/shadow_fit.py: {project}")
    sys.path.insert(0, str(project))
    from mini3d.shadow_fit import receiver_matrix

    lib = load_library(args.library.resolve())
    results = verify_valid_cases(lib, receiver_matrix)
    verify_invalid_inputs(lib)
    for name, error in results:
        print(f"PASS {name}: max_abs_error={error:.3g}")
    print("PASS invalid ABI/input fallbacks")


if __name__ == "__main__":
    main()
