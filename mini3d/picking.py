"""Viewport projection and exact triangle picking, independent of OpenGL.

Shared mesh geometry is cached weakly. Ray directions transformed to mesh space
are intentionally *not* normalized, preserving world-space distance under scale.
"""
import weakref

import numpy as np


_TRIANGLES = weakref.WeakKeyDictionary()
_CHUNK_SIZE = 2048


def _rect(viewport_rect):
    x, y, width, height = map(float, viewport_rect)
    if not np.isfinite([x, y, width, height]).all() or width <= 0 or height <= 0:
        raise ValueError('Viewport rectangle must have positive finite dimensions')
    return x, y, width, height


def screen_ray(camera, screen_pos, viewport_rect):
    """Return a normalized world ray from a top-left-origin screen position."""
    x, y, width, height = _rect(viewport_rect)
    px, py = screen_pos
    projection = camera.projection_matrix(width / height)
    local = np.array([(2 * (px - x) / width - 1) / projection[0, 0],
                      (1 - 2 * (py - y) / height) / projection[1, 1], -1.0])
    direction = camera.rotation @ local
    direction /= np.linalg.norm(direction)
    return camera.position, direction


def project_point(camera, point, viewport_rect):
    """Project a world point to screen pixels; points behind the eye return None.

    Points outside the viewport can still be projected (useful for clipped
    overlays); this method deliberately does not clamp them to its edges.
    """
    x, y, width, height = _rect(viewport_rect)
    homogeneous = np.append(np.asarray(point, dtype=np.float64), 1.0)
    clip = camera.projection_matrix(width / height) @ camera.view_matrix @ homogeneous
    if not np.isfinite(clip).all() or clip[3] <= 0:
        return None
    ndc = clip[:2] / clip[3]
    return (x + (ndc[0] + 1) * width * .5,
            y + (1 - ndc[1]) * height * .5)


def ground_hit(ray):
    """Intersect a forward ray with the engine's Z=0 ground plane."""
    origin, direction = (np.asarray(vector, dtype=np.float64) for vector in ray)
    if not np.isfinite(origin).all() or not np.isfinite(direction).all() or abs(direction[2]) < 1e-12:
        return None
    distance = -origin[2] / direction[2]
    if distance < 0:
        return None
    point = origin + distance * direction
    point[2] = 0.0
    return point


def _aabb(origin, direction, bounds, lower, upper):
    """Slab intersection, also safe for flat boxes and exactly parallel rays."""
    minimum, maximum = bounds
    for axis in range(3):
        if direction[axis] == 0:
            if origin[axis] < minimum[axis] or origin[axis] > maximum[axis]:
                return None
            continue
        a = (minimum[axis] - origin[axis]) / direction[axis]
        b = (maximum[axis] - origin[axis]) / direction[axis]
        lower = max(lower, min(a, b))
        upper = min(upper, max(a, b))
        if upper < lower:
            return None
    return lower, upper


def _triangle_data(mesh):
    cached = _TRIANGLES.get(mesh)
    if cached is None:
        triangles = np.asarray(mesh.vertices[:, :3], dtype=np.float32)[mesh.indices]
        starts = np.ascontiguousarray(triangles[:, 0])
        edges_one = np.ascontiguousarray(triangles[:, 1] - triangles[:, 0])
        edges_two = np.ascontiguousarray(triangles[:, 2] - triangles[:, 0])
        chunks = []
        for offset in range(0, len(triangles), _CHUNK_SIZE):
            stop = min(offset + _CHUNK_SIZE, len(triangles))
            part = triangles[offset:stop]
            chunks.append((offset, stop, (part.min(axis=(0, 1)), part.max(axis=(0, 1)))))
        cached = (starts, edges_one, edges_two, chunks)
        _TRIANGLES[mesh] = cached
    return cached


def _triangle_hit(mesh, origin, direction, lower, upper):
    starts, edges_one, edges_two, chunks = _triangle_data(mesh)
    closest = None
    for offset, stop, box in chunks:
        if _aabb(origin, direction, box, lower, upper) is None:
            continue
        v0 = starts[offset:stop]
        edge1 = edges_one[offset:stop]
        edge2 = edges_two[offset:stop]
        cross = np.cross(direction, edge2)
        determinant = np.einsum('ij,ij->i', edge1, cross)
        # Relative degeneracy tolerance works for assets at very different units.
        tolerance = 1e-12 * np.linalg.norm(edge1, axis=1) * np.linalg.norm(cross, axis=1)
        valid = np.abs(determinant) > tolerance
        if not valid.any():
            continue
        inverse = np.zeros_like(determinant)
        np.divide(1.0, determinant, out=inverse, where=valid)
        translated = origin - v0
        u = np.einsum('ij,ij->i', translated, cross) * inverse
        valid &= (u >= -1e-9) & (u <= 1 + 1e-9)
        cross_two = np.cross(translated, edge1)
        v = np.einsum('j,ij->i', direction, cross_two) * inverse
        valid &= (v >= -1e-9) & (u + v <= 1 + 1e-9)
        distance = np.einsum('ij,ij->i', edge2, cross_two) * inverse
        valid &= (distance >= lower) & (distance <= upper)
        if valid.any():
            upper = float(distance[valid].min())
            closest = upper
    return closest


def pick_entity(scene, camera, screen_pos, rect):
    """Return (top-level instance, world hit), or (None, None).

    Hidden subtrees and geometry outside the camera clipping range are excluded.
    Geometric triangles are tested on both sides; texture alpha is not sampled.
    """
    x, y, width, height = _rect(rect)
    px, py = screen_pos
    if not (x <= px < x + width and y <= py < y + height):
        return None, None
    scene.update()
    origin, direction = screen_ray(camera, screen_pos, rect)
    depth_per_unit = float(np.dot(direction, camera.forward))
    if depth_per_unit <= 0:
        return None, None
    lower = camera.near / depth_per_unit
    upper = camera.far / depth_per_unit
    candidates = []

    def collect(entity, root):
        if not entity.visible:
            return
        mesh = entity.model
        if mesh is not None and mesh.bounds is not None and len(mesh.indices):
            try:
                inverse = np.linalg.inv(entity.world_matrix)
            except np.linalg.LinAlgError:
                inverse = None
            if inverse is not None:
                local_origin = inverse[:3, :3] @ origin + inverse[:3, 3]
                local_direction = inverse[:3, :3] @ direction
                interval = _aabb(local_origin, local_direction, mesh.bounds, lower, upper)
                if interval is not None:
                    candidates.append((interval[0], root, mesh, local_origin, local_direction))
        for child in entity.children:
            collect(child, root)

    for root in scene.root_entities:
        collect(root, root)
    candidates.sort(key=lambda item: item[0])
    selected = None
    for entry, root, mesh, local_origin, local_direction in candidates:
        if entry > upper:
            break
        distance = _triangle_hit(mesh, local_origin, local_direction, lower, upper)
        if distance is not None:
            selected, upper = root, distance
    return (selected, origin + upper * direction) if selected is not None else (None, None)
