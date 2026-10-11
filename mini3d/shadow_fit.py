"""Conservative Shot Camera receivers plus all directional casters.

Intersect convex boxes by retaining enclosed corners and edge/face crossings
from both polyhedra. This includes the cases missed by corner-only fitting.
No mesh scan, depth readback, occlusion assumptions or GPU caster culling.
"""
from itertools import product
import numpy as np

_SIGNS = np.array(list(product((-1., 1.), repeat=3)))
_EDGES = np.array([(a,b) for a in range(8) for b in range(a+1,8)
                   if np.count_nonzero(_SIGNS[a] != _SIGNS[b]) == 1])


def _corners(bounds):
    lo, hi = np.asarray(bounds, dtype=float)
    return (lo+hi)*.5 + _SIGNS*(hi-lo)*.5


def _planes(lo, hi):
    return np.concatenate((np.column_stack((np.eye(3), -lo)),
                           np.column_stack((-np.eye(3), hi))))


def _crossings(corners, planes):
    starts = corners[_EDGES[:,0]]
    deltas = corners[_EDGES[:,1]]-starts
    distances = starts @ planes[:,:3].T + planes[:,3]
    denominator = deltas @ planes[:,:3].T
    t = np.divide(-distances, denominator, out=np.full_like(distances, np.nan),
                  where=np.abs(denominator)>1e-15)
    edge, plane = np.where(np.isfinite(t) & (t >= -1e-10) & (t <= 1+1e-10))
    return starts[edge] + t[edge,plane,None]*deltas[edge]


def _intersection(bounds, world, planes, clip_corners):
    """World vertices of local AABB intersected with a convex hexahedron."""
    corners = _corners(bounds)
    local_planes = planes @ world
    norm = np.linalg.norm(local_planes[:,:3],axis=1)
    if np.any(norm == 0):
        raise ValueError('Degenerate clipping planes')
    local_planes /= norm[:,None]
    tol = max(float(np.max(np.abs(corners)))*1e-9,1e-12)
    distances = corners @ local_planes[:,:3].T + local_planes[:,3]
    if np.all(distances >= -tol):
        return corners @ world[:3,:3].T + world[:3,3]
    if np.any(np.max(distances,axis=0) < -tol):
        return np.empty((0,3))
    inverse = np.linalg.inv(world)
    clip_local = clip_corners @ inverse[:3,:3].T + inverse[:3,3]
    box_planes = _planes(*np.asarray(bounds,dtype=float))
    candidates = np.concatenate((corners,clip_local,_crossings(corners,local_planes),
                                 _crossings(clip_local,box_planes)))
    inside = ((candidates @ local_planes[:,:3].T + local_planes[:,3] >= -tol).all(axis=1) &
              (candidates @ box_planes[:,:3].T + box_planes[:,3] >= -tol).all(axis=1))
    points = candidates[inside]
    return points @ world[:3,:3].T + world[:3,3]


def _intersections(bounds, worlds, corners, world_corners, tolerances, planes, clip_corners):
    """Batch the unchanged corner/plane early-outs; exact clipping for partials.

    Prepared geometry belongs to this fit only. It is rebuilt from current
    bounds/world matrix values, so in-place changes need no dirty flags or IDs.
    Both receiver and caster classification use the same local corners and
    world corners; the camera-visible set never replaces the caster set.
    """
    local_planes = planes @ worlds
    norms = np.linalg.norm(local_planes[:, :, :3], axis=2)
    if np.any(norms == 0):
        raise ValueError('Degenerate clipping planes')
    local_planes /= norms[:, :, None]
    distances = corners @ local_planes[:, :, :3].transpose(0, 2, 1) + local_planes[:, None, :, 3]
    contained = np.all(distances >= -tolerances[:, None, None], axis=(1, 2))
    rejected = np.any(np.max(distances, axis=1) < -tolerances[:, None], axis=1)
    result = []
    for i in range(len(bounds)):
        if contained[i]:
            result.append(world_corners[i])
        elif not rejected[i]:
            result.append(_intersection(bounds[i], worlds[i], planes, clip_corners))
    return result


def receiver_matrix(entities, direction, camera, resolution):
    """Return a conservative fit or None, signaling whole-scene fallback.

    Directional rays keep light-space XY constant. Bounds clipped to a padded
    receiver XY prism therefore include every caster capable of reaching an
    in-frame receiver, including off-camera geometry. Their clipped Z extrema
    bound the entire depth path without inflating XY with unrelated background.
    """
    try:
        light = np.asarray(direction,dtype=float).copy()
        light /= np.max(np.abs(light))
        light /= np.linalg.norm(light)
        up = np.eye(3)[np.argmin(np.abs(light))]
        right = np.cross(up,light)
        right /= np.linalg.norm(right)
        rotation = np.stack((right,np.cross(light,right),light))
        vp = camera.projection_matrix(camera.aspect) @ camera.view_matrix
        planes = np.array([vp[3]+sign*vp[axis] for axis in range(3) for sign in (1,-1)])
        homogeneous = np.column_stack((_SIGNS,np.ones(8))) @ np.linalg.inv(vp).T
        frustum = homogeneous[:,:3]/homogeneous[:,3,None]
        boxes = []
        for entity in entities:
            bounds = getattr(entity.model,'bounds',None)
            if bounds is None:
                continue
            world = np.asarray(entity.world_matrix,dtype=float)
            boxes.append((bounds,world))
        if not boxes:
            return None
        bounds = np.asarray([box[0] for box in boxes], dtype=float)
        worlds = np.asarray([box[1] for box in boxes], dtype=float)
        lo_local, hi_local = bounds[:, 0], bounds[:, 1]
        corners = ((lo_local + hi_local)[:, None, :] * .5 +
                   _SIGNS * (hi_local - lo_local)[:, None, :] * .5)
        world_corners = corners @ worlds[:, :3, :3].transpose(0, 2, 1) + worlds[:, None, :3, 3]
        tolerances = np.maximum(np.max(np.abs(corners), axis=(1, 2)) * 1e-9, 1e-12)
        receivers = [points @ rotation.T for points in
                     _intersections(bounds, worlds, corners, world_corners, tolerances, planes, frustum)
                     if len(points)]
        if not receivers:
            return None
        points = np.concatenate(receivers)
        lo,hi = points.min(axis=0),points.max(axis=0)
        extent = hi-lo
        # More than a PCF kernel of padding, including numerical boundaries.
        margin = max(float(extent[:2].max())*max(.02,4/resolution),1e-12)
        lo[:2] -= margin
        hi[:2] += margin
        global_points = np.concatenate(world_corners @ rotation.T)
        lo[2],hi[2] = global_points[:,2].min()-margin,global_points[:,2].max()+margin
        clip_corners = _corners((lo,hi)) @ rotation
        light_planes = _planes(lo,hi)
        light_planes[:,:3] = light_planes[:,:3] @ rotation
        casters = _intersections(bounds, worlds, corners, world_corners, tolerances, light_planes, clip_corners)
        caster_points = np.concatenate([p for p in casters if len(p)]) @ rotation.T
        lo[2],hi[2] = caster_points[:,2].min(),caster_points[:,2].max()
        depth_margin = max(float((hi-lo).max())*.02,1e-12)
        lo[2] -= depth_margin
        hi[2] += depth_margin
        scale = 2/(hi-lo)
        scale[2] *= -1
        matrix = np.eye(4)
        matrix[:3,:3] = scale[:,None]*rotation
        matrix[:3,3] = -scale*(lo+hi)*.5
        return matrix if np.isfinite(matrix).all() else None
    except (ValueError, np.linalg.LinAlgError, FloatingPointError, OverflowError):
        return None
