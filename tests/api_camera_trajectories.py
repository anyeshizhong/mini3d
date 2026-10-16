"""Reusable deterministic camera tracks for public MINI3D AI API tests.

These functions only produce JSON-safe position/target commands. They have no
OpenGL context, renderer, editor, or hidden scene mutation.
"""
import math
import numpy as np


def _point(value, name):
    data = np.asarray(value, dtype=float)
    if data.shape != (3,) or not np.all(np.isfinite(data)):
        raise ValueError('{} must be three finite numbers'.format(name))
    return data


def _frames(count):
    if isinstance(count, bool) or not isinstance(count, int) or count < 2:
        raise ValueError('frames must be an integer >= 2')
    return count


def linear_path(start_position, end_position, start_target, end_target, frames):
    """Inclusive linear motion; a moving target permits a lateral camera track."""
    count = _frames(frames)
    p0 = _point(start_position, 'start_position')
    p1 = _point(end_position, 'end_position')
    q0 = _point(start_target, 'start_target')
    q1 = _point(end_target, 'end_target')
    for u in np.linspace(0.0, 1.0, count):
        yield dict(position=((1 - u) * p0 + u * p1).tolist(),
                   target=((1 - u) * q0 + u * q1).tolist())


def orbit_path(target, radius, height, frames, start_angle=0.0, turns=1.0):
    """An orbit around a fixed look-at point; angles are radians."""
    count = _frames(frames)
    center = _point(target, 'target')
    for name, value in [('radius', radius), ('height', height),
                        ('start_angle', start_angle), ('turns', turns)]:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('{} must be finite'.format(name))
    if radius <= 0:
        raise ValueError('radius must be positive')
    for u in np.linspace(0.0, 1.0, count):
        theta = start_angle + 2 * math.pi * turns * float(u)
        position = center + [radius * math.cos(theta), radius * math.sin(theta), height]
        yield dict(position=position.tolist(), target=center.tolist())
