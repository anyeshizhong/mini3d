from pathlib import Path
from mini3d.viewer import Viewer
# main.py
import math
import numpy as np
import pygame
from pygame.locals import OPENGL, DOUBLEBUF, RESIZABLE
from stl import mesh


# Mini3D importsd
from mini3d.geometry import make_box
from mini3d.math3d import normalize, get_rotation_matrix
from mini3d.gl_renderer import GLRenderer
from mini3d.urdf_loader import load_urdf, build_entity_tree, joint_transform


DTYPE = np.float32


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
        render_list = []
        def traverse(node):
            if node.model is not None or getattr(node, "isaxes", False):
                render_list.append(node)
            for child in node.children:
                traverse(child)

        for entity in self.root_entities:
            traverse(entity)
        return render_list


# ================= 3. 渲染器 (Renderer) =================
# 迁移到 gl_renderer.py 文件中


# ================= 4. 相机类 (Camera) =================


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


# -------------------------
# main
# -------------------------
def main():
    pygame.init()
    W, H = 1200, 800
    pygame.display.set_mode((W, H), OPENGL | DOUBLEBUF | RESIZABLE)
    pygame.display.set_caption("Mini3D URDF | Drag: orbit | Shift+drag: pan | Wheel: zoom | F/Home/R")

    gl_renderer = GLRenderer(W, H)
    clock = pygame.time.Clock()

    # ---- Load URDF ----
    asset_dir = Path(__file__).resolve().parent
    urdf = load_urdf(
        str(asset_dir / "model" / "07_urdf_car" / "car" / "urdf" / "car.urdf"),
        package_map={"car": str(asset_dir / "model" / "07_urdf_car" / "car")}
    )

    def model_loader(mesh_path, rgba01):
        rgb = np.array([rgba01[0]*255, rgba01[1]*255, rgba01[2]*255], dtype=np.float32)
        return STLModel(mesh_path, color=rgb)

    link_entities, joint_order = build_entity_tree(
        urdf,
        EntityClass=Entity,
        model_loader=model_loader
    )

    # ---- Scene ----
    scene = Scene()
    scene.light_dir = normalize(np.array([0.0, 0.0, 1.0], dtype=DTYPE))

    root = link_entities[urdf.root_link]
    root.scale = 1000.0
    root.pos = np.array([0.0, 30.0, 14.0], dtype=DTYPE)
    root.rot = np.array([0.0, 0.0, 0.0], dtype=DTYPE)
    scene.add(root)
    
    # root.isaxes = True  # 画坐标轴辅助观察

    # ---- Add a ground box for reference ----
    box_verts, box_inds = make_box(w=200, h=200, d=10)
    ground_model = Mesh(box_verts, box_inds, color=np.array([120,120,120]))
    ground = Entity(model=ground_model, pos=[0, 0, -5], rot=[0,0,0], scale=1.0)
    scene.add(ground)

    viewer = Viewer(scene, W, H)
    viewer.selected_entity = root
    viewer.focus(root)
    viewer.save_camera()
    print("Camera: drag to orbit; Shift+drag/right drag to pan; wheel to zoom")
    print("F: focus car/selected wheel; Home: frame all; 1/3/7: front/right/top; R: reset")

    # ---- Joint state ----
    q = {jname: 0.0 for jname in joint_order}
    active_joint_idx = 0
    joint_speed = 1.2  # radians per second

    # ---- Debug: draw axes at some links / joints ----
    # 你可以让某些 link_ent.isaxes=True 来看 link frame
    # 比如：让末端 link 画轴
    # link_entities["some_link_name"].isaxes = True
    # link_entities["wheel_fl"].isaxes = True
    
    print("links:", list(link_entities.keys()))
    print("joints:", joint_order)


    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        # Events
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            elif e.type == pygame.VIDEORESIZE:
                gl_renderer.resize(max(1, e.w), max(1, e.h))
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_TAB and joint_order:
                    active_joint_idx = (active_joint_idx + 1) % len(joint_order)
                    viewer.selected_entity = link_entities[urdf.joints[joint_order[active_joint_idx]].child]
                    print("Active joint:", joint_order[active_joint_idx])
            viewer.handle_event(e)

        keys = pygame.key.get_pressed()

        # Move whole robot root (这就是“车前进”的关键：移动 root)
        # I/K 前后，J/L 左右，U/O 转向
        if keys[pygame.K_i]: root.pos[1] -= 60.0 * dt
        if keys[pygame.K_k]: root.pos[1] += 60.0 * dt
        if keys[pygame.K_j]: root.pos[0] -= 60.0 * dt
        if keys[pygame.K_l]: root.pos[0] += 60.0 * dt
        if keys[pygame.K_u]: root.rot[1] += 1.8 * dt
        if keys[pygame.K_o]: root.rot[1] -= 1.8 * dt

        # ro control (选中一个关节调角)
        if joint_order:
            active_joint = joint_order[active_joint_idx]
            if keys[pygame.K_z]: q[active_joint] += joint_speed * dt
            if keys[pygame.K_x]: q[active_joint] -= joint_speed * dt

        # Apply joint transforms: set child_link.extra_local
        for jname in joint_order:
            j = urdf.joints[jname]
            angle = q[jname]

            if j.joint_type in ("fixed",):
                T = joint_transform(j.origin_xyz, j.origin_rpy, j.axis_xyz, 0.0)
            elif j.joint_type in ("revolute", "continuous"):
                T = joint_transform(j.origin_xyz, j.origin_rpy, j.axis_xyz, angle)
            elif j.joint_type in ("prismatic",):
                # prismatic: translate along axis in joint frame (simple version)
                # T = T(origin) * R(origin_rpy) * T(axis* q)
                # 这里给个最小实现（足够让车/滑台“动起来”）
                base = joint_transform(j.origin_xyz, j.origin_rpy, j.axis_xyz, 0.0)
                axis = j.axis_xyz / (np.linalg.norm(j.axis_xyz) + 1e-12)
                trans = np.eye(4, dtype=DTYPE)
                trans[:3, 3] = axis * angle
                T = base @ trans
            else:
                T = joint_transform(j.origin_xyz, j.origin_rpy, j.axis_xyz, angle)

            child_ent = link_entities[j.child]
            child_ent.extra_local = T

        # Update
        scene.update()

        # Render
        gl_renderer.render(scene, viewer.camera)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
