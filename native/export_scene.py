#!/usr/bin/env python3
"""Offline exporter for the SPQR native prototype bundle.

This uses Mini3D's own builders, OpenGL renderer and shader sources. It writes
a deterministic bundle and reference captures without changing the source tree.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import time
import struct

_DLL_DIRECTORY_HANDLES = []
if os.name == "nt" and hasattr(os, "add_dll_directory"):
    _python_prefix = Path(sys.prefix)
    for _dll_dir in (_python_prefix, _python_prefix / "Library" / "bin",
                     _python_prefix / "DLLs"):
        if _dll_dir.is_dir():
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(_dll_dir)))

import numpy as np

WARMUP_FRAMES = 24
MEASURED_FRAMES = 120
FRAMES_PER_ROUTE = WARMUP_FRAMES + MEASURED_FRAMES
ROUTES = ("walk", "orbit")
CAPTURES = {"walk-0": 24, "walk-mid": 84, "orbit-0": 168, "orbit-mid": 228}
PER_MATERIAL = {
    "baseFactor", "emissiveFactor", "specularColorFactor", "metallicFactor",
    "roughnessFactor", "normalScale", "aoStrength", "specularFactor",
    "alphaCutoff", "alphaMode", "shadingMode", "photographicGround",
    "hasBase", "hasMR", "hasNormal", "hasAO", "hasEmissive",
    "hasSpecular", "hasSpecularColor",
}
DYNAMIC_UNIFORMS = {
    "material": ["model", "normalMatrix", "view", "projection", "eye",
                 "useInstances", "shadowMatrix", "shadowWorldScale",
                 "shadowEnabled", "photoFar"],
    "sky": ["inverseProjection", "cameraRotation"],
}


class BinaryWriter:
    def __init__(self):
        self.data = bytearray()

    def raw(self, value):
        self.data.extend(value)

    def u32(self, value):
        self.data.extend(struct.pack("<I", int(value)))

    def i32(self, value):
        self.data.extend(struct.pack("<i", int(value)))

    def f32(self, value):
        self.data.extend(struct.pack("<f", float(value)))

    def f64(self, value):
        self.data.extend(struct.pack("<d", float(value)))

    def string(self, value):
        encoded = str(value).encode("utf-8")
        self.u32(len(encoded))
        self.raw(encoded)

    def f32_array(self, values):
        self.raw(np.asarray(values, dtype="<f4").reshape(-1).tobytes())

    def f64_array(self, values):
        self.raw(np.asarray(values, dtype="<f8").reshape(-1).tobytes())

    def u32_array(self, values):
        self.raw(np.asarray(values, dtype="<u4").reshape(-1).tobytes())

    def i32_array(self, values):
        self.raw(np.asarray(values, dtype="<i4").reshape(-1).tobytes())


def route_pose(name, t):
    """Same deterministic walk/orbit function as the performance benchmark."""
    if name == "walk":
        return [1, -10 + 16 * t, 1.7], [0, 20, 3]
    if name == "orbit":
        angle = -2.8 + t * 2.2
        return [25 * math.cos(angle), 8 + 25 * math.sin(angle), 10], [0, 8, 2]
    raise ValueError("unsupported route: " + str(name))


def route_t(local_frame):
    if local_frame < WARMUP_FRAMES:
        return 0.0
    return (local_frame - WARMUP_FRAMES) / (MEASURED_FRAMES - 1)


def set_camera_frame(api, route, local_frame):
    camera = api._app.viewer.camera
    position, target = route_pose(route, route_t(local_frame))
    camera.position = position
    camera.look_at(target)
    api._app.viewer.update_clipping()
    return camera


def as_array(result, dtype, shape):
    if isinstance(result, (bytes, bytearray, memoryview)):
        array = np.frombuffer(result, dtype=dtype)
    else:
        array = np.asarray(result, dtype=dtype).reshape(-1)
    expected = int(np.prod(shape))
    if array.size != expected:
        raise RuntimeError("OpenGL readback returned {} values; expected {}".format(array.size, expected))
    return np.array(array.reshape(shape), copy=True)


def raw_uniform_records(program, gl):
    """Reflect active values through explicit ctypes destinations."""
    from OpenGL.raw.GL.VERSION.GL_2_0 import glGetUniformfv, glGetUniformiv

    active_count = int(gl.glGetProgramiv(program, gl.GL_ACTIVE_UNIFORMS))
    type_shapes = {
        gl.GL_FLOAT: (1, 1), gl.GL_FLOAT_VEC2: (2, 1),
        gl.GL_FLOAT_VEC3: (3, 1), gl.GL_FLOAT_VEC4: (4, 1),
        gl.GL_INT: (1, 1), gl.GL_INT_VEC2: (2, 1),
        gl.GL_INT_VEC3: (3, 1), gl.GL_INT_VEC4: (4, 1),
        gl.GL_BOOL: (1, 1), gl.GL_BOOL_VEC2: (2, 1),
        gl.GL_BOOL_VEC3: (3, 1), gl.GL_BOOL_VEC4: (4, 1),
        gl.GL_FLOAT_MAT2: (4, 2), gl.GL_FLOAT_MAT3: (9, 3),
        gl.GL_FLOAT_MAT4: (16, 4),
    }
    sampler_names = (
        "GL_SAMPLER_1D", "GL_SAMPLER_2D", "GL_SAMPLER_3D", "GL_SAMPLER_CUBE",
        "GL_SAMPLER_1D_SHADOW", "GL_SAMPLER_2D_SHADOW", "GL_SAMPLER_CUBE_SHADOW",
        "GL_SAMPLER_1D_ARRAY", "GL_SAMPLER_2D_ARRAY", "GL_SAMPLER_1D_ARRAY_SHADOW",
        "GL_SAMPLER_2D_ARRAY_SHADOW", "GL_INT_SAMPLER_1D", "GL_INT_SAMPLER_2D",
        "GL_INT_SAMPLER_3D", "GL_INT_SAMPLER_CUBE", "GL_UNSIGNED_INT_SAMPLER_1D",
        "GL_UNSIGNED_INT_SAMPLER_2D", "GL_UNSIGNED_INT_SAMPLER_3D",
        "GL_UNSIGNED_INT_SAMPLER_CUBE",
    )
    sampler_types = {getattr(gl, name) for name in sampler_names if hasattr(gl, name)}
    records = []
    for index in range(active_count):
        raw_name, array_size, uniform_type = gl.glGetActiveUniform(program, index)[:3]
        name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
        uniform_type, array_size = int(uniform_type), int(array_size)
        if uniform_type in sampler_types:
            records.append(dict(name=name, type=uniform_type, array_size=array_size,
                                scalar_count=array_size, values=None, sampler=True))
            continue
        if uniform_type not in type_shapes:
            raise RuntimeError("Unsupported active uniform type 0x{:x} for {}".format(uniform_type, name))
        scalar_per_element, matrix_dimension = type_shapes[uniform_type]
        scalar_count = scalar_per_element * array_size
        location = int(gl.glGetUniformLocation(program, name))
        if location < 0:
            raise RuntimeError("Active uniform has no location: " + name)
        integer = uniform_type in (
            gl.GL_INT, gl.GL_INT_VEC2, gl.GL_INT_VEC3, gl.GL_INT_VEC4,
            gl.GL_BOOL, gl.GL_BOOL_VEC2, gl.GL_BOOL_VEC3, gl.GL_BOOL_VEC4)
        if integer:
            buffer = (ctypes.c_int * scalar_count)()
            glGetUniformiv(program, location, buffer)
            values = np.ctypeslib.as_array(buffer).astype(np.int32, copy=True)
        else:
            buffer = (ctypes.c_float * scalar_count)()
            glGetUniformfv(program, location, buffer)
            values = np.ctypeslib.as_array(buffer).astype(np.float32, copy=True)
            if matrix_dimension > 1:
                values = values.reshape(array_size, matrix_dimension, matrix_dimension)
                values = values.transpose(0, 2, 1).reshape(-1).copy()
        records.append(dict(name=name, type=uniform_type, array_size=array_size,
                            scalar_count=scalar_count, values=values.tolist(),
                            sampler=False, integer=integer))
    return records


def is_sampler(record, gl):
    return bool(record.get("sampler"))


def write_uniform_block(writer, records):
    records = sorted(records, key=lambda item: item["name"])
    writer.u32(len(records))
    for record in records:
        if record.get("sampler"):
            raise RuntimeError("Sampler cannot be serialized in a uniform block: " + record["name"])
        writer.string(record["name"])
        writer.u32(record["type"])
        writer.u32(record["scalar_count"])
        if record.get("integer"):
            writer.i32_array(record["values"])
        else:
            writer.f32_array(record["values"])


def reflect_program(program, gl):
    gl.glUseProgram(program)
    return raw_uniform_records(program, gl)


def get_tex_parameter(gl, target, pname, label):
    value = gl.glGetTexParameteriv(target, pname)
    if isinstance(value, np.ndarray):
        if value.size != 1:
            raise RuntimeError("Unexpected {} texture parameter vector".format(label))
        value = value.reshape(-1)[0]
    return int(value)


def capture_texture(handle, target, gl):
    from OpenGL.raw.GL.VERSION.GL_1_1 import glGetTexImage

    handle, target = int(handle), int(target)
    gl.glBindTexture(target, handle)
    pack_state = set_pixel_pack_safe(gl)
    levels = []
    try:
        for level in range(32):
            query_target = gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X if target == gl.GL_TEXTURE_CUBE_MAP else target
            width = int(gl.glGetTexLevelParameteriv(query_target, level, gl.GL_TEXTURE_WIDTH))
            height = int(gl.glGetTexLevelParameteriv(query_target, level, gl.GL_TEXTURE_HEIGHT))
            if width == 0 or height == 0:
                if level == 0:
                    raise RuntimeError("Texture {} has no allocated level zero".format(handle))
                break
            faces = []
            face_targets = ([target] if target == gl.GL_TEXTURE_2D else
                            [gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X + face for face in range(6)])
            for face_target in face_targets:
                face_width = int(gl.glGetTexLevelParameteriv(face_target, level, gl.GL_TEXTURE_WIDTH))
                face_height = int(gl.glGetTexLevelParameteriv(face_target, level, gl.GL_TEXTURE_HEIGHT))
                if (face_width, face_height) != (width, height):
                    raise RuntimeError("Cube texture faces have inconsistent mip dimensions")
                byte_count = width * height * 4 * ctypes.sizeof(ctypes.c_float)
                output = ctypes.create_string_buffer(byte_count)
                glGetTexImage(face_target, level, gl.GL_RGBA, gl.GL_FLOAT,
                              ctypes.cast(output, ctypes.c_void_p))
                pixels = np.frombuffer(output, dtype=np.float32).copy()
                if pixels.size != width * height * 4 or not np.isfinite(pixels).all():
                    raise RuntimeError("Invalid/non-finite texture readback for GL name {}".format(handle))
                faces.append(pixels)
            internal = int(gl.glGetTexLevelParameteriv(face_targets[0], level,
                                                       gl.GL_TEXTURE_INTERNAL_FORMAT))
            levels.append(dict(width=width, height=height, internal_format=internal, faces=faces))
    finally:
        restore_pixel_pack(gl, pack_state)
    if len(levels) == 32:
        raise RuntimeError("Texture mip chain exceeds supported 32 levels")
    parameters = dict(
        min_filter=get_tex_parameter(gl, target, gl.GL_TEXTURE_MIN_FILTER, "min_filter"),
        mag_filter=get_tex_parameter(gl, target, gl.GL_TEXTURE_MAG_FILTER, "mag_filter"),
        wrap_s=get_tex_parameter(gl, target, gl.GL_TEXTURE_WRAP_S, "wrap_s"),
        wrap_t=get_tex_parameter(gl, target, gl.GL_TEXTURE_WRAP_T, "wrap_t"),
        wrap_r=get_tex_parameter(gl, target, gl.GL_TEXTURE_WRAP_R, "wrap_r"),
    )
    return dict(target=target, internal_format=levels[0]["internal_format"],
                parameters=parameters, levels=levels)


def add_texture(handle, target, gl, texture_records, texture_by_handle):
    handle = int(handle)
    if handle == 0:
        return 0xffffffff
    if handle not in texture_by_handle:
        texture_by_handle[handle] = len(texture_records)
        texture_records.append(capture_texture(handle, target, gl))
    elif texture_records[texture_by_handle[handle]]["target"] != int(target):
        raise RuntimeError("GL texture {} was observed with conflicting targets".format(handle))
    return texture_by_handle[handle]


def validate_material(material, label):
    if not isinstance(material, dict):
        raise RuntimeError("Legacy/non-dictionary material is unsupported: " + label)
    allowed_extensions = {"KHR_materials_unlit", "KHR_materials_specular",
                          "KHR_materials_emissive_strength"}
    unsupported = set(material.get("extensions", {})) - allowed_extensions
    if unsupported:
        raise RuntimeError("Unsupported material extensions on {}: {}".format(label, sorted(unsupported)))
    alpha_mode = material.get("alphaMode", "OPAQUE")
    if alpha_mode not in ("OPAQUE", "MASK", "BLEND"):
        raise RuntimeError("Unsupported alphaMode on {}: {}".format(label, alpha_mode))
    textures = material.get("textures", {})
    supported = {"baseColor", "metallicRoughness", "normal", "occlusion", "emissive",
                 "specular", "specularColor"}
    unknown = set(textures) - supported
    if unknown:
        raise RuntimeError("Unsupported texture slots on {}: {}".format(label, sorted(unknown)))
    for slot, texture in textures.items():
        if not isinstance(texture, dict) or "image" not in texture:
            raise RuntimeError("Malformed {} texture on {}".format(slot, label))
        if texture.get("texCoord", 0) != 0:
            raise RuntimeError("Only TEXCOORD_0 is supported ({} on {})".format(slot, label))
        if texture.get("extensions"):
            raise RuntimeError("Texture extensions are unsupported ({} on {})".format(slot, label))


def flatten_scene(render_scene, ground):
    flattened = []
    for root_index, root in enumerate(render_scene.root_entities):
        root_id = getattr(root, "entity_id", None)
        root_label = root_id if root_id else (
            "photographic-ground" if root is ground else "render-only-root-{:04d}".format(root_index))

        def visit(node, path, child_index):
            if not getattr(node, "visible", True):
                return
            local_name = str(getattr(node, "name", "") or node.__class__.__name__)
            node_path = path + "/" + local_name + "#{:04d}".format(child_index)
            if getattr(node, "model", None) is not None:
                model = node.model
                material = getattr(model, "material", None)
                if material is None:
                    raise RuntimeError("Unsupported legacy material entity: {}".format(node_path))
                validate_material(material, node_path)
                flattened.append(dict(entity=node, root=root, model=model, material=material,
                    root_id=root_label, stable_id=root_label + "/" + node_path,
                    name=local_name, photographic_ground=node is ground))
            for index, child in enumerate(getattr(node, "children", ())):
                visit(child, node_path, index)

        visit(root, root_label, root_index)
    if ground is not None and not any(row["entity"] is ground for row in flattened):
        raise RuntimeError("Photographic ground was configured but not present in render flattening")
    return flattened


def mesh_payload(mesh):
    positions = np.asarray(mesh.vertices, dtype=np.float32)
    if positions.ndim != 2 or positions.shape[1] < 3:
        raise RuntimeError("Mesh positions must be Nx3 or wider")
    positions = positions[:, :3]
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    texcoords = getattr(mesh, "texcoords", None)
    texcoords = np.zeros((len(positions), 2), np.float32) if texcoords is None else np.asarray(texcoords, np.float32)
    colors = getattr(mesh, "vertex_colors", None)
    if colors is None:
        colors = np.ones((len(positions), 4), np.float32)
    else:
        colors = np.asarray(colors, dtype=np.float32)
        if colors.ndim != 2 or colors.shape[0] != len(positions) or colors.shape[1] not in (3, 4):
            raise RuntimeError("Vertex colors must be Nx3 or Nx4")
        if colors.shape[1] == 3:
            colors = np.column_stack((colors, np.ones(len(positions), np.float32)))
    if normals.shape != (len(positions), 3) or texcoords.shape != (len(positions), 2):
        raise RuntimeError("Mesh normal/UV attribute dimensions do not match positions")
    vertices = np.ascontiguousarray(np.column_stack((positions, normals, texcoords, colors)), dtype=np.float32)
    indices = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1)
    if len(indices) % 3 or (len(indices) and int(indices.max()) >= len(positions)):
        raise RuntimeError("Mesh indices are malformed or out of range")
    bounds = getattr(mesh, "bounds", None)
    if bounds is None:
        if not len(positions):
            raise RuntimeError("Empty mesh has no valid bounds")
        bounds = (positions.min(axis=0), positions.max(axis=0))
    bounds = np.asarray(bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[0] > bounds[1]):
        raise RuntimeError("Mesh local bounds are invalid")
    if not np.isfinite(vertices).all():
        raise RuntimeError("Mesh contains non-finite vertex data")
    return vertices, indices, bounds


def set_pixel_pack_safe(gl):
    names = (gl.GL_PACK_ALIGNMENT, gl.GL_PACK_ROW_LENGTH, gl.GL_PACK_SKIP_ROWS,
             gl.GL_PACK_SKIP_PIXELS)
    values = [int(gl.glGetIntegerv(name)) for name in names]
    buffer = int(gl.glGetIntegerv(gl.GL_PIXEL_PACK_BUFFER_BINDING))
    gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, 0)
    for name, value in zip(names, (1, 0, 0, 0)):
        gl.glPixelStorei(name, value)
    return names, values, buffer


def restore_pixel_pack(gl, state):
    names, values, buffer = state
    for name, value in zip(names, values):
        gl.glPixelStorei(name, value)
    gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, buffer)


def read_capture_pixels(width, height, shadow_map, gl):
    pack_state = set_pixel_pack_safe(gl)
    read_framebuffer = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    try:
        rgba = as_array(gl.glReadPixels(0, 0, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE),
                        np.uint8, (height, width, 4))
        if not shadow_map.fbo or not shadow_map.size:
            raise RuntimeError("No fitted shadow depth framebuffer exists for the reference frame")
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, shadow_map.fbo)
        size = int(shadow_map.size)
        depth = as_array(gl.glReadPixels(0, 0, size, size,
                         gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT), np.float32, (size, size))
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read_framebuffer)
        restore_pixel_pack(gl, pack_state)
    return rgba, depth


def camera_json(camera, aspect):
    return dict(position=np.asarray(camera.position, dtype=float).tolist(),
        rotation=np.asarray(camera.rotation, dtype=float).tolist(),
        view=np.asarray(camera.view_matrix, dtype=float).tolist(),
        projection=np.asarray(camera.projection_matrix(aspect), dtype=float).tolist(),
        near=float(camera.near), far=float(camera.far), fov_y=float(camera.fov_y),
        aspect=float(aspect))


def complete_source_hashes(project, bundle_dir, exporter, output):
    entries = []
    inputs = []
    inputs.extend(sorted((project / "mini3d").rglob("*.py")))
    inputs.extend(sorted((project / "mini3d" / "resources").rglob("*")))
    inputs.extend([project / "tools" / "build_pompeii.py",
                   project / "tools" / "build_roman_street.py",
                   project / "tests" / "spqr_performance_benchmark.py",
                   project / "model" / "manifest.json"])
    for path in sorted(set(inputs)):
        if not path.is_file() or path.is_symlink():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        entries.append(dict(path="project/" + path.relative_to(project).as_posix(),
                            size_bytes=path.stat().st_size, sha256=digest.hexdigest()))
    files = [(bundle_dir / "FORMAT.md", "bundle/FORMAT.md"),
             (exporter, "bundle/tools/export_scene.py")]
    for path in sorted((bundle_dir / "src").rglob("*")):
        if path.is_file():
            files.append((path, "bundle/src/" + path.relative_to(bundle_dir / "src").as_posix()))
    for path in sorted((bundle_dir / "shaders").rglob("*")):
        if path.is_file():
            files.append((path, "bundle/shaders/" + path.relative_to(bundle_dir / "shaders").as_posix()))
    for path in (output / "scene.bin", output / "frames.bin"):
        files.append((path, "output/" + path.name))
    if (output / "python-render-reference.json").is_file():
        files.append((output / "python-render-reference.json", "output/python-render-reference.json"))
    for path in sorted((output / "shaders").rglob("*")):
        if path.is_file():
            files.append((path, "output/shaders/" + path.relative_to(output / "shaders").as_posix()))
    for path in sorted((output / "reference").rglob("*")):
        if path.is_file():
            files.append((path, "output/reference/" + path.relative_to(output / "reference").as_posix()))
    for path, label in files:
        if path.is_file():
            entries.append(dict(path=label, size_bytes=path.stat().st_size,
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return entries


def write_scene_binary(path, texture_records, material_globals, sky_globals,
                       material_rows, mesh_rows, entity_rows, opaque_indices,
                       scene, ground_z, gl):
    writer = BinaryWriter()
    writer.raw(b"SPQRN001")
    writer.u32(1)
    writer.u32(len(texture_records))
    for record in texture_records:
        writer.u32(record["target"])
        writer.u32(record["internal_format"])
        p = record["parameters"]
        writer.u32(p["min_filter"]); writer.u32(p["mag_filter"])
        writer.u32(p["wrap_s"]); writer.u32(p["wrap_t"]); writer.u32(p["wrap_r"])
        writer.u32(len(record["levels"]))
        faces_expected = 1 if record["target"] == gl.GL_TEXTURE_2D else 6
        for level in record["levels"]:
            writer.u32(level["width"]); writer.u32(level["height"])
            if len(level["faces"]) != faces_expected:
                raise RuntimeError("Texture face count violates the bundle contract")
            for face in level["faces"]:
                writer.f32_array(face)
    write_uniform_block(writer, material_globals)
    write_uniform_block(writer, sky_globals)
    writer.u32(len(material_rows))
    for material in material_rows:
        write_uniform_block(writer, material["parameters"])
        writer.u32(material["flags"])
        if len(material["texture_indices"]) != 13:
            raise RuntimeError("Material texture array must contain exactly 13 units")
        writer.u32_array(material["texture_indices"])
    writer.u32(len(mesh_rows))
    for mesh in mesh_rows:
        writer.u32(mesh["material_index"])
        writer.u32(mesh["vertices"].shape[0])
        writer.u32(mesh["indices"].size)
        writer.f64_array(mesh["bounds"])
        writer.f32_array(mesh["vertices"])
        writer.u32_array(mesh["indices"])
    writer.u32(len(entity_rows))
    for entity in entity_rows:
        writer.string(entity["stable_id"])
        writer.u32(entity["mesh_index"])
        writer.u32(entity["flags"])
        writer.f64_array(entity["world"])
        writer.f32_array(entity["normal"])
    writer.u32(len(opaque_indices))
    writer.u32_array(opaque_indices)
    from mini3d.lighting import scene_light_direction
    writer.f64_array(np.asarray(scene_light_direction(scene), dtype=np.float64))
    writer.u32(int(scene.shadow_resolution))
    writer.f32(float(scene.shadow_bias))
    writer.f32(0.0)  # Reserved normal bias; the source shadow shader has no normal-bias term.
    writer.f32(1.0)  # Reserved strength; source shadow visibility is not strength-scaled.
    writer.u32(1 if scene.shadows_enabled else 0)
    writer.f64(float(ground_z))
    path.write_bytes(writer.data)


def set_material_uniforms(material_renderer, material, mode, gl):
    material_renderer._material_texture_state = {}
    gl.glUseProgram(material_renderer.program)
    material_renderer._material(material, mode)
    records = raw_uniform_records(material_renderer.program, gl)
    parameters = [record for record in records
                  if record["name"] in PER_MATERIAL and not is_sampler(record, gl)]
    missing = PER_MATERIAL - {record["name"] for record in parameters}
    if missing:
        raise RuntimeError("Material parameter uniforms were not reflected: {}".format(sorted(missing)))
    return parameters


def write_benchmark_report(output, benchmark, renderer, gl, width, height):
    from threadpoolctl import threadpool_info

    report = {
        "renderer": (gl.glGetString(gl.GL_RENDERER).decode("utf-8", "replace")
                     if gl.glGetString(gl.GL_RENDERER) else "unknown"),
        "size": [width, height],
        "warmup_frames_per_route": WARMUP_FRAMES,
        "measured_frames_per_route": MEASURED_FRAMES,
        "glFinish": True,
        "includes": ["scene_frame synchronization (scene.update + snapshot)",
                     "viewer.update_clipping", "GLRenderer.render", "glFinish"],
        "threadpool_info": threadpool_info(),
        "routes": {},
    }
    for route in ROUTES:
        samples = np.asarray(benchmark[route]["samples_ms"], dtype=np.float64)
        if len(samples) != MEASURED_FRAMES:
            raise RuntimeError("Benchmark requires 120 measured samples for " + route)
        report["routes"][route] = dict(
            raw_frame_ms=samples.tolist(),
            mean_ms=float(np.mean(samples)),
            median_ms=float(np.median(samples)),
            p95_ms=float(np.percentile(samples, 95)),
            draw_calls=benchmark[route]["draw_calls"],
            submitted_triangles=benchmark[route]["submitted_triangles"])
    path = output / "python-render-reference.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True,
                        help="Source work/mini3d project root")
    parser.add_argument("--output", type=Path, required=True, help="Bundle output directory")
    parser.add_argument("--width", type=int, default=1081)
    parser.add_argument("--height", type=int, default=662)
    parser.add_argument("--benchmark", action="store_true",
                        help="Also time route frames with GLRenderer + glFinish")
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        parser.error("--width and --height must be positive")
    project = args.project.expanduser().resolve()
    if (project / "mini3d").is_dir() and not (project / "tools" / "build_pompeii.py").is_file():
        project = project / "mini3d"
    if not (project / "tools" / "build_pompeii.py").is_file() or not (project / "mini3d").is_dir():
        parser.error("--project must contain tools/build_pompeii.py and mini3d/")
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    import importlib.util
    from PIL import Image
    from OpenGL import GL as gl
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.scene_snapshot import scene_frame
    from mini3d.atmosphere import atmosphere_state, prepare_photographic_scene
    from mini3d.sky_renderer import VERTEX as SKY_VERTEX, FRAGMENT as SKY_FRAGMENT
    from mini3d.material_shaders import VERTEX_SHADER, FRAGMENT_SHADER
    from mini3d.shadow_map import DEPTH_VERTEX, DEPTH_FRAGMENT

    spec = importlib.util.spec_from_file_location(
        "spqr_export_capture", project / "tools" / "capture_sunset.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the source project's desktop GL context helper")
    capture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture_module)

    renderer = target = None
    with capture_module.desktop_context():
        try:
            renderer = GLRenderer(args.width, args.height)
            renderer.render_mode = "REALISTIC"
            api = Mini3DAPI(renderer=renderer)
            builder = importlib.import_module("tools.build_pompeii")
            build_summary = builder.build_scene(api)
            scene = api._app.scene
            scene.show_grid = bool(api._app.show_grid)
            scene.show_axes = False
            scene.render_mode = api._app.render_mode
            scene.update()
            api._app.viewer.resize(args.width, args.height)
            renderer.resize(args.width, args.height)
            target = RenderTarget(samples=1)
            target.resize(args.width, args.height, samples=1)
            aspect = float(args.width) / args.height
            captured = {}
            frame_records = []
            benchmark = {route: dict(samples_ms=[], draw_calls=[], submitted_triangles=[])
                         for route in ROUTES}
            benchmark_enabled = bool(args.benchmark)
            previous_multisample = bool(gl.glIsEnabled(gl.GL_MULTISAMPLE))
            gl.glDisable(gl.GL_MULTISAMPLE)

            for route_index, route in enumerate(ROUTES):
                route_start = route_index * FRAMES_PER_ROUTE
                for local_frame in range(FRAMES_PER_ROUTE):
                    frame_index = route_start + local_frame
                    camera = set_camera_frame(api, route, local_frame)
                    t = route_t(local_frame)
                    frame_records.append(dict(route=route, t=t,
                        position=np.asarray(camera.position, dtype=np.float64),
                        rotation=np.asarray(camera.rotation, dtype=np.float64),
                        view=np.asarray(camera.view_matrix, dtype=np.float64),
                        projection=np.asarray(camera.projection_matrix(aspect), dtype=np.float64),
                        near=float(camera.near), far=float(camera.far)))
                    capture_name = next((name for name, index in CAPTURES.items()
                                         if index == frame_index), None)
                    if benchmark_enabled:
                        started = time.perf_counter()
                        with scene_frame(scene):
                            api._app.viewer.update_clipping()
                            target.bind()
                            gl.glDisable(gl.GL_SCISSOR_TEST)
                            gl.glDepthMask(True)
                            renderer.render(scene, camera)
                            target.resolve()
                            gl.glFinish()
                        elapsed = (time.perf_counter() - started) * 1000.0
                        if local_frame >= WARMUP_FRAMES:
                            benchmark[route]["samples_ms"].append(float(elapsed))
                            benchmark[route]["draw_calls"].append(
                                int(renderer.render_stats.get("draw_calls", 0)))
                            benchmark[route]["submitted_triangles"].append(
                                int(renderer.render_stats.get("submitted_triangles", 0)))
                    elif capture_name is not None:
                        scene.update()
                        api._app.viewer.update_clipping()
                        target.bind()
                        gl.glDisable(gl.GL_SCISSOR_TEST)
                        gl.glDepthMask(True)
                        renderer.render(scene, camera)
                        target.resolve()
                    if capture_name is not None:
                        rgba, depth = read_capture_pixels(args.width, args.height,
                                                           renderer.shadow_map, gl)
                        png_path = output / "reference" / (capture_name + ".png")
                        depth_path = output / "reference" / (capture_name + ".depth.npy")
                        png_path.parent.mkdir(parents=True, exist_ok=True)
                        Image.fromarray(np.ascontiguousarray(rgba[::-1, :, :3]), mode="RGB").save(png_path)
                        with depth_path.open("wb") as stream:
                            np.save(stream, depth, allow_pickle=False)
                        _, ground = prepare_photographic_scene(scene, camera,
                            getattr(renderer, "_photo_ground", None))
                        shadow_matrix = getattr(renderer.shadow_map, "matrix", None)
                        if shadow_matrix is None:
                            raise RuntimeError("Reference render did not produce a fitted shadow matrix")
                        stats = dict(renderer.render_stats)
                        captured[capture_name] = dict(frame_index=frame_index, route=route,
                            local_frame=local_frame, t=t, camera=camera_json(camera, aspect),
                            ground_world=(None if ground is None else
                                          np.asarray(ground.world_matrix, dtype=float).tolist()),
                            fitted_shadow_matrix=np.asarray(shadow_matrix, dtype=float).tolist(),
                            drawcalls=dict(total=int(stats.get("draw_calls", 0)),
                                color=int(stats.get("color_draw_calls", 0)),
                                shadow=int(stats.get("shadow_draw_calls", 0))),
                            triangles=dict(submitted=int(stats.get("submitted_triangles", 0)),
                                color=int(stats.get("color_triangles", 0)),
                                shadow=int(stats.get("shadow_triangles", 0))),
                            png=png_path.relative_to(output).as_posix(),
                            depth=depth_path.relative_to(output).as_posix(),
                            image_origin="topdown", depth_origin="GL bottomup",
                            depth_kind="fitted shadow map", depth_size=int(renderer.shadow_map.size))
                print("Finished {} route frames".format(route), flush=True)
            if previous_multisample:
                gl.glEnable(gl.GL_MULTISAMPLE)
            benchmark_path = None
            if benchmark_enabled:
                benchmark_path = write_benchmark_report(
                    output, benchmark, renderer, gl, args.width, args.height)

            # scene.bin starts with the walk-0 ground pose; native updates it per frame.
            first_camera = set_camera_frame(api, "walk", WARMUP_FRAMES)
            scene.update()
            photo_scene, ground = prepare_photographic_scene(
                scene, first_camera, getattr(renderer, "_photo_ground", None))
            render_rows = flatten_scene(photo_scene, ground)
            if ground is None or not any(row["photographic_ground"] for row in render_rows):
                raise RuntimeError("Pompeii scene requires its camera-following photographic ground")

            material_renderer = getattr(renderer, "material_renderer", None)
            if material_renderer is None:
                raise RuntimeError("Pompeii scene produced no material renderer")
            material_objects = []
            material_by_id = {}
            for row in render_rows:
                material = row["material"]
                if id(material) not in material_by_id:
                    material_by_id[id(material)] = len(material_objects)
                    material_objects.append(material)
                for texture in material.get("textures", {}).values():
                    # Use the renderer's decoder, sampler setup and mip generation.
                    material_renderer._texture(texture)

            if not hasattr(renderer, "sky_renderer"):
                raise RuntimeError("Atmosphere was enabled but SkyRenderer was not constructed")
            material_program_records = reflect_program(material_renderer.program, gl)
            sky_program_records = reflect_program(renderer.sky_renderer.program, gl)
            material_global_records = [record for record in material_program_records
                if record["name"] not in PER_MATERIAL
                and record["name"] not in DYNAMIC_UNIFORMS["material"]
                and not is_sampler(record, gl)]
            sky_global_records = [record for record in sky_program_records
                if record["name"] not in DYNAMIC_UNIFORMS["sky"]
                and not is_sampler(record, gl)]
            for required in ("light0", "lightIntensity", "ambientIntensity", "sceneLighting",
                             "atmosphereEnabled", "sunDirection", "sunColor", "shadowPCF"):
                if required not in {record["name"] for record in material_global_records}:
                    raise RuntimeError("Expected material global uniform was not reflected: " + required)

            texture_records = []
            texture_by_handle = {}
            material_rows = []
            for material in material_objects:
                parameters = set_material_uniforms(material_renderer, material, scene.render_mode, gl)
                texture_indices = [0xffffffff] * 13
                slots = ("baseColor", "metallicRoughness", "normal", "occlusion",
                         "emissive", "specular", "specularColor")
                for unit, slot in enumerate(slots):
                    texture = material.get("textures", {}).get(slot)
                    if texture is not None:
                        handle = material_renderer._texture(texture)
                        texture_indices[unit] = add_texture(handle, gl.GL_TEXTURE_2D,
                            gl, texture_records, texture_by_handle)
                material_rows.append(dict(parameters=parameters,
                    flags=1 if material.get("doubleSided", False) else 0,
                    texture_indices=texture_indices))

            environment = (material_renderer.photo_environment.environment
                if material_renderer.photo_environment.environment is not None
                else material_renderer.environment)
            if environment is None or len(environment.handles) != 3:
                raise RuntimeError("Expected the active renderer environment textures to be initialized")
            global_texture_indices = {
                8: add_texture(environment.handles[0], gl.GL_TEXTURE_CUBE_MAP,
                               gl, texture_records, texture_by_handle),
                9: add_texture(environment.handles[1], gl.GL_TEXTURE_CUBE_MAP,
                               gl, texture_records, texture_by_handle),
                10: add_texture(environment.handles[2], gl.GL_TEXTURE_2D,
                                gl, texture_records, texture_by_handle),
            }
            panorama = int(getattr(material_renderer.photo_environment, "panorama", 0) or 0)
            if panorama:
                global_texture_indices[11] = add_texture(panorama, gl.GL_TEXTURE_2D,
                                                          gl, texture_records, texture_by_handle)
            for material_row in material_rows:
                for unit, texture_index in global_texture_indices.items():
                    material_row["texture_indices"][unit] = texture_index
                # Units 7 and 12 are bound to live shadow resources by the native runtime.
                material_row["texture_indices"][7] = 0xffffffff
                material_row["texture_indices"][12] = 0xffffffff

            mesh_rows = []
            mesh_by_id = {}
            entity_rows = []
            for row in render_rows:
                mesh = row["model"]
                key = id(mesh)
                if key not in mesh_by_id:
                    vertices, indices, bounds = mesh_payload(mesh)
                    mesh_by_id[key] = len(mesh_rows)
                    mesh_rows.append(dict(material_index=material_by_id[id(row["material"])],
                        vertices=vertices, indices=indices, bounds=bounds.reshape(-1)))
                matrix = np.asarray(row["entity"].world_matrix, dtype=np.float64)
                if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
                    raise RuntimeError("Invalid entity world matrix: " + row["stable_id"])
                linear = matrix[:3, :3].astype(np.float32)
                normal = np.asarray(np.linalg.pinv(linear).T, dtype=np.float32)
                flags = (1 if row["photographic_ground"] else 0) | (
                    2 if float(np.linalg.det(linear)) < 0 else 0)
                entity_rows.append(dict(stable_id=row["stable_id"],
                    mesh_index=mesh_by_id[key], flags=flags, world=matrix.reshape(-1),
                    normal=normal.reshape(-1)))

            from mini3d.draw_order import OpaqueOrder
            ranks = OpaqueOrder().ranks_for([row["entity"] for row in render_rows])
            opaque_indices = [index for index, row in enumerate(render_rows)
                if row["material"].get("alphaMode", "OPAQUE") != "BLEND"]
            opaque_indices.sort(key=lambda index: ranks.get(id(render_rows[index]["entity"]), index))
            ground_settings = atmosphere_state(scene)
            write_scene_binary(output / "scene.bin", texture_records,
                material_global_records, sky_global_records, material_rows, mesh_rows,
                entity_rows, opaque_indices, scene, ground_settings["ground_z"], gl)

            frames_writer = BinaryWriter()
            frames_writer.raw(b"SPQRF001")
            frames_writer.u32(len(frame_records))
            for frame in frame_records:
                frames_writer.string(frame["route"])
                frames_writer.f64(frame["t"])
                frames_writer.f64_array(frame["position"])
                frames_writer.f64_array(frame["rotation"])
                frames_writer.f64_array(frame["view"])
                frames_writer.f64_array(frame["projection"])
                frames_writer.f64(frame["near"])
                frames_writer.f64(frame["far"])
            (output / "frames.bin").write_bytes(frames_writer.data)

            shaders = output / "shaders"
            shaders.mkdir(parents=True, exist_ok=True)
            shader_files = {
                "material.vert": VERTEX_SHADER, "material.frag": FRAGMENT_SHADER,
                "sky.vert": SKY_VERTEX, "sky.frag": SKY_FRAGMENT,
                "shadow.vert": DEPTH_VERTEX, "shadow.frag": DEPTH_FRAGMENT,
            }
            for filename, source in shader_files.items():
                with (shaders / filename).open("w", encoding="utf-8", newline="\n") as stream:
                    stream.write(source)
            native_shadow = bundle_dir / "shaders" / "shadow_cascade.glsl"
            if not native_shadow.is_file():
                raise RuntimeError("Missing native stable shadow shader: " + str(native_shadow))
            (shaders / native_shadow.name).write_bytes(native_shadow.read_bytes())

            source_hashes = complete_source_hashes(
                project, bundle_dir, Path(__file__).resolve(), output)
            (output / "sourcehashes.json").write_text(
                json.dumps(source_hashes, indent=2), encoding="utf-8")
            from mini3d.lighting import scene_light_direction
            metadata = {
                "bundle_version": 1,
                "format": "SPQRN001 / SPQRF001",
                "project_root": str(project),
                "build_summary": build_summary,
                "source_hash_manifest": "sourcehashes.json",
                "source_hash_count": len(source_hashes),
                "size": [args.width, args.height],
                "quality": {
                    "arrange_reference": True, "aa_samples": 1,
                    "shadow_resolution": int(scene.shadow_resolution),
                    "shadow_bias": float(scene.shadow_bias),
                    "shadow_pcf": bool(scene.shadow_pcf),
                    "render_mode": scene.render_mode,
                    "lighting_mode": scene.lighting_mode,
                    "tone_mapping": ground_settings["tone_mapping"],
                    "photographic_tone_capture": False,
                    "shadow_reserved_normal_bias": 0.0,
                    "shadow_reserved_strength": 1.0,
                    "shadow_reserved_fields_note":
                        "The source Python shadow shader has no normal-bias or strength term; these protocol fields are neutral reserved values.",
                },
                "counts": {
                    "editable_roots": len(api.list_entities()),
                    "render_primitives": len(render_rows) - 1,
                    "entities_including_photographic_ground": len(entity_rows),
                    "meshes": len(mesh_rows), "materials": len(material_rows),
                    "textures": len(texture_records), "opaque_order": len(opaque_indices),
                    "triangles_per_mesh_sum": int(sum(row["indices"].size // 3 for row in mesh_rows)),
                    "entity_triangles": int(sum(mesh_rows[row["mesh_index"]]["indices"].size // 3
                                                for row in entity_rows)),
                },
                "frames": {
                    "file": "frames.bin",
                    "route_order": list(ROUTES),
                    "per_route": FRAMES_PER_ROUTE,
                    "warmup_frames": WARMUP_FRAMES,
                    "measured_frames": MEASURED_FRAMES,
                    "normalized_t": "warmup uses t=0; measured frames cover [0,1] inclusive",
                    "dynamic_uniforms_by_program": DYNAMIC_UNIFORMS,
                    "native_dynamic_work": [
                        "fit shadow matrix each frame",
                        "update camera-following ground world transform",
                        "frustum culling and draw membership",
                    ],
                },
                "captures": captured,
                "capture_frame_map": CAPTURES,
                "lighting": {
                    "direction_surface_to_light":
                        np.asarray(scene_light_direction(scene), dtype=float).tolist(),
                    "diffuse": float(scene.diffuse),
                    "ambient": float(scene.ambient),
                    "shadows_enabled": bool(scene.shadows_enabled),
                    "ground_z": float(ground_settings["ground_z"]),
                },
                "uniforms": {
                    "material_globals": [record["name"] for record in material_global_records],
                    "sky_globals": [record["name"] for record in sky_global_records],
                    "per_material": sorted(PER_MATERIAL),
                    "texture_units": {
                        "0-6": "material textures", "7": "runtime shadow depth",
                        "8": "diffuse environment cubemap", "9": "specular environment cubemap",
                        "10": "BRDF LUT", "11": "optional HDR panorama",
                        "12": "runtime raw shadow depth",
                    },
                },
                "limitations": [
                    "Only the bundled Pompeii scene and reflected Mini3D material features are exported.",
                    "The ground world matrix starts at walk-0; native updates this flagged entity for each camera frame.",
                    "Reference images are Arrange-style renders, not the photographic capture workflow.",
                ],
            }
            (output / "metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8")
            print(json.dumps({"output": str(output), "counts": metadata["counts"],
                              "captures": sorted(captured),
                              "benchmark": benchmark_enabled}, indent=2), flush=True)
        finally:
            if target is not None:
                target.close()
            if renderer is not None:
                renderer.close()


if __name__ == "__main__":
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1, user_api="blas"):
        main()
