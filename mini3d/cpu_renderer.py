# cpu_renderer.py
import pygame
import numpy as np

DTYPE = np.float32


def project(screen, point_camera, fov):
    return np.array([
        fov * (point_camera[0] / point_camera[2]) + screen.get_rect().width / 2,
        fov * (point_camera[1] / point_camera[2]) + screen.get_rect().height / 2
    ])


def draw_line(screen, color, start, end, camera, near=None, width=1):
    near = camera.near if near is None else near
    az, bz = start[2], end[2]
    if az < near and bz < near:
        return None
    if az < near:
        t = (near - az) / (bz - az)
        start = start + t * (end - start)
    if bz < near:
        t = (near - bz) / (az - bz)
        end = end + t * (start - end)

    focal = screen.get_height() / (2 * np.tan(np.deg2rad(camera.fov_y) / 2))
    sp1 = project(screen, start, focal)
    sp2 = project(screen, end, focal)
    pygame.draw.line(screen, color, (int(sp1[0]), int(sp1[1])), (int(sp2[0]), int(sp2[1])), width)

    
def draw_axes(screen, camera, T_o_to_w, axis_len=20.0, width=3, near=None):
    """
    使用 draw_line 在屏幕上绘制一个坐标轴（RGB = XYZ）
    - camera: 需要 camera.T_w_to_c
    - T_o_to_w: 物体到世界的 4x4
    - axis_len: 坐标轴长度（世界单位）
    """
    O = T_o_to_w @ np.array([0, 0, 0, 1], dtype=DTYPE)
    X = T_o_to_w @ np.array([axis_len, 0, 0, 1], dtype=DTYPE)
    Y = T_o_to_w @ np.array([0, axis_len, 0, 1], dtype=DTYPE)
    Z = T_o_to_w @ np.array([0, 0, axis_len, 1], dtype=DTYPE)

    # 变到相机系（你的 draw_line 输入是相机系点）
    O_c = camera.T_w_to_c @ O
    X_c = camera.T_w_to_c @ X
    Y_c = camera.T_w_to_c @ Y
    Z_c = camera.T_w_to_c @ Z

    draw_line(screen, (255, 0, 0), O_c, X_c, camera, near=near, width=width)  # X 红
    draw_line(screen, (0, 255, 0), O_c, Y_c, camera, near=near, width=width)  # Y 绿
    draw_line(screen, (0, 0, 255), O_c, Z_c, camera, near=near, width=width)  # Z 蓝

class Renderer:
    def __init__(self, screen):
        self.screen = screen
        self.width = screen.get_width()
        self.height = screen.get_height()
        self.half_w = self.width / 2
        self.half_h = self.height / 2

    def render(self, scene, camera):
        self.width, self.height = self.screen.get_size()
        self.half_w, self.half_h = self.width / 2, self.height / 2
        entities = scene.get_flat_render_list()
        if not entities: return
        # print("CPU Renderer: Drawing {} entities".format(len(entities)))

        all_verts_world = [] 
        all_indices = []     
        all_colors = []      
        all_vert_intensities = [] # <--- 新增：存储每个顶点的光照强度
        
        vertex_offset_counter = 0 

        # --- 1. 批处理：Model -> World ---
        for ent in entities:
            # mesh_data = ent.model
            # if not isinstance(mesh_data, Mesh): continue
            mesh_data = getattr(ent, "model", None)
            if mesh_data is None:
                continue

            # 鸭子类型：只要它像 Mesh（有这些字段）就画
            need = ("vertices", "indices", "colors", "vertex_normals")
            if not all(hasattr(mesh_data, k) for k in need):
                continue

            # A. 顶点变换 (位置)
            verts_world = mesh_data.vertices @ ent.world_matrix.T
            all_verts_world.append(verts_world)
            
            # B. 法线变换 (方向)
            # 只有旋转矩阵影响法线，平移不影响。提取 world_matrix 的左上 3x3
            # Normal_World = Normal_Local @ Rotation_Matrix.T
            rot_matrix = ent.world_matrix[:3, :3]
            norms_world = mesh_data.vertex_normals @ rot_matrix.T
            
            # C. 计算顶点光照 (Vertex Lighting) - 核心改动
            # 在这里直接算出每个点的亮度，而不是等三角形组装
            # dot(N, L)
            # light_dir 是反向的吗？通常 light_dir 指向光源。
            # 如果 scene.light_dir 是光线射入方向，需要取反；如果是指向光源方向，直接点乘。
            # 假设 scene.light_dir 是指向光源的归一化向量。
            v_intensity = np.dot(norms_world, scene.light_dir)
            
            # 简单的半兰伯特或直接截断，防止背光全黑太难看
            # 0.5 * dot + 0.5 是半兰伯特，看起来更柔和，类似 SolidWorks 默认光
            v_intensity = v_intensity * 0.5 + 0.5 
            v_intensity = np.clip(v_intensity, 0, 1)
            
            # 叠加环境光
            final_v_intensity = scene.ambient + scene.diffuse * v_intensity
            all_vert_intensities.append(final_v_intensity) # 存起来

            # D. 索引偏移 & 颜色
            current_indices = mesh_data.indices + vertex_offset_counter
            all_indices.append(current_indices)
            all_colors.append(mesh_data.colors)
            vertex_offset_counter += len(mesh_data.vertices)

        if not all_verts_world: return
        
        # 合并数据
        global_verts_world = np.vstack(all_verts_world)
        global_indices = np.vstack(all_indices)
        global_colors = np.vstack(all_colors)
        global_intensities = np.hstack(all_vert_intensities) # (Total_V, ) 扁平数组

        # --- 2. World -> Camera -> Project (和之前一样) ---
        verts_cam = global_verts_world @ camera.T_w_to_c.T
        x, y, z = verts_cam[:, 0], verts_cam[:, 1], verts_cam[:, 2]
        
        screen_coords = np.zeros((len(verts_cam), 2), dtype=np.int32)
        valid_mask = (z > camera.near) & (z < camera.far)
        
        if np.any(valid_mask):
            focal = self.height / (2 * np.tan(np.deg2rad(camera.fov_y) / 2))
            factor = focal / z[valid_mask]
            screen_coords[valid_mask, 0] = (x[valid_mask] * factor + self.half_w).astype(np.int32)
            screen_coords[valid_mask, 1] = (y[valid_mask] * factor + self.half_h).astype(np.int32)

        # --- 3. 组装 (Assembly) ---
        # 查表
        tris_screen_coords = screen_coords[global_indices]
        tris_z_values = z[global_indices]
        
        # 关键：查表获取每个三角形 3 个顶点的亮度
        # (Total_N, 3)
        tris_vert_intensities = global_intensities[global_indices]
        
        # 算出三角形的平均亮度 (Gouraud 的简化版)
        # Face_Intensity = (I_v1 + I_v2 + I_v3) / 3
        face_intensities = np.mean(tris_vert_intensities, axis=1)

        # --- 4. 剔除与排序 ---
        tri_valid = valid_mask[global_indices].all(axis=1)
        
        visible_tris = tris_screen_coords[tri_valid]
        visible_z = tris_z_values[tri_valid]
        visible_colors = global_colors[tri_valid]
        visible_intensities = face_intensities[tri_valid] # 对应的亮度
        
        if len(visible_tris) == 0: return

        # 排序
        avg_z = np.mean(visible_z, axis=1)
        sort_idx = np.argsort(avg_z)[::-1]
        
        sorted_tris = visible_tris[sort_idx]
        sorted_colors = visible_colors[sort_idx]
        sorted_intensities = visible_intensities[sort_idx]

        # --- 5. 绘制 ---
        # 此时已经不需要再算 cross product 了，直接乘亮度即可
        
        # 预计算最终颜色 (利用 NumPy 广播)
        # (N, 3) * (N, 1)
        final_colors = sorted_colors * sorted_intensities[:, np.newaxis]
        final_colors = np.clip(final_colors, 0, 255).astype(np.uint8)

        for i, tri in enumerate(sorted_tris):
            pygame.draw.polygon(self.screen, final_colors[i], tri)
            # pygame.draw.polygon(self.screen, (20,20,20), tri, 1) # 线框可选

        # --- 6. 画坐标轴（可选） ---
        for ent in entities:
            if ent.isaxes:
                draw_axes(self.screen, camera, ent.world_matrix)
    
    def draw_grid(self, camera, grid_size=200, step=20, z0=0.0, near=None):
        """
        Z-up 世界：画“地面”网格 => XY 平面，z = z0
        - 主轴加粗：X轴(红)、Y轴(绿)
        - 普通网格：灰
        """
        base_color = (90, 90, 90)
        x_axis_color = (180, 80, 80)   # 红一点
        y_axis_color = (80, 180, 80)   # 绿一点

        # --- 1) 构建线段端点（世界坐标，齐次）---
        lines = []
        colors = []
        widths = []

        for i in range(-grid_size, grid_size + 1, step):
            # 线1：x = i，y 从 -grid_size 到 +grid_size（平行 Y）
            a1 = [i, -grid_size, z0, 1]
            b1 = [i,  grid_size, z0, 1]

            # 线2：y = i，x 从 -grid_size 到 +grid_size（平行 X）
            a2 = [-grid_size, i, z0, 1]
            b2 = [ grid_size, i, z0, 1]

            # 主轴：x=0 是 Y 轴线；y=0 是 X 轴线（在 XY 平面里）
            if i == 0:
                # x=0 的线：沿 y 方向 => 这是“Y轴”
                lines.append([a1, b1]); colors.append(y_axis_color); widths.append(2)
                # y=0 的线：沿 x 方向 => 这是“X轴”
                lines.append([a2, b2]); colors.append(x_axis_color); widths.append(2)
            else:
                lines.append([a1, b1]); colors.append(base_color); widths.append(1)
                lines.append([a2, b2]); colors.append(base_color); widths.append(1)

        lines = np.array(lines, dtype=DTYPE)  # (N,2,4)

        # --- 2) 批量 World -> Camera ---
        flat = lines.reshape(-1, 4)                 # (N*2,4)
        flat_cam = flat @ camera.T_w_to_c.T         # (N*2,4)
        lines_cam = flat_cam.reshape(-1, 2, 4)      # (N,2,4)

        # --- 3) 逐线裁剪+投影绘制（用你成熟的 draw_line）---
        for seg, col, w in zip(lines_cam, colors, widths):
            draw_line(self.screen, col, seg[0], seg[1], camera=camera, near=near, width=w)
