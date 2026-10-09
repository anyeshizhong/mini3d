"""World-space directional-light convention shared by both GL render paths.

Mini3D light_dir points FROM the surface TO the light (the opposite of a
KHR_lights_punctual node's emission direction). No camera transform is involved.
Independent adaptation; research/source notes: docs/directional-light.md.
"""
from numbers import Real

import numpy as np


def _direction(value):
    try:
        values = list(value)
        if len(values) != 3 or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Real)
                                   for v in values):
            raise ValueError
        direction = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('direction must contain three finite numbers') from exc
    if not np.isfinite(direction).all():
        raise ValueError('direction must contain three finite numbers')
    if np.max(np.abs(direction)) == 0:
        raise ValueError('direction must be nonzero')
    return direction


def lighting_state(scene):
    """Independent JSON-safe snapshot; preserve the user's unnormalized vector."""
    return dict(mode=scene.lighting_mode, direction=np.asarray(scene.light_dir).tolist(),
                diffuse=float(scene.diffuse), ambient=float(scene.ambient))


def update_lighting(scene, mode=None, direction=None, diffuse=None, ambient=None):
    """Validate a complete candidate before publishing any of its parameters."""
    candidate = lighting_state(scene)
    for name, value in (('mode', mode), ('direction', direction),
                        ('diffuse', diffuse), ('ambient', ambient)):
        if value is not None:
            candidate[name] = value
    if not isinstance(candidate['mode'], str) or candidate['mode'] not in ('Studio', 'Scene'):
        raise ValueError('mode must be Studio or Scene')
    vector = _direction(candidate['direction'])
    for name in ('diffuse', 'ambient'):
        value = candidate[name]
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ValueError(name + ' must be a finite nonnegative number')
        try:
            value = float(value)
        except (ValueError, OverflowError) as exc:
            raise ValueError(name + ' must be a finite nonnegative number') from exc
        if not np.isfinite(value) or value < 0:
            raise ValueError(name + ' must be a finite nonnegative number')
        candidate[name] = value
    scene.lighting_mode, scene.light_dir = candidate['mode'], vector
    scene.diffuse, scene.ambient = candidate['diffuse'], candidate['ambient']
    return lighting_state(scene)


def scene_light_direction(scene):
    direction = _direction(scene.light_dir)
    scale = np.max(np.abs(direction))
    direction = direction / scale
    return np.asarray(direction / np.linalg.norm(direction), dtype=np.float32)


def shadow_state(scene):
    return dict(enabled=scene.shadows_enabled, resolution=scene.shadow_resolution,
                bias=scene.shadow_bias, pcf=scene.shadow_pcf)


def update_shadows(scene, enabled=None, resolution=None, bias=None, pcf=None):
    """Validate atomically. Bias is measured in normalized shadow depth units."""
    candidate = shadow_state(scene)
    for name, value in (('enabled', enabled), ('resolution', resolution), ('bias', bias), ('pcf', pcf)):
        if value is not None:
            candidate[name] = value
    for key in ('enabled','pcf'):
        if not isinstance(candidate[key], bool):
            raise ValueError(key + ' must be boolean')
    size = candidate['resolution']
    if isinstance(size, bool) or not isinstance(size, int) or size not in (256,512,1024,2048,4096):
        raise ValueError('resolution must be 256, 512, 1024, 2048 or 4096')
    value = candidate['bias']
    if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value) or not 0 <= value <= .05:
        raise ValueError('bias must be finite and between 0 and 0.05')
    candidate['bias'] = float(value)
    scene.shadows_enabled, scene.shadow_resolution = candidate['enabled'], size
    scene.shadow_bias, scene.shadow_pcf = candidate['bias'], candidate['pcf']
    return shadow_state(scene)
