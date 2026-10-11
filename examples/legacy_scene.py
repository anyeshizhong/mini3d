"""Shared compatibility types for the original geometry and URDF demos.

These demos use scalar scale, [pitch, yaw, roll] and extra @ T @ R @ S.
The editor's mini3d.scene uses XYZ Euler angles, vector scale and T @ R @ S
outside the imported basis. Keep this adapter here to preserve demo behavior;
new editor/API features should use mini3d.scene.
"""
from pathlib import Path

import numpy as np
import pygame
from stl import mesh

from mini3d.math3d import get_rotation_matrix, normalize

DTYPE = np.float32
PROJECT = Path(__file__).resolve().parents[1]

class Entity:
    def __init__(self, model=None, pos=None, rot=None, world_matrix=None, name="", scale=1.0):
        self.model = model
        self.pos = np.array(pos if pos is not None else [0,0,0], dtype=DTYPE)

        self.rot = np.array(rot if rot is not None else [0,0,0], dtype=DTYPE)

        self.scale = float(scale)

        self.parent = None
        self.children = []

        self.name = name

        self.isaxes = False

        self.local_matrix = np.eye(4, dtype=DTYPE)
        self.world_matrix = (np.asarray(world_matrix, dtype=DTYPE)
                             if world_matrix is not None else np.eye(4, dtype=DTYPE))

        self.extra_local = np.eye(4, dtype=DTYPE)

    def add_child(self, child):
        self.children.append(child)
        child.parent = self

    def update_transform(self, parent_matrix=None):
        S = np.diag([self.scale, self.scale, self.scale, 1.0]).astype(DTYPE)

        R_mat = get_rotation_matrix(self.rot[0], self.rot[1], self.rot[2])
        R = np.eye(4, dtype=DTYPE)
        R[:3, :3] = R_mat

        T = np.eye(4, dtype=DTYPE)
        T[:3, 3] = self.pos

        self.local_matrix = self.extra_local @ T @ R @ S

        if parent_matrix is not None:
            self.world_matrix = parent_matrix @ self.local_matrix
        else:
            self.world_matrix = self.local_matrix

        for child in self.children:
            child.update_transform(self.world_matrix)

    def handle_input(self, keys, dt=1.0 / 60):
        if keys[pygame.K_i]: self.pos[1] -= 60 * dt  # 上
        if keys[pygame.K_k]: self.pos[1] += 60 * dt  # 下
        if keys[pygame.K_j]: self.pos[0] -= 60 * dt  # 左
        if keys[pygame.K_l]: self.pos[0] += 60 * dt  # 右
        if keys[pygame.K_u]: self.rot[1] += 3 * dt # 旋转
        if keys[pygame.K_o]: self.rot[1] -= 3 * dt

class Scene:
    def __init__(self):
        self.root_entities = [] # 顶层实体
        self.light_dir = normalize(np.array([-0.5, 1.0, -0.5], dtype=DTYPE))
        self.ambient = 0.2
        self.diffuse = 0.8

    def add(self, entity):
        self.root_entities.append(entity)

    def update(self):
        """更新整个场景图"""
        for entity in self.root_entities:
            entity.update_transform(parent_matrix=None)

    def get_flat_render_list(self):
        """获取扁平化的渲染列表（深度遍历）"""
        render_list = []
        def traverse(node):
            if node.model is not None or getattr(node, "isaxes", False):
                render_list.append(node)
            for child in node.children:
                traverse(child)

        for entity in self.root_entities:
            traverse(entity)
        return render_list

class Mesh:
    def __init__(self, vertices, indices, color=np.array([200, 200, 200])):
        verts = np.asarray(vertices, dtype=DTYPE)
        self.vertices = np.zeros((len(verts), 4), dtype=DTYPE)
        self.vertices[:, :3] = verts
        self.vertices[:, 3] = 1.0
        self.indices = np.asarray(indices, dtype=np.int32)

        self.base_color = np.array(color, dtype=np.float32)  # 新增：统一材质色

        N_faces = len(self.indices)
        self.colors = np.tile(color, (N_faces, 1)).astype(np.uint8)

        self.vertex_normals = self.compute_vertex_normals()

    def compute_vertex_normals(self):
        """
        计算平滑法线：
        1. 遍历所有三角形，算出面法线。
        2. 把面法线累加到它所包含的三个顶点上。
        3. 最后对每个顶点归一化。
        """
        v_normals = np.zeros((len(self.vertices), 3), dtype=DTYPE)

        tris_verts = self.vertices[self.indices][:, :, :3]

        v0 = tris_verts[:, 0]
        v1 = tris_verts[:, 1]
        v2 = tris_verts[:, 2]
        edge1 = v1 - v0
        edge2 = v2 - v0
        face_normals = np.cross(edge1, edge2)

        for i, face in enumerate(self.indices):
            v_normals[face[0]] += face_normals[i]
            v_normals[face[1]] += face_normals[i]
            v_normals[face[2]] += face_normals[i]

        norms = np.linalg.norm(v_normals, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        v_normals = v_normals / norms

        return v_normals

class STLModel(Mesh):
    """
    STL 加载器 (自动转为 Indexed Mesh)
    """
    def __init__(self, filename, color=np.array([200, 180, 150])):
        stl_mesh = mesh.Mesh.from_file(filename)

        points = stl_mesh.vectors.reshape(-1, 3)

        unique_points, inverse = np.unique(points, axis=0, return_inverse=True)

        indices = inverse.reshape(-1, 3)

        print(f"STL Loaded: {filename}")
        print(f"  原始顶点数: {len(points)} -> 优化后: {len(unique_points)} (节省 {(1-len(unique_points)/len(points))*100:.1f}%)")

        super().__init__(unique_points, indices, color)
