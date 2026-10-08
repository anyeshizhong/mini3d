"""Reusable scene instances; mesh/material resources are shared by clones."""
import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


def rotation_xyz(angles):
    x, y, z = angles
    cx, cy, cz = np.cos(angles)
    sx, sy, sz = np.sin(angles)
    return (np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @
            np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @
            np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]))


def euler_xyz(matrix):
    """Convert an orthonormal world rotation to the engine's XYZ Euler angles."""
    matrix = np.asarray(matrix, dtype=np.float64)
    y = np.arcsin(np.clip(-matrix[2, 0], -1.0, 1.0))
    if abs(np.cos(y)) > 1e-8:
        x = np.arctan2(matrix[2, 1], matrix[2, 2])
        z = np.arctan2(matrix[1, 0], matrix[0, 0])
    else:
        x = np.arctan2(-matrix[1, 2], matrix[1, 1])
        z = 0.0
    return np.array([x, y, z], dtype=np.float64)


@dataclass
class SceneGroup:
    """Editor membership only; never reparents an imported mesh hierarchy."""
    group_id: Optional[str]
    name: str
    member_ids: List[str]


class Mesh:
    def __init__(self, vertices, indices, normals=None, texcoords=None, material=None):
        points = np.asarray(vertices, dtype=np.float32)[:, :3]
        self.vertices = np.column_stack((points, np.ones(len(points), np.float32)))
        self.indices = np.asarray(indices, dtype=np.uint32).reshape(-1, 3)
        if self.indices.size and self.indices.max() >= len(points):
            raise ValueError("Mesh indices exceed vertex count")
        if normals is None:
            normals = np.zeros_like(points)
            triangles = points[self.indices]
            faces = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            for col in range(3):
                np.add.at(normals, self.indices[:, col], faces)
        normals = np.asarray(normals, dtype=np.float32)
        self.vertex_normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        self.texcoords = (np.zeros((len(points), 2), np.float32) if texcoords is None
                          else np.asarray(texcoords, dtype=np.float32))
        self.material = material
        self.base_color = np.array([200, 200, 200], np.float32)
        self.colors = np.tile(self.base_color, (len(self.indices), 1)).astype(np.uint8)
        self.bounds = (points.min(axis=0), points.max(axis=0)) if len(points) else None


class Entity:
    def __init__(self, model=None, name="", matrix=None):
        self.model, self.name = model, name
        self.pos = np.zeros(3, np.float64)
        self.rot = np.zeros(3, np.float64)
        self.scale = np.ones(3, np.float64)
        self.extra_local = np.eye(4) if matrix is None else np.asarray(matrix, dtype=np.float64).copy()
        self.local_matrix = np.eye(4)
        self.world_matrix = np.eye(4)
        self.children = []
        self.parent = None
        self.visible = True
        self.isaxes = False
        self.asset_path = None
        # Only scene roots receive IDs; imported templates/hierarchy nodes do not.
        self.entity_id = None
        self.locked = False
        self.placement_type = "prop"
        self.placement_anchor = "bounds_bottom"
        self.keep_upright = False

    def add_child(self, child):
        if child.parent is not None:
            child.parent.children.remove(child)
        child.parent = self
        self.children.append(child)

    def update_transform(self, parent_matrix=None):
        transform = np.eye(4)
        transform[:3, :3] = rotation_xyz(self.rot) @ np.diag(self.scale)
        transform[:3, 3] = self.pos
        # User placement acts in engine world axes, outside the imported basis.
        self.local_matrix = transform @ self.extra_local
        self.world_matrix = self.local_matrix if parent_matrix is None else parent_matrix @ self.local_matrix
        for child in self.children:
            child.update_transform(self.world_matrix)

    def clone(self):
        duplicate = Entity(self.model, self.name, self.extra_local)
        duplicate.pos, duplicate.rot, duplicate.scale = self.pos.copy(), self.rot.copy(), self.scale.copy()
        duplicate.visible, duplicate.asset_path = self.visible, self.asset_path
        duplicate.isaxes = self.isaxes
        duplicate.locked = self.locked
        duplicate.placement_type = self.placement_type
        duplicate.placement_anchor = self.placement_anchor
        duplicate.keep_upright = self.keep_upright
        for child in self.children:
            duplicate.add_child(child.clone())
        return duplicate


class Scene:
    def __init__(self):
        self.root_entities = []
        from .placement_plane import PlacementPlane
        self.placement_plane = PlacementPlane()
        # Legacy slot only; never traversed, rendered or queried implicitly.
        self.ground = None
        self._next_entity_id = 1
        self.groups = []
        self._next_group_id = 1
        self.selected_ids = []
        self.primary_selection_id = None
        self.selected_group_id = None
        # World-space surface-to-light direction; independent of every camera.
        self.light_dir = np.array([.4, -.5, .8], np.float32)
        self.light_dir /= np.linalg.norm(self.light_dir)
        self.ambient, self.diffuse = .3, .7
        self.show_grid = True
        self.show_axes = False
        self.render_mode = "Lit"
        self.lighting_mode = "Studio"  # Editor preview; render_shot forces Scene.

    def add(self, entity):
        if entity.parent is not None:
            raise ValueError("Only root entities can be added to a scene")
        if entity in self.root_entities:
            raise ValueError("Entity is already in the scene")
        if entity.entity_id is None:
            # Never rewind this counter on undo/delete, so IDs are never reused.
            while self.find_by_id("ent_{:06d}".format(self._next_entity_id)) is not None:
                self._next_entity_id += 1
            entity.entity_id = "ent_{:06d}".format(self._next_entity_id)
        if not isinstance(entity.entity_id, str) or not re.fullmatch(r"ent_\d{6,}", entity.entity_id):
            raise ValueError("Invalid entity ID: {!r}".format(entity.entity_id))
        if self.find_by_id(entity.entity_id) is not None:
            raise ValueError("Duplicate entity ID: " + entity.entity_id)
        self._next_entity_id = max(self._next_entity_id, int(entity.entity_id[4:]) + 1)
        self.root_entities.append(entity)
        return entity

    def find_by_id(self, entity_id):
        return next((root for root in self.root_entities if root.entity_id == entity_id), None)

    def find_group_by_id(self, group_id):
        return next((group for group in self.groups if group.group_id == group_id), None)

    def add_group(self, group):
        if not isinstance(group, SceneGroup):
            raise ValueError("Expected a SceneGroup")
        if not isinstance(group.name, str):
            raise ValueError("Group name must be a string")
        members = group.member_ids
        if (not isinstance(members, list) or not members
                or any(not isinstance(value, str) for value in members)
                or len(set(members)) != len(members)):
            raise ValueError("Group members must be nonempty, unique entity IDs")
        if any(self.find_by_id(value) is None for value in members):
            raise ValueError("Group members must refer to existing scene entities")
        group_id = group.group_id
        if group_id is None:
            while self.find_group_by_id("grp_{:06d}".format(self._next_group_id)) is not None:
                self._next_group_id += 1
            group_id = "grp_{:06d}".format(self._next_group_id)
        if not isinstance(group_id, str) or not re.fullmatch(r"grp_\d{6,}", group_id):
            raise ValueError("Invalid group ID: {!r}".format(group_id))
        if self.find_group_by_id(group_id) is not None:
            raise ValueError("Duplicate group ID: " + group_id)
        self._next_group_id = max(self._next_group_id, int(group_id[4:]) + 1)
        group.group_id = group_id
        group.member_ids = list(members)
        self.groups.append(group)
        return group

    @property
    def selected_entities(self):
        return [entity for entity_id in self.selected_ids
                for entity in [self.find_by_id(entity_id)] if entity is not None]

    @property
    def primary_selection(self):
        return self.find_by_id(self.primary_selection_id)

    @property
    def editable_selection(self):
        return [entity for entity in self.selected_entities if not entity.locked]

    def clean_selection(self):
        """Drop stale references after removal, load, and history restoration."""
        self.selected_ids = list(dict.fromkeys(
            value for value in self.selected_ids if self.find_by_id(value) is not None))
        if self.primary_selection_id not in self.selected_ids:
            self.primary_selection_id = self.selected_ids[-1] if self.selected_ids else None
        group = self.find_group_by_id(self.selected_group_id)
        if group is None or set(group.member_ids) != set(self.selected_ids):
            self.selected_group_id = None

    def update(self):
        for entity in self.root_entities:
            entity.update_transform()

    def get_flat_render_list(self):
        result = []
        def visit(node):
            if not node.visible:
                return
            if node.model is not None:
                result.append(node)
            for child in node.children:
                visit(child)
        for root in self.root_entities:
            visit(root)
        return result
