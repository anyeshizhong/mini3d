"""World-space directional-light convention shared by both GL render paths.

Mini3D light_dir points FROM the surface TO the light (the opposite of a
KHR_lights_punctual node's emission direction). No camera transform is involved.
Independent adaptation; research/source notes: docs/directional-light.md.
"""
import numpy as np


def scene_light_direction(scene):
    direction = np.asarray(scene.light_dir, dtype=np.float64)
    if direction.shape != (3,) or not np.isfinite(direction).all():
        raise ValueError('light_dir must contain three finite values')
    scale = np.max(np.abs(direction))
    if scale == 0:
        raise ValueError('light_dir must be nonzero')
    direction = direction / scale
    return np.asarray(direction / np.linalg.norm(direction), dtype=np.float32)
