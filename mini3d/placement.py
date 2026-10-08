"""Pure placement geometry shared by editor commands and future clients.

Anchors do not modify imported meshes or pivots. Bounds Bottom is the bottom
centre of the exact world AABB at the requested orientation. It anchors to one
surface hit, not a collision/contact solver for uneven support geometry.
"""
from dataclasses import dataclass

import numpy as np

from .picking import raycast_entities, screen_ray
from .scene import Entity, Mesh, rotation_xyz


@dataclass
class SurfaceHit:
    position: np.ndarray
    normal: np.ndarray
    entity: object = None
    distance: float = None

    def __post_init__(self):
        self.position = _vector(self.position, 'Surface position')
        self.normal = _vector(self.normal, 'Surface normal')
        length = np.linalg.norm(self.normal)
        if length < 1e-12:
            raise ValueError('Surface normal must be nonzero')
        self.normal /= length


def _vector(value, label):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError('{} must contain three finite values'.format(label))
    return result.copy()


def create_ground(size=2000.0):
    """Create a real, ordinary two-triangle Entity (never added implicitly)."""
    size = float(size)
    if not np.isfinite(size) or size <= 0:
        raise ValueError('Ground size must be positive and finite')
    half = size / 2
    mesh = Mesh([[-half, -half, 0], [half, -half, 0], [half, half, 0], [-half, half, 0]],
                [[0, 1, 2], [0, 2, 3]], material={
                    'pbrMetallicRoughness': {'baseColorFactor': [.18, .20, .22, 1],
                                             'metallicFactor': 0.0, 'roughnessFactor': 1.0},
                    'doubleSided': True})
    ground = Entity(mesh, 'Ground')
    ground.update_transform()
    return ground


def raycast_surface(scene, camera, screen_pos, rect, exclude=None, fallback=None):
    """Hit scene Mesh first, then mathematical PlacementPlane, then fallback.

    Locked instances remain placement surfaces. ``exclude`` prevents placing
    an instance on its own geometry when repositioning it.
    """
    hit = raycast_entities(scene.root_entities, camera, screen_pos, rect,
                           include_locked=True, exclude=exclude)
    if hit is not None:
        entity, position, normal, distance = hit
        return SurfaceHit(position, normal, entity, distance)
    plane = getattr(scene, 'placement_plane', None)
    if plane is not None:
        origin, direction = screen_ray(camera, screen_pos, rect)
        intersection = plane.intersect(origin, direction)
        if intersection is not None:
            position, distance = intersection
            return SurfaceHit(position, (0, 0, 1), distance=distance)
    if fallback is not None:
        return SurfaceHit(fallback, (0, 0, 1))
    return None


def geometry_bounds(entity, position=None, rotation=None):
    """Exact complete geometry bounds, including imported hierarchy and scale.

    Computes matrices locally without mutating transforms or their cached world
    matrices. This runs on placement commands, never each render frame.
    """
    minimum, maximum = np.full(3, np.inf), np.full(3, -np.inf)

    def visit(node, parent, root=False):
        transform = np.eye(4)
        rot = node.rot if not root or rotation is None else rotation
        pos = node.pos if not root or position is None else position
        transform[:3, :3] = rotation_xyz(rot) @ np.diag(node.scale)
        transform[:3, 3] = pos
        matrix = parent @ transform @ node.extra_local
        if node.model is not None and len(node.model.vertices):
            points = node.model.vertices[:, :3] @ matrix[:3, :3].T + matrix[:3, 3]
            np.minimum(minimum, points.min(axis=0), out=minimum)
            np.maximum(maximum, points.max(axis=0), out=maximum)
        for child in node.children:
            visit(child, matrix)

    visit(entity, np.eye(4), True)
    return None if not np.isfinite(minimum).all() else (minimum, maximum)


def compute_placement(entity, hit, anchor=None, keep_upright=None, align_normal=False):
    """Return independent (position, Euler rotation) arrays; mutate nothing.

    Upright characters retain world yaw and discard user pitch/roll. Imported
    axis conversion remains inside extra_local. Normal alignment is reserved
    for V2 and rejected explicitly rather than silently approximated.
    """
    if align_normal:
        raise NotImplementedError('Align Normal is not supported by Placement V1')
    anchor = getattr(entity, 'placement_anchor', 'bounds_bottom') if anchor is None else anchor
    if anchor not in ('pivot', 'bounds_bottom'):
        raise ValueError('Unknown placement anchor: {}'.format(anchor))
    if keep_upright is not None and not isinstance(keep_upright, (bool, np.bool_)):
        raise ValueError('Keep upright must be a boolean')
    upright = (getattr(entity, 'keep_upright', False) or
               getattr(entity, 'placement_type', 'prop') == 'character') if keep_upright is None else keep_upright
    rotation = _vector(entity.rot, 'Rotation')
    if upright:
        rotation[:2] = 0
    position = _vector(hit.position, 'Surface position')
    if anchor == 'bounds_bottom':
        bounds = geometry_bounds(entity, position=np.zeros(3), rotation=rotation)
        if bounds is not None:
            minimum, maximum = bounds
            bottom = (minimum + maximum) * .5
            bottom[2] = minimum[2]
            position -= bottom
    return position, rotation
