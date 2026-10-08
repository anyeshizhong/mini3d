"""UI-independent placement commands with atomic, resource-sharing history.

Angles are XYZ Euler radians and all coordinates are engine coordinates. Use
``transaction(label)`` to group many API calls, or begin/commit/cancel around a
mouse gesture. History snapshots retain entity/mesh identities; they never copy
mesh or texture data. The mathematical placement plane is not an instance.
"""
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .scene import SceneGroup, euler_xyz, rotation_xyz


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
        return {
            "entities": [(entity, entity.entity_id, entity.pos.copy(), entity.rot.copy(), entity.scale.copy(),
                          tuple(getattr(entity, field) for field in _FIELDS))
                         for entity in self.scene.root_entities],
            "groups": [(group, group.group_id, group.name, tuple(group.member_ids))
                       for group in self.scene.groups],
            "selection": (tuple(self.scene.selected_ids), self.scene.primary_selection_id,
                          self.scene.selected_group_id),
        }

    @staticmethod
    def _same(first, second):
        a_entities, b_entities = first["entities"], second["entities"]
        a_groups, b_groups = first["groups"], second["groups"]
        return (first["selection"] == second["selection"]
            and len(a_groups) == len(b_groups)
            and all(a[0] is b[0] and a[1:] == b[1:] for a, b in zip(a_groups, b_groups))
            and len(a_entities) == len(b_entities) and all(
            a[0] is b[0] and a[1] == b[1] and a[5] == b[5]
            and all(np.array_equal(a[index], b[index]) for index in (2, 3, 4))
            for a, b in zip(a_entities, b_entities)))

    def _restore(self, snapshot):
        self.scene.root_entities[:] = [state[0] for state in snapshot["entities"]]
        for entity, entity_id, pos, rot, scale, metadata in snapshot["entities"]:
            entity.entity_id = entity_id
            entity.pos, entity.rot, entity.scale = pos.copy(), rot.copy(), scale.copy()
            for field, value in zip(_FIELDS, metadata):
                setattr(entity, field, value)
        self.scene.groups[:] = [state[0] for state in snapshot["groups"]]
        for group, group_id, name, member_ids in snapshot["groups"]:
            group.group_id, group.name, group.member_ids = group_id, name, list(member_ids)
        ids, primary_id, group_id = snapshot["selection"]
        self.scene.selected_ids = list(ids)
        self.scene.primary_selection_id, self.scene.selected_group_id = primary_id, group_id
        self.scene.clean_selection()
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
            for group in self.scene.groups:
                group.member_ids[:] = [value for value in group.member_ids if value != entity.entity_id]
            self.scene.groups[:] = [group for group in self.scene.groups if group.member_ids]
            self.scene.clean_selection()
        return entity

    @property
    def selected_entities(self):
        return self.scene.selected_entities

    @property
    def primary_selection(self):
        return self.scene.primary_selection

    @property
    def editable_selection(self):
        return self.scene.editable_selection

    def set_selection(self, ids, primary_id=None, group_id=None):
        """Choose stable IDs without adding a standalone history entry.

        Locked entities may be selected by management UI, but editable_selection
        always excludes them. Calling this inside a transaction captures the
        resulting selection along with that operation.
        """
        if isinstance(ids, str):
            raise ValueError("Selection must be a sequence of entity IDs")
        values = list(ids)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("Selection must contain entity IDs")
        values = list(dict.fromkeys(values))
        for value in values:
            self._entity(value)
        if primary_id is not None and primary_id not in values:
            raise ValueError("Primary selection must belong to selected IDs")
        if group_id is not None:
            group = self._group(group_id)
            if set(values) != set(group.member_ids):
                raise ValueError("Group selection must contain all group members")
        self.scene.selected_ids = values
        self.scene.primary_selection_id = primary_id if primary_id is not None else (values[-1] if values else None)
        self.scene.selected_group_id = group_id
        return self.selected_entities

    def _group(self, group_id):
        group = self.scene.find_group_by_id(group_id)
        if group is None:
            raise ValueError("Unknown scene group: {!r}".format(group_id))
        return group

    def select_group(self, group_id):
        group = self._group(group_id)
        return self.set_selection(group.member_ids, group_id=group_id)

    def create_group(self, member_ids, name=None):
        if isinstance(member_ids, str):
            raise ValueError("Group members must be a sequence of entity IDs")
        group = SceneGroup(None, "Group" if name is None else str(name), list(member_ids))
        with self._operation("Group"):
            self.scene.add_group(group)
            self.select_group(group.group_id)
        return group

    def rename_group(self, group_id, name):
        group = self._group(group_id)
        with self._operation("Rename group"):
            group.name = str(name)
        return group

    def ungroup(self, group_id):
        group = self._group(group_id)
        with self._operation("Ungroup"):
            self.scene.groups.remove(group)
            self.scene.clean_selection()
        return group

    def transform_many(self, ids, translation=None, rotation=None, scale=None,
                       pivot=None, initial=None):
        """Apply world deltas about the mean editable root position.

        ``initial`` maps IDs to position/rotation/scale copies captured at mouse
        down, making updates independent of frame count. Nonuniform scale uses
        TRS approximation: world offsets and each instance scale are multiplied
        componentwise, with no shear. Locked instances are always skipped.
        """
        if isinstance(ids, str):
            raise ValueError("Transform IDs must be a sequence")
        entities = []
        seen = set()
        for value in ids:
            entity = self._entity(value)
            if entity.entity_id not in seen and not entity.locked:
                entities.append(entity)
                seen.add(entity.entity_id)
        delta = np.zeros(3) if translation is None else _vector(translation, "translation")
        angles = np.zeros(3) if rotation is None else _vector(rotation, "rotation")
        factors = np.ones(3) if scale is None else _vector(scale, "scale", positive=True)
        basis = rotation_xyz(angles)
        originals = []
        for entity in entities:
            if initial is None:
                pos, rot, size = entity.pos.copy(), entity.rot.copy(), entity.scale.copy()
            else:
                try:
                    state = initial[entity.entity_id]
                    pos = _vector(state["position"], "initial position")
                    rot = _vector(state["rotation"], "initial rotation")
                    size = _vector(state["scale"], "initial scale", positive=True)
                except (KeyError, TypeError):
                    raise ValueError("initial must contain position, rotation and scale for every editable ID")
            originals.append((entity, pos, rot, size))
        center = (np.mean([state[1] for state in originals], axis=0) if originals else np.zeros(3))
        if pivot is not None:
            center = _vector(pivot, "pivot")
        with self._operation("Multi transform"):
            for entity, pos, rot, size in originals:
                entity.pos = center + basis @ ((pos - center) * factors) + delta
                # Avoid Euler roundoff/no-op history when only moving/scaling.
                entity.rot = euler_xyz(basis @ rotation_xyz(rot)) if np.any(angles) else rot.copy()
                entity.scale = size * factors
        return entities

    def create_rectangular_formation(self, source_id, rows, columns, spacing_x,
                                     spacing_y, facing=None, include_source=True):
        from .formation import create_rectangular_formation
        return create_rectangular_formation(self, source_id, rows, columns,
                                            spacing_x, spacing_y, facing=facing,
                                            include_source=include_source)

    def begin_surface_drag(self, entity_id):
        from .surface_drag import SurfaceDrag
        return SurfaceDrag(self, entity_id)

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
