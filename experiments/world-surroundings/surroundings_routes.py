"""Deterministic CPU camera fixtures and routes for SUR-00.

This module defines observation paths for the finite surroundings experiment.
It does not add interactive free-flight controls or change the editor camera.
World coordinates are metres, right-handed, and Z-up; north is +Y.
"""

from __future__ import annotations

import math
import operator
from pathlib import Path

import numpy as np

from mini3d.camera import Camera
from native.export_scene import BinaryWriter


CAMERA_BOUNDS = {
    "xy": (-200.0, 200.0),
    "agl": (1.6, 120.0),
}

# The existing native viewer and surroundings fixtures render at this aspect.
FRAME_WIDTH = 1081
FRAME_HEIGHT = 662
FRAME_ASPECT = FRAME_WIDTH / FRAME_HEIGHT

_DEFAULT_FOV_Y = 52.0
_FULL_FRAME_WIDTH_MM = 36.0
_FULL_FRAME_HEIGHT_MM = 24.0
_TELEPHOTO_FOCAL_MM = 85.0
_ROUTE_NAMES = frozenset((
    "outbound", "lateral", "ascent", "orbit", "boundary", "boundary_low",
))


def _clip_planes(near, far):
    try:
        near = float(near)
        far = float(far)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("near and far must be finite numbers satisfying 0 < near < far") from exc
    if not (math.isfinite(near) and math.isfinite(far) and 0.0 < near < far):
        raise ValueError("near and far must be finite numbers satisfying 0 < near < far")
    return near, far


def _render_aspect(aspect):
    try:
        aspect = float(aspect)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("aspect must be positive and finite") from exc
    if not math.isfinite(aspect) or aspect <= 0.0:
        raise ValueError("aspect must be positive and finite")
    return aspect


def _sample_count(samples, *, minimum=2):
    if isinstance(samples, (bool, np.bool_)):
        raise ValueError("samples must be an integer >= {}".format(minimum))
    try:
        count = operator.index(samples)
    except TypeError as exc:
        raise ValueError("samples must be an integer >= {}".format(minimum)) from exc
    if count < minimum:
        raise ValueError("samples must be an integer >= {}".format(minimum))
    return count


def _ground_z(height_fn, x, y):
    try:
        height = float(height_fn(float(x), float(y)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("height_fn must return one finite ground height") from exc
    if not math.isfinite(height):
        raise ValueError("height_fn must return one finite ground height")
    return height


def _smoothstep(value):
    value = min(1.0, max(0.0, float(value)))
    return value * value * (3.0 - 2.0 * value)


def _camera(position, target, *, fov_y, near, far, name=None, lens=None):
    camera = Camera(position=position, fov_y=fov_y, near=near, far=far)
    camera.look_at(target, up=(0.0, 0.0, 1.0))
    if name is not None:
        camera.name = str(name)
    if lens is not None:
        camera.lens = dict(lens)
    return camera


def _at_agl(height_fn, x, y, agl):
    return (float(x), float(y), _ground_z(height_fn, x, y) + float(agl))


def _aim_at_ground(height_fn, x, y, above_ground=0.0):
    return (float(x), float(y), _ground_z(height_fn, x, y) + float(above_ground))


def fixed_views(height_fn, *, near=0.1, far=8000.0) -> dict[str, Camera]:
    """Return named, deterministic centre, edge, corner, and lens fixtures.

    The exit camera faces south along the outbound view direction. A companion
    ``exit_return`` view at the same station faces back toward the city.
    Cardinal and corner samples keep the finite boundary review small and
    symmetric. All elevations are measured from ``height_fn``.
    """
    near, far = _clip_planes(near, far)

    specs = []

    def add(name, position_xy, agl, target_xy, target_agl=0.0, fov_y=_DEFAULT_FOV_Y,
            lens=None):
        position = _at_agl(height_fn, position_xy[0], position_xy[1], agl)
        target = _aim_at_ground(height_fn, target_xy[0], target_xy[1], target_agl)
        specs.append((name, _camera(position, target, fov_y=fov_y, near=near,
                                    far=far, name=name, lens=lens)))

    # Street-level view toward the northern ridge and a south-facing outbound
    # view plus a separate return glance toward the town.
    add("street", (0.0, -15.0), 1.7, (0.0, 135.0), 42.0)
    add("exit", (20.0, -60.0), 12.0, (20.0, -180.0), 0.0)
    add("exit_return", (20.0, -60.0), 12.0, (0.0, -5.0), 12.0)
    add("aerial", (140.0, -180.0), 120.0, (0.0, 135.0), 48.0)
    add("nadir", (190.0, 0.0), 120.0, (190.0, 0.0), 0.0)

    telephoto_fov_y = math.degrees(
        2.0 * math.atan(_FULL_FRAME_HEIGHT_MM / (2.0 * _TELEPHOTO_FOCAL_MM))
    )
    telephoto_lens = {
        "format": "full_frame",
        "fit_axis": "vertical",
        "sensor_width_mm": _FULL_FRAME_WIDTH_MM,
        "sensor_height_mm": _FULL_FRAME_HEIGHT_MM,
        "focal_length_mm": _TELEPHOTO_FOCAL_MM,
    }
    # The distant ridge is a fixed world-space aim point beyond the camera
    # envelope; it does not require height_fn to answer outside its terrain.
    telephoto_position = _at_agl(height_fn, 165.0, 120.0, 40.0)
    telephoto_camera = _camera(
        telephoto_position,
        (0.0, 900.0, 220.0),
        fov_y=telephoto_fov_y,
        near=near,
        far=far,
        name="telephoto",
        lens=telephoto_lens,
    )
    specs.append(("telephoto", telephoto_camera))

    # High boundary looks expose all four cardinal edges and corners. The
    # boundary route also visits every corner continuously.
    edge_specs = (
        ("edge_west", (-200.0, 0.0)),
        ("edge_east", (200.0, 0.0)),
        ("edge_south", (0.0, -200.0)),
        ("edge_north", (0.0, 200.0)),
    )
    for name, xy in edge_specs:
        add(name, xy, 120.0, (0.0, 0.0), 12.0)

    corner_specs = (
        ("corner_sw", (-200.0, -200.0)),
        ("corner_se", (200.0, -200.0)),
        ("corner_ne", (200.0, 200.0)),
        ("corner_nw", (-200.0, 200.0)),
    )
    for name, xy in corner_specs:
        add(name, xy, 120.0, (0.0, 0.0), 12.0)

    return dict(specs)


def _route_camera(height_fn, x, y, agl, target, near, far, *, name):
    position = _at_agl(height_fn, x, y, agl)
    return _camera(position, target, fov_y=_DEFAULT_FOV_Y, near=near,
                   far=far, name=name)


def _boundary_points(samples, extent):
    """Yield a square perimeter with exact corners and eased edge motion."""
    intervals = samples - 1
    base, remainder = divmod(intervals, 4)
    corners = (
        (-extent, -extent),
        (extent, -extent),
        (extent, extent),
        (-extent, extent),
        (-extent, -extent),
    )
    points = []
    for edge in range(4):
        edge_intervals = base + (1 if edge < remainder else 0)
        start = np.asarray(corners[edge], dtype=np.float64)
        end = np.asarray(corners[edge + 1], dtype=np.float64)
        first_step = 0 if edge == 0 else 1
        for step in range(first_step, edge_intervals + 1):
            t = _smoothstep(step / edge_intervals)
            point = start + (end - start) * t
            points.append((float(point[0]), float(point[1])))
    return points


def route_frames(name, height_fn, *, samples=120, near=0.1, far=8000.0) -> list[Camera]:
    """Build one repeatable camera path wholly inside the SUR-00 envelope.

    Supported routes are ``outbound``, ``lateral``, ``ascent``, ``orbit``,
    ``boundary`` (120 m AGL), and ``boundary_low`` (12 m AGL). Paths use
    smoothstep timing so their endpoint poses are stable and frame spacing is
    finite. These are prerecorded routes, not time- or input-driven controls.
    """
    if not isinstance(name, str) or name not in _ROUTE_NAMES:
        raise ValueError(
            "name must be one of: outbound, lateral, ascent, orbit, "
            "boundary, boundary_low"
        )
    near, far = _clip_planes(near, far)
    minimum = 5 if name in ("boundary", "boundary_low") else 2
    count = _sample_count(samples, minimum=minimum)

    cameras = []
    boundary_points = (
        _boundary_points(count, 200.0)
        if name in ("boundary", "boundary_low") else None
    )
    for index in range(count):
        u = index / (count - 1)
        eased = _smoothstep(u)
        if name == "outbound":
            y = 15.0 - 205.0 * eased
            agl = 1.7 + 10.3 * eased
            target_y = max(CAMERA_BOUNDS["xy"][0], y - 70.0)
            target = _aim_at_ground(height_fn, 0.0, target_y, 2.0)
            camera = _route_camera(height_fn, 0.0, y, agl, target, near, far,
                                   name=name)
        elif name == "lateral":
            x = -190.0 + 380.0 * eased
            target = _aim_at_ground(height_fn, 0.0, 125.0, 40.0)
            camera = _route_camera(height_fn, x, -12.0, 12.0, target, near, far,
                                   name=name)
        elif name == "ascent":
            agl = 1.7 + (120.0 - 1.7) * eased
            target = _aim_at_ground(height_fn, 0.0, 120.0, 42.0)
            camera = _route_camera(height_fn, 140.0, -180.0, agl, target, near,
                                   far, name=name)
        elif name == "orbit":
            angle = 2.0 * math.pi * eased
            x = 78.0 * math.cos(angle)
            y = 78.0 * math.sin(angle)
            target = _aim_at_ground(height_fn, 0.0, 0.0, 12.0)
            camera = _route_camera(height_fn, x, y, 55.0, target, near, far,
                                   name=name)
        elif name in ("boundary", "boundary_low"):
            agl = 120.0 if name == "boundary" else 12.0
            target = _aim_at_ground(height_fn, 0.0, 0.0, 8.0)
            x, y = boundary_points[index]
            camera = _route_camera(height_fn, x, y, agl, target, near, far,
                                   name=name)
        cameras.append(camera)
    return cameras


def in_envelope(camera, height_fn) -> bool:
    """Return whether a camera is within XY bounds and 1.6–120 m AGL."""
    try:
        position = np.asarray(camera.position, dtype=np.float64)
        if position.shape != (3,) or not np.all(np.isfinite(position)):
            return False
        ground = _ground_z(height_fn, position[0], position[1])
        lower_xy, upper_xy = CAMERA_BOUNDS["xy"]
        lower_agl, upper_agl = CAMERA_BOUNDS["agl"]
        agl = float(position[2] - ground)
        tolerance = 1e-9
        return bool(
            lower_xy - tolerance <= position[0] <= upper_xy + tolerance
            and lower_xy - tolerance <= position[1] <= upper_xy + tolerance
            and lower_agl - tolerance <= agl <= upper_agl + tolerance
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


def camera_record(camera, *, aspect=FRAME_ASPECT) -> dict:
    """Return JSON-safe camera pose and lens data for deterministic manifests."""
    aspect = _render_aspect(aspect)
    projection = np.asarray(camera.projection_matrix(aspect), dtype=np.float64)
    position = np.asarray(camera.position, dtype=np.float64)
    rotation = np.asarray(camera.rotation, dtype=np.float64)
    view = np.asarray(camera.view_matrix, dtype=np.float64)
    values = (position, rotation, view, projection)
    if any(not np.all(np.isfinite(value)) for value in values):
        raise ValueError("camera pose and projection must be finite")
    record = {
        "position": position.tolist(),
        "rotation": rotation.tolist(),
        "view": view.tolist(),
        "projection": projection.tolist(),
        "aspect": aspect,
        "near": float(camera.near),
        "far": float(camera.far),
        "fov_y_degrees": float(camera.fov_y),
        "forward": np.asarray(camera.forward, dtype=np.float64).tolist(),
        "up_axis": "Z",
    }
    name = getattr(camera, "name", None)
    if name is not None:
        record["name"] = str(name)
    lens = getattr(camera, "lens", None)
    if lens is not None:
        record["lens"] = dict(lens)
        if lens.get("fit_axis") == "vertical":
            record["lens"]["projected_width_mm"] = lens["sensor_height_mm"] * aspect
    return record


def write_route_frames(path, cameras, *, aspect=FRAME_ASPECT):
    """Write static camera records in the native SPQRF001 frames.bin format.

    Every record carries its own pose and matrices. ``walk`` is the native
    parser's accepted label for the static records; no native route interpolation
    or viewer is needed to generate this file.
    """
    cameras = tuple(cameras)
    if not cameras:
        raise ValueError("at least one camera frame is required")
    aspect = _render_aspect(aspect)

    writer = BinaryWriter()
    writer.raw(b"SPQRF001")
    writer.u32(len(cameras))
    last_index = len(cameras) - 1
    for index, camera in enumerate(cameras):
        record = camera_record(camera, aspect=aspect)
        writer.string("walk")
        writer.f64(index / last_index if last_index else 0.0)
        writer.f64_array(record["position"])
        writer.f64_array(record["rotation"])
        writer.f64_array(record["view"])
        writer.f64_array(record["projection"])
        writer.f64(record["near"])
        writer.f64(record["far"])

    target = Path(path)
    if target.suffix.lower() != ".bin":
        target.mkdir(parents=True, exist_ok=True)
        target = target / "frames.bin"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(writer.data)
    return target
