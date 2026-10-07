"""UI-independent placement commands with atomic, resource-sharing history.

Angles are XYZ Euler radians and all coordinates are engine coordinates. Use
``transaction(label)`` to group many API calls, or begin/commit/cancel around a
mouse gesture. History snapshots retain entity/mesh identities; they never copy
mesh or texture data. The built-in ground is not an editable scene instance.
"""
from contextlib import contextmanager
from pathlib import Path

import numpy as np


_FIELDS = ("name", "visible", "locked", "placement_type", "placement_anchor", "keep_upright")


def _vector(value, label, positive=False):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ValueError(label + " must contain three finite numbers")
    if positive and np.any(result <= 0):
        raise ValueError(label + " must be positive")
    return result.copy()


def _placement_metadata(placement_type, anchor, keep_upright):
    if placement_type not in ("prop", "character"):
        raise ValueError("placement_type must be prop or character")
    if anchor not in ("pivot", "bounds_bottom"):
        raise ValueError("anchor must be pivot or bounds_bottom")
    if keep_upright is not None and not isinstance(keep_upright, (bool, np.bool_)):
        raise ValueError("keep_upright must be a boolean")


class PlacementCommands:
    def __init__(self, scene, cache):
        self.scene, self.cache = scene, cache
        self._undo, self._redo = [], []
        self._transaction = None

    @property
    def undo_count(self):
        return len(self._undo)

    @property
    def redo_count(self):
        return len(self._redo)

    @property
    def active_transaction(self):
        return self._transaction is not None

    def _snapshot(self):
        return [(entity, entity.entity_id, entity.pos.copy(), entity.rot.copy(), entity.scale.copy(),
                 tuple(getattr(entity, field) for field in _FIELDS))
                for entity in self.scene.root_entities]

    @staticmethod
    def _same(first, second):
        return len(first) == len(second) and all(
            a[0] is b[0] and a[1] == b[1] and a[5] == b[5]
            and all(np.array_equal(a[index], b[index]) for index in (2, 3, 4))
            for a, b in zip(first, second))

    def _restore(self, snapshot):
        self.scene.root_entities[:] = [state[0] for state in snapshot]
        for entity, entity_id, pos, rot, scale, metadata in snapshot:
            entity.entity_id = entity_id
            entity.pos, entity.rot, entity.scale = pos.copy(), rot.copy(), scale.copy()
            for field, value in zip(_FIELDS, metadata):
                setattr(entity, field, value)
        self.scene.update()

    def _record(self, label, before, after):
        if not self._same(before, after):
            self._undo.append((label, before, after))
            self._redo.clear()

    @contextmanager
    def _operation(self, label):
        before = self._snapshot()
        try:
            yield
            self.scene.update()
        except Exception:
            self._restore(before)
            raise
        if not self.active_transaction:
            self._record(label, before, self._snapshot())

    def begin_transaction(self, label="Placement"):
        if self.active_transaction:
            raise RuntimeError("A placement transaction is already active")
        self._transaction = (str(label), self._snapshot())

    def commit_transaction(self):
        if not self.active_transaction:
            raise RuntimeError("No active placement transaction")
        label, before = self._transaction
        self._transaction = None
        self._record(label, before, self._snapshot())

    def cancel_transaction(self):
        if not self.active_transaction:
            raise RuntimeError("No active placement transaction")
        _, before = self._transaction
        self._transaction = None
        self._restore(before)

    @contextmanager
    def transaction(self, label="Placement"):
        self.begin_transaction(label)
        try:
            yield self
        except Exception:
            self.cancel_transaction()
            raise
        else:
            self.commit_transaction()

    def clear_history(self):
        if self.active_transaction:
            raise RuntimeError("Finish the active transaction before clearing history")
        self._undo.clear()
        self._redo.clear()

    def undo(self):
        if self.active_transaction:
            raise RuntimeError("Finish the active transaction before undo")
        if not self._undo:
            return False
        item = self._undo.pop()
        self._restore(item[1])
        self._redo.append(item)
        return True

    def redo(self):
        if self.active_transaction:
            raise RuntimeError("Finish the active transaction before redo")
        if not self._redo:
            return False
        item = self._redo.pop()
        self._restore(item[2])
        self._undo.append(item)
        return True

    def _entity(self, entity_or_id, editable=False):
        entity = (self.scene.find_by_id(entity_or_id) if isinstance(entity_or_id, str)
                  else entity_or_id)
        if entity is None or entity not in self.scene.root_entities:
            raise ValueError("Entity is not a scene instance: {!r}".format(entity_or_id))
        if editable and entity.locked:
            raise ValueError("Entity is locked: " + entity.entity_id)
        return entity

    def spawn(self, asset_path, name=None, position=None, rotation=None, scale=None,
              placement_type=None, anchor="bounds_bottom", keep_upright=None):
        if placement_type is None:
            # A known bundled asset default, not a general character classifier.
            placement_type = "character" if Path(asset_path).stem == "roman_legionnaire" else "prop"
        _placement_metadata(placement_type, anchor, keep_upright)
        pos = None if position is None else _vector(position, "position")
        rot = None if rotation is None else _vector(rotation, "rotation")
        size = None if scale is None else _vector(scale, "scale", positive=True)
        root = self.cache.load(asset_path).instantiate()
        if name is not None:
            root.name = str(name)
        if pos is not None:
            root.pos = pos
        if rot is not None:
            root.rot = rot
        if size is not None:
            root.scale = size
        root.locked = False
        root.placement_type, root.placement_anchor = placement_type, anchor
        root.keep_upright = placement_type == "character" if keep_upright is None else bool(keep_upright)
        with self._operation("Spawn"):
            self.scene.add(root)
        return root

    def set_transform(self, entity_or_id, position=None, rotation=None, scale=None):
        entity = self._entity(entity_or_id, editable=True)
        values = [(key, _vector(value, key, positive=key == "scale"))
                  for key, value in (("pos", position), ("rot", rotation), ("scale", scale))
                  if value is not None]
        with self._operation("Transform"):
            for key, value in values:
                setattr(entity, key, value)
        return entity

    def place_on_surface(self, entity_or_id, hit, anchor=None, keep_upright=None, align_normal=False):
        from .placement import compute_placement
        entity = self._entity(entity_or_id, editable=True)
        with self._operation("Surface placement"):
            position, rotation = compute_placement(entity, hit, anchor=anchor,
                keep_upright=keep_upright, align_normal=align_normal)
            entity.pos = _vector(position, "position")
            entity.rot = _vector(rotation, "rotation")
        return entity

    def duplicate(self, entity_or_id, name=None):
        original = self._entity(entity_or_id)
        root = original.clone()
        root.name = original.name + " copy" if name is None else str(name)
        # A locked backdrop can be cloned, but the new instance is editable.
        root.locked = False
        with self._operation("Duplicate"):
            self.scene.add(root)
        return root

    def delete(self, entity_or_id):
        entity = self._entity(entity_or_id, editable=True)
        with self._operation("Delete"):
            self.scene.root_entities.remove(entity)
        return entity

    def lock(self, entity_or_id):
        entity = self._entity(entity_or_id)
        with self._operation("Lock"):
            entity.locked = True
        return entity

    def unlock(self, entity_or_id):
        entity = self._entity(entity_or_id)
        with self._operation("Unlock"):
            entity.locked = False
        return entity

    def set_metadata(self, entity_or_id, name=None, visible=None, placement_type=None,
                     placement_anchor=None, keep_upright=None):
        entity = self._entity(entity_or_id)
        _placement_metadata(entity.placement_type if placement_type is None else placement_type,
                            entity.placement_anchor if placement_anchor is None else placement_anchor,
                            keep_upright)
        if visible is not None and not isinstance(visible, (bool, np.bool_)):
            raise ValueError("visible must be a boolean")
        values = {"name": name, "visible": visible, "placement_type": placement_type,
                  "placement_anchor": placement_anchor, "keep_upright": keep_upright}
        if name is not None:
            values["name"] = str(name)
        if placement_type == "character" and keep_upright is None:
            values["keep_upright"] = True
        with self._operation("Properties"):
            for field, value in values.items():
                if value is not None:
                    setattr(entity, field, value)
        return entity
