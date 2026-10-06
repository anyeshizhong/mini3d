"""Reusable scene instances; mesh/material resources are shared by clones."""
import numpy as np


def rotation_xyz(angles):
    x, y, z = angles
    cx, cy, cz = np.cos(angles)
    sx, sy, sz = np.sin(angles)
    return (np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @
            np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @
            np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]))


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
        for child in self.children:
            duplicate.add_child(child.clone())
        return duplicate


class Scene:
    def __init__(self):
        self.root_entities = []
        self.light_dir = np.array([.4, -.5, .8], np.float32)
        self.light_dir /= np.linalg.norm(self.light_dir)
        self.ambient, self.diffuse = .3, .7
        self.show_grid = True
        self.show_axes = False
        self.render_mode = "Lit"

    def add(self, entity):
        self.root_entities.append(entity)

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
