"""Export the live Shot Camera scene to the native renderer's bundle format.

This module deliberately borrows the application's current OpenGL context. It
never creates a window or renders a frame. Bundle creation reads the textures
already owned by the existing GL renderers; global-only refreshes do not read
texture data back from the GPU.
"""
from __future__ import annotations

from functools import lru_cache
import importlib.util
from pathlib import Path

import numpy as np
from OpenGL import GL as gl


class UnsupportedNativeScene(RuntimeError):
    """The live scene uses an asset/material shape the native format cannot encode."""


@lru_cache(maxsize=1)
def _export_helpers():
    path = Path(__file__).resolve().parents[1] / "native" / "export_scene.py"
    if not path.is_file():
        raise RuntimeError("Missing native export helper: " + str(path))
    spec = importlib.util.spec_from_file_location("_mini3d_native_export_scene", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load native export helper: " + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_photo_scene(scene, camera, renderer):
    from .atmosphere import atmosphere_state, prepare_photographic_scene

    photo_scene, candidate = prepare_photographic_scene(
        scene, camera, getattr(renderer, "_photo_ground", None))
    state = atmosphere_state(photo_scene)
    ground = candidate if state["ground"] else None
    if ground is not None:
        renderer._photo_ground = ground
    return photo_scene, ground, state


def _ensure_renderers(renderer):
    material_renderer = getattr(renderer, "material_renderer", None)
    if material_renderer is None:
        from .material_renderer import MaterialRenderer
        material_renderer = MaterialRenderer()
        renderer.material_renderer = material_renderer
    sky_renderer = getattr(renderer, "sky_renderer", None)
    if sky_renderer is None:
        from .sky_renderer import SkyRenderer
        sky_renderer = SkyRenderer()
        renderer.sky_renderer = sky_renderer
    return material_renderer, sky_renderer


def _uniform_location(program, name, required=False):
    location = int(gl.glGetUniformLocation(program, name))
    if location < 0 and required:
        raise RuntimeError("Expected live shader uniform was not found: " + name)
    return location


def _set_material_shadow_globals(program, scene, atmosphere):
    """Initialize the non-camera shadow controls without binding/drawing a map."""
    from .shadow_map import ShadowMap

    values = (
        ("shadowEnabled", lambda loc: gl.glUniform1i(loc, 0), False),
        ("shadowDepth", lambda loc: gl.glUniform1i(loc, ShadowMap.UNIT), True),
        ("shadowRaw", lambda loc: gl.glUniform1i(loc, 12), True),
        ("shadowPCF", lambda loc: gl.glUniform1i(loc, int(scene.shadow_pcf)), True),
        ("shadowBias", lambda loc: gl.glUniform1f(loc, float(scene.shadow_bias)), True),
        ("sunRadius", lambda loc: gl.glUniform1f(
            loc, float(np.tan(np.radians(float(atmosphere["sun_size"]) * 0.5)))), True),
    )
    for name, setter, required in values:
        location = _uniform_location(program, name, required=required)
        if location >= 0:
            setter(location)


def _collect_globals_prepared(scene, camera, renderer, atmosphere):
    from .atmosphere import sun_color
    from .lighting import scene_light_direction
    from .sky_renderer import bind_photo_sky

    helpers = _export_helpers()
    material_renderer, sky_renderer = _ensure_renderers(renderer)

    gl.glUseProgram(material_renderer.program)
    material_renderer._lighting(scene, camera)
    bind_photo_sky(material_renderer.program, scene,
                   material_renderer.photo_environment, lighting=True)
    _set_material_shadow_globals(material_renderer.program, scene, atmosphere)
    material_records = helpers.reflect_program(material_renderer.program, gl)

    gl.glUseProgram(sky_renderer.program)
    bind_photo_sky(sky_renderer.program, scene, sky_renderer.environment)
    location = _uniform_location(sky_renderer.program, "sunDirection", required=True)
    gl.glUniform3fv(location, 1, np.asarray(scene_light_direction(scene), dtype=np.float32))
    location = _uniform_location(sky_renderer.program, "sunColor", required=True)
    gl.glUniform3fv(location, 1, np.asarray(sun_color(atmosphere["sun_temperature"]),
                                           dtype=np.float32))
    location = _uniform_location(sky_renderer.program, "exposureEV", required=True)
    gl.glUniform1f(location, float(atmosphere["exposure_ev"]))
    sky_records = helpers.reflect_program(sky_renderer.program, gl)

    per_material = helpers.PER_MATERIAL
    dynamic = helpers.DYNAMIC_UNIFORMS
    material_globals = [
        record for record in material_records
        if record["name"] not in per_material
        and record["name"] not in dynamic["material"]
        and not helpers.is_sampler(record, gl)
    ]
    sky_globals = [
        record for record in sky_records
        if record["name"] not in dynamic["sky"]
        and not helpers.is_sampler(record, gl)
    ]

    material_names = {record["name"] for record in material_globals}
    required_material = {
        "sceneLighting", "light0", "lightIntensity", "ambientIntensity",
        "atmosphereEnabled", "sunDirection", "sunColor", "shadowPCF",
        "shadowBias", "sunRadius",
    }
    missing = required_material - material_names
    if missing:
        raise RuntimeError("Required material globals were not reflected: " +
                           ", ".join(sorted(missing)))
    sky_names = {record["name"] for record in sky_globals}
    missing = {"sunDirection", "sunColor", "exposureEV"} - sky_names
    if missing:
        raise RuntimeError("Required sky globals were not reflected: " +
                           ", ".join(sorted(missing)))
    return material_globals, sky_globals


def collect_live_globals(scene, camera, renderer):
    """Return reflected non-dynamic material and sky uniform records.

    The caller may pack these records with pack_globals after a low-frequency
    exposure, white-balance, sun, or lighting change. This path does not read
    back textures or render either shader.
    """
    photo_scene, _ground, atmosphere = _prepare_photo_scene(scene, camera, renderer)
    return _collect_globals_prepared(photo_scene, camera, renderer, atmosphere)


def pack_globals(material_records, sky_records):
    """Pack two consecutive protocol UniformBlocks and return their bytes."""
    helpers = _export_helpers()
    writer = helpers.BinaryWriter()
    helpers.write_uniform_block(writer, material_records)
    helpers.write_uniform_block(writer, sky_records)
    return bytes(writer.data)


def _flatten_or_raise(helpers, scene, ground):
    try:
        rows = helpers.flatten_scene(scene, ground)
    except RuntimeError as exc:
        message = str(exc)
        unsupported_prefixes = (
            "Unsupported legacy material entity:",
            "Legacy/non-dictionary material is unsupported:",
            "Unsupported material extensions on ",
            "Unsupported alphaMode on ",
            "Unsupported texture slots on ",
            "Malformed ",
            "Only TEXCOORD_0 is supported ",
            "Texture extensions are unsupported ",
        )
        if message.startswith(unsupported_prefixes):
            raise UnsupportedNativeScene(message) from exc
        raise
    if not rows:
        raise UnsupportedNativeScene(
            "Native scene export requires at least one visible mesh with a supported material")
    return rows


def _material_rows(render_rows, material_renderer, scene, helpers, texture_records,
                   texture_by_handle, gl_module):
    materials = []
    material_by_id = {}
    for row in render_rows:
        material = row["material"]
        key = id(material)
        if key not in material_by_id:
            material_by_id[key] = len(materials)
            materials.append(material)

    slots = ("baseColor", "metallicRoughness", "normal", "occlusion",
             "emissive", "specular", "specularColor")
    rows = []
    for material in materials:
        parameters = helpers.set_material_uniforms(
            material_renderer, material, scene.render_mode, gl_module)
        texture_indices = [0xffffffff] * 13
        for unit, slot in enumerate(slots):
            texture = material.get("textures", {}).get(slot)
            if texture is not None:
                handle = material_renderer._texture(texture)
                texture_indices[unit] = helpers.add_texture(
                    handle, gl_module.GL_TEXTURE_2D, gl_module,
                    texture_records, texture_by_handle)
        rows.append({
            "parameters": parameters,
            "flags": 1 if material.get("doubleSided", False) else 0,
            "texture_indices": texture_indices,
        })
    return materials, material_by_id, rows


def _global_texture_indices(scene, material_renderer, helpers, texture_records,
                            texture_by_handle, gl_module):
    from .atmosphere import PROCEDURAL_SKIES, atmosphere_state

    atmosphere = atmosphere_state(scene)
    photo_hdr = (atmosphere["enabled"]
                 and atmosphere["sky_texture"] not in PROCEDURAL_SKIES)
    result = {}
    environment = (material_renderer.photo_environment.environment
                   if photo_hdr else material_renderer.environment)
    if environment is not None:
        handles = list(getattr(environment, "handles", ()))
        if len(handles) != 3:
            raise RuntimeError("Initialized environment must own diffuse/specular/LUT textures")
        result[8] = helpers.add_texture(handles[0], gl_module.GL_TEXTURE_CUBE_MAP,
                                        gl_module, texture_records, texture_by_handle)
        result[9] = helpers.add_texture(handles[1], gl_module.GL_TEXTURE_CUBE_MAP,
                                        gl_module, texture_records, texture_by_handle)
        result[10] = helpers.add_texture(handles[2], gl_module.GL_TEXTURE_2D,
                                         gl_module, texture_records, texture_by_handle)
    if photo_hdr:
        panorama = int(getattr(material_renderer.photo_environment, "panorama", 0) or 0)
        if not panorama:
            raise RuntimeError("HDR atmosphere is enabled but its panorama texture is missing")
        result[11] = helpers.add_texture(panorama, gl_module.GL_TEXTURE_2D,
                                         gl_module, texture_records, texture_by_handle)
    return result


def _mesh_entity_rows(render_rows, material_by_id, helpers):
    mesh_rows = []
    mesh_by_id = {}
    entity_rows = []
    for row in render_rows:
        mesh = row["model"]
        mesh_key = id(mesh)
        if mesh_key not in mesh_by_id:
            vertices, indices, bounds = helpers.mesh_payload(mesh)
            mesh_by_id[mesh_key] = len(mesh_rows)
            mesh_rows.append({
                "material_index": material_by_id[id(row["material"])],
                "vertices": vertices,
                "indices": indices,
                "bounds": bounds.reshape(-1),
            })
        matrix = np.asarray(row["entity"].world_matrix, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise RuntimeError("Invalid entity world matrix: " + row["stable_id"])
        linear = matrix[:3, :3].astype(np.float32)
        normal = np.asarray(np.linalg.pinv(linear).T, dtype=np.float32)
        if not np.isfinite(normal).all():
            raise RuntimeError("Invalid entity normal transform: " + row["stable_id"])
        flags = (1 if row["photographic_ground"] else 0) | (
            2 if float(np.linalg.det(linear)) < 0 else 0)
        entity_rows.append({
            "stable_id": row["stable_id"],
            "mesh_index": mesh_by_id[mesh_key],
            "flags": flags,
            "world": matrix.reshape(-1),
            "normal": normal.reshape(-1),
        })
    return mesh_rows, entity_rows


def _write_shaders(output, native_source):
    from .material_shaders import VERTEX_SHADER, FRAGMENT_SHADER, analytic_ground_shader
    from .sky_renderer import VERTEX as SKY_VERTEX, FRAGMENT as SKY_FRAGMENT
    from .shadow_map import DEPTH_VERTEX, DEPTH_FRAGMENT

    native_shadow = Path(native_source).expanduser().resolve() / "shaders" / "shadow_cascade.glsl"
    if not native_shadow.is_file():
        raise FileNotFoundError("Missing native shadow shader: " + str(native_shadow))
    shaders = output / "shaders"
    shaders.mkdir(parents=True, exist_ok=True)
    sources = {
        "material.vert": VERTEX_SHADER,
        "material.frag": FRAGMENT_SHADER,
        "ground.vert": analytic_ground_shader(VERTEX_SHADER),
        "ground.frag": analytic_ground_shader(FRAGMENT_SHADER),
        "sky.vert": SKY_VERTEX,
        "sky.frag": SKY_FRAGMENT,
        "shadow.vert": DEPTH_VERTEX,
        "shadow.frag": DEPTH_FRAGMENT,
    }
    for filename, source in sources.items():
        with (shaders / filename).open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(source)
    (shaders / "shadow_cascade.glsl").write_bytes(native_shadow.read_bytes())
    return shaders


def export_live_bundle(scene, camera, renderer, output: Path,
                       native_source: Path) -> dict:
    """Write the live material scene and shader bundle using the current GL context.

    The scene is traversed in full, including off-camera shadow casters. Meshes
    and materials remain shared by identity, material texture slots occupy
    protocol units 0-6, 8-11 hold available environment resources, and 7/12
    remain for the native runtime's shadow textures.
    """
    helpers = _export_helpers()
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    photo_scene, ground, atmosphere = _prepare_photo_scene(scene, camera, renderer)
    render_rows = _flatten_or_raise(helpers, photo_scene, ground)

    material_renderer, _sky_renderer = _ensure_renderers(renderer)
    material_globals, sky_globals = _collect_globals_prepared(
        photo_scene, camera, renderer, atmosphere)

    texture_records = []
    texture_by_handle = {}
    materials, material_by_id, material_rows = _material_rows(
        render_rows, material_renderer, photo_scene, helpers,
        texture_records, texture_by_handle, gl)
    global_indices = _global_texture_indices(
        photo_scene, material_renderer, helpers,
        texture_records, texture_by_handle, gl)
    for material_row in material_rows:
        for unit, index in global_indices.items():
            material_row["texture_indices"][unit] = index
        # Units 7 and 12 are owned and updated by the native shadow runtime.
        material_row["texture_indices"][7] = 0xffffffff
        material_row["texture_indices"][12] = 0xffffffff

    mesh_rows, entity_rows = _mesh_entity_rows(render_rows, material_by_id, helpers)
    from .draw_order import OpaqueOrder
    entities = [row["entity"] for row in render_rows]
    ranks = OpaqueOrder().ranks_for(entities)
    opaque_indices = [
        index for index, row in enumerate(render_rows)
        if row["material"].get("alphaMode", "OPAQUE") != "BLEND"
    ]
    opaque_indices.sort(key=lambda index: ranks.get(id(entities[index]), index))

    scene_path = output / "scene.bin"
    helpers.write_scene_binary(
        scene_path, texture_records, material_globals, sky_globals,
        material_rows, mesh_rows, entity_rows, opaque_indices,
        photo_scene, atmosphere["ground_z"], gl)
    shaders_dir = _write_shaders(output, native_source)
    ground_id = next((row["stable_id"] for row in render_rows
                      if row["photographic_ground"]), None)
    return {
        "scene_bin": scene_path,
        "shaders_dir": shaders_dir,
        "photo_scene": photo_scene,
        "ground_entity": ground,
        "ground_stable_id": ground_id,
        "ground_z": float(atmosphere["ground_z"]),
        "material_globals": material_globals,
        "sky_globals": sky_globals,
        "counts": {
            "entities": len(entity_rows),
            "meshes": len(mesh_rows),
            "materials": len(material_rows),
            "textures": len(texture_records),
            "opaque_order": len(opaque_indices),
            "ground": ground is not None,
            "atmosphere": bool(atmosphere["enabled"]),
        },
    }
