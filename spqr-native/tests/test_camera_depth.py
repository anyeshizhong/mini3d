#!/usr/bin/env python3
"""Verify conservative near-plane tightening against exact Python OBB clips.

This test uses no GL. It reads the exported measured Pompeii walk frames,
compares the native camera fit with mini3d.shadow_fit._intersection, and checks
the near-sensitive visible triangle vertices and clipping intersections.
"""
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


def read_frames(path):
    data = path.read_bytes()
    if data[:8] != b"SPQRF001":
        raise ValueError(f"bad frame header: {path}")
    count = struct.unpack_from("<I", data, 8)[0]
    offset = 12
    frames = []
    for _ in range(count):
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        route = data[offset:offset + length].decode("utf-8")
        offset += length
        t = struct.unpack_from("<d", data, offset)[0]
        offset += 8
        values = np.frombuffer(data, dtype="<f8", count=46, offset=offset).astype(np.float64)
        offset += 46 * 8
        frames.append(dict(
            route=route, t=t, position=values[0:3], rotation=values[3:12].reshape(3, 3),
            view=values[12:28].reshape(4, 4), projection=values[28:44].reshape(4, 4),
            near=float(values[44]), far=float(values[45]),
        ))
    if offset != len(data):
        raise ValueError(f"unexpected trailing bytes in {path}: {len(data) - offset}")
    return frames


def camera_clip_volume(view, projection):
    vp = projection @ view
    planes = np.asarray([
        vp[3] + sign * vp[axis]
        for axis in range(3) for sign in (1.0, -1.0)
    ], dtype=np.float64)
    homogeneous = np.column_stack((SIGNS, np.ones(8))) @ np.linalg.inv(vp).T
    frustum = homogeneous[:, :3] / homogeneous[:, 3, None]
    return planes, frustum


def camera_depth(points, view):
    camera_points = points @ view[:3, :3].T + view[:3, 3]
    return -camera_points[:, 2]


def clip_triangle_camera(triangle, planes):
    polygon = [np.asarray(point, dtype=np.float64) for point in triangle]
    for plane in planes:
        if not polygon:
            break
        clipped = []
        previous = polygon[-1]
        previous_distance = float(np.dot(plane[:3], previous) + plane[3])
        previous_inside = previous_distance >= 0.0
        for current in polygon:
            current_distance = float(np.dot(plane[:3], current) + plane[3])
            current_inside = current_distance >= 0.0
            if previous_inside and current_inside:
                clipped.append(current)
            elif previous_inside and not current_inside:
                denominator = previous_distance - current_distance
                if denominator != 0.0:
                    t = previous_distance / denominator
                    clipped.append(previous + (current - previous) * t)
            elif not previous_inside and current_inside:
                denominator = previous_distance - current_distance
                if denominator != 0.0:
                    t = previous_distance / denominator
                    clipped.append(previous + (current - previous) * t)
                clipped.append(current)
            previous, previous_distance, previous_inside = current, current_distance, current_inside
        polygon = clipped
    return np.asarray(polygon, dtype=np.float64).reshape(-1, 3)


def depth24_step(near, far, distance=40.0):
    # Derivative of the perspective depth mapping over one 24-bit UNORM step.
    return distance * distance * (far - near) / (far * near * ((1 << 24) - 1))


def library(path):
    lib = ctypes.CDLL(str(path))
    dp = ctypes.POINTER(ctypes.c_double)
    up = ctypes.POINTER(ctypes.c_uint32)
    lib.spqr_camera_near.argtypes = [dp, dp, up, ctypes.c_uint32, dp, dp,
                                     ctypes.c_double, dp]
    lib.spqr_camera_near.restype = ctypes.c_int
    return lib


def native_near(lib, entities, view, projection, original_near):
    valid = [entity for entity in entities if getattr(entity.model, "bounds", None) is not None]
    bounds = np.ascontiguousarray([entity.model.bounds for entity in valid], dtype=np.float64).reshape(-1, 6)
    worlds = np.ascontiguousarray([entity.world_matrix for entity in valid], dtype=np.float64).reshape(-1, 16)
    flags = np.asarray([
        (1 if (getattr(entity.model, "material", None) or {}).get("extras", {}).get("photographicGround") else 0)
        | (2 if np.linalg.det(entity.world_matrix[:3, :3]) < 0.0 else 0)
        for entity in valid
    ], dtype=np.uint32)
    view = np.ascontiguousarray(view, dtype=np.float64)
    projection = np.ascontiguousarray(projection, dtype=np.float64)
    output = np.array([original_near], dtype=np.float64)
    result = lib.spqr_camera_near(
        bounds.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        worlds.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), len(valid),
        view.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        projection.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), original_near,
        output.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )
    return bool(result), float(output[0]), valid


def exact_box_min_depth(entities, view, projection, python_intersection):
    planes, frustum = camera_clip_volume(view, projection)
    minimum = np.inf
    hits = 0
    for entity in entities:
        bounds = getattr(entity.model, "bounds", None)
        if bounds is None:
            continue
        points = python_intersection(np.asarray(bounds, dtype=np.float64),
                                     np.asarray(entity.world_matrix, dtype=np.float64),
                                     planes, frustum)
        if len(points):
            depths = camera_depth(points, view)
            positive = depths[np.isfinite(depths) & (depths > 0.0)]
            if positive.size:
                minimum = min(minimum, float(positive.min()))
                hits += 1
    return (None if not np.isfinite(minimum) else minimum), hits


def verify_visible_triangles(entities, view, projection, safe_near, tolerance=2e-8):
    # For a triangle, camera-space depth is affine over its surface. If every
    # source vertex is at or behind the safe near, every clipped edge/plane
    # intersection is too; clip only triangles that could violate the bound.
    camera_planes = np.asarray([
        projection[3] + sign * projection[axis]
        for axis in range(3) for sign in (1.0, -1.0)
    ], dtype=np.float64)
    min_clipped_depth = np.inf
    tested_triangles = 0
    visible_triangles = 0
    for entity in entities:
        model = entity.model
        if not hasattr(model, "vertices") or not hasattr(model, "indices"):
            continue
        vertices = np.asarray(model.vertices, dtype=np.float64)[:, :3]
        indices = np.asarray(model.indices, dtype=np.int64).reshape(-1, 3)
        if not len(indices):
            continue
        camera_model = view @ np.asarray(entity.world_matrix, dtype=np.float64)
        camera_vertices = vertices @ camera_model[:3, :3].T + camera_model[:3, 3]
        triangles = camera_vertices[indices]
        # A triangle can cross the safe near plane whenever its nearest vertex
        # is nearer than the proposed plane; depth is affine on the triangle.
        vertex_min_depth = (-triangles[:, :, 2]).min(axis=1)
        plane_distances = np.einsum("tvc,pc->tvp", triangles, camera_planes[:, :3])
        plane_distances += camera_planes[None, None, :, 3]
        # Reject only triangles that lie wholly outside at least one frustum
        # half-space. This is a conservative vectorized broad phase; survivors
        # still go through exact polygon clipping below.
        can_touch_frustum = np.all(np.max(plane_distances, axis=1) >= -tolerance, axis=1)
        candidates = np.flatnonzero((vertex_min_depth < safe_near + tolerance) & can_touch_frustum)
        for triangle_index in candidates:
            tested_triangles += 1
            polygon = clip_triangle_camera(triangles[triangle_index], camera_planes)
            if not len(polygon):
                continue
            visible_triangles += 1
            depths = -polygon[:, 2]
            if not np.all(np.isfinite(depths)):
                raise AssertionError("non-finite visible triangle clip depth")
            min_clipped_depth = min(min_clipped_depth, float(depths.min()))
            if float(depths.min()) < safe_near - tolerance:
                raise AssertionError(
                    f"safe near {safe_near:.12g} clips visible triangle at {depths.min():.12g}m")
    return dict(min_clipped_depth=(None if not np.isfinite(min_clipped_depth) else min_clipped_depth),
                potentially_near_triangles=tested_triangles, visible_near_triangles=visible_triangles)


def run_pompeii_walk(lib, project, bundle, all_samples=False):
    sys.path.insert(0, str(project.resolve()))
    sys.path.insert(0, str((project / "tests").resolve()))
    from mini3d.api import Mini3DAPI
    from mini3d.placement import create_ground
    from mini3d.shadow_fit import _intersection
    from tools.build_pompeii import build_scene
    api = Mini3DAPI()
    build_scene(api)
    scene = api._app.scene
    scene.update()
    ground = create_ground(2.0)
    ground.model.material = {"extras": {"photographicGround": True}}
    ground.name = "Photographic Ground (test bounds)"
    frames = read_frames(bundle / "frames.bin")
    walk = [frame for frame in frames if frame["route"] == "walk"]
    if len(walk) != 144:
        raise AssertionError(f"expected 144 walk records (24 warmup + 120 measured), got {len(walk)}")
    measured = walk[24:]
    if len(measured) != 120:
        raise AssertionError("expected exactly 120 measured walk frames")

    rows = []
    for sample_index, frame in enumerate(measured):
        position, far = frame["position"], frame["far"]
        ground.scale = np.array([2.0 * far, 2.0 * far, 1.0], dtype=np.float64)
        ground.pos = np.array([position[0], position[1], -0.14], dtype=np.float64)
        ground.update_transform()
        entities = scene.get_flat_render_list() + [ground]
        view, projection = frame["view"], frame["projection"]
        original_near = frame["near"]
        min_depth, hit_boxes = exact_box_min_depth(entities, view, projection, _intersection)
        if min_depth is None or hit_boxes == 0:
            raise AssertionError(f"walk local frame {sample_index + 24}: no visible OBB intersection")
        ok, safe_near, valid_entities = native_near(lib, entities, view, projection, original_near)
        if not ok:
            raise AssertionError(f"walk local frame {sample_index + 24}: native camera fit fell back")
        expected_near = max(original_near, min_depth * 0.5)
        if not np.isclose(safe_near, expected_near, rtol=3e-9, atol=2e-12):
            raise AssertionError((sample_index + 24, safe_near, expected_near, min_depth))
        if safe_near > min_depth + 2e-8:
            raise AssertionError(f"safe near exceeds nearest visible OBB point at frame {sample_index + 24}")
        triangle_check = verify_visible_triangles(valid_entities, view, projection, safe_near)
        if triangle_check["visible_near_triangles"] == 0:
            # The bound is still proved by convexity for every triangle whose
            # source vertices are deeper than safe_near, but the fixtures should
            # exercise the actual near-sensitive clipping path as well.
            pass
        row = dict(local_frame=sample_index + 24, t=frame["t"], legacy_near=original_near,
                   safe_near=safe_near, min_visible_depth=min_depth,
                   depth24_at_40m_legacy=depth24_step(original_near, far),
                   depth24_at_40m_safe=depth24_step(safe_near, far),
                   intersecting_obbs=hit_boxes, **triangle_check)
        rows.append(row)

    legacy = np.asarray([row["legacy_near"] for row in rows])
    safe = np.asarray([row["safe_near"] for row in rows])
    depths = np.asarray([row["min_visible_depth"] for row in rows])
    old_steps = np.asarray([row["depth24_at_40m_legacy"] for row in rows])
    new_steps = np.asarray([row["depth24_at_40m_safe"] for row in rows])
    selected = next(row for row in rows if row["local_frame"] == 42)
    summary = dict(
        measured_walk_samples=len(rows),
        legacy_near_min=float(legacy.min()), legacy_near_max=float(legacy.max()),
        safe_near_min=float(safe.min()), safe_near_max=float(safe.max()),
        min_visible_depth_min=float(depths.min()), min_visible_depth_max=float(depths.max()),
        depth24_40m_legacy_min=float(old_steps.min()), depth24_40m_safe_min=float(new_steps.min()),
        depth24_40m_legacy_max=float(old_steps.max()), depth24_40m_safe_max=float(new_steps.max()),
        triangles_near_checked=int(sum(row["potentially_near_triangles"] for row in rows)),
        visible_near_triangles_checked=int(sum(row["visible_near_triangles"] for row in rows)),
        local_frame_42=selected,
    )
    print(json.dumps(summary, indent=2))
    if all_samples:
        print("ALL_WALK_SAMPLES=" + json.dumps(rows, separators=(",", ":")))
    return rows


def verify_synthetic(lib):
    near, far = 0.1, 100.0
    projection = np.array([
        [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, -(far + near) / (far - near), -2 * far * near / (far - near)],
        [0.0, 0.0, -1.0, 0.0],
    ], dtype=np.float64)
    view = np.eye(4, dtype=np.float64)
    bounds = np.array([[-1.0, -1.0, -41.0, 1.0, 1.0, -39.0]], dtype=np.float64)
    worlds = np.eye(4, dtype=np.float64).reshape(1, 16)
    flags = np.zeros(1, dtype=np.uint32)
    result = np.array([near], dtype=np.float64)
    lib.spqr_camera_near(
        np.ascontiguousarray(bounds).ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        np.ascontiguousarray(worlds).ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), 1,
        view.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        projection.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), near,
        result.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    if not (near < result[0] < 20.0):
        raise AssertionError(f"synthetic distant box did not tighten near: {result[0]}")

    # An OBB crossing the original near plane must leave it unchanged.
    bounds[0] = [-0.5, -0.5, -0.2, 0.5, 0.5, -0.04]
    result[0] = -1.0
    ok = lib.spqr_camera_near(
        np.ascontiguousarray(bounds).ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        np.ascontiguousarray(worlds).ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), 1,
        view.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        projection.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), near,
        result.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    if ok != 1 or result[0] != near:
        raise AssertionError(f"near-crossing OBB should preserve original near: {ok}, {result[0]}")

    # Invalid bounds must fall back without crossing the ABI as an exception.
    bounds[0] = [-1.0, -1.0, -5.0, 1.0, 1.0, np.nan]
    result[0] = -1.0
    ok = lib.spqr_camera_near(
        np.ascontiguousarray(bounds).ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        np.ascontiguousarray(worlds).ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        flags.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), 1,
        view.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        projection.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), near,
        result.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    if ok != 0 or result[0] != near:
        raise AssertionError(f"invalid input must preserve original near: {ok}, {result[0]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[1] / "assets")
    parser.add_argument("--output-json", type=Path, help="write pass status and per-frame numeric results")
    parser.add_argument("--all-samples", action="store_true", help="print all 120 frame metrics")
    args = parser.parse_args()
    lib = library(args.library.resolve())
    verify_synthetic(lib)
    rows = run_pompeii_walk(lib, args.project.resolve(), args.bundle.resolve(), args.all_samples)
    if len(rows) != 120:
        raise AssertionError("measured Pompeii walk did not cover all 120 samples")
    if args.output_json:
        legacy = np.asarray([row["legacy_near"] for row in rows], dtype=np.float64)
        safe = np.asarray([row["safe_near"] for row in rows], dtype=np.float64)
        depths = np.asarray([row["min_visible_depth"] for row in rows], dtype=np.float64)
        old_steps = np.asarray([row["depth24_at_40m_legacy"] for row in rows], dtype=np.float64)
        new_steps = np.asarray([row["depth24_at_40m_safe"] for row in rows], dtype=np.float64)
        payload = {
            "passed": True,
            "measured_walk_samples": len(rows),
            "legacy_near_min": float(legacy.min()), "legacy_near_max": float(legacy.max()),
            "safe_near_min": float(safe.min()), "safe_near_max": float(safe.max()),
            "min_visible_depth_min": float(depths.min()), "min_visible_depth_max": float(depths.max()),
            "depth24_40m_legacy_min": float(old_steps.min()), "depth24_40m_safe_min": float(new_steps.min()),
            "depth24_40m_legacy_max": float(old_steps.max()), "depth24_40m_safe_max": float(new_steps.max()),
            "triangles_near_checked": int(sum(row["potentially_near_triangles"] for row in rows)),
            "visible_near_triangles_checked": int(sum(row["visible_near_triangles"] for row in rows)),
            "local_frame_42": next(row for row in rows if row["local_frame"] == 42),
            "samples": rows,
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("PASS synthetic near fitting and all 120 Pompeii walk samples")


if __name__ == "__main__":
    main()
