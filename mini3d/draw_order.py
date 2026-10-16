"""Group disjoint opaque geometry without changing overlapping surface order.

Equal-depth fragments depend on draw order. Within each material we retain an
ordering edge for every pair of touching/overlapping world AABBs, and choose a
topological order favoring the previous mesh. Camera changes do not alter this
order. Invalid bounds act as barriers; MASK/BLEND retain their original order.
"""
import numpy as np
from .geometry_cache import box_geometry


def _group_order(meshes, bounds):
    count = len(meshes)
    if count < 2 or len(set(meshes)) < 2:
        return list(range(count))
    boxes = np.asarray([b if b is not None else [[-np.inf]*3, [np.inf]*3]
                        for b in bounds])
    # Account for float32 GPU position arithmetic, including touching surfaces.
    magnitude = np.max(np.where(np.isfinite(boxes), np.abs(boxes), 0), axis=(1, 2))
    padding = 1e-5 * (magnitude + 1.)
    lo = boxes[:, 0] - padding[:, None]
    hi = boxes[:, 1] + padding[:, None]
    overlaps = np.all((lo[:, None] <= hi[None, :]) & (hi[:, None] >= lo[None, :]), axis=2)
    edges = np.triu(overlaps, 1)
    incoming = edges.sum(axis=0)
    order, previous = [], None
    for _ in range(count):
        ready = np.flatnonzero(incoming == 0)
        index = next((int(i) for i in ready if meshes[i] == previous), int(ready[0]))
        order.append(index); previous = meshes[index]
        incoming[index] = -1
        incoming[edges[index]] -= 1
    return order


class OpaqueOrder:
    """One-scene value-checked cache, no persistent entity references."""
    def __init__(self):
        self.key = None
        self.ranks = {}
        self.groups = {}
        self._prepared_parts = {}
        self._rank_signature = None

    def _prepared_ranks(self, prepared):
        parts = ([prepared.base, prepared.extra] if getattr(prepared, 'base', None) is not None
                 else [prepared])
        grouped, retained = {}, {}
        for part in parts:
            previous = self._prepared_parts.get(id(part))
            if previous is not None and previous[0] == part.revision:
                groups = previous[1]
            else:
                groups = {}
                for entity in part.entities:
                    mesh = entity.model
                    material = getattr(mesh, 'material', None)
                    if material is None:
                        continue
                    source = part.records[id(entity)]
                    geometry = source['geometry']
                    groups.setdefault(id(material), []).append((id(entity), id(mesh),
                        material.get('alphaMode', 'OPAQUE'),
                        None if geometry is None else geometry[3], source['token']))
                groups = {mid: (tuple((r[0], r[1], r[2], r[4]) for r in rows), rows)
                          for mid, rows in groups.items()}
            retained[id(part)] = (part.revision, groups)
            for mid, group in groups.items():
                grouped.setdefault(mid, []).append(group)
        self._prepared_parts = retained
        result, signature = {}, []
        for mid, entries in grouped.items():
            key = tuple(entry[0] for entry in entries)
            previous = self.groups.get(mid)
            if previous is not None and previous[0] == key:
                ids = previous[1]
            else:
                rows = [row for _, group in entries for row in group]
                ids = []
                for start in range(0, len(rows), 512):
                    chunk = rows[start:start + 512]
                    order = (_group_order([r[1] for r in chunk], [r[3] for r in chunk])
                             if chunk[0][2] == 'OPAQUE' else range(len(chunk)))
                    ids.extend(chunk[i][0] for i in order)
                ids = tuple(ids)
            result[mid] = (key, ids)
            signature.append((mid, ids))
        signature = tuple(signature)
        if signature != self._rank_signature:
            ids = [ident for _, group in signature for ident in group]
            self.ranks = {ident: index for index, ident in enumerate(ids)}
            self._rank_signature = signature
        self.groups = result
        self.key = None  # Switching to a standalone call must value-check again.
        return self.ranks

    def ranks_for(self, entities, prepared=None):
        if prepared is not None and hasattr(prepared, 'revision') and entities is prepared.entities:
            return self._prepared_ranks(prepared)
        self._rank_signature = None
        records, key = [], []
        for entity in entities:
            model = entity.model
            material = getattr(model, 'material', None)
            if material is None:
                continue
            cached = None if prepared is None else prepared.records[id(entity)]
            geometry = box_geometry(entity) if cached is None else cached['geometry']
            bounds = None if geometry is None else geometry[3]
            alpha = material.get('alphaMode', 'OPAQUE')
            # The shared scene synchronization already checked mutable arrays.
            # Reuse its immutable record token instead of serializing bounds
            # again for every consumer. Standalone callers remain value-checked.
            stamp = (cached.get('token', id(cached)) if cached is not None else
                     None if bounds is None else bounds.tobytes())
            records.append((id(entity), id(model), id(material), alpha, bounds, stamp))
            key.append((id(entity), id(model), id(material), alpha,
                        stamp))
        key = tuple(key)
        if key == self.key:
            return self.ranks
        materials = {}
        for record in records:
            materials.setdefault(record[2], []).append(record)
        ranks, cached_groups = {}, {}
        for group in materials.values():
            group_key = tuple((r[0], r[1], r[3], r[5]) for r in group)
            previous = self.groups.get(group[0][2])
            if previous is not None and previous[0] == group_key:
                for ident in previous[1]:
                    ranks[ident] = len(ranks)
                cached_groups[group[0][2]] = previous
                continue
            ordered_ids = []
            # Bound quadratic work/memory for unusually large imported scenes.
            # Chunks never cross one another, preserving all cross-chunk edges.
            for start in range(0, len(group), 512):
                chunk = group[start:start + 512]
                order = (_group_order([r[1] for r in chunk], [r[4] for r in chunk])
                         if chunk[0][3] == 'OPAQUE' else range(len(chunk)))
                for i in order:
                    ranks[chunk[i][0]] = len(ranks)
                    ordered_ids.append(chunk[i][0])
            cached_groups[group[0][2]] = (group_key, ordered_ids)
        self.key, self.ranks = key, ranks
        self.groups = cached_groups
        return ranks
