"""One compatibility scan per frame; persistent derived data for every pass.

Public arrays and material dictionaries remain mutable. Only this boundary
checks their values; consumers use record tokens instead of serializing them
again. A frame starts after editor/API mutations and ends before the next input.
"""
from contextlib import contextmanager

import numpy as np
from .geometry_cache import box_geometry, normal_transform


def value_key(value):
    if isinstance(value, np.ndarray):
        return value.shape, value.dtype.str, value.tobytes()
    if isinstance(value, bytes):
        return id(value)  # Encoded texture payloads are immutable resources.
    if isinstance(value, dict):
        return tuple((key, value_key(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(value_key(item) for item in value)
    return value


class SceneSnapshot:
    def __init__(self):
        self.records = {}
        self.entities = []
        self.bounds = []
        self.corners = np.empty((0, 8, 3))
        self.revision = self.geometry_revision = self.material_revision = 0
        self.key = self._material_key = None
        self.normal_cache = {}
        self.material_keys = {}
        self.mesh_keys = {}
        self._token = 0
        self.complete = True
        self._plan_inputs = None

    def refresh(self, scene):
        return self.refresh_entities(scene.get_flat_render_list())

    def refresh_entities(self, entities):
        meshes, materials, bounds_keys = {}, {}, {}
        keys, records = [], {}
        for entity in entities:
            mesh = entity.model
            mid = id(mesh)
            material = getattr(mesh, 'material', None)
            material_id = id(material)
            if material_id not in materials:
                materials[material_id] = value_key(material)
            if mid not in meshes:
                bound = getattr(mesh, 'bounds', None)
                converted = None if bound is None else np.asarray(bound, dtype=float)
                bounds_keys[mid] = None if converted is None else (converted.shape, converted.tobytes())
                meshes[mid] = (bounds_keys[mid], value_key(getattr(mesh, 'base_color', None)))
            world = np.asarray(entity.world_matrix)
            key = (mid, bounds_keys[mid], world.shape, world.dtype.str,
                   world.tobytes(), getattr(entity, 'isaxes', False))
            material_key = (material_id, materials[material_id], meshes[mid][1])
            prior = self.records.get(id(entity))
            if prior is None or prior['key'] != key or prior['material_key'] != material_key:
                if prior is None or prior['key'] != key:
                    geometry = box_geometry(entity)
                    matrix = np.array(world, np.float32, copy=True)
                    normal, mirrored = (normal_transform(matrix, self.normal_cache)
                                        if matrix.shape == (4, 4) and np.isfinite(matrix).all()
                                        else (None, False))
                else:
                    geometry, matrix = prior['geometry'], prior['matrix']
                    normal, mirrored = prior['normal'], prior['mirrored']
                self._token += 1
                prior = dict(key=key, material_key=material_key, geometry=geometry,
                             matrix=matrix, normal=normal, mirrored=mirrored,
                             token=(id(self), self._token))
            records[id(entity)] = prior
            keys.append((id(entity), key))
        key = tuple(keys)
        material_key = (tuple(materials.items()), tuple(meshes.items()),
                        tuple((id(e), id(getattr(e.model, 'material', None))) for e in entities))
        changed = False
        if key != self.key:
            self.geometry_revision += 1
            self.bounds = [None if records[id(e)]['geometry'] is None else records[id(e)]['geometry'][3]
                           for e in entities]
            self.corners = np.asarray([records[id(e)]['geometry'][2] for e in entities
                                       if records[id(e)]['geometry'] is not None]).reshape(-1, 8, 3)
            self.complete = all(b is not None for b in self.bounds)
            self.key = key
            changed = True
        if material_key != self._material_key:
            self.material_revision += 1
            self._material_key = material_key
            changed = True
        if changed:
            self.revision += 1
            self._plan_inputs = None
        self.material_keys, self.mesh_keys = materials, meshes
        self.records, self.entities = records, entities
        return self


class OverlaySnapshot:
    """A camera-following receiver must not invalidate the static city's data."""
    def __init__(self):
        self.extra = SceneSnapshot()
        self.base = None
        self.geometry_revision = self.material_revision = self.revision = 0
        self._geometry_key = self._material_key = None
        self._plan_inputs = None

    def refresh(self, base, extras):
        self.base = base
        extra = self.extra.refresh_entities(extras)
        geometry_key = (id(base), base.geometry_revision, extra.geometry_revision)
        material_key = (id(base), base.material_revision, extra.material_revision)
        changed = False
        if geometry_key != self._geometry_key:
            self.geometry_revision += 1
            self.entities = base.entities + extra.entities
            self.bounds = base.bounds + extra.bounds
            self.corners = np.concatenate((base.corners, extra.corners))
            self.complete = base.complete and extra.complete
            self._geometry_key = geometry_key
            changed = True
        if material_key != self._material_key:
            self.material_revision += 1
            self._material_key = material_key
            changed = True
        if changed:
            self.revision += 1
            self._plan_inputs = None
            # A small C-level dict copy is cheaper than Python ChainMap lookups
            # in every downstream pass. Unchanged record objects stay shared.
            self.records = dict(base.records)
            self.records.update(extra.records)
            self.material_keys = dict(base.material_keys)
            self.material_keys.update(extra.material_keys)
            self.mesh_keys = dict(base.mesh_keys)
            self.mesh_keys.update(extra.mesh_keys)
        return self


def snapshot(scene):
    base = getattr(scene, '_render_base_scene', None)
    if base is not None:
        bank = base._snapshot_bank
        extras = scene._render_extra_entities
        key = ('overlay', tuple(id(e) for e in extras))
        if key not in bank:
            # Renderers may be recreated; don't retain their old floor objects.
            if len(bank) > 4:
                for old in list(bank):
                    if old is not None:
                        del bank[old]
            bank[key] = OverlaySnapshot()
        return bank[key].refresh(snapshot(base), extras)
    active = getattr(scene, '_frame_geometry', None)
    if active is not None:
        return active
    bank = getattr(scene, '_snapshot_bank', None)
    if bank is None:
        bank = scene._snapshot_bank = {}
    if None not in bank:
        bank[None] = SceneSnapshot()
    return bank[None].refresh(scene)


@contextmanager
def scene_frame(scene):
    """Synchronize once, including direct array writes; nested renders reuse it."""
    if getattr(scene, '_frame_geometry', None) is not None:
        yield snapshot(scene)
        return
    scene.update()
    prepared = snapshot(scene)
    scene._frame_geometry = prepared
    try:
        yield prepared
    finally:
        scene._frame_geometry = None
