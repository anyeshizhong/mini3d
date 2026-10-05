from pathlib import Path
from mini3d.viewer import Viewer, world_bounds
from mini3d.urdf_loader import load_urdf, build_entity_tree
import pygame
import numpy as np
from stl import mesh
import math
from pygame.locals import OPENGL, DOUBLEBUF, RESIZABLE
from mini3d.gl_renderer import GLRenderer
from mini3d.geometry import make_box, make_sphere, make_cylinder
from mini3d.math3d import normalize, get_rotation_matrix, xyzrpy_to_T

# --- 常量定义 ---
FOV = 500
WIDTH, HEIGHT = 800, 600
DTYPE = np.float32

# --- 辅助函数 ---


def urdf_rpy_matrix(roll, pitch, yaw):
    """
    URDF 约定：fixed-axis RPY (roll around X, pitch around Y, yaw around Z)
    常用实现：R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    """
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)

    Rx = np.array([[1,0,0],[0,cr,-sr],[0,sr,cr]], dtype=DTYPE)
    Ry = np.array([[cp,0,sp],[0,1,0],[-sp,0,cp]], dtype=DTYPE)
    Rz = np.array([[cy,-sy,0],[sy,cy,0],[0,0,1]], dtype=DTYPE)

    return Rz @ Ry @ Rx


# ================= 1. 实体类 (Entity) =================
class Entity:
    def __init__(self, model=None, pos=None, rot=None, world_matrix=None, name="", scale=1.0):
        self.model = model
        self.pos = np.array(pos if pos is not None else [0,0,0], dtype=DTYPE)

        # rot 约定：rot = [pitch, yaw, roll] ——务必与你 get_rotation_matrix 一致
        self.rot = np.array(rot if rot is not None else [0,0,0], dtype=DTYPE)

        self.scale = float(scale)

        self.parent = None
        self.children = []

        self.name = name
        
        self.isaxes = False

        # 变换矩阵
        self.local_matrix = np.eye(4, dtype=DTYPE)
        self.world_matrix = (np.asarray(world_matrix, dtype=DTYPE)
                             if world_matrix is not None else np.eye(4, dtype=DTYPE))

        # 额外局部变换（URDF joint / 修正）
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

        # 统一约定：local = extra @ T @ R @ S
        self.local_matrix = self.extra_local @ T @ R @ S

        if parent_matrix is not None:
            self.world_matrix = parent_matrix @ self.local_matrix
        else:
            self.world_matrix = self.local_matrix

        for child in self.children:
            child.update_transform(self.world_matrix)
    
    def handle_input(self, keys):
        # 简单的控制示例
        if keys[pygame.K_i]: self.pos[1] -= 1  # 上
        if keys[pygame.K_k]: self.pos[1] += 1  # 下
        if keys[pygame.K_j]: self.pos[0] -= 1  # 左
        if keys[pygame.K_l]: self.pos[0] += 1  # 右
        if keys[pygame.K_u]: self.rot[1] += 0.05 # 旋转
        if keys[pygame.K_o]: self.rot[1] -= 0.05

# ================= 2. 场景类 (Scene) =================
class Scene:
    def __init__(self):
        self.root_entities = [] # 顶层实体
        # 光照设置 (方向光)
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
            if node.model:
                render_list.append(node)
            for child in node.children:
                traverse(child)
        
        for entity in self.root_entities:
            traverse(entity)
        return render_list



# ================= 3. 渲染器 (Renderer) =================
# 迁移到 gl_renderer.py 文件中


# Camera interaction lives in mini3d.viewer.

# ================= 5. 数据结构层 (Mesh) =================
class Mesh:
    def __init__(self, vertices, indices, color=np.array([200, 200, 200])):
        # ... (之前的 vertices 和 indices 代码保持不变) ...
        verts = np.asarray(vertices, dtype=DTYPE)
        self.vertices = np.zeros((len(verts), 4), dtype=DTYPE)
        self.vertices[:, :3] = verts
        self.vertices[:, 3] = 1.0
        self.indices = np.asarray(indices, dtype=np.int32)
        
        self.base_color = np.array(color, dtype=np.float32)  # 新增：统一材质色
        
        # 颜色
        N_faces = len(self.indices)
        self.colors = np.tile(color, (N_faces, 1)).astype(np.uint8)
        
        # --- 新增：预计算顶点法线 ---
        self.vertex_normals = self.compute_vertex_normals()

    def compute_vertex_normals(self):
        """
        计算平滑法线：
        1. 遍历所有三角形，算出面法线。
        2. 把面法线累加到它所包含的三个顶点上。
        3. 最后对每个顶点归一化。
        """
        # 初始化所有顶点法线为 0
        v_normals = np.zeros((len(self.vertices), 3), dtype=DTYPE)
        
        # 提取顶点坐标 (N_faces, 3, 3)
        # 这是一个很棒的 NumPy 索引技巧，不用循环就能拿到所有三角形的坐标
        tris_verts = self.vertices[self.indices][:, :, :3]
        
        # 计算所有面法线 (Cross Product)
        v0 = tris_verts[:, 0]
        v1 = tris_verts[:, 1]
        v2 = tris_verts[:, 2]
        edge1 = v1 - v0
        edge2 = v2 - v0
        # (N_faces, 3)
        face_normals = np.cross(edge1, edge2) 
        
        # --- 累加法线到顶点 ---
        # 这一步用循环做比较直观，虽然也能向量化但容易写错
        # 遍历每个面，把它的法线加到它的3个顶点头上
        for i, face in enumerate(self.indices):
            # face 是 [idx1, idx2, idx3]
            # face_normals[i] 是当前面的法线
            v_normals[face[0]] += face_normals[i]
            v_normals[face[1]] += face_normals[i]
            v_normals[face[2]] += face_normals[i]
            
        # --- 归一化 ---
        norms = np.linalg.norm(v_normals, axis=1, keepdims=True)
        # 防止除以0
        norms = np.where(norms == 0, 1, norms)
        v_normals = v_normals / norms
        
        return v_normals

class STLModel(Mesh):
    """
    STL 加载器 (自动转为 Indexed Mesh)
    """
    def __init__(self, filename, color=np.array([200, 180, 150])):
        # 加载原始数据
        stl_mesh = mesh.Mesh.from_file(filename)
        # stl_mesh.vectors 是 (N, 3, 3)
        
        # --- 关键步骤：去重并生成索引 ---
        # 1. 把 (N, 3, 3) 展平成 (N*3, 3)
        points = stl_mesh.vectors.reshape(-1, 3)
        
        # 2. 使用 unique 找出唯一顶点，并获取反向索引
        # unique_points: (V, 3) 唯一的顶点
        # inverse: (N*3,) 原来每个点对应 unique_points 里的哪个下标
        unique_points, inverse = np.unique(points, axis=0, return_inverse=True)
        
        # 3. 重组索引 (N, 3)
        indices = inverse.reshape(-1, 3)
        
        print(f"STL Loaded: {filename}")
        print(f"  原始顶点数: {len(points)} -> 优化后: {len(unique_points)} (节省 {(1-len(unique_points)/len(points))*100:.1f}%)")
        
        # 调用父类初始化
        super().__init__(unique_points, indices, color)



def main():
    pygame.init()
    width, height = 1200, 800
    pygame.display.set_mode((width, height), OPENGL | DOUBLEBUF | RESIZABLE)
    pygame.display.set_caption("Mini3D | Drag: orbit | Shift+drag: pan | Wheel: zoom | F/Home/R")
    renderer = GLRenderer(width, height)
    clock = pygame.time.Clock()
    scene = Scene()
    scene.light_dir = normalize(np.array([0.0, 1.0, 1.0], dtype=DTYPE))
    asset_dir = Path(__file__).resolve().parent
    cube_model = STLModel(str(asset_dir / "model" / "cube.STL"), color=np.array([100, 200, 100]))
    model = Entity(cube_model, pos=[45, 0, 0], name="STL cube")
    model.isaxes = True
    scene.add(model)

    box_model = Mesh(*make_box(w=10, h=10, d=10), color=np.array([100, 100, 255]))
    entity_box = Entity(box_model, pos=[50, 0, 0], name="Box")
    scene.add(entity_box)
    viewer = Viewer(scene, width, height)
    controllable_entities = [entity_box, model]
    control_target_idx = 0
    viewer.selected_entity = controllable_entities[control_target_idx]
    print("Camera: drag to orbit; Shift+drag/right drag to pan; wheel to zoom")
    print("F: focus selection; Home: frame all; 1/3/7: front/right/top; Ctrl: opposite; R: reset")
    print("Tab: select focus target; box moves automatically; Esc: exit")
    # The moving box completes its circle around the origin in the XZ plane.
    # Frame the whole path once at startup so it remains visible while moving.
    lo, hi = world_bounds(scene.root_entities)
    viewer.controller.focus_bounds(np.minimum(lo, [-55, -5, -55]),
                                   np.maximum(hi, [55, 5, 55]), viewer.aspect)
    viewer.save_camera()
    angle = 0.0
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.VIDEORESIZE:
                renderer.resize(max(1, event.w), max(1, event.h))
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                control_target_idx = (control_target_idx + 1) % len(controllable_entities)
                viewer.selected_entity = controllable_entities[control_target_idx]
                print("Selected:", viewer.selected_entity.name)
            viewer.handle_event(event)
        angle += dt
        entity_box.pos[:] = [50 * math.cos(angle), 0, 50 * math.sin(angle)]
        scene.update()
        renderer.render(scene, viewer.camera)
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
