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


def _receiver_boxes(entities, light):
    """Bound an infinite ground by possible caster footprints, in world space.

    Distant unshadowed ground needs no shadow texels. Project every ordinary
    caster AABB along the directional light onto each photographic plane, so
    offscreen casters and long low-sun shadows remain conservatively included.
    Ordinary receiver geometry keeps its existing exact local bounds.
    """
    boxes, grounds = [], []
    for entity in entities:
        bounds = getattr(entity.model, 'bounds', None)
        if bounds is None:
            continue
        world = np.asarray(entity.world_matrix, dtype=float)
        material = getattr(entity.model, 'material', None) or {}
        if material.get('extras', {}).get('photographicGround'):
            grounds.append((bounds, world))
        else:
            boxes.append((bounds, world))
    if not grounds:
        return boxes
    if not boxes:
        return boxes  # Nothing can cast a shadow onto the photographic ground.
    # Project the same centered corners in one NumPy batch. A large street no
    # longer creates and transforms thousands of tiny arrays every moving frame.
    bounds = np.asarray([box[0] for box in boxes], dtype=float)
    worlds = np.asarray([box[1] for box in boxes], dtype=float)
    corners = (bounds[:, 0] + bounds[:, 1])[:, None, :] * .5 + _SIGNS * (
        bounds[:, 1] - bounds[:, 0])[:, None, :] * .5
    points = (corners @ worlds[:, :3, :3].transpose(0, 2, 1)
              + worlds[:, None, :3, 3]).reshape(-1, 3)
    for bounds, world in grounds:
        normal = np.linalg.inv(world[:3,:3]).T @ np.array([0.,0.,1.])
        denominator = float(normal @ light)
        if abs(denominator) < 1e-10:
            boxes.append((bounds, world))  # Parallel sun: preserve conservative fallback.
            continue
        plane = world[:3,:3] @ np.asarray(bounds, dtype=float).mean(axis=0) + world[:3,3]
        projected = points - ((points-plane) @ normal / denominator)[:,None] * light
        # Use local bounds of this finite footprint; the ground itself is unchanged.
        inverse = np.linalg.inv(world)
        local = projected @ inverse[:3,:3].T + inverse[:3,3]
        lo, hi = local.min(axis=0), local.max(axis=0)
        # Exact planar Z avoids growing the fit from numerical projection noise.
        lo[2] = hi[2] = np.asarray(bounds, dtype=float).mean(axis=0)[2]
        boxes.append((np.stack((lo,hi)), world))
    return boxes


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
    return _partial(corners, world, local_planes, clip_corners,
                    _planes(*np.asarray(bounds,dtype=float)), inverse, tol)


def _partial(corners, world, local_planes, clip_corners, box_planes, inverse, tol):
    """Exact crossing path, with transform-only data prepared by the caller."""
    clip_local = clip_corners @ inverse[:3,:3].T + inverse[:3,3]
    candidates = np.concatenate((corners,clip_local,_crossings(corners,local_planes),
                                 _crossings(clip_local,box_planes)))
    inside = ((candidates @ local_planes[:,:3].T + local_planes[:,3] >= -tol).all(axis=1) &
              (candidates @ box_planes[:,:3].T + box_planes[:,3] >= -tol).all(axis=1))
    points = candidates[inside]
    return points @ world[:3,:3].T + world[:3,3]


def _batch_crossings(corners, planes):
    starts = corners[:, _EDGES[:,0]]
    deltas = corners[:, _EDGES[:,1]] - starts
    distances = starts @ planes[:, :,:3].transpose(0,2,1) + planes[:, None,:,3]
    denominator = deltas @ planes[:, :,:3].transpose(0,2,1)
    t = np.divide(-distances, denominator, out=np.full_like(distances, np.nan),
                  where=np.abs(denominator)>1e-15)
    t[~(np.isfinite(t) & (t >= -1e-10) & (t <= 1+1e-10))] = np.nan
    return (starts[:,:,None,:] + t[:,:,:,None]*deltas[:,:,None,:]).reshape(-1,72,3)


def _batch_partials(bounds, worlds, corners, local_planes, clip_corners, tolerances, prepared):
    inverses, box_planes = [], []
    for i in range(len(bounds)):
        if prepared is None:
            inverses.append(np.linalg.inv(worlds[i]))
            box_planes.append(_planes(*bounds[i]))
        else:
            record = prepared[i]
            if record['inverse'] is None:
                record['inverse'] = np.linalg.inv(worlds[i])
            inverses.append(record['inverse'])
            box_planes.append(record['planes'])
    inverses, box_planes = np.asarray(inverses), np.asarray(box_planes)
    clip_local = clip_corners @ inverses[:,:3,:3].transpose(0,2,1) + inverses[:,None,:3,3]
    candidates = np.concatenate((corners, clip_local, _batch_crossings(corners, local_planes),
                                 _batch_crossings(clip_local, box_planes)), axis=1)
    inside = ((candidates @ local_planes[:,:,:3].transpose(0,2,1) + local_planes[:,None,:,3]
               >= -tolerances[:,None,None]).all(axis=2) &
              (candidates @ box_planes[:,:,:3].transpose(0,2,1) + box_planes[:,None,:,3]
               >= -tolerances[:,None,None]).all(axis=2))
    return [points[keep] @ world[:3,:3].T + world[:3,3]
            for points, keep, world in zip(candidates, inside, worlds)]


def _intersections(bounds, worlds, corners, world_corners, tolerances, planes, clip_corners,
                   prepared=None):
    """Batch the unchanged corner/plane early-outs; exact clipping for partials.

    Prepared geometry is checked against current bounds/world values. Camera
    planes and exact intersections are always recomputed for the current fit.
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
    partial = np.flatnonzero(~contained & ~rejected)
    clipped = iter(_batch_partials(bounds[partial], worlds[partial], corners[partial],
                   local_planes[partial], clip_corners, tolerances[partial],
                   None if prepared is None else [prepared[i] for i in partial])) if len(partial) else iter(())
    result = []
    for i in range(len(bounds)):
        if contained[i]:
            result.append(world_corners[i])
        elif not rejected[i]:
            result.append(next(clipped))
    return result


def _prepare_boxes(boxes, cache):
    """Cache bounded transform-only data, never camera-dependent fit results."""
    records = []
    for bound, world in boxes:
        bound, world = np.asarray(bound, float), np.asarray(world, float)
        key = (bound.shape, bound.tobytes(), world.shape, world.tobytes())
        record = cache.get(key)
        if record is None:
            bound, world = bound.copy(), world.copy()
            corners = _corners(bound)
            record = dict(bounds=bound, world=world, corners=corners,
                          world_corners=corners @ world[:3,:3].T + world[:3,3],
                          tolerance=max(float(np.max(np.abs(corners)))*1e-9,1e-12),
                          planes=_planes(*bound), inverse=None)
            if len(cache) >= 2048:
                cache.clear()
            cache[key] = record
        records.append(record)
    return records


def _prepare_box(bound, world):
    """The original centered-corner convention, prepared only on a change."""
    bound, world = np.asarray(bound, float).copy(), np.asarray(world, float).copy()
    corners = _corners(bound)
    return dict(bounds=bound, world=world, corners=corners,
                world_corners=corners @ world[:3, :3].T + world[:3, 3],
                tolerance=max(float(np.max(np.abs(corners))) * 1e-9, 1e-12),
                planes=_planes(*bound), inverse=None)


class _PreparedReceivers:
    """Persistent shadow inputs sourced from the frame's checked geometry.

    Camera-dependent intersections remain exact and are recomputed. This only
    avoids revalidating and repacking every static instance for every consumer.
    Photographic grounds retain the original finite projected footprint.
    """
    _fields = ('bounds', 'world', 'corners', 'world_corners', 'tolerance')

    def __init__(self):
        self.sources = {}
        self.parts = {}
        self.ordinary_key = self.ground_key = None
        self.ordinary_points = None
        self.ground_records = []
        self.records = []
        self.arrays = None

    def _collect(self, entities, geometry, revision):
        previous_part = self.parts.get(id(geometry))
        if revision is not None and previous_part is not None and previous_part[0] == revision:
            return previous_part[1:]
        ordinary, grounds, sources, material_kinds = [], [], {}, {}
        for entity in entities:
            mesh = entity.model
            if getattr(mesh, 'bounds', None) is None:
                continue
            source = geometry.records.get(id(entity))
            value = None if source is None else source['geometry']
            if value is None:
                # Unsupported public transforms keep the legacy fit/fallback.
                bound = np.asarray(mesh.bounds, float)
                world = np.asarray(entity.world_matrix, float)
                token = (bound.shape, bound.tobytes(), world.shape, world.tobytes())
            else:
                bound, world = value[:2]
                token = source.get('token', source['key'])
            source_key = (id(entity), token)
            mid = id(mesh)
            if mid not in material_kinds:
                material_kinds[mid] = bool((getattr(mesh, 'material', None) or {}).get(
                    'extras', {}).get('photographicGround'))
            if material_kinds[mid]:
                grounds.append((source_key, bound, world))
                continue
            previous = self.sources.get(id(entity))
            record = (previous[1] if previous is not None and previous[0] == token
                      else _prepare_box(bound, world))
            sources[id(entity)] = (token, record)
            ordinary.append(record)
        self.sources.update(sources)
        self.parts[id(geometry)] = (revision, ordinary, grounds)
        return ordinary, grounds

    def refresh(self, entities, light, geometry):
        base = getattr(geometry, 'base', None)
        parts = ([base, geometry.extra] if base is not None else [geometry])
        if entities is not geometry.entities and entities != geometry.entities:
            # External callers may intentionally fit a subset of the snapshot.
            collected = [self._collect(entities, geometry, None)]
        else:
            collected = [self._collect(part.entities, part, part.revision) for part in parts]
        ordinary_parts = [item[0] for item in collected if item[0]]
        ordinary_key = tuple(id(part) for part in ordinary_parts)
        ordinary_changed = ordinary_key != self.ordinary_key
        if ordinary_changed:
            ordinary = [record for part in ordinary_parts for record in part]
            self.ordinary = ordinary
            self.ordinary_key = ordinary_key
            self.ordinary_points = (np.asarray([r['world_corners'] for r in ordinary]).reshape(-1, 3)
                                    if ordinary else None)
        else:
            ordinary = self.ordinary
        grounds = [ground for _, part in collected for ground in part]
        ground_key = (ordinary_key, tuple(item[0] for item in grounds), tuple(light))
        if ground_key == self.ground_key and not ordinary_changed:
            return self.records, self.arrays
        if ground_key != self.ground_key:
            self.ground_key = ground_key
            self.ground_records = []
            if ordinary:
                points = self.ordinary_points
                for _, bound, world in grounds:
                    normal = np.linalg.inv(world[:3, :3]).T @ np.array([0., 0., 1.])
                    denominator = float(normal @ light)
                    if abs(denominator) < 1e-10:
                        self.ground_records.append(_prepare_box(bound, world))
                        continue
                    plane = world[:3, :3] @ np.asarray(bound, float).mean(axis=0) + world[:3, 3]
                    projected = points - ((points - plane) @ normal / denominator)[:, None] * light
                    inverse = np.linalg.inv(world)
                    local = projected @ inverse[:3, :3].T + inverse[:3, 3]
                    lo, hi = local.min(axis=0), local.max(axis=0)
                    lo[2] = hi[2] = np.asarray(bound, float).mean(axis=0)[2]
                    self.ground_records.append(_prepare_box(np.stack((lo, hi)), world))
        records = ordinary + self.ground_records
        if self.arrays is None or len(records) != len(self.records):
            self.arrays = tuple(np.asarray([r[field] for r in records]) for field in self._fields)
        else:
            start = 0 if ordinary_changed else len(ordinary)
            for index in range(start, len(records)):
                old, new = self.records[index], records[index]
                if old is not new:
                    for field, array in zip(self._fields, self.arrays):
                        array[index] = new[field]
        self.records = records
        # Retain only the current scene's prepared records and overlay parts.
        if ordinary_changed:
            self.sources = {id(entity): self.sources[id(entity)]
                            for part in parts for entity in part.entities
                            if id(entity) in self.sources}
            self.parts = {id(part): self.parts[id(part)] for part in parts if id(part) in self.parts}
        return records, self.arrays


def _stabilize_bounds(lo, hi, rotation, resolution, state=None):
    """Snap a local fit while retaining its texel pitch across small pose changes.

    Snapping translation alone does not stabilize a tight fit whose scale changes
    every frame. A small span hysteresis holds that scale until the local
    receiver region grows or shrinks enough to need a new fit. This never locks
    the map to the whole scene. Reserve a texel so rounding cannot clip a receiver.
    """
    lo, hi = np.array(lo, dtype=float, copy=True), np.array(hi, dtype=float, copy=True)
    center, required = (lo + hi) * .5, hi - lo
    key = (int(resolution), rotation.tobytes())
    if state is not None and state.get('key') != key:
        state.clear()
    previous = None if state is None else state.get('bounds')
    # At tiny unsupported resolutions snapping has no useful conservative fit.
    if resolution <= 2:
        return lo, hi
    span = required[:2] * 1.02 / (1 - 2 / resolution)
    if previous is not None:
        old_lo, old_hi = previous
        old_span = old_hi - old_lo
        growth_reserve = 1.02 / (1 - 2 / resolution)
        shrink_ratio = .96 * growth_reserve
        grow_ratio = growth_reserve * (1 - 1 / resolution)
        shrinking = span >= old_span[:2] * shrink_ratio
        keep = (span <= old_span[:2] * grow_ratio) & shrinking
        span = np.where(keep, old_span[:2], span)
    texel = span / resolution
    center[:2] = np.floor(center[:2] / texel + .5) * texel
    lo[:2], hi[:2] = center[:2] - span * .5, center[:2] + span * .5
    if state is not None:
        state.update(key=key, bounds=(lo.copy(), hi.copy()))
    return lo, hi


def receiver_matrix(entities, direction, camera, resolution, aspect=None, geometry_cache=None,
                    prepared=None, stability=None):
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
        aspect = camera.aspect if aspect is None else aspect
        vp = camera.projection_matrix(aspect) @ camera.view_matrix
        planes = np.array([vp[3]+sign*vp[axis] for axis in range(3) for sign in (1,-1)])
        homogeneous = np.column_stack((_SIGNS,np.ones(8))) @ np.linalg.inv(vp).T
        frustum = homogeneous[:,:3]/homogeneous[:,3,None]
        cache = {} if geometry_cache is None else geometry_cache
        if prepared is not None:
            bank = cache.get('_prepared_receivers')
            if bank is None:
                bank = cache['_prepared_receivers'] = _PreparedReceivers()
            records, arrays = bank.refresh(entities, light, prepared)
            if not records:
                return None
            bounds, worlds, corners, world_corners, tolerances = arrays
        else:
            boxes = _receiver_boxes(entities, light)
            if not boxes:
                return None
            records = _prepare_boxes(boxes, cache)
            bounds = np.asarray([r['bounds'] for r in records])
            worlds = np.asarray([r['world'] for r in records])
            corners = np.asarray([r['corners'] for r in records])
            world_corners = np.asarray([r['world_corners'] for r in records])
            tolerances = np.asarray([r['tolerance'] for r in records])
        receivers = [points @ rotation.T for points in
                     _intersections(bounds, worlds, corners, world_corners, tolerances, planes, frustum, records)
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
        # Stabilize XY before fitting caster Z: expanded/snapped coverage must
        # retain offscreen casters whose shadows enter the new edge texels.
        xy_lo, xy_hi = _stabilize_bounds(lo, hi, rotation, resolution, stability)
        lo[:2], hi[:2] = xy_lo[:2], xy_hi[:2]
        global_points = np.concatenate(world_corners @ rotation.T)
        lo[2],hi[2] = global_points[:,2].min()-margin,global_points[:,2].max()+margin
        clip_corners = _corners((lo,hi)) @ rotation
        light_planes = _planes(lo,hi)
        light_planes[:,:3] = light_planes[:,:3] @ rotation
        casters = _intersections(bounds, worlds, corners, world_corners, tolerances, light_planes, clip_corners, records)
        caster_points = np.concatenate([p for p in casters if len(p)]) @ rotation.T
        lo[2],hi[2] = caster_points[:,2].min(),caster_points[:,2].max()
        caster_depth = (lo[2], hi[2])
        depth_margin = max(float((hi-lo).max())*.02,1e-12)
        lo[2] -= depth_margin
        hi[2] += depth_margin
        if stability is not None:
            previous = stability.get('depth')
            if (previous is not None and caster_depth[0] >= previous[0] + depth_margin * .25
                    and caster_depth[1] <= previous[1] - depth_margin * .25
                    and hi[2] - lo[2] >= (previous[1] - previous[0]) * .96):
                lo[2], hi[2] = previous
            stability['depth'] = (float(lo[2]), float(hi[2]))
        scale = 2/(hi-lo)
        scale[2] *= -1
        matrix = np.eye(4)
        matrix[:3,:3] = scale[:,None]*rotation
        matrix[:3,3] = -scale*(lo+hi)*.5
        return matrix if np.isfinite(matrix).all() else None
    except (ValueError, np.linalg.LinAlgError, FloatingPointError, OverflowError):
        return None
