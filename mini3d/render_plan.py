"""Per-frame draw preparation. Color visibility never filters shadow candidates.

Matrices act on column vectors; OpenGL clip depth is [-w, w]. Bounds and
transforms are value-checked after Scene.update, including in-place edits.
GPU uploads remain lazy in the existing renderer mesh/texture caches.
"""
from dataclasses import dataclass
from time import perf_counter

import numpy as np


def frustum_planes(view, projection):
    clip = np.asarray(projection, np.float64) @ np.asarray(view, np.float64)
    return np.array([clip[3] + clip[i] * sign
                     for i in range(3) for sign in (1, -1)])


def aabb_visible(bounds, planes):
    """Batch conservative six-plane test; touching/invalid boxes stay visible.

    This is a rejection test, not an exact polyhedron intersection. A box
    enclosing the frustum is retained even if all its corners are outside.
    Unnormalized planes avoid amplifying nearly degenerate far-plane errors.
    """
    boxes = np.asarray(bounds, np.float64).reshape(-1, 2, 3)
    planes = np.asarray(planes, np.float64)
    if planes.shape != (6, 4) or not np.all(np.isfinite(planes)):
        return np.ones(len(boxes), dtype=bool)
    lo, hi = boxes[:, 0], boxes[:, 1]
    center = lo * .5 + hi * .5
    radius = hi * .5 - lo * .5
    support = center @ planes[:, :3].T + radius @ np.abs(planes[:, :3]).T + planes[:, 3]
    # Float32 GPU matrix/vertex arithmetic, including large-world cancellation.
    tolerance = 1e-5 * (np.maximum(np.abs(lo), np.abs(hi)) @
                       np.abs(planes[:, :3]).T + np.abs(planes[:, 3]) + 1)
    valid = np.all(np.isfinite(boxes), axis=(1, 2)) & np.all(lo <= hi, axis=1)
    return ~valid | np.all(support >= -tolerance, axis=1)


def world_bounds(mesh, matrix):
    bounds = getattr(mesh, 'bounds', None)
    if bounds is None:
        return None
    bounds = np.asarray(bounds, np.float64)
    world = np.asarray(matrix, np.float64)
    if (bounds.shape != (2, 3) or world.shape != (4, 4)
            or not np.all(np.isfinite(bounds)) or not np.all(np.isfinite(world))
            or np.any(bounds[0] > bounds[1])
            or not np.array_equal(world[3], [0, 0, 0, 1])):
        return None  # Unsupported/projective transform: never guess a bound.
    center = world[:3, :3] @ (bounds[0] * .5 + bounds[1] * .5) + world[:3, 3]
    radius = np.abs(world[:3, :3]) @ (bounds[1] * .5 - bounds[0] * .5)
    return np.stack((center - radius, center + radius))


def batch_world_bounds(entities):
    """Reuse value-checked affine AABBs; invalid bounds stay uncullable."""
    from .geometry_cache import box_geometry
    return [None if geometry is None else geometry[3]
            for geometry in (box_geometry(entity) for entity in entities)]



@dataclass
class DrawItem:
    entity: object
    model: object
    world_matrix: np.ndarray
    material: object
    bounds: object
    prepared: object = None

    @property
    def isaxes(self):
        return getattr(self.entity, 'isaxes', False)


@dataclass
class RenderPlan:
    # Separate purposes: shadow fitting needs all receivers and offscreen casters.
    shadow_candidates: list
    legacy: list
    imported: list
    opaque: list
    transparent: list
    view: np.ndarray
    projection: np.ndarray
    stats: dict
    geometry: object = None


def _inputs(geometry):
    """View-independent culling arrays, shared until a scene edit occurs."""
    cached = geometry._plan_inputs
    if cached is not None:
        return cached
    if getattr(geometry, 'base', None) is not None:
        left, right = _inputs(geometry.base), _inputs(geometry.extra)
        cached = tuple(np.concatenate((a, b), axis=0) for a, b in zip(left, right))
    else:
        boxes = np.zeros((len(geometry.entities), 2, 3), np.float64)
        eligible = np.zeros(len(boxes), bool)
        outlined = np.zeros(len(boxes), bool)
        for index, (entity, bound) in enumerate(zip(geometry.entities, geometry.bounds)):
            if bound is not None:
                boxes[index] = bound
                eligible[index] = not getattr(entity, 'isaxes', False)
            outlined[index] = getattr(entity.model, 'material', None) is None
        cached = boxes, eligible, outlined
    geometry._plan_inputs = cached
    return cached


def _draw_item(entity, record, bound):
    item = record.get('draw_item')
    if item is None:
        item = record['draw_item'] = DrawItem(entity, entity.model, record['matrix'],
            getattr(entity.model, 'material', None), bound, record)
    return item


def build_render_plan(scene, camera, width, height, culling=True, legacy_mode='REALISTIC'):
    started = perf_counter()
    from .scene_snapshot import snapshot
    geometry = snapshot(scene)
    entities = geometry.entities
    view = np.asarray(camera.view_matrix, np.float32)
    projection = np.asarray(camera.projection_matrix(float(width) / height), np.float32)
    prepared_bounds = geometry.bounds if culling else [None] * len(entities)
    if culling:
        all_boxes, eligible, outlined = _inputs(geometry)
        tested = np.flatnonzero(eligible & ~outlined if legacy_mode == 'OUTLINE' else eligible)
        boxes = all_boxes[tested]
    else:
        tested = np.empty(0, dtype=int)
        boxes = np.empty((0, 2, 3))
    visible = np.ones(len(entities), dtype=bool)
    if len(boxes):
        planes = frustum_planes(view, projection)
        if len(boxes) >= 512 and getattr(scene, 'spatial_culling_enabled', False):
            from .spatial_index import SpatialIndex
            index = getattr(scene, '_color_spatial_index', None)
            if index is None:
                index = scene._color_spatial_index = SpatialIndex()
            index.update(boxes)
            candidates = index.query(planes)
            keep = np.zeros(len(boxes), dtype=bool)
            if len(candidates):
                keep[candidates] = aabb_visible(np.asarray(boxes)[candidates], planes)
            visible[tested] = keep
        else:
            visible[tested] = aabb_visible(boxes, planes)
    # Prepare draw records only after coarse/fine culling, keeping scene order.
    color = [_draw_item(entities[i], geometry.records[id(entities[i])], prepared_bounds[i])
             for i in np.flatnonzero(visible)]
    legacy = [item for item in color if item.material is None]
    imported = [item for item in color if item.material is not None]
    transparent = [item for item in imported if item.material.get('alphaMode') == 'BLEND']
    opaque = [item for item in color if item.material is None or item.material.get('alphaMode') != 'BLEND']
    stats = dict(entities_before=len(entities), entities_after=len(color),
                 entities_culled=len(entities) - len(color), bounds_tested=len(tested),
                 shadow_candidates=len(entities), opaque_entities=len(opaque),
                 transparent_entities=len(transparent), color_draw_calls=0,
                 shadow_draw_calls=0, color_triangles=0, shadow_triangles=0,
                 render_plan_cpu_ms=(perf_counter() - started) * 1000)
    return RenderPlan(entities, legacy, imported, opaque, transparent, view, projection, stats,geometry)
