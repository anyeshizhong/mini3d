"""Deterministic Roman countryside fixture for the World Surroundings study.

This module only builds ordinary Mini3D ``Scene``/``Mesh``/``Entity`` data.
It reuses the experimental heightfield's canonical grid topology and normal
builder, the shared Roman asset kit, and Mini3D's existing photographic
atmosphere settings. It owns no renderer, GL context, or external assets.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from numbers import Integral, Real
from typing import Mapping

import numpy as np

from mini3d.assets import Asset, AssetCache
from mini3d.commands import PlacementCommands
from mini3d.roman_assets import ROMAN_ASSETS, create_roman_asset
from mini3d.scene import Entity, Mesh, Scene
from heightfield import _area_weighted_normals, _grid_indices


DEFAULT_CONFIG = {
    "seed": 24037,
    "grid": {
        "extent": 9000.0,
        "inner_extent": 256.0,
        "inner_step": 8.0,
        "mid_extent": 1500.0,
        "mid_step": 24.0,
        "far_extent": 4000.0,
        "far_step": 64.0,
        "outer_step": 128.0,
    },
    "city": {
        "anchor_xy": [0.0, 0.0],
        "footprint_xy": [128.0, 128.0],
        "plateau_z": 100.0,
        "plateau_radius": 100.0,
        "blend_width": 360.0,
    },
    "terrain": {
        "base_z": 72.0,
        "east_slope": 0.00045,
        "north_slope": 0.00035,
        "relief_amplitude": 3.5,
        "surface_clearance": 0.02,
    },
    "ridge": {
        # Relative to the city anchor: x, y, and absolute summit elevation.
        "controls": [
            [-1800.0, 1120.0, 300.0],
            [-900.0, 850.0, 365.0],
            [0.0, 1190.0, 340.0],
            [900.0, 820.0, 390.0],
            [1800.0, 1160.0, 315.0],
        ],
        "half_width": 520.0,
        "cross_sigma": 350.0,
        "edge_fade": 180.0,
    },
    "valley": {
        "half_width": 440.0,
        "depth": 18.0,
        "activation_length": 950.0,
        # The valley opens south from the Roman gate and bends gently east.
        "centerline": [
            [0.0, -24.0],
            [0.0, -220.0],
            [24.0, -520.0],
            [82.0, -980.0],
            [142.0, -1680.0],
            [176.0, -2800.0],
            [92.0, -4700.0],
            [0.0, -7000.0],
            [0.0, -9000.0],
        ],
    },
    "exit": {
        "length": 1800.0,
        "road_width": 6.0,
        "surface_lift": 0.025,
        "sample_spacing": 8.0,
    },
}


_CONFIG_KEYS = {
    "seed": None,
    "grid": {"extent", "inner_extent", "inner_step", "mid_extent", "mid_step",
             "far_extent", "far_step", "outer_step"},
    "city": {"anchor_xy", "footprint_xy", "plateau_z", "plateau_radius", "blend_width"},
    "terrain": {"base_z", "east_slope", "north_slope", "relief_amplitude", "surface_clearance"},
    "ridge": {"controls", "half_width", "cross_sigma", "edge_fade"},
    "valley": {"half_width", "depth", "activation_length", "centerline"},
    "exit": {"length", "road_width", "surface_lift", "sample_spacing"},
}

_TERRAIN_MATERIAL = {
    "pbrMetallicRoughness": {
        "baseColorFactor": [0.34, 0.39, 0.27, 1.0],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.94,
    },
    "alphaMode": "OPAQUE",
}
_EXIT_ROAD_MATERIAL = {
    "pbrMetallicRoughness": {
        "baseColorFactor": [0.43, 0.37, 0.27, 1.0],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.92,
    },
    "alphaMode": "OPAQUE",
}
_MOUNTAIN_MATERIAL = {
    "pbrMetallicRoughness": {
        "baseColorFactor": [0.37, 0.39, 0.31, 1.0],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.96,
    },
    "alphaMode": "OPAQUE",
}

_COMMON_TERRAIN_NAME = "SUR Common Terrain"
_EXIT_ROAD_NAME = "SUR Static Exit Road"
_FAR_MOUNTAIN_NAME = "SUR Far Mountains"
_CITY_SEGMENTS = 12
_CITY_ROAD_WIDTH = 6.0
_MAX_AXIS_SAMPLES = 1600
_MAX_TERRAIN_VERTICES = 750_000
_MAX_CONTROL_POINTS = 32
_MOUNTAIN_COPLANAR_EPSILON = 0.01


def _number(value, label, *, minimum=None, maximum=None):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
            or not math.isfinite(value)):
        raise ValueError(label + " must be a finite number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError(label + " must be at least " + str(minimum))
    if maximum is not None and result > maximum:
        raise ValueError(label + " must be at most " + str(maximum))
    return result


def _sequence_length(value, label, minimum, maximum, unit="points"):
    try:
        count = len(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("{} must contain between {} and {} {}".format(
            label, minimum, maximum, unit)) from exc
    if count < minimum or count > maximum:
        raise ValueError("{} must contain between {} and {} {}".format(
            label, minimum, maximum, unit))
    return count


def _bounded_sequence(value, label, minimum, maximum, unit="points"):
    """Check a sequence's size before copying or iterating it."""
    _sequence_length(value, label, minimum, maximum, unit)
    try:
        return list(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must contain between {} and {} {}".format(
            label, minimum, maximum, unit)) from exc


def _pair(value, label, *, positive=False):
    values = _bounded_sequence(value, label, 2, 2, "finite numbers")
    pair = [_number(item, label + "[{}]".format(index)) for index, item in enumerate(values)]
    if positive and any(item <= 0.0 for item in pair):
        raise ValueError(label + " values must be positive")
    return pair


def _merge_config(overrides):
    if overrides is None:
        return _validate_config(deepcopy(DEFAULT_CONFIG))
    if not isinstance(overrides, Mapping):
        raise ValueError("config must be a mapping")
    unknown = set(overrides) - set(_CONFIG_KEYS)
    if unknown:
        raise ValueError("Unknown config keys: " + ", ".join(sorted(map(str, unknown))))
    result = deepcopy(DEFAULT_CONFIG)
    for key, value in overrides.items():
        if key == "seed":
            result[key] = value
            continue
        if not isinstance(value, Mapping):
            raise ValueError("config[{}] must be a mapping".format(key))
        allowed = _CONFIG_KEYS[key]
        unknown_nested = set(value) - allowed
        if unknown_nested:
            raise ValueError("Unknown config[{}] keys: {}".format(
                key, ", ".join(sorted(map(str, unknown_nested)))))
        bulk_field = {"ridge": "controls", "valley": "centerline"}.get(key)
        if bulk_field is not None and bulk_field in value:
            minimum = 3 if key == "ridge" else 2
            _sequence_length(value[bulk_field], "{}.{}".format(key, bulk_field),
                             minimum, _MAX_CONTROL_POINTS)
            # These sequences are normalized into fresh numeric lists by
            # _validate_config. Avoid recursively copying caller data before
            # its control-point count has been checked.
            nested = deepcopy({nested_key: nested_value
                               for nested_key, nested_value in value.items()
                               if nested_key != bulk_field})
            nested[bulk_field] = value[bulk_field]
            result[key].update(nested)
        else:
            result[key].update(deepcopy(dict(value)))
    return _validate_config(result)


def _validate_config(config):
    seed = config["seed"]
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, Integral) or not 0 <= seed <= 2147483647:
        raise ValueError("seed must be an integer from 0 to 2147483647")
    config["seed"] = int(seed)

    grid = config["grid"]
    for name in ("extent", "inner_extent", "mid_extent", "far_extent",
                 "inner_step", "mid_step", "far_step", "outer_step"):
        grid[name] = _number(grid[name], "grid." + name, minimum=0.01, maximum=50000.0)
    if not (200.0 <= grid["inner_extent"] < grid["mid_extent"] < grid["far_extent"] < grid["extent"]):
        raise ValueError("grid extents must satisfy 200 <= inner < mid < far < extent")
    if grid["extent"] > 50000.0:
        raise ValueError("grid.extent exceeds the fixture geometry budget")
    for name, upper in (("inner_step", 8.0), ("mid_step", 128.0),
                        ("far_step", 256.0), ("outer_step", 512.0)):
        if grid[name] > upper:
            raise ValueError("grid.{} is too coarse for the fixture".format(name))

    city = config["city"]
    city["anchor_xy"] = _pair(city["anchor_xy"], "city.anchor_xy")
    city["footprint_xy"] = _pair(city["footprint_xy"], "city.footprint_xy", positive=True)
    if any(value < 32.0 or value > 512.0 for value in city["footprint_xy"]):
        raise ValueError("city.footprint_xy dimensions must be from 32 to 512 metres")
    city["plateau_z"] = _number(city["plateau_z"], "city.plateau_z", minimum=-1000.0, maximum=1000.0)
    city["plateau_radius"] = _number(city["plateau_radius"], "city.plateau_radius", minimum=1.0, maximum=2000.0)
    city["blend_width"] = _number(city["blend_width"], "city.blend_width", minimum=20.0, maximum=3000.0)
    half_diagonal = math.hypot(city["footprint_xy"][0] / 2.0, city["footprint_xy"][1] / 2.0)
    if city["plateau_radius"] < half_diagonal:
        raise ValueError("city.plateau_radius must cover the configured city footprint")

    terrain = config["terrain"]
    terrain["base_z"] = _number(terrain["base_z"], "terrain.base_z", minimum=-1000.0, maximum=1000.0)
    for name in ("east_slope", "north_slope"):
        terrain[name] = _number(terrain[name], "terrain." + name, minimum=-0.01, maximum=0.01)
    terrain["relief_amplitude"] = _number(terrain["relief_amplitude"], "terrain.relief_amplitude",
                                         minimum=0.0, maximum=20.0)
    terrain["surface_clearance"] = _number(terrain["surface_clearance"],
                                           "terrain.surface_clearance", minimum=0.005, maximum=0.1)

    ridge = config["ridge"]
    controls = _bounded_sequence(ridge["controls"], "ridge.controls", 3,
                                 _MAX_CONTROL_POINTS)
    clean_controls = []
    for index, point in enumerate(controls):
        values = _bounded_sequence(point, "ridge.controls[{}]".format(index),
                                   3, 3, "values")
        x = _number(values[0], "ridge.controls[{}].x".format(index),
                    minimum=-grid["extent"], maximum=grid["extent"])
        y = _number(values[1], "ridge.controls[{}].y".format(index),
                    minimum=-grid["extent"], maximum=grid["extent"])
        z = _number(values[2], "ridge.controls[{}].summit_z".format(index), minimum=180.0, maximum=500.0)
        if clean_controls and x <= clean_controls[-1][0]:
            raise ValueError("ridge.controls x coordinates must be strictly increasing")
        clean_controls.append([x, y, z])
    ridge["controls"] = clean_controls
    ridge["half_width"] = _number(ridge["half_width"], "ridge.half_width", minimum=100.0, maximum=2000.0)
    ridge["cross_sigma"] = _number(ridge["cross_sigma"], "ridge.cross_sigma", minimum=40.0, maximum=1500.0)
    ridge["edge_fade"] = _number(ridge["edge_fade"], "ridge.edge_fade", minimum=20.0, maximum=1000.0)
    ridge_x_low = clean_controls[0][0] - ridge["edge_fade"]
    ridge_x_high = clean_controls[-1][0] + ridge["edge_fade"]
    ridge_y_low = min(point[1] for point in clean_controls) - ridge["half_width"] - ridge["edge_fade"]
    ridge_y_high = max(point[1] for point in clean_controls) + ridge["half_width"] + ridge["edge_fade"]
    if max(abs(ridge_x_low), abs(ridge_x_high), abs(ridge_y_low), abs(ridge_y_high)) > grid["extent"]:
        raise ValueError("ridge footprint must remain within grid.extent")

    valley = config["valley"]
    valley["half_width"] = _number(valley["half_width"], "valley.half_width", minimum=80.0, maximum=2000.0)
    valley["depth"] = _number(valley["depth"], "valley.depth", minimum=0.0, maximum=100.0)
    valley["activation_length"] = _number(valley["activation_length"], "valley.activation_length",
                                          minimum=1.0, maximum=grid["extent"] * 2.0)
    path = _bounded_sequence(valley["centerline"], "valley.centerline", 2,
                             _MAX_CONTROL_POINTS)
    valley_path = [_pair(point, "valley.centerline[{}]".format(index))
                   for index, point in enumerate(path)]
    if any(max(abs(value) for value in point) > grid["extent"] for point in valley_path):
        raise ValueError("valley.centerline must remain within grid.extent")
    if any(np.allclose(a, b, rtol=0.0, atol=1e-6) for a, b in zip(valley_path, valley_path[1:])):
        raise ValueError("valley.centerline cannot contain duplicate consecutive points")
    valley["centerline"] = valley_path

    exit_cfg = config["exit"]
    exit_cfg["length"] = _number(exit_cfg["length"], "exit.length", minimum=1.0,
                                 maximum=grid["extent"] * 2.0)
    exit_cfg["road_width"] = _number(exit_cfg["road_width"], "exit.road_width", minimum=3.0, maximum=14.0)
    exit_cfg["surface_lift"] = _number(exit_cfg["surface_lift"], "exit.surface_lift", minimum=0.001, maximum=0.2)
    exit_cfg["sample_spacing"] = _number(exit_cfg["sample_spacing"], "exit.sample_spacing", minimum=2.0, maximum=32.0)

    anchor = city["anchor_xy"]
    if (abs(anchor[0]) + grid["extent"] > np.finfo(np.float32).max / 4.0
            or abs(anchor[1]) + grid["extent"] > np.finfo(np.float32).max / 4.0):
        raise ValueError("city.anchor_xy is outside the finite geometry range")
    return config


def _config_json(config):
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _smoothstep(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def _axis_sample_upper_bound(extent, bands, anchors):
    """Return a safe symmetric-axis size bound without constructing samples."""
    interval_count = 0
    start = 0.0
    for end, step in bands:
        interval_count += max(1, int(math.ceil((end - start) / step)))
        start = end
    anchor_count = sum(1 for value in anchors if 0.0 <= abs(value) <= extent)
    # Each band contributes count+1 values, plus the initial 0/extent pair;
    # uniqueness can only reduce this raw count. Mirroring doubles it minus 1.
    raw_positive_count = 2 + interval_count + len(bands) + anchor_count
    return 2 * raw_positive_count - 1


def _positive_axis(extent, bands, anchors=()):
    anchors = tuple(anchors)
    if _axis_sample_upper_bound(extent, bands, anchors) > _MAX_AXIS_SAMPLES:
        raise ValueError("grid configuration creates too many terrain samples")
    values = [0.0, float(extent)]
    start = 0.0
    for end, step in bands:
        count = max(1, int(math.ceil((end - start) / step)))
        values.extend(np.linspace(start, end, count + 1, dtype=np.float64).tolist())
        start = end
    values.extend(float(abs(value)) for value in anchors if 0.0 <= abs(value) <= extent)
    positive = np.unique(np.asarray(values, dtype=np.float64))
    positive = positive[(positive >= 0.0) & (positive <= extent)]
    axis = np.concatenate((-positive[:0:-1], positive))
    return axis.astype(np.float32)


def _build_axes(config):
    grid = config["grid"]
    bands = ((grid["inner_extent"], grid["inner_step"]),
             (grid["mid_extent"], grid["mid_step"]),
             (grid["far_extent"], grid["far_step"]),
             (grid["extent"], grid["outer_step"]))
    ridge = config["ridge"]
    controls = ridge["controls"]
    x_low = controls[0][0] - ridge["edge_fade"]
    x_high = controls[-1][0] + ridge["edge_fade"]
    y_values = [point[1] for point in controls]
    y_low = min(y_values) - ridge["half_width"] - ridge["edge_fade"]
    y_high = max(y_values) + ridge["half_width"] + ridge["edge_fade"]
    anchors_x = [x_low, x_high]
    anchors_y = [y_low, y_high]
    anchors_x.extend(point[0] for point in controls)
    anchors_y.extend(point[1] for point in controls)
    anchors_x.extend(point[0] for point in config["valley"]["centerline"])
    anchors_y.extend(point[1] for point in config["valley"]["centerline"])
    x_rel = _positive_axis(grid["extent"], bands, anchors_x)
    y_rel = _positive_axis(grid["extent"], bands, anchors_y)
    # An anchor outside [-extent,+extent] is rejected before the builder. The
    # extents are symmetric around the city, so both mountain feet stay on-grid.
    if len(x_rel) > _MAX_AXIS_SAMPLES or len(y_rel) > _MAX_AXIS_SAMPLES:
        raise ValueError("grid configuration creates too many terrain samples")
    anchor_x, anchor_y = config["city"]["anchor_xy"]
    x_world = (x_rel.astype(np.float64) + anchor_x).astype(np.float32)
    y_world = (y_rel.astype(np.float64) + anchor_y).astype(np.float32)
    if np.any(np.diff(x_world.astype(np.float64)) <= 0.0) or np.any(np.diff(y_world.astype(np.float64)) <= 0.0):
        raise ValueError("grid coordinates collapse in float32 at city.anchor_xy")
    return x_world, y_world


def _polyline_distance_and_station(x, y, points):
    best_distance_squared = np.full(np.broadcast(x, y).shape, np.inf, dtype=np.float64)
    best_station = np.zeros(best_distance_squared.shape, dtype=np.float64)
    station = 0.0
    for first, second in zip(points, points[1:]):
        ax, ay = first
        bx, by = second
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        t = np.clip(((x - ax) * dx + (y - ay) * dy) / (length * length), 0.0, 1.0)
        px, py = ax + t * dx, ay + t * dy
        distance_squared = (x - px) ** 2 + (y - py) ** 2
        closer = distance_squared < best_distance_squared
        best_distance_squared = np.where(closer, distance_squared, best_distance_squared)
        best_station = np.where(closer, station + t * length, best_station)
        station += length
    return np.sqrt(best_distance_squared), best_station


def _analytic_common_height(x_rel, y_rel, config):
    terrain = config["terrain"]
    city = config["city"]
    dx = x_rel
    dy = y_rel
    # Broad, low-amplitude regional relief keeps the shared surface legible
    # without producing an enclosing wall of random hills.
    phase = (config["seed"] % 997) / 997.0 * (2.0 * math.pi)
    regional = (terrain["base_z"] + terrain["east_slope"] * dx + terrain["north_slope"] * dy
                + terrain["relief_amplitude"] * np.sin(dx / 2700.0 + phase)
                * np.cos(dy / 3100.0 - phase * 0.5))
    radius = np.hypot(dx, dy)
    blend = 1.0 - _smoothstep((radius - city["plateau_radius"]) / city["blend_width"])
    # Keep the common receiver a few centimetres below Roman paving and the
    # static road so depth24 never has to choose between coplanar surfaces.
    plateau_ground_z = city["plateau_z"] - terrain["surface_clearance"]
    height = regional + blend * (plateau_ground_z - regional)

    valley = config["valley"]
    path = valley["centerline"]
    distance, station = _polyline_distance_and_station(dx, dy, path)
    cross_section = np.exp(-0.5 * (distance / valley["half_width"]) ** 2)
    longitudinal = _smoothstep(station / valley["activation_length"])
    height -= valley["depth"] * cross_section * longitudinal
    # An exit begins at the centre of the southern Roman gate; the city plateau
    # dominates here, so the route joins the urban paving without a step.
    return height


@lru_cache(maxsize=4)
def _ground_data_cached(config_key):
    config = _validate_config(json.loads(config_key))
    x_axis, y_axis = _build_axes(config)
    if len(x_axis) * len(y_axis) > _MAX_TERRAIN_VERTICES:
        raise ValueError("grid configuration exceeds the terrain vertex budget")
    x_rel = x_axis.astype(np.float64) - config["city"]["anchor_xy"][0]
    y_rel = y_axis.astype(np.float64) - config["city"]["anchor_xy"][1]
    xx, yy = np.meshgrid(x_rel, y_rel)
    heights = _analytic_common_height(xx, yy, config).astype(np.float32)
    if not np.isfinite(heights).all():
        raise ValueError("terrain configuration produced non-finite heights")
    x_axis.setflags(write=False)
    y_axis.setflags(write=False)
    heights.setflags(write=False)
    return config, x_axis, y_axis, heights


def _ground_data(config):
    return _ground_data_cached(_config_json(config))


def terrain_height(x, y, *, config=None):
    """Query the common terrain's exact emitted triangle surface.

    Scalars return a Python float. Arrays follow NumPy broadcasting. Inputs
    outside the finite fixture or with non-finite values are rejected.
    """
    resolved = _merge_config(config)
    try:
        x_values = np.asarray(x, dtype=np.float64)
        y_values = np.asarray(y, dtype=np.float64)
        x_values, y_values = np.broadcast_arrays(x_values, y_values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("x and y must be numeric and broadcast-compatible") from exc
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        raise ValueError("x and y must be finite")
    _, x_axis, y_axis, heights = _ground_data(resolved)
    if (np.any(x_values < x_axis[0]) or np.any(x_values > x_axis[-1])
            or np.any(y_values < y_axis[0]) or np.any(y_values > y_axis[-1])):
        raise ValueError("x and y must lie within the finite terrain bounds")

    col = np.clip(np.searchsorted(x_axis, x_values, side="right") - 1, 0, len(x_axis) - 2)
    row = np.clip(np.searchsorted(y_axis, y_values, side="right") - 1, 0, len(y_axis) - 2)
    x0, x1 = x_axis[col].astype(np.float64), x_axis[col + 1].astype(np.float64)
    y0, y1 = y_axis[row].astype(np.float64), y_axis[row + 1].astype(np.float64)
    u = np.clip((x_values - x0) / (x1 - x0), 0.0, 1.0)
    v = np.clip((y_values - y0) / (y1 - y0), 0.0, 1.0)
    a, b = heights[row, col].astype(np.float64), heights[row, col + 1].astype(np.float64)
    c, d = heights[row + 1, col + 1].astype(np.float64), heights[row + 1, col].astype(np.float64)
    lower = (1.0 - u) * a + (u - v) * b + v * c
    upper = (1.0 - v) * a + u * c + (v - u) * d
    result = np.where(v <= u, lower, upper)
    if result.ndim == 0:
        return float(result)
    return result


def _height_grid_mesh(x_axis, y_axis, heights, material):
    xx, yy = np.meshgrid(x_axis, y_axis)
    vertices = np.stack((xx, yy, heights), axis=-1).astype(np.float32).reshape(-1, 3)
    indices = _grid_indices(len(y_axis), len(x_axis))
    normals = _area_weighted_normals(vertices, indices)
    uvs = np.stack((xx / 64.0, yy / 64.0), axis=-1).astype(np.float32).reshape(-1, 2)
    return Mesh(vertices, indices, normals=normals, texcoords=uvs, material=material)


def _mountain_mesh(config, x_axis, y_axis, ground_heights):
    ridge = config["ridge"]
    controls = np.asarray(ridge["controls"], dtype=np.float64)
    fade = ridge["edge_fade"]
    x_min, x_max = controls[0, 0] - fade, controls[-1, 0] + fade
    y_min = float(controls[:, 1].min() - ridge["half_width"] - fade)
    y_max = float(controls[:, 1].max() + ridge["half_width"] + fade)
    anchor_x, anchor_y = config["city"]["anchor_xy"]
    # The exact patch bounds were inserted into the shared axes above. This
    # makes the C mesh foot ring bit-for-bit coincident with the common surface.
    col_mask = (x_axis >= anchor_x + x_min) & (x_axis <= anchor_x + x_max)
    row_mask = (y_axis >= anchor_y + y_min) & (y_axis <= anchor_y + y_max)
    cols, rows = np.flatnonzero(col_mask), np.flatnonzero(row_mask)
    if len(cols) < 2 or len(rows) < 2:
        raise ValueError("ridge controls do not create a supported mountain patch")
    x = x_axis[cols].astype(np.float64) - anchor_x
    y = y_axis[rows].astype(np.float64) - anchor_y
    xx, yy = np.meshgrid(x, y)

    center_y = np.interp(xx, controls[:, 0], controls[:, 1])
    summit_z = np.interp(xx, controls[:, 0], controls[:, 2])
    cross = np.abs(yy - center_y)
    transverse = np.exp(-0.5 * (cross / ridge["cross_sigma"]) ** 2)
    transverse *= _smoothstep((ridge["half_width"] + fade - cross) / fade)
    x_fade = _smoothstep((xx - (controls[0, 0] - fade)) / fade)
    x_fade *= _smoothstep(((controls[-1, 0] + fade) - xx) / fade)

    ground_patch = ground_heights[np.ix_(rows, cols)].astype(np.float64)
    # Normalize each ridge station to its configured absolute summit elevation.
    center_ground = _analytic_common_height(
        x,
        np.interp(x, controls[:, 0], controls[:, 1]),
        config,
    )
    amplitude = np.maximum(0.0, summit_z - center_ground[None, :])
    mountain_heights = ground_patch + amplitude * transverse * x_fade
    vertices_x, vertices_y = np.meshgrid(x_axis[cols], y_axis[rows])
    vertices = np.stack((vertices_x, vertices_y, mountain_heights), axis=-1).astype(np.float32).reshape(-1, 3)
    source_indices = _grid_indices(len(rows), len(cols))
    clearance = vertices[:, 2].astype(np.float64) - ground_patch.reshape(-1)
    keep_triangles = np.max(clearance[source_indices], axis=1) > _MOUNTAIN_COPLANAR_EPSILON
    source_indices = source_indices[keep_triangles]
    if len(source_indices) == 0:
        raise ValueError("ridge controls produce no elevated mountain triangles")
    used_vertices, remapped_indices = np.unique(source_indices.reshape(-1), return_inverse=True)
    indices = remapped_indices.astype(np.uint32).reshape(-1, 3)
    vertices = vertices[used_vertices]
    vertices_x = vertices_x.reshape(-1)[used_vertices]
    vertices_y = vertices_y.reshape(-1)[used_vertices]
    normals = _area_weighted_normals(vertices, indices)
    uvs = np.column_stack((vertices_x / 64.0, vertices_y / 64.0)).astype(np.float32)
    mesh = Mesh(vertices, indices, normals=normals, texcoords=uvs, material=_MOUNTAIN_MATERIAL)
    return mesh, {
        "vertices": int(len(vertices)),
        "triangles": int(len(indices)),
        "grid_rows": int(len(rows)),
        "grid_cols": int(len(cols)),
        "xy_bounds": [[float(vertices_x.min()), float(vertices_x.max())],
                      [float(vertices_y.min()), float(vertices_y.max())]],
    }


def _resample_polyline(points, length, spacing):
    points = np.asarray(points, dtype=np.float64)
    vectors = np.diff(points, axis=0)
    segment_lengths = np.linalg.norm(vectors, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    limit = min(float(length), float(cumulative[-1]))
    if limit <= 0.0:
        raise ValueError("exit road has no positive length")
    count = max(1, int(math.ceil(limit / spacing)))
    stations = np.linspace(0.0, limit, count + 1, dtype=np.float64)
    indices = np.clip(np.searchsorted(cumulative, stations, side="right") - 1,
                      0, len(segment_lengths) - 1)
    local = (stations - cumulative[indices]) / segment_lengths[indices]
    return points[indices] + vectors[indices] * local[:, None]


def _exit_road_mesh(config):
    city = config["city"]
    exit_cfg = config["exit"]
    path = np.asarray(config["valley"]["centerline"], dtype=np.float64)
    path[:, 0] += city["anchor_xy"][0]
    path[:, 1] += city["anchor_xy"][1]
    centers = _resample_polyline(path, exit_cfg["length"], exit_cfg["sample_spacing"])
    tangents = np.empty_like(centers)
    tangents[0] = centers[1] - centers[0]
    tangents[-1] = centers[-1] - centers[-2]
    if len(centers) > 2:
        tangents[1:-1] = centers[2:] - centers[:-2]
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), 1e-12)
    side = np.column_stack((-tangents[:, 1], tangents[:, 0]))
    half_width = exit_cfg["road_width"] * 0.5
    edges = np.stack((centers[:, :2] + side * half_width,
                      centers[:, :2] - side * half_width), axis=1)
    edge_z = terrain_height(edges[..., 0], edges[..., 1], config=config) + exit_cfg["surface_lift"]
    vertices = np.column_stack((edges.reshape(-1, 2), edge_z.reshape(-1))).astype(np.float32)
    rows = np.arange(len(centers) - 1, dtype=np.uint32)
    a = rows * 2
    b, c, d = a + 1, a + 3, a + 2
    indices = np.stack((np.stack((a, b, c), axis=1),
                        np.stack((a, c, d), axis=1)), axis=1).reshape(-1, 3)
    normals = _area_weighted_normals(vertices, indices)
    uvs = np.column_stack((np.repeat(np.linspace(0.0, 1.0, len(centers)), 2),
                           np.tile((0.0, 1.0), len(centers)))).astype(np.float32)
    mesh = Mesh(vertices, indices, normals=normals, texcoords=uvs,
                material=_EXIT_ROAD_MATERIAL)
    return mesh, {
        "vertices": int(len(vertices)),
        "triangles": int(len(indices)),
        "sample_count": int(len(centers)),
        "width": float(exit_cfg["road_width"]),
        "surface_lift": float(exit_cfg["surface_lift"]),
        "length": float(np.linalg.norm(np.diff(centers, axis=0), axis=1).sum()),
    }


@lru_cache(maxsize=1)
def _roman_asset_cache():
    """Create shared original Roman templates once, on the CPU."""
    cache = AssetCache()
    paths = [item["path"] for item in ROMAN_ASSETS]
    for path in paths:
        cache.adopt(Asset(path, create_roman_asset(path)))
    return cache


def _add_outer_quarter(scene, cache, city, seed):
    rng = np.random.RandomState(seed ^ 0x5A17)
    names = []
    for side in (-1.0, 1.0):
        for y in (-32.0, 0.0, 32.0):
            palette = ("", "-ochre", "-rose")[int(rng.randint(0, 3))]
            path = "builtin:roman-house" + palette
            entity = cache.load(path).instantiate()
            entity.name = "SUR Quarter House {} {:g} {:g}".format(
                "West" if side < 0.0 else "East", side * 24.0, y)
            entity.pos = np.asarray((city["anchor_xy"][0] + side * 24.0,
                                     city["anchor_xy"][1] + y,
                                     city["plateau_z"]), dtype=np.float64)
            # The built-in facade faces local -Y. Rotate the outer row toward
            # the central Roman street while keeping the assets upright.
            entity.rot = np.asarray((0.0, 0.0, math.pi / 2.0 if side < 0 else -math.pi / 2.0))
            entity.placement_anchor = "pivot"
            scene.add(entity)
            names.append(entity.name)
    return names


def _mesh_stats(roots):
    meshes = []
    def visit(entity):
        if entity.model is not None:
            meshes.append(entity.model)
        for child in entity.children:
            visit(child)
    for root in roots:
        visit(root)
    unique = {id(mesh): mesh for mesh in meshes}
    unique_materials = {id(mesh.material) for mesh in unique.values() if mesh.material is not None}
    return {
        "render_mesh_instances": len(meshes),
        "unique_mesh_resources": len(unique),
        "unique_material_resources": len(unique_materials),
        "vertices": int(sum(len(mesh.vertices) for mesh in unique.values())),
        "triangles": int(sum(len(mesh.indices) for mesh in unique.values())),
        "instance_vertices": int(sum(len(mesh.vertices) for mesh in meshes)),
        "instance_triangles": int(sum(len(mesh.indices) for mesh in meshes)),
    }


def _configure_scene(scene, haze, sun):
    from mini3d.atmosphere import update_atmosphere

    scene.show_grid = False
    scene.show_axes = False
    scene.render_mode = "Lit"
    scene.lighting_mode = "Scene"
    scene.environment_enabled = False
    scene.environment_intensity = 0.0
    scene.shadows_enabled = True
    scene.shadow_resolution = 1024
    scene.shadow_bias = 0.0005
    scene.shadow_pcf = True
    if sun == "day":
        azimuth, elevation = -48.0, 49.0
        temperature, exposure, ambient, diffuse, sun_size = 5500.0, 0.0, 0.28, 1.5, 0.53
    else:
        azimuth, elevation = -145.0, 9.0
        temperature, exposure, ambient, diffuse, sun_size = 3500.0, 0.25, 0.12, 3.0, 0.53
    scene.ambient, scene.diffuse = ambient, diffuse
    update_atmosphere(
        scene,
        enabled=True,
        ground=False,
        sun_temperature=temperature,
        exposure_ev=exposure,
        haze=haze,
        ground_scale=1.0,
        ground_z=0.0,
        azimuth=azimuth,
        elevation=elevation,
        sky_texture="procedural",
        sky_intensity=1.0,
        ground_texture="procedural",
        sun_size=sun_size,
        tone_mapping="reinhard",
        celestial_body="sun",
    )


def build_scene(variant="A", *, haze=0.0001, sun="day", config=None):
    """Build the common Roman fixture, optionally adding C's 3D ridge.

    ``variant`` accepts A (shared terrain/road/city with the existing sky) or
    C (the same inputs plus a world-anchored low-poly mountain mesh). B can be
    assembled by the caller from C's ``far_entities`` metadata.
    """
    if variant not in ("A", "C"):
        raise ValueError("variant must be 'A' or 'C'")
    if sun not in ("day", "sunset"):
        raise ValueError("sun must be 'day' or 'sunset'")
    haze = _number(haze, "haze", minimum=0.0, maximum=1.0)
    resolved = _merge_config(config)
    resolved_key = _config_json(resolved)
    scene = Scene()
    _configure_scene(scene, haze, sun)

    ground_config, x_axis, y_axis, heights = _ground_data_cached(resolved_key)
    terrain_mesh = _height_grid_mesh(x_axis, y_axis, heights, _TERRAIN_MATERIAL)
    scene.add(Entity(terrain_mesh, _COMMON_TERRAIN_NAME))

    city = ground_config["city"]
    cache = _roman_asset_cache()
    commands = PlacementCommands(scene, cache)
    street_start = len(scene.root_entities)
    street_summary = commands.create_roman_street(
        segments=_CITY_SEGMENTS,
        road_width=_CITY_ROAD_WIDTH,
        origin=(city["anchor_xy"][0], city["anchor_xy"][1], city["plateau_z"]),
        facing=math.pi,
        variation=True,
        seed=ground_config["seed"],
        extension_segments=0,
    )
    # Capture exactly the roots created by the street transaction. Palette
    # variants have their own asset paths, so filtering only base paths would
    # silently omit some of the shared Roman instances from the metadata.
    street_roots = scene.root_entities[street_start:]
    city_names = [entity.name for entity in street_roots]
    quarter_names = _add_outer_quarter(scene, cache, city, ground_config["seed"])
    city_roots = street_roots + [entity for entity in scene.root_entities
                                 if entity.name in quarter_names]

    road_mesh, road_counts = _exit_road_mesh(ground_config)
    scene.add(Entity(road_mesh, _EXIT_ROAD_NAME))

    mountain_counts = {"vertices": 0, "triangles": 0, "grid_rows": 0,
                       "grid_cols": 0, "xy_bounds": None}
    far_entity_names = []
    if variant == "C":
        mountain_mesh, mountain_counts = _mountain_mesh(
            ground_config, x_axis, y_axis, heights)
        scene.add(Entity(mountain_mesh, _FAR_MOUNTAIN_NAME))
        far_entity_names.append(_FAR_MOUNTAIN_NAME)

    scene.update()
    ground_stats = {
        "vertices": int(len(terrain_mesh.vertices)),
        "triangles": int(len(terrain_mesh.indices)),
        "grid_rows": int(len(y_axis)),
        "grid_cols": int(len(x_axis)),
        "xy_bounds": [[float(x_axis[0]), float(x_axis[-1])],
                      [float(y_axis[0]), float(y_axis[-1])]],
    }
    city_stats = _mesh_stats(city_roots)
    all_stats = _mesh_stats(scene.get_flat_render_list())
    # _mesh_stats accepts roots and recursively visits them. A flat render list
    # contains mesh-bearing nodes, so passing it also yields the scene totals.
    config_digest = hashlib.sha256(resolved_key.encode("utf-8")).hexdigest()
    anchor_x, anchor_y = city["anchor_xy"]
    footprint_x, footprint_y = city["footprint_xy"]
    valley_world = [[float(anchor_x + p[0]), float(anchor_y + p[1])]
                    for p in ground_config["valley"]["centerline"]]
    ridge_controls_world = [[float(anchor_x + p[0]), float(anchor_y + p[1]), float(p[2])]
                            for p in ground_config["ridge"]["controls"]]
    metadata = {
        "contract": "SUR-00 Roman countryside CPU fixture v1",
        "variant": variant,
        "sun": sun,
        "haze": haze,
        "seed": ground_config["seed"],
        "configuration": deepcopy(ground_config),
        "config_sha256": config_digest,
        "geography": {
            "up_axis": "Z",
            "world_unit": "metre by experiment convention",
            "city_anchor_xy": [float(anchor_x), float(anchor_y)],
            "city_plateau_z": float(city["plateau_z"]),
            "city_footprint_xy": [[float(anchor_x - footprint_x / 2.0),
                                   float(anchor_x + footprint_x / 2.0)],
                                  [float(anchor_y - footprint_y / 2.0),
                                   float(anchor_y + footprint_y / 2.0)]],
            "camera_xy_bounds": [[float(anchor_x - 200.0), float(anchor_x + 200.0)],
                                 [float(anchor_y - 200.0), float(anchor_y + 200.0)]],
            "camera_agl_bounds": [1.6, 120.0],
            "terrain_xy_bounds": [[float(x_axis[0]), float(x_axis[-1])],
                                  [float(y_axis[0]), float(y_axis[-1])]],
            "ridge_controls_world": ridge_controls_world,
            "valley_centerline_world": valley_world,
            "main_ridge_side": "north",
            "valley_opening": "south",
        },
        "entity_names": {
            "city": city_names + quarter_names,
            "common_terrain": _COMMON_TERRAIN_NAME,
            "exit_road": _EXIT_ROAD_NAME,
            "far_mountains": _FAR_MOUNTAIN_NAME if variant == "C" else None,
        },
        "far_entities": far_entity_names,
        "street": {
            **street_summary,
            "group_name": "Roman_Street_001",
            "facing_radians": math.pi,
            "city_entity_count": len(city_names) + len(quarter_names),
        },
        "geometry": {
            "terrain": ground_stats,
            "exit_road": road_counts,
            "far_mountains": mountain_counts,
            "city": city_stats,
            "scene": all_stats,
            "scene_root_entities": len(scene.root_entities),
            "external_models": 0,
            "external_textures": 0,
            "photographic_ground": False,
        },
    }
    return scene, metadata
