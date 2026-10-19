"""Deterministic LAB-00 scene and offline SPQR v1 bundle adapter.

The caller owns the desktop OpenGL context and a ``GLRenderer``. This module
builds only ordinary Mini3D Scene/Mesh/Entity data and delegates all native
scene, material, texture, uniform, and shader export to the existing bundle
adapter. It does not implement or draw a renderer.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mini3d.camera import Camera
from mini3d.scene import Entity, Mesh, Scene
from native.export_scene import BinaryWriter, FRAMES_PER_ROUTE, MEASURED_FRAMES, WARMUP_FRAMES


WIDTH = 1081
HEIGHT = 662
VIEW_NAMES = ("horizontal", "oblique", "distant")
GROUND_SIZE = (36.0, 26.0)
GROUND_Z = 0.0
SHADOW_RESOLUTION = 1024
CAPTURE_FRAME_INDEX = WARMUP_FRAMES + 60

_GROUND_MATERIAL = {
    "pbrMetallicRoughness": {
        "baseColorFactor": [0.34, 0.39, 0.25, 1.0],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.88,
    },
    "alphaMode": "OPAQUE",
}

_MARKERS = (
    # name, x, y, half-width, half-depth, height, linear base color
    ("Red Tower", -9.0, -5.0, 0.9, 1.25, 4.2, (0.88, 0.12, 0.08, 1.0)),
    ("Blue Post", 5.0, 5.5, 0.72, 0.72, 2.6, (0.07, 0.26, 0.91, 1.0)),
    ("Yellow Bar", 10.0, -1.0, 1.8, 0.55, 1.35, (0.96, 0.67, 0.06, 1.0)),
)

_CAMERA_POSES = {
    "horizontal": {
        "position": (0.0, -32.0, 4.4),
        "target": (0.0, 0.0, 1.4),
        "fov_y": 52.0,
        "near": 0.05,
        "far": 300.0,
    },
    "oblique": {
        "position": (25.0, -31.0, 25.0),
        "target": (0.0, 0.0, 0.0),
        "fov_y": 52.0,
        "near": 0.05,
        "far": 300.0,
    },
    "distant": {
        "position": (58.0, -75.0, 58.0),
        "target": (0.0, 0.0, 0.0),
        "fov_y": 52.0,
        "near": 0.05,
        "far": 500.0,
    },
}


def _material(color):
    return {
        "pbrMetallicRoughness": {
            "baseColorFactor": [float(value) for value in color],
            "metallicFactor": 0.0,
            "roughnessFactor": 0.82,
        },
        "alphaMode": "OPAQUE",
    }


def _ground_mesh(size_x, size_y, material):
    half_x, half_y = size_x * 0.5, size_y * 0.5
    vertices = np.asarray((
        (-half_x, -half_y, GROUND_Z),
        (half_x, -half_y, GROUND_Z),
        (half_x, half_y, GROUND_Z),
        (-half_x, half_y, GROUND_Z),
    ), dtype=np.float32)
    indices = np.asarray((0, 1, 2, 0, 2, 3), dtype=np.uint32)
    normals = np.tile(np.asarray((0.0, 0.0, 1.0), dtype=np.float32), (4, 1))
    texcoords = vertices[:, :2].copy()
    return Mesh(vertices, indices, normals=normals, texcoords=texcoords,
                material=material)


def _box_mesh(half_width, half_depth, height, material):
    """Make a flat-shaded, closed box rooted at z=0 with outward winding."""
    x, y, z = float(half_width), float(half_depth), float(height)
    faces = (
        ((x, -y, 0), (x, y, 0), (x, y, z), (x, -y, z), (1, 0, 0)),
        ((x, y, 0), (-x, y, 0), (-x, y, z), (x, y, z), (0, 1, 0)),
        ((-x, y, 0), (-x, -y, 0), (-x, -y, z), (-x, y, z), (-1, 0, 0)),
        ((-x, -y, 0), (x, -y, 0), (x, -y, z), (-x, -y, z), (0, -1, 0)),
        ((-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z), (0, 0, 1)),
        ((-x, y, 0), (x, y, 0), (x, -y, 0), (-x, -y, 0), (0, 0, -1)),
    )
    vertices = []
    normals = []
    texcoords = []
    indices = []
    for face in faces:
        points, normal = face[:4], face[4]
        offset = len(vertices)
        vertices.extend(points)
        normals.extend((normal,) * 4)
        texcoords.extend(((0, 0), (1, 0), (1, 1), (0, 1)))
        indices.extend((offset, offset + 1, offset + 2,
                        offset, offset + 2, offset + 3))
    return Mesh(np.asarray(vertices, dtype=np.float32),
                np.asarray(indices, dtype=np.uint32),
                normals=np.asarray(normals, dtype=np.float32),
                texcoords=np.asarray(texcoords, dtype=np.float32),
                material=material)


def create_baseline_scene():
    """Return the fixed finite Z-up test scene using no external assets."""
    scene = Scene()
    scene.show_grid = False
    scene.show_axes = False
    scene.render_mode = "Lit"
    scene.lighting_mode = "Scene"
    scene.light_dir = np.asarray((0.42, -0.48, 0.77), dtype=np.float32)
    scene.ambient = 0.28
    scene.diffuse = 1.5
    scene.environment_enabled = False
    scene.environment_intensity = 0.0
    scene.shadows_enabled = True
    scene.shadow_resolution = SHADOW_RESOLUTION
    scene.shadow_bias = 0.0005
    scene.shadow_pcf = True
    from mini3d.atmosphere import update_atmosphere
    update_atmosphere(
        scene,
        enabled=True,
        ground=False,
        sun_temperature=5500.0,
        exposure_ev=0.0,
        haze=0.002,
        ground_scale=1.0,
        ground_z=GROUND_Z,
        sky_texture="procedural",
        sky_intensity=1.0,
        ground_texture="procedural",
        sun_size=0.53,
        tone_mapping="reinhard",
        celestial_body="sun",
    )

    ground = Entity(
        _ground_mesh(GROUND_SIZE[0], GROUND_SIZE[1], _material(_GROUND_MATERIAL[
            "pbrMetallicRoughness"]["baseColorFactor"])),
        "Finite Ground",
    )
    scene.add(ground)

    for name, x, y, half_width, half_depth, height, color in _MARKERS:
        marker = Entity(_box_mesh(half_width, half_depth, height, _material(color)), name)
        marker.pos = np.asarray((x, y, GROUND_Z), dtype=np.float64)
        scene.add(marker)

    scene.update()
    return scene


def camera_for_view(view, width=WIDTH, height=HEIGHT):
    """Build one fixed Z-up camera pose for horizontal, oblique, or distant."""
    if view not in _CAMERA_POSES:
        raise ValueError("view must be one of: " + ", ".join(VIEW_NAMES))
    if isinstance(width, bool) or isinstance(height, bool) or width <= 0 or height <= 0:
        raise ValueError("camera dimensions must be positive integers")
    spec = _CAMERA_POSES[view]
    camera = Camera(position=spec["position"], fov_y=spec["fov_y"],
                    near=spec["near"], far=spec["far"])
    camera.look_at(spec["target"], up=(0.0, 0.0, 1.0))
    return camera


def _camera_metadata(camera, width, height, target):
    return {
        "position": np.asarray(camera.position, dtype=np.float64).tolist(),
        "target": [float(value) for value in target],
        "rotation": np.asarray(camera.rotation, dtype=np.float64).tolist(),
        "view": np.asarray(camera.view_matrix, dtype=np.float64).tolist(),
        "projection": np.asarray(
            camera.projection_matrix(float(width) / float(height)), dtype=np.float64
        ).tolist(),
        "fov_y_degrees": float(camera.fov_y),
        "near": float(camera.near),
        "far": float(camera.far),
        "aspect": float(width) / float(height),
        "up_axis": "Z",
    }


def _frame_bytes(camera, width, height):
    writer = BinaryWriter()
    writer.raw(b"SPQRF001")
    writer.u32(FRAMES_PER_ROUTE)
    position = np.asarray(camera.position, dtype=np.float64)
    rotation = np.asarray(camera.rotation, dtype=np.float64)
    view_matrix = np.asarray(camera.view_matrix, dtype=np.float64)
    projection = np.asarray(
        camera.projection_matrix(float(width) / float(height)), dtype=np.float64
    )
    for _frame_index in range(FRAMES_PER_ROUTE):
        # The native viewer recognizes only walk/orbit. One static orbit route
        # keeps the 24 warmup + 120 measured contract and supports captures at
        # frame 24 and frame 84 without changing the camera.
        writer.string("orbit")
        writer.f64(0.0)
        writer.f64_array(position)
        writer.f64_array(rotation)
        writer.f64_array(view_matrix)
        writer.f64_array(projection)
        writer.f64(float(camera.near))
        writer.f64(float(camera.far))
    return bytes(writer.data)


def write_frames(output, pose, width=WIDTH, height=HEIGHT):
    """Write a deterministic 144-frame route; output may be a folder or file."""
    target = Path(output)
    if target.suffix.lower() != ".bin":
        target.mkdir(parents=True, exist_ok=True)
        target = target / "frames.bin"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_frame_bytes(pose, width, height))
    return target


def _metadata(view, camera, counts):
    pose = _CAMERA_POSES[view]
    return {
        "contract": {
            "scene_magic": "SPQRN001",
            "scene_version": 1,
            "frames_magic": "SPQRF001",
            "frames_per_route": FRAMES_PER_ROUTE,
            "route": "orbit",
            "warmup_frames": WARMUP_FRAMES,
            "measured_frames": MEASURED_FRAMES,
            "capture_frame_indices": {
                "orbit-0": WARMUP_FRAMES,
                "orbit-mid": CAPTURE_FRAME_INDEX,
            },
            "coordinates": {
                "handedness": "right",
                "up_axis": "Z",
                "world_unit": "meter by LAB-00 experiment convention",
                "asset_scale_policy": (
                    "Existing imported model units are unchanged; this fixture has no imported assets."
                ),
                "matrix_layout": "row major, column vectors",
            },
            "vertex_layout": ["position3", "normal3", "uv2", "color4"],
            "lighting": "SPQR shared Mini3D material and sky shaders",
        },
        "view": view,
        "camera": _camera_metadata(camera, WIDTH, HEIGHT, pose["target"]),
        "quality": {
            "width": WIDTH,
            "height": HEIGHT,
            "native_msaa_samples": 1,
            "native_shadows_enabled": True,
            "shadow_resolution": SHADOW_RESOLUTION,
            "shadow_bias": 0.0005,
            "finite_ground_size_xy": [float(value) for value in GROUND_SIZE],
            "geometry_markers": len(_MARKERS),
            "external_models": 0,
            "external_textures": 0,
            "sky": "enabled procedural Mini3D atmosphere and existing sky shader",
            "environment": "project-bundled neutral IBL used by the procedural sky",
            "fixed_camera_route": True,
        },
        "counts": counts,
    }


def export_baseline(output, view="horizontal", *, renderer):
    """Export one fixed-camera LAB-00 offline v1 Bundle.

    The caller must establish a current desktop OpenGL context and pass its
    ``GLRenderer``. Three output directories may be produced by calling this
    function once for each value in ``VIEW_NAMES``; every view has identical
    scene.bin/shaders and a view-specific fixed-camera frames.bin.
    """
    if view not in _CAMERA_POSES:
        raise ValueError("view must be one of: " + ", ".join(VIEW_NAMES))

    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    scene = create_baseline_scene()
    camera = camera_for_view(view)

    from mini3d.native_photo_bundle import export_live_bundle

    root = Path(__file__).resolve().parents[2]
    bundle = export_live_bundle(
        scene,
        camera,
        renderer,
        output,
        root / "spqr-native",
        shared_textures=False,
    )
    write_frames(output, camera)
    metadata = _metadata(view, camera, bundle["counts"])
    metadata_path = output / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata
