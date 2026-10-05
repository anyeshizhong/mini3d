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


# ================= 4. 相机类 (Camera) =================

class Camera:
    def __init__(self, camera_pos, camera_nv):
        """
        __init__ 的 Docstring
        
        :param camera_pos: 相机系的原点在世界系的坐标
        :param camera_nv: 相机系的基底在世界系的表示，第一行是X轴方向，第二行是Y轴方向，第三行是Z轴方向
        """ 
        self.cam_pos = camera_pos
        self.cam_nv = camera_nv
        self.cam_pos_ = camera_pos.copy()
        self.cam_nv_ = camera_nv.copy()
        
        self.fov = 500.0
        self.fov_min = 300.0
        self.fov_max = 3000.0

        
        self.yaw = 0
        self.pitch = 0
        self.roll = 0
        
        # 运动参数
        self.move_speed = 1.0
        self.rotate_speed = 0.01
        
        # 根据公式(X Y Z)(p-C_0)得到，世界系点p到相机系q的变换
        self.T_w_to_c = np.eye(4, dtype=DTYPE)
        self.T_w_to_c[:3, :3] = self.cam_nv_
        self.T_w_to_c[:3, 3] = - self.cam_nv_ @ self.cam_pos_
        pass
    def update(self):
        # 构建旋转矩阵
        cx, sx = math.cos(self.pitch), math.sin(self.pitch)
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
                
        # 组合旋转 (Euler Angles)
        R_x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        R_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        R = R_x @ R_y # 先绕X再绕Y R = R_y @ R_x @ R_z（旋转顺序Z→X→Y，矩阵顺序Y→X→Z） 小心万向节死锁现象
        
        self.cam_nv_ = R @ self.cam_nv
        self.T_w_to_c[:3, :3] = self.cam_nv_
        self.T_w_to_c[:3, 3] = - self.cam_nv_ @ self.cam_pos_
        
    def handle_input(self, keys): 
        if keys[pygame.K_w]: 
            self.cam_pos_ += self.cam_nv_[2] * self.move_speed
        if keys[pygame.K_s]: 
            self.cam_pos_ -= self.cam_nv_[2] * self.move_speed
        if keys[pygame.K_a]: 
            self.cam_pos_ -= self.cam_nv_[0] * self.move_speed
        if keys[pygame.K_d]: 
            self.cam_pos_ += self.cam_nv_[0] * self.move_speed 
        # 简单的飞行 (Q/E)
        if keys[pygame.K_q]: 
            self.cam_pos_ -= self.cam_nv_[1] * self.move_speed
        if keys[pygame.K_e]: 
            self.cam_pos_ += self.cam_nv_[1] * self.move_speed
        
        if keys[pygame.K_r]: 
            self.cam_pos_ = self.cam_pos.copy()
            self.yaw = 0
            self.pitch = 0
        
        # 控制yaw,绕y轴转动
        if keys[pygame.K_LEFT]: self.yaw += self.rotate_speed
        if keys[pygame.K_RIGHT]: self.yaw -= self.rotate_speed
        # 控制pitch，绕x轴转动
        if keys[pygame.K_UP]: self.pitch -= self.rotate_speed
        if keys[pygame.K_DOWN]: self.pitch += self.rotate_speed
        pass

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
        
        print(f"✓ STL Loaded: {filename}")
        print(f"  原始顶点数: {len(points)} -> 优化后: {len(unique_points)} (节省 {(1-len(unique_points)/len(points))*100:.1f}%)")
        
        # 调用父类初始化
        super().__init__(unique_points, indices, color)


# --- 主程序 ---

pygame.init()
WIDTH, HEIGHT = 1200, 800
screen = pygame.display.set_mode((WIDTH, HEIGHT), OPENGL | DOUBLEBUF | RESIZABLE)
pygame.display.set_caption("Winter Leaf Engine v2.0 (OpenGL)")

gl_renderer = GLRenderer(WIDTH, HEIGHT)

clock = pygame.time.Clock()

# 1. 场景初始化
scene = Scene()
scene.light_dir = normalize(np.array([0.0, 1.0, 1.0], dtype=DTYPE))

# 2. 资源加载
cube_model = STLModel("model/cube.stl", color=np.array([100, 200, 100])) # 假设用同一个模型演示
model = Entity(cube_model, pos=[45, 0, 0])
model.isaxes = True
scene.add(model)



# 方块
box_verts, box_inds = make_box(w=10, h=10, d=10)
box_model = Mesh(box_verts, box_inds, color=np.array([100, 100, 255]))
# 一个方块放在右边
entity_box = Entity(box_model, pos=[40, 0, 100])
scene.add(entity_box)


# 3. 系统组件
cam_pos = np.array([100.0, 0.0, 0.0], dtype=DTYPE)
# 让相机看向原点：简单 LookAt 逻辑
# target = np.array([0,0,0], dtype=DTYPE)
# fwd = normalize(target - cam_pos) # Z轴 (LookDir)
# right = normalize(np.cross(np.array([0,1,0]), fwd)) # X轴 (World Up cross Fwd) (左手系/右手系调整这里)
# up = np.cross(fwd, right) # Y轴

# 构造旋转矩阵 [Right, Up, -Fwd] (取决于你的坐标系定义，这里沿用你的逻辑)
# 你的原始代码：cam_nv 第三行是 -Z。
# cam_nv = np.array([right, up, -fwd]) 
cam_nv = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, -1.0], [-1.0, 0.0, 0.0]]) 

camera = Camera(cam_pos, cam_nv)
# 4. 状态控制
running = True
control_target_idx = 0
# controllable_entities = [entity_box, model] # 可以按 Tab 切换控制的列表

entities = scene.get_flat_render_list()
print("entities:", len(entities))
print("with model:", sum(1 for e in entities if e.model is not None))
for e in entities[:3]:
    if e.model:
        print(e.name, "verts:", len(e.model.vertices))
for e in entities[:5]:
    print(e.world_matrix)


control_target_idx = 0

dt = 0
v_x = 0.1
v_y = 0.1
v_z = 0
g = 0.1
angle = 0
L = 500

while running:
    # --- Event ---
    for e in pygame.event.get():
        if e.type == pygame.QUIT: running = False
        elif e.type == pygame.VIDEORESIZE:
            screen = pygame.display.set_mode((e.w, e.h), OPENGL | DOUBLEBUF | RESIZABLE)
            gl_renderer.resize(e.w, e.h)
        # elif e.type == pygame.KEYDOWN:
        #         if e.key == pygame.K_TAB:
        #             control_target_idx = (control_target_idx + 1) % len(controllable_entities)
        #             print("控制目标切换到:", controllable_entities[control_target_idx].name)
        
        elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_1: # perspective
                    # Look_At:
                    target = entity_box.pos
                    camera.cam_pos_ = target + np.array([30, 0, 0])
                    camera.cam_nv = np.array([[0,1,0],
                                               [0,0,-1],
                                               [-1,0,0]])
                    # Z = normalize(target - camera.cam_pos_) # Z轴 (LookDir)
                    # X = normalize(np.cross(np.array([0,1,0]), Z)) # X轴 (World Up cross Fwd) (左手系/右手系调整这里)
                    # Y = np.cross(Z, X)
                    # camera.cam_nv_ = np.array([X, Y, Z]).T
                    camera.yaw = 0
                    camera.pitch = 0
                    pass
                elif e.key == pygame.K_2: # top
                    target = entity_box.pos
                    camera.cam_pos_ = target + np.array([0, 0, 30])
                    camera.cam_nv = np.array([[0,1,0],
                                               [1,0,0],
                                               [0,0,-1]])
                    camera.yaw = 0
                    camera.pitch = 0
                elif e.key == pygame.K_3: # side
                    target = entity_box.pos
                    camera.cam_pos_ = target + np.array([0, 30, 0])
                    camera.cam_nv = np.array([[-1,0,0],
                                               [0,0,-1],
                                               [0,-1,0]])
                    camera.yaw = 0
                    camera.pitch = 0
        elif e.type == pygame.MOUSEWHEEL:
            # e.y: 向上滚是 +1，向下滚是 -1（pygame 2.x）
            zoom = 1.1 ** e.y
            camera.fov = float(np.clip(camera.fov * zoom, camera.fov_min, camera.fov_max))
            print("camera.fov =", camera.fov)
            
        

    # --- Update ---
    keys = pygame.key.get_pressed()
    
    # 相机一直可以控制
    camera.handle_input(keys)
    camera.update()
    
    # 实体控制
    # current_entity = controllable_entities[control_target_idx]
    # current_entity.handle_input(keys)
    
    
    
    
    # 物理公式
    dt = clock.get_time() / 1000.0  # 秒
    # entity_box.pos[2] += v_z * dt
    # entity_box.pos[1] += v_y * dt
    # v_z -= g * dt
    angle += 1 * dt
    entity_box.pos[0] = 0 + 50 * math.cos(angle)    # X
    entity_box.pos[1] = 0                               # Y (保持高度)
    entity_box.pos[2] = 0 + 50 * math.sin(angle)    # Z

    
    
    # 位置限制
    entity_box.pos[0] = np.clip(entity_box.pos[0], -L,L)
    entity_box.pos[1] = np.clip(entity_box.pos[1], -L,L)
    entity_box.pos[2] = np.clip(entity_box.pos[2], -L,L)
    
    
    
    # 更新场景矩阵
    scene.update()

    # --- Render ---
    screen.fill((30, 30, 35))

    gl_renderer.render(scene, camera)


    fps = int(clock.get_fps())
        
        
    pygame.display.flip()
    clock.tick(60)

pygame.quit()