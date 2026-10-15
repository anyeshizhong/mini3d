"""Small value-checked caches for mutable entity transforms and local bounds.

No command dirty flags: public arrays, imported parents and undo may all change
values in place. Entries live on their entity, so removed scenes are collectible.
Mesh payloads retain the existing immutable GPU-resource contract.
"""
from itertools import product

import numpy as np

_SIGNS = np.array(list(product((-1., 1.), repeat=3)))


def box_geometry(entity):
    """Return (bounds, world, world corners, world AABB), or None.

    Use exact endpoint corners for navigation; shadow fitting keeps its own
    centered-corner convention to preserve its numerical tolerances.
    """
    mesh = entity.model
    bound = getattr(mesh, 'bounds', None)
    if bound is None:
        return None
    bounds = np.asarray(bound, np.float64)
    world = np.asarray(entity.world_matrix, np.float64)
    key = (id(mesh), bounds.shape, bounds.tobytes(), world.shape, world.tobytes())
    cached = getattr(entity, '_box_geometry_cache', None)
    if cached is not None and cached[0] == key:
        return cached[1]
    if (bounds.shape != (2, 3) or world.shape != (4, 4)
            or not np.isfinite(bounds).all() or not np.isfinite(world).all()
            or np.any(bounds[0] > bounds[1])
            or not np.array_equal(world[3], [0, 0, 0, 1])):
        result = None
    else:
        bounds, world = bounds.copy(), world.copy()
        corners = np.where(_SIGNS < 0, bounds[0], bounds[1])
        with np.errstate(over='ignore', invalid='ignore'):
            points = corners @ world[:3, :3].T + world[:3, 3]
            center = world[:3, :3] @ (bounds[0] * .5 + bounds[1] * .5) + world[:3, 3]
            radius = np.abs(world[:3, :3]) @ (bounds[1] * .5 - bounds[0] * .5)
            aabb = np.stack((center - radius, center + radius))
        result = (bounds, world, points, aabb) if np.isfinite(aabb).all() else None
    entity._box_geometry_cache = (key, result)
    return result


def normal_transform(matrix, cache):
    """Persistent, bounded cache of pseudoinverse normals and mirrored winding."""
    linear = np.asarray(matrix, np.float32)[:3, :3]
    key = linear.tobytes()
    result = cache.get(key)
    if result is None:
        result = (np.asarray(np.linalg.pinv(linear).T, np.float32),
                  bool(np.linalg.det(linear) < 0))
        if len(cache) >= 256:
            cache.clear()
        cache[key] = result
    return result
