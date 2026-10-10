"""Per-frame draw preparation. Color visibility never filters shadow candidates.

Matrices act on column vectors; OpenGL clip depth is [-w, w]. Bounds and
transforms are read anew after Scene.update: no persistent cache to invalidate.
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


@dataclass
class DrawItem:
    entity: object
    model: object
    world_matrix: np.ndarray
    material: object
    bounds: object

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


def build_render_plan(scene, camera, width, height, culling=True, legacy_mode='REALISTIC'):
    started = perf_counter()
    entities = scene.get_flat_render_list()
    view = np.asarray(camera.view_matrix, np.float32)
    projection = np.asarray(camera.projection_matrix(float(width) / height), np.float32)
    items, boxes, tested = [], [], []
    for entity in entities:
        mesh = entity.model
        matrix = np.asarray(entity.world_matrix, np.float32)
        material = getattr(mesh, 'material', None)
        bounds = world_bounds(mesh, matrix) if culling else None
        item = DrawItem(entity, mesh, matrix, material, bounds)
        items.append(item)
        # The legacy outline shader expands geometry by 0.15 in model space;
        # axes can extend beyond the mesh. Retain these editor helper cases.
        if bounds is not None and not item.isaxes and not (material is None and legacy_mode == 'OUTLINE'):
            tested.append(len(items) - 1)
            boxes.append(bounds)
    visible = np.ones(len(items), dtype=bool)
    if boxes:
        visible[tested] = aabb_visible(boxes, frustum_planes(view, projection))
    color = [item for item, keep in zip(items, visible) if keep]
    legacy = [item for item in color if item.material is None]
    imported = [item for item in color if item.material is not None]
    transparent = [item for item in imported if item.material.get('alphaMode') == 'BLEND']
    opaque = [item for item in color if item.material is None or item.material.get('alphaMode') != 'BLEND']
    stats = dict(entities_before=len(items), entities_after=len(color),
                 entities_culled=len(items) - len(color), bounds_tested=len(tested),
                 shadow_candidates=len(entities), opaque_entities=len(opaque),
                 transparent_entities=len(transparent), color_draw_calls=0,
                 shadow_draw_calls=0, color_triangles=0, shadow_triangles=0,
                 render_plan_cpu_ms=(perf_counter() - started) * 1000)
    return RenderPlan(entities, legacy, imported, opaque, transparent, view, projection, stats)
