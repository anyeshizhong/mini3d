"""Value-based invalidation of the editor's retained viewport texture.

Only presentation is cached. Scene/history/API remain authoritative and every
UI frame still runs events and IPC. Mesh and encoded image payloads use the
same immutable-resource contract as the existing renderer GPU caches.
"""
import numpy as np


def _value(value):
    if isinstance(value, np.ndarray):
        return (value.shape, value.dtype.str, value.tobytes())
    if isinstance(value, bytes):
        return id(value)
    if isinstance(value, dict):
        return tuple((key, _value(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_value(item) for item in value)
    return value


def viewport_key(app, size, photo_preview, renderer_mode):
    """Call after Scene.update(), so direct NumPy edits also invalidate."""
    scene = app.scene
    camera = app.shot_camera if app.camera_view else app.viewer.camera
    camera_key = (_value(camera.position), _value(camera.rotation),
                  camera.fov_y, camera.near, camera.far)
    shot_key = None if app.shot_camera is None else (
        app.shot_camera.size, app.shot_camera.samples, app.shot_camera.dof_enabled,
        app.shot_camera.focus_distance, app.shot_camera.f_number,
        app.shot_camera.white_balance_kelvin, app.shot_camera.color_preset)
    from .scene_snapshot import snapshot
    geometry = snapshot(scene)
    # One scene-wide value scan happened at the frame boundary. Consumers only
    # compare revisions; camera motion no longer serializes the city again.
    scene_key = (id(geometry), geometry.geometry_revision, geometry.material_revision)
    if getattr(scene, '_frame_geometry', None) is None:
        # Standalone callers retain value equality (including undo to a state).
        scene_key = (geometry.key, geometry._material_key)
    settings = tuple(_value(getattr(scene, name, None)) for name in (
        'light_dir', 'ambient', 'diffuse', 'lighting_mode', 'shadows_enabled',
        'shadow_resolution', 'shadow_bias', 'shadow_pcf', 'environment_enabled',
        'environment_intensity', 'material_light_intensity', 'material_ambient_intensity',
        'render_mode', 'show_grid', 'grid_scale', 'show_axes', '_hide_entity_axes', '_atmosphere'))
    return (tuple(size), app.camera_view, photo_preview, renderer_mode, camera_key, shot_key,
            scene_key, settings,
            None if app.camera_view or app.selection is None else id(app.selection))
