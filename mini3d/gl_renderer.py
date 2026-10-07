# # gl_renderer.py
# import numpy as np
# from OpenGL.GL import *
# from OpenGL.GL.shaders import compileShader, compileProgram
# import ctypes


# DTYPE = np.float32

# SCREEN_LINE_VERT = """
# #version 330 core
# layout(location=0) in vec2 aPosNdc;   // 已经是 NDC
# layout(location=1) in vec3 aColor;

# out vec3 vColor;
# void main(){
#     vColor = aColor;
#     gl_Position = vec4(aPosNdc, 0.0, 1.0);
# }
# """

# SCREEN_LINE_FRAG = """
# #version 330 core
# in vec3 vColor;
# out vec4 FragColor;
# void main(){
#     FragColor = vec4(vColor, 1.0);
# }
# """


# LINE_VERT = """
# #version 330 core
# layout(location=0) in vec3 aPos;
# layout(location=1) in vec3 aColor;

# uniform mat4 uView;
# uniform mat4 uProj;

# out vec3 vColor;

# void main(){
#     vColor = aColor;
#     gl_Position = uProj * uView * vec4(aPos, 1.0);
# }
# """

# LINE_FRAG = """
# #version 330 core
# in vec3 vColor;
# out vec4 FragColor;
# void main(){
#     FragColor = vec4(vColor, 1.0);
# }
# """


# VERT_SRC = """
# #version 330 core
# layout(location=0) in vec3 aPos;
# layout(location=1) in vec3 aNormal;

# uniform mat4 uModel;
# uniform mat4 uView;
# uniform mat4 uProj;

# out vec3 vNormalW;
# out vec3 vPosW;

# void main(){
#     vec4 posW = uModel * vec4(aPos, 1.0);
#     vPosW = posW.xyz;

#     // 法线用 inverse-transpose(model) 变换到世界
#     mat3 nMat = mat3(transpose(inverse(uModel)));
#     vNormalW = normalize(nMat * aNormal);

#     gl_Position = uProj * uView * posW;
# }
# """

# FRAG_SRC = """
# #version 330 core
# in vec3 vNormalW;
# in vec3 vPosW;

# uniform vec3 uBaseColor;   // 0~1
# uniform vec3 uLightDirW;   // 世界系方向光(单位向量)
# uniform float uAmbient;
# uniform float uDiffuse;

# out vec4 FragColor;

# void main(){
#     vec3 N = normalize(vNormalW);
#     float ndl = max(dot(N, normalize(uLightDirW)), 0.0);
#     float intensity = uAmbient + uDiffuse * ndl;
#     vec3 col = clamp(uBaseColor * intensity, 0.0, 1.0);
#     FragColor = vec4(col, 1.0);
# }
# """

# def perspective_from_focal(focal_px: float, w: int, h: int, near=0.1, far=5000.0):
#     """
#     你原来用的是“像素焦距” fov=500 的投影：x' = f * x/z + cx
#     这里把它转成 OpenGL perspective 矩阵（等价焦距）。
#     """
#     f = float(focal_px)
#     w = float(w); h = float(h)
#     # 由焦距推 fovy: f = (h/2) / tan(fovy/2)
#     fovy = 2.0 * np.arctan((h/2.0) / (f + 1e-9))
#     aspect = w / (h + 1e-9)

#     t = np.tan(fovy/2.0) * near
#     r = t * aspect

#     # OpenGL 标准右手透视（相机看向 -Z）
#     P = np.zeros((4,4), dtype=DTYPE)
#     P[0,0] = near / r
#     P[1,1] = near / t
#     P[2,2] = -(far + near) / (far - near)
#     P[2,3] = -(2.0 * far * near) / (far - near)
#     P[3,2] = -1.0
    
#     return P

# def perspective_from_focal_direct(focal_px: float, w: int, h: int, near=1.0, far=5000.0):
#     """
#     直接把旧版: x_s = f*x/z + W/2 映射到 OpenGL clip space
#     假设主点在屏幕中心 (cx=W/2, cy=H/2)
#     """
#     f = float(focal_px)
#     w = float(w); h = float(h)

#     P = np.zeros((4,4), dtype=np.float32)

#     # 关键：把“像素焦距”变成 NDC 的缩放
#     P[0,0] = 2.0 * f / (w + 1e-9)
#     P[1,1] = 2.0 * f / (h + 1e-9)

#     # 标准深度项（OpenGL 相机看向 -Z）
#     P[2,2] = -(far + near) / (far - near)
#     P[2,3] = -(2.0 * far * near) / (far - near)
#     P[3,2] = -1.0

#     return P

# def add_axis_with_arrow(p0, p1, col, scale = 50.0,
#                 head_len_ratio=0.18, head_w_ratio=0.08):
#             """
#             p0->p1 主轴线，并在 p1 处加 V 形箭头（3D 里正确朝向）
#             """
#             head_len = float(scale) * float(head_len_ratio)
#             head_w   = float(scale) * float(head_w_ratio)
#             seg_verts = []
#             seg_cols = []

#             # 主轴线
#             seg_verts += [p0, p1]
#             seg_cols  += [col, col]

#             # 箭头两条边
#             d = p1 - p0
#             dn = d / (np.linalg.norm(d) + 1e-9)

#             # 选一个不平行的 up 来构造侧向量
#             up = np.array([0, 0, 1], dtype=np.float32)
#             if abs(float(np.dot(dn, up))) > 0.9:
#                 up = np.array([0, 1, 0], dtype=np.float32)

#             s = np.cross(dn, up)
#             s = s / (np.linalg.norm(s) + 1e-9)

#             base = p1 - dn * head_len
#             a = base + s * head_w
#             b = base - s * head_w

#             seg_verts += [p1, a,  p1, b]
#             seg_cols  += [col, col, col, col]

#             return seg_verts, seg_cols


# class GLGrid:
#     def __init__(self, grid_size=200, step=20, z0=0.0):
#         base = np.array([90, 90, 90], dtype=np.float32)/255.0
#         xcol = np.array([180, 80, 80], dtype=np.float32)/255.0
#         ycol = np.array([80, 180, 80], dtype=np.float32)/255.0

#         verts = []
#         colors = []

#         for i in range(-grid_size, grid_size + 1, step):
#             # x=i, y from -grid..grid
#             a1 = [i, -grid_size, z0]; b1 = [i, grid_size, z0]
#             # y=i, x from -grid..grid
#             a2 = [-grid_size, i, z0]; b2 = [grid_size, i, z0]

#             if i == 0:
#                 # x=0 这条是“Y轴线”（绿色）
#                 verts += [a1, b1]; colors += [ycol, ycol]
#                 # y=0 这条是“X轴线”（红色）
#                 verts += [a2, b2]; colors += [xcol, xcol]
#             else:
#                 verts += [a1, b1, a2, b2]
#                 colors += [base, base, base, base]

#         inter = np.hstack([np.asarray(verts, np.float32), np.asarray(colors, np.float32)])  # (N,6)

#         self.count = inter.shape[0]
#         self.vao = glGenVertexArrays(1)
#         self.vbo = glGenBuffers(1)

#         glBindVertexArray(self.vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

#         stride = 6 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
#         glBindVertexArray(0)


# class GLMeshGPU:
#     def __init__(self, mesh):
#         """
#         mesh: 你的 Mesh/STLModel 实例
#         需要：mesh.vertices (N,4) 或 (N,?)，mesh.indices (F,3)，mesh.vertex_normals (N,3)
#         """
#         # 顶点
#         v = np.asarray(mesh.vertices, dtype=DTYPE)
#         if v.shape[1] >= 3:
#             pos = v[:, :3].astype(DTYPE)
#         else:
#             raise ValueError("mesh.vertices 维度不对")

#         nrm = np.asarray(mesh.vertex_normals, dtype=DTYPE)
#         if nrm.shape[0] != pos.shape[0]:
#             raise ValueError("vertex_normals 数量必须与顶点数一致")

#         # indices
#         idx = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1)

#         # interleave: pos(3) + normal(3)
#         inter = np.concatenate([pos, nrm], axis=1).astype(DTYPE)

#         self.count = idx.size

#         self.vao = glGenVertexArrays(1)
#         self.vbo = glGenBuffers(1)
#         self.ebo = glGenBuffers(1)

#         glBindVertexArray(self.vao)

#         glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

#         glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
#         glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)

#         stride = inter.shape[1] * 4  # float32=4 bytes

#         # aPos
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))

#         # aNormal
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

#         glBindVertexArray(0)
        
        

# class GLRenderer:
#     def __init__(self, width, height):
#         self.w = width
#         self.h = height

#         self.program = compileProgram(
#             compileShader(VERT_SRC, GL_VERTEX_SHADER),
#             compileShader(FRAG_SRC, GL_FRAGMENT_SHADER),
#         )

#         glUseProgram(self.program)

#         # uniform locations
#         self.locModel = glGetUniformLocation(self.program, "uModel")
#         self.locView  = glGetUniformLocation(self.program, "uView")
#         self.locProj  = glGetUniformLocation(self.program, "uProj")
#         self.locBase  = glGetUniformLocation(self.program, "uBaseColor")
#         self.locLdir  = glGetUniformLocation(self.program, "uLightDirW")
#         self.locAmb   = glGetUniformLocation(self.program, "uAmbient")
#         self.locDif   = glGetUniformLocation(self.program, "uDiffuse")

#         # GL state
#         glEnable(GL_DEPTH_TEST)
#         glEnable(GL_CULL_FACE)
#         glCullFace(GL_BACK)

#         self.gpu_cache = {}  # id(mesh) -> GLMeshGPU

#         self.resize(width, height)
        
#         self.line_program = compileProgram(
#             compileShader(LINE_VERT, GL_VERTEX_SHADER),
#             compileShader(LINE_FRAG, GL_FRAGMENT_SHADER),
#         )
#         self.line_locView = glGetUniformLocation(self.line_program, "uView")
#         self.line_locProj = glGetUniformLocation(self.line_program, "uProj")

#         self.grid = GLGrid(grid_size=200, step=20, z0=0.0)
        
#         self.screen_line_program = compileProgram(
#             compileShader(SCREEN_LINE_VERT, GL_VERTEX_SHADER),
#             compileShader(SCREEN_LINE_FRAG, GL_FRAGMENT_SHADER),
#         )
#         self.screen_line_vao = glGenVertexArrays(1)
#         self.screen_line_vbo = glGenBuffers(1)
        
#         # ---- Axes (dynamic line VBO) ----
#         self.axes_vao = glGenVertexArrays(1)
#         self.axes_vbo = glGenBuffers(1)



#     def resize(self, width, height):
#         self.w = width
#         self.h = height
#         glViewport(0, 0, width, height)

#     def _get_gpu(self, mesh):
#         key = id(mesh)
#         if key not in self.gpu_cache:
#             self.gpu_cache[key] = GLMeshGPU(mesh)
#         return self.gpu_cache[key]

#     def render(self, scene, camera):
#         glClearColor(30/255, 30/255, 35/255, 1.0)
#         glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

#         glUseProgram(self.program)

#         # --- View 矩阵 ---
#         # 你现在的 camera.T_w_to_c：点从 world -> camera，并且你 CPU 投影里用的是 z>0 在前方:contentReference[oaicite:1]{index=1}
#         # OpenGL 默认相机看向 -Z，所以这里做一个 Z 翻转，把“+Z 向前”的相机系映射成 OpenGL 的“-Z 向前”
#         Z_FLIP = np.diag([1, 1, -1, 1]).astype(DTYPE)
#         V = (Z_FLIP @ camera.T_w_to_c).astype(DTYPE)

#         # --- Proj 矩阵：继续用你原本的 focal_px(camera.fov) ---
#         # P = perspective_from_focal(camera.fov, self.w, self.h, near=0.1, far=5000.0).astype(DTYPE)
#         P = perspective_from_focal_direct(camera.fov, self.w, self.h, near=1.0, far=5000.0)

#         P[1, 1] *= -1.0  # ✅ 将 OpenGL 的 y-up 翻转为你旧版的 y-down
        
            
#         # =========================
#         # ② 三角形模型渲染
#         # =========================
#         glUseProgram(self.program)
#         # 注意：PyOpenGL glUniformMatrix4fv 默认按列主序解释；
#         # 我们这里传 transpose=GL_TRUE，直接用你现成的“行主序 numpy矩阵”
#         glUniformMatrix4fv(self.locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.locProj, 1, GL_TRUE, P)

#         # 光照参数：沿用你 Scene 的 light_dir/ambient/diffuse
#         ldir = np.asarray(scene.light_dir, dtype=DTYPE)
#         glUniform3f(self.locLdir, float(ldir[0]), float(ldir[1]), float(ldir[2]))
#         glUniform1f(self.locAmb, float(scene.ambient))
#         glUniform1f(self.locDif, float(scene.diffuse))
        
#         # 切回三角形 shader
#         glUseProgram(self.program)

#         # 绘制所有实体
#         entities = scene.get_flat_render_list()
#         for ent in entities:
#             if not ent.model:
#                 continue

#             gpu = self._get_gpu(ent.model)

#             M = ent.world_matrix.astype(DTYPE)
#             glUniformMatrix4fv(self.locModel, 1, GL_TRUE, M)

#             if hasattr(ent.model, "base_color"):
#                 bc = np.asarray(ent.model.base_color, dtype=np.float32) / 255.0
#             else:
#                 bc = (np.asarray(ent.model.colors[0], dtype=np.float32) / 255.0)

#             glUniform3f(self.locBase, float(bc[0]), float(bc[1]), float(bc[2]))

#             glBindVertexArray(gpu.vao)
#             glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
#             glBindVertexArray(0)

            
#         use_cpu_like_grid = False   # 改成 False 就用纯OpenGL GLGr
        
#         if use_cpu_like_grid:
#             # ✅ 旧数学 + OpenGL画线（你现在已经验证正确）
#             self.draw_grid_cpu_like(camera, grid_size=200, step=20, z0=0.0, near=1.0)
#         else:
#             # ✅ 纯 OpenGL：必须切 line_program + 设置 uniform
#             glUseProgram(self.line_program)
#             glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#             glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#             glBindVertexArray(self.grid.vao)
#             glLineWidth(1.0)
#             glDrawArrays(GL_LINES, 0, self.grid.count)
#             glBindVertexArray(0)
            
#         glDisable(GL_DEPTH_TEST)
#         for ent in entities:
#             if ent.isaxes:
#                 self.draw_axes_at_matrix(V, P, ent.world_matrix, scale=30.0)
#         self.draw_axes_world(V, P, origin=(0,0,0), scale=60.0) 
#         glEnable(GL_DEPTH_TEST)

#     def draw_axes_world(self, V, P, origin=(0.0, 0.0, 0.0), scale=50.0,
#                     head_len_ratio=0.18, head_w_ratio=0.08):
#         """
#         画世界坐标轴：X红、Y绿、Z蓝（世界空间）+ 线段箭头
#         - 箭头用两条线组成“V”
#         """
#         o = np.array(origin, dtype=np.float32)

#         # 三个轴端点
#         x = o + np.array([scale, 0, 0], dtype=np.float32)
#         y = o + np.array([0, scale, 0], dtype=np.float32)
#         z = o + np.array([0, 0, scale], dtype=np.float32)

#         # 颜色
#         R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
#         G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
#         B = np.array([0.2, 0.2, 1.0], dtype=np.float32)


#         verts = []
#         cols = []

#         v, c = add_axis_with_arrow(o, x, R); verts += v; cols += c
#         v, c = add_axis_with_arrow(o, y, G); verts += v; cols += c
#         v, c = add_axis_with_arrow(o, z, B); verts += v; cols += c

#         verts = np.asarray(verts, dtype=np.float32)
#         cols  = np.asarray(cols,  dtype=np.float32)

#         inter = np.hstack([verts, cols]).astype(np.float32)  # (N,6)

#         prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

#         glUseProgram(self.line_program)
#         glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#         glBindVertexArray(self.axes_vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         stride = 6 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

#         glLineWidth(2.0)
#         glDrawArrays(GL_LINES, 0, verts.shape[0])

#         glBindVertexArray(0)
#         glUseProgram(prev_prog)


#     def draw_axes_at_matrix(self, V, P, T_w, scale=30.0):
#         """
#         在某个坐标系(由 4x4 齐次矩阵 T_w 指定)画局部坐标轴
#         T_w: 该坐标系在世界中的位姿（列/行都行，只要你内部 world_matrix 一致）
#             我们按“行主序 + 右乘”的你现有习惯，取：
#             origin = T_w[:3,3]
#             basis  = T_w[:3,0/1/2]
#         """
#         T = np.asarray(T_w, dtype=np.float32)

#         o = T[:3, 3]
#         ex = T[:3, 0]; ex = ex / (np.linalg.norm(ex) + 1e-9)
#         ey = T[:3, 1]; ey = ey / (np.linalg.norm(ey) + 1e-9)
#         ez = T[:3, 2]; ez = ez / (np.linalg.norm(ez) + 1e-9)


#         x = o + ex * scale
#         y = o + ey * scale
#         z = o + ez * scale

#         verts = np.array([o, x,  o, y,  o, z], dtype=np.float32)

#         R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
#         G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
#         B = np.array([0.2, 0.2, 1.0], dtype=np.float32)
        
#         # ========== 核心修改：复用 add_axis_with_arrow 生成带箭头的顶点 ==========
#         verts = []
#         cols = []
#         # 生成X轴（红）带箭头的顶点和颜色
#         v, c = add_axis_with_arrow(o, x, R); verts += v; cols += c
#         v, c = add_axis_with_arrow(o, y, G); verts += v; cols += c
#         v, c = add_axis_with_arrow(o, z, B); verts += v; cols += c

#         # 转换为numpy数组（和 draw_axes_world 逻辑一致）
#         verts = np.asarray(verts, dtype=np.float32)
#         cols = np.asarray(cols, dtype=np.float32)

#         # 拼接顶点和颜色数据（位置3维 + 颜色3维 = 6维 per 顶点）
#         inter = np.hstack([verts, cols]).astype(np.float32)

#         prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)
        
#         glUseProgram(self.line_program)
#         glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#         glBindVertexArray(self.axes_vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         stride = 6 * 4  # 6个float，每个4字节
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))  # 位置
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12)) # 颜色

#         glLineWidth(2.0)
#         # ========== 关键修改：顶点数量从固定6改为动态的 verts.shape[0] ==========
#         glDrawArrays(GL_LINES, 0, verts.shape[0])

#         glBindVertexArray(0)
#         glUseProgram(prev_prog)
#         # cols = np.array([R, R,  G, G,  B, B], dtype=np.float32)
        
        

#         # inter = np.hstack([verts, cols]).astype(np.float32)
#         # prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)
        
#         # glUseProgram(self.line_program)
#         # glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#         # glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#         # glBindVertexArray(self.axes_vao)
#         # glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
#         # glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         # stride = 6 * 4
#         # glEnableVertexAttribArray(0)
#         # glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         # glEnableVertexAttribArray(1)
#         # glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

#         # glLineWidth(2.0)
#         # glDrawArrays(GL_LINES, 0, 6)

#         # glBindVertexArray(0)
#         # glUseProgram(prev_prog)
        
        

#     def draw_screen_lines(self, segments_px, colors_rgb, widths=None):
#         """
#         segments_px: (M,2,2)  每条线段两个端点，每个端点(x,y)像素
#         colors_rgb : (M,3)    每条线一个颜色，0~255
#         widths: 可选(M,)      线宽（OpenGL 线宽支持不稳定，先尽力）
#         """
#         if len(segments_px) == 0:
#             return

#         seg = np.asarray(segments_px, np.float32)  # (M,2,2)
#         col = np.asarray(colors_rgb, np.float32) / 255.0  # (M,3)

#         W, H = float(self.w), float(self.h)

#         # px -> ndc
#         x = seg[..., 0]
#         y = seg[..., 1]
#         x_ndc = 2.0 * (x / (W + 1e-9)) - 1.0
#         y_ndc = 1.0 - 2.0 * (y / (H + 1e-9))  # 像素y向下 => NDC y向上

#         # 展平成顶点流：每条线2个点
#         pos = np.stack([x_ndc, y_ndc], axis=-1).reshape(-1, 2)  # (M*2,2)

#         # 每条线颜色重复2次
#         col2 = np.repeat(col, 2, axis=0)  # (M*2,3)

#         inter = np.hstack([pos, col2]).astype(np.float32)  # (M*2,5)

#         glUseProgram(self.screen_line_program)
#         glBindVertexArray(self.screen_line_vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.screen_line_vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         stride = 5 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

#         # 线宽（很多平台只支持1）
#         if widths is not None:
#             # 只能整体设置一次，不支持每条线不同宽度（这就是 OpenGL 的限制）
#             glLineWidth(float(np.max(widths)))
#         else:
#             glLineWidth(1.0)

#         glDrawArrays(GL_LINES, 0, inter.shape[0])
#         glBindVertexArray(0)
        
#     def draw_grid_cpu_like(self, camera, grid_size=200, step=20, z0=0.0, near=1.0):
#         base_color = (90, 90, 90)
#         x_axis_color = (180, 80, 80)
#         y_axis_color = (80, 180, 80)

#         lines = []
#         colors = []
#         widths = []

#         for i in range(-grid_size, grid_size + 1, step):
#             a1 = [i, -grid_size, z0, 1]
#             b1 = [i,  grid_size, z0, 1]
#             a2 = [-grid_size, i, z0, 1]
#             b2 = [ grid_size, i, z0, 1]

#             if i == 0:
#                 lines.append([a1, b1]); colors.append(y_axis_color); widths.append(2)
#                 lines.append([a2, b2]); colors.append(x_axis_color); widths.append(2)
#             else:
#                 lines.append([a1, b1]); colors.append(base_color); widths.append(1)
#                 lines.append([a2, b2]); colors.append(base_color); widths.append(1)

#         lines = np.asarray(lines, dtype=np.float32)  # (N,2,4)

#         # 完全复刻你旧版：flat @ T_w_to_c.T
#         flat = lines.reshape(-1, 4)
#         flat_cam = flat @ camera.T_w_to_c.T
#         lines_cam = flat_cam.reshape(-1, 2, 4)

#         # 投影 + near 裁剪（用你旧版 camera.project 的逻辑等价）
#         seg2d = []
#         segcol = []
#         segw = []

#         for seg, col, w in zip(lines_cam, colors, widths):
#             p0 = seg[0]; p1 = seg[1]

#             # near 裁剪：只做最小版本（两端都在 near 后才画）
#             # 如果你旧 draw_line 支持跨 near 裁剪（截断），这里也可以补齐
#             if p0[2] <= near or p1[2] <= near:
#                 continue

#             x0 = camera.fov * (p0[0] / p0[2]) + self.w/2.0
#             y0 = camera.fov * (p0[1] / p0[2]) + self.h/2.0
#             x1 = camera.fov * (p1[0] / p1[2]) + self.w/2.0
#             y1 = camera.fov * (p1[1] / p1[2]) + self.h/2.0

#             seg2d.append([[x0, y0], [x1, y1]])
#             segcol.append(col)
#             segw.append(w)

#         self.draw_screen_lines(seg2d, segcol, segw)

# # gl_renderer.py (Optimized Version)
# import numpy as np
# from OpenGL.GL import *
# from OpenGL.GL.shaders import compileShader, compileProgram
# import ctypes


# DTYPE = np.float32

# # ==================== Shaders ====================

# SCREEN_LINE_VERT = """
# #version 330 core
# layout(location=0) in vec2 aPosNdc;
# layout(location=1) in vec3 aColor;

# out vec3 vColor;
# void main(){
#     vColor = aColor;
#     gl_Position = vec4(aPosNdc, 0.0, 1.0);
# }
# """

# SCREEN_LINE_FRAG = """
# #version 330 core
# in vec3 vColor;
# out vec4 FragColor;
# void main(){
#     FragColor = vec4(vColor, 1.0);
# }
# """

# LINE_VERT = """
# #version 330 core
# layout(location=0) in vec3 aPos;
# layout(location=1) in vec3 aColor;

# uniform mat4 uView;
# uniform mat4 uProj;

# out vec3 vColor;

# void main(){
#     vColor = aColor;
#     gl_Position = uProj * uView * vec4(aPos, 1.0);
# }
# """

# LINE_FRAG = """
# #version 330 core
# in vec3 vColor;
# out vec4 FragColor;
# void main(){
#     FragColor = vec4(vColor, 1.0);
# }
# """

# VERT_SRC = """
# #version 330 core
# layout(location=0) in vec3 aPos;
# layout(location=1) in vec3 aNormal;

# uniform mat4 uModel;
# uniform mat4 uView;
# uniform mat4 uProj;

# out vec3 vNormalW;
# out vec3 vPosW;

# void main(){
#     vec4 posW = uModel * vec4(aPos, 1.0);
#     vPosW = posW.xyz;
    
#     // Normal transform: use normal matrix (inverse transpose of model matrix's upper-left 3x3)
#     mat3 normalMatrix = mat3(transpose(inverse(uModel)));
#     vNormalW = normalize(normalMatrix * aNormal);
    
#     gl_Position = uProj * uView * posW;
# }
# """

# FRAG_SRC = """
# #version 330 core
# in vec3 vNormalW;
# in vec3 vPosW;

# uniform vec3 uBaseColor;
# uniform vec3 uLightDirW;
# uniform float uAmbient;
# uniform float uDiffuse;

# out vec4 FragColor;

# void main(){
#     vec3 N = normalize(vNormalW);
#     vec3 L = normalize(uLightDirW);
    
#     // Diffuse lighting
#     float ndl = max(dot(N, L), 0.0);
    
#     // Combined lighting
#     float intensity = uAmbient + uDiffuse * ndl;
#     intensity = clamp(intensity, 0.0, 1.0);
    
#     vec3 col = uBaseColor * intensity;
#     FragColor = vec4(col, 1.0);
# }
# """


# # ==================== Helper Functions ====================

# def perspective_matrix(fov_y_deg, aspect, near, far):
#     """
#     Standard OpenGL perspective projection matrix
#     """
#     fov_rad = np.radians(fov_y_deg)
#     f = 1.0 / np.tan(fov_rad / 2.0)
    
#     P = np.zeros((4, 4), dtype=DTYPE)
#     P[0, 0] = f / aspect
#     P[1, 1] = f
#     P[2, 2] = (far + near) / (near - far)
#     P[2, 3] = (2.0 * far * near) / (near - far)
#     P[3, 2] = -1.0
    
#     return P


# def perspective_from_focal(focal_px, w, h, near=0.1, far=5000.0):
#     """
#     Convert pixel focal length to OpenGL perspective matrix
#     Improved calculation to match your existing projection
#     """
#     f = float(focal_px)
#     width = float(w)
#     height = float(h)
    
#     # Calculate field of view from focal length
#     # For pixel coordinates: x_screen = f * (X/Z) + width/2
#     # This means: tan(fov_x/2) = (width/2) / f
#     fov_x = 2.0 * np.arctan(width / (2.0 * f))
#     fov_y = 2.0 * np.arctan(height / (2.0 * f))
    
#     # Use fov_y for standard perspective matrix
#     aspect = width / height
    
#     P = np.zeros((4, 4), dtype=DTYPE)
    
#     # Standard perspective matrix
#     tan_half_fov_y = np.tan(fov_y / 2.0)
    
#     P[0, 0] = 1.0 / (aspect * tan_half_fov_y)
#     P[1, 1] = 1.0 / tan_half_fov_y
#     P[2, 2] = -(far + near) / (far - near)
#     P[2, 3] = -(2.0 * far * near) / (far - near)
#     P[3, 2] = -1.0
    
#     return P


# def add_axis_with_arrow(p0, p1, col, scale=50.0, head_len_ratio=0.18, head_w_ratio=0.08):
#     """
#     Create axis line with arrow head
#     """
#     head_len = float(scale) * float(head_len_ratio)
#     head_w = float(scale) * float(head_w_ratio)
#     seg_verts = []
#     seg_cols = []

#     # Main axis line
#     seg_verts += [p0, p1]
#     seg_cols += [col, col]

#     # Arrow head
#     d = p1 - p0
#     dn = d / (np.linalg.norm(d) + 1e-9)

#     # Choose perpendicular vector
#     up = np.array([0, 0, 1], dtype=np.float32)
#     if abs(float(np.dot(dn, up))) > 0.9:
#         up = np.array([0, 1, 0], dtype=np.float32)

#     s = np.cross(dn, up)
#     s = s / (np.linalg.norm(s) + 1e-9)

#     base = p1 - dn * head_len
#     a = base + s * head_w
#     b = base - s * head_w

#     seg_verts += [p1, a, p1, b]
#     seg_cols += [col, col, col, col]

#     return seg_verts, seg_cols


# # ==================== OpenGL Objects ====================

# class GLGrid:
#     def __init__(self, grid_size=200, step=20, z0=0.0):
#         base = np.array([90, 90, 90], dtype=np.float32) / 255.0
#         xcol = np.array([180, 80, 80], dtype=np.float32) / 255.0
#         ycol = np.array([80, 180, 80], dtype=np.float32) / 255.0

#         verts = []
#         colors = []

#         for i in range(-grid_size, grid_size + 1, step):
#             # Parallel to Y axis (X=i)
#             a1 = [i, -grid_size, z0]
#             b1 = [i, grid_size, z0]
#             # Parallel to X axis (Y=i)
#             a2 = [-grid_size, i, z0]
#             b2 = [grid_size, i, z0]

#             if i == 0:
#                 # X=0 is Y-axis (green)
#                 verts += [a1, b1]
#                 colors += [ycol, ycol]
#                 # Y=0 is X-axis (red)
#                 verts += [a2, b2]
#                 colors += [xcol, xcol]
#             else:
#                 verts += [a1, b1, a2, b2]
#                 colors += [base, base, base, base]

#         inter = np.hstack([
#             np.asarray(verts, np.float32),
#             np.asarray(colors, np.float32)
#         ])

#         self.count = inter.shape[0]
#         self.vao = glGenVertexArrays(1)
#         self.vbo = glGenBuffers(1)

#         glBindVertexArray(self.vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

#         stride = 6 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        
#         glBindVertexArray(0)


# class GLMeshGPU:
#     def __init__(self, mesh):
#         """
#         Upload mesh data to GPU
#         """
#         # Vertices
#         v = np.asarray(mesh.vertices, dtype=DTYPE)
#         if v.shape[1] >= 3:
#             pos = v[:, :3].astype(DTYPE)
#         else:
#             raise ValueError("mesh.vertices dimension incorrect")

#         # Normals
#         nrm = np.asarray(mesh.vertex_normals, dtype=DTYPE)
#         if nrm.shape[0] != pos.shape[0]:
#             raise ValueError("vertex_normals count must match vertices")

#         # Indices
#         idx = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1)

#         # Interleave: pos(3) + normal(3)
#         inter = np.concatenate([pos, nrm], axis=1).astype(DTYPE)

#         self.count = idx.size

#         self.vao = glGenVertexArrays(1)
#         self.vbo = glGenBuffers(1)
#         self.ebo = glGenBuffers(1)

#         glBindVertexArray(self.vao)

#         glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

#         glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
#         glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)

#         stride = 6 * 4

#         # Position attribute
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))

#         # Normal attribute
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

#         glBindVertexArray(0)


# # ==================== Main Renderer ====================

# class GLRenderer:
#     def __init__(self, width, height):
#         self.w = width
#         self.h = height

#         # Main mesh shader
#         self.program = compileProgram(
#             compileShader(VERT_SRC, GL_VERTEX_SHADER),
#             compileShader(FRAG_SRC, GL_FRAGMENT_SHADER),
#         )

#         # Get uniform locations
#         self.locModel = glGetUniformLocation(self.program, "uModel")
#         self.locView = glGetUniformLocation(self.program, "uView")
#         self.locProj = glGetUniformLocation(self.program, "uProj")
#         self.locBase = glGetUniformLocation(self.program, "uBaseColor")
#         self.locLdir = glGetUniformLocation(self.program, "uLightDirW")
#         self.locAmb = glGetUniformLocation(self.program, "uAmbient")
#         self.locDif = glGetUniformLocation(self.program, "uDiffuse")

#         # Line shader
#         self.line_program = compileProgram(
#             compileShader(LINE_VERT, GL_VERTEX_SHADER),
#             compileShader(LINE_FRAG, GL_FRAGMENT_SHADER),
#         )
#         self.line_locView = glGetUniformLocation(self.line_program, "uView")
#         self.line_locProj = glGetUniformLocation(self.line_program, "uProj")

#         # Screen line shader
#         self.screen_line_program = compileProgram(
#             compileShader(SCREEN_LINE_VERT, GL_VERTEX_SHADER),
#             compileShader(SCREEN_LINE_FRAG, GL_FRAGMENT_SHADER),
#         )

#         # OpenGL state
#         glEnable(GL_DEPTH_TEST)
#         glDepthFunc(GL_LESS)
#         glEnable(GL_CULL_FACE)
#         glCullFace(GL_BACK)
#         glFrontFace(GL_CCW)  # Counter-clockwise winding
        
#         # Enable MSAA if available
#         glEnable(GL_MULTISAMPLE)

#         # GPU cache
#         self.gpu_cache = {}

#         # Grid
#         self.grid = GLGrid(grid_size=200, step=20, z0=0.0)

#         # Dynamic buffers
#         self.screen_line_vao = glGenVertexArrays(1)
#         self.screen_line_vbo = glGenBuffers(1)
#         self.axes_vao = glGenVertexArrays(1)
#         self.axes_vbo = glGenBuffers(1)

#         self.resize(width, height)

#     def resize(self, width, height):
#         self.w = width
#         self.h = height
#         glViewport(0, 0, width, height)

#     def _get_gpu(self, mesh):
#         key = id(mesh)
#         if key not in self.gpu_cache:
#             self.gpu_cache[key] = GLMeshGPU(mesh)
#         return self.gpu_cache[key]

#     def render(self, scene, camera):
#         # Clear
#         glClearColor(30/255, 30/255, 35/255, 1.0)
#         glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

#         # ==================== View Matrix ====================
#         # Your camera uses Z-forward (+Z is forward)
#         # OpenGL uses Z-backward (-Z is forward)
#         # Apply Z-flip to convert
#         Z_FLIP = np.diag([1, 1, -1, 1]).astype(DTYPE)
#         V = (Z_FLIP @ camera.T_w_to_c).astype(DTYPE)

#         # ==================== Projection Matrix ====================
#         P = perspective_from_focal(camera.fov, self.w, self.h, near=1.0, far=5000.0)
        
#         # Flip Y to match your coordinate system (Y-down in screen space)
#         P[1, 1] *= -1.0

#         # ==================== Render Meshes ====================
#         glUseProgram(self.program)
        
#         # Set view and projection (transpose for row-major numpy arrays)
#         glUniformMatrix4fv(self.locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.locProj, 1, GL_TRUE, P)

#         # Set lighting
#         ldir = np.asarray(scene.light_dir, dtype=DTYPE)
#         glUniform3f(self.locLdir, float(ldir[0]), float(ldir[1]), float(ldir[2]))
#         glUniform1f(self.locAmb, float(scene.ambient))
#         glUniform1f(self.locDif, float(scene.diffuse))

#         # Render entities
#         entities = scene.get_flat_render_list()
#         for ent in entities:
#             if not ent.model:
#                 continue

#             gpu = self._get_gpu(ent.model)

#             # Set model matrix
#             M = ent.world_matrix.astype(DTYPE)
#             glUniformMatrix4fv(self.locModel, 1, GL_TRUE, M)

#             # Set base color
#             if hasattr(ent.model, "base_color"):
#                 bc = np.asarray(ent.model.base_color, dtype=np.float32) / 255.0
#             else:
#                 bc = np.asarray(ent.model.colors[0], dtype=np.float32) / 255.0

#             glUniform3f(self.locBase, float(bc[0]), float(bc[1]), float(bc[2]))

#             # Draw
#             glBindVertexArray(gpu.vao)
#             glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
#             glBindVertexArray(0)

#         # ==================== Render Grid ====================
#         glUseProgram(self.line_program)
#         glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#         glBindVertexArray(self.grid.vao)
#         glLineWidth(1.0)
#         glDrawArrays(GL_LINES, 0, self.grid.count)
#         glBindVertexArray(0)

#         # ==================== Render Axes ====================
#         glDisable(GL_DEPTH_TEST)
        
#         # World axes
#         self.draw_axes_world(V, P, origin=(0, 0, 0), scale=60.0)
        
#         # Entity axes
#         for ent in entities:
#             if getattr(ent, "isaxes", False):
#                 self.draw_axes_at_matrix(V, P, ent.world_matrix, scale=30.0)
        
#         glEnable(GL_DEPTH_TEST)

#     def draw_axes_world(self, V, P, origin=(0.0, 0.0, 0.0), scale=50.0,
#                         head_len_ratio=0.18, head_w_ratio=0.08):
#         """
#         Draw world coordinate axes: X(red), Y(green), Z(blue)
#         """
#         o = np.array(origin, dtype=np.float32)

#         # Axis endpoints
#         x = o + np.array([scale, 0, 0], dtype=np.float32)
#         y = o + np.array([0, scale, 0], dtype=np.float32)
#         z = o + np.array([0, 0, scale], dtype=np.float32)

#         # Colors
#         R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
#         G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
#         B = np.array([0.2, 0.2, 1.0], dtype=np.float32)

#         verts = []
#         cols = []

#         v, c = add_axis_with_arrow(o, x, R, scale)
#         verts += v
#         cols += c
#         v, c = add_axis_with_arrow(o, y, G, scale)
#         verts += v
#         cols += c
#         v, c = add_axis_with_arrow(o, z, B, scale)
#         verts += v
#         cols += c

#         verts = np.asarray(verts, dtype=np.float32)
#         cols = np.asarray(cols, dtype=np.float32)

#         inter = np.hstack([verts, cols]).astype(np.float32)

#         prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

#         glUseProgram(self.line_program)
#         glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#         glBindVertexArray(self.axes_vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         stride = 6 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

#         glLineWidth(2.0)
#         glDrawArrays(GL_LINES, 0, verts.shape[0])

#         glBindVertexArray(0)
#         glUseProgram(prev_prog)

#     def draw_axes_at_matrix(self, V, P, T_w, scale=30.0):
#         """
#         Draw local coordinate axes at given transform matrix
#         """
#         T = np.asarray(T_w, dtype=np.float32)

#         o = T[:3, 3]
#         ex = T[:3, 0]
#         ex = ex / (np.linalg.norm(ex) + 1e-9)
#         ey = T[:3, 1]
#         ey = ey / (np.linalg.norm(ey) + 1e-9)
#         ez = T[:3, 2]
#         ez = ez / (np.linalg.norm(ez) + 1e-9)

#         x = o + ex * scale
#         y = o + ey * scale
#         z = o + ez * scale

#         R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
#         G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
#         B = np.array([0.2, 0.2, 1.0], dtype=np.float32)

#         verts = []
#         cols = []

#         v, c = add_axis_with_arrow(o, x, R, scale)
#         verts += v
#         cols += c
#         v, c = add_axis_with_arrow(o, y, G, scale)
#         verts += v
#         cols += c
#         v, c = add_axis_with_arrow(o, z, B, scale)
#         verts += v
#         cols += c

#         verts = np.asarray(verts, dtype=np.float32)
#         cols = np.asarray(cols, dtype=np.float32)

#         inter = np.hstack([verts, cols]).astype(np.float32)

#         prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

#         glUseProgram(self.line_program)
#         glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
#         glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

#         glBindVertexArray(self.axes_vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         stride = 6 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

#         glLineWidth(2.0)
#         glDrawArrays(GL_LINES, 0, verts.shape[0])

#         glBindVertexArray(0)
#         glUseProgram(prev_prog)

#     def draw_screen_lines(self, segments_px, colors_rgb, widths=None):
#         """
#         Draw 2D lines in screen space (pixel coordinates)
#         """
#         if len(segments_px) == 0:
#             return

#         seg = np.asarray(segments_px, np.float32)
#         col = np.asarray(colors_rgb, np.float32) / 255.0

#         W, H = float(self.w), float(self.h)

#         # Convert pixel coords to NDC
#         x = seg[..., 0]
#         y = seg[..., 1]
#         x_ndc = 2.0 * (x / (W + 1e-9)) - 1.0
#         y_ndc = 1.0 - 2.0 * (y / (H + 1e-9))

#         # Flatten to vertex stream
#         pos = np.stack([x_ndc, y_ndc], axis=-1).reshape(-1, 2)

#         # Repeat colors
#         col2 = np.repeat(col, 2, axis=0)

#         inter = np.hstack([pos, col2]).astype(np.float32)

#         glUseProgram(self.screen_line_program)
#         glBindVertexArray(self.screen_line_vao)
#         glBindBuffer(GL_ARRAY_BUFFER, self.screen_line_vbo)
#         glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

#         stride = 5 * 4
#         glEnableVertexAttribArray(0)
#         glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
#         glEnableVertexAttribArray(1)
#         glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

#         if widths is not None:
#             glLineWidth(float(np.max(widths)))
#         else:
#             glLineWidth(1.0)

#         glDrawArrays(GL_LINES, 0, inter.shape[0])
#         glBindVertexArray(0)

#     def draw_grid_cpu_like(self, camera, grid_size=200, step=20, z0=0.0, near=1.0):
#         """
#         Fallback: CPU-side grid rendering (for compatibility)
#         """
#         base_color = (90, 90, 90)
#         x_axis_color = (180, 80, 80)
#         y_axis_color = (80, 180, 80)

#         lines = []
#         colors = []
#         widths = []

#         for i in range(-grid_size, grid_size + 1, step):
#             a1 = [i, -grid_size, z0, 1]
#             b1 = [i, grid_size, z0, 1]
#             a2 = [-grid_size, i, z0, 1]
#             b2 = [grid_size, i, z0, 1]

#             if i == 0:
#                 lines.append([a1, b1])
#                 colors.append(y_axis_color)
#                 widths.append(2)
#                 lines.append([a2, b2])
#                 colors.append(x_axis_color)
#                 widths.append(2)
#             else:
#                 lines.append([a1, b1])
#                 colors.append(base_color)
#                 widths.append(1)
#                 lines.append([a2, b2])
#                 colors.append(base_color)
#                 widths.append(1)

#         lines = np.asarray(lines, dtype=np.float32)

#         # Transform to camera space
#         flat = lines.reshape(-1, 4)
#         flat_cam = flat @ camera.T_w_to_c.T
#         lines_cam = flat_cam.reshape(-1, 2, 4)

#         # Project
#         seg2d = []
#         segcol = []
#         segw = []

#         for seg, col, w in zip(lines_cam, colors, widths):
#             p0 = seg[0]
#             p1 = seg[1]

#             if p0[2] <= near or p1[2] <= near:
#                 continue

#             x0 = camera.fov * (p0[0] / p0[2]) + self.w / 2.0
#             y0 = camera.fov * (p0[1] / p0[2]) + self.h / 2.0
#             x1 = camera.fov * (p1[0] / p1[2]) + self.w / 2.0
#             y1 = camera.fov * (p1[1] / p1[2]) + self.h / 2.0

#             seg2d.append([[x0, y0], [x1, y1]])
#             segcol.append(col)
#             segw.append(w)

#         self.draw_screen_lines(seg2d, segcol, segw)

# gl_renderer.py (Optimized Version with NPR Support)
import numpy as np
from OpenGL.GL import *
from OpenGL.GL.shaders import compileShader, compileProgram
import ctypes


DTYPE = np.float32

# ==================== Rendering Modes ====================
# Set render_mode to control rendering style:
# - "REALISTIC" : Standard PBR-like shading
# - "TOON" : Cel-shaded anime/cartoon style (3D to 2D look)
# - "OUTLINE" : Toon + black outlines

RENDER_MODE = "OUTLINE"  # Change this to: "REALISTIC", "TOON", or "OUTLINE"

# ==================== Shaders ====================

SCREEN_LINE_VERT = """
#version 330 core
layout(location=0) in vec2 aPosNdc;
layout(location=1) in vec3 aColor;

out vec3 vColor;
void main(){
    vColor = aColor;
    gl_Position = vec4(aPosNdc, 0.0, 1.0);
}
"""

SCREEN_LINE_FRAG = """
#version 330 core
in vec3 vColor;
out vec4 FragColor;
void main(){
    FragColor = vec4(vColor, 1.0);
}
"""

LINE_VERT = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aColor;

uniform mat4 uView;
uniform mat4 uProj;

out vec3 vColor;

void main(){
    vColor = aColor;
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

LINE_FRAG = """
#version 330 core
in vec3 vColor;
out vec4 FragColor;
void main(){
    FragColor = vec4(vColor, 1.0);
}
"""

VERT_SRC = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;

out vec3 vNormalW;
out vec3 vPosW;

void main(){
    vec4 posW = uModel * vec4(aPos, 1.0);
    vPosW = posW.xyz;
    
    // Normal transform: use normal matrix (inverse transpose of model matrix's upper-left 3x3)
    mat3 normalMatrix = mat3(transpose(inverse(uModel)));
    vNormalW = normalize(normalMatrix * aNormal);
    
    gl_Position = uProj * uView * posW;
}
"""

FRAG_SRC = """
#version 330 core
in vec3 vNormalW;
in vec3 vPosW;

uniform vec3 uBaseColor;
uniform vec3 uLightDirW;
uniform float uAmbient;
uniform float uDiffuse;

out vec4 FragColor;

void main(){
    vec3 N = normalize(vNormalW);
    vec3 L = normalize(uLightDirW);
    
    // Diffuse lighting
    float ndl = max(dot(N, L), 0.0);
    
    // Combined lighting
    float intensity = uAmbient + uDiffuse * ndl;
    intensity = clamp(intensity, 0.0, 1.0);
    
    vec3 col = uBaseColor * intensity;
    FragColor = vec4(col, 1.0);
}
"""

# ==================== NPR (Toon/Cel Shading) Shaders ====================

TOON_FRAG = """
#version 330 core
in vec3 vNormalW;
in vec3 vPosW;

uniform vec3 uBaseColor;
uniform vec3 uLightDirW;
uniform float uAmbient;
uniform float uDiffuse;
uniform vec3 uCameraPos;

out vec4 FragColor;

void main(){
    vec3 N = normalize(vNormalW);
    vec3 L = normalize(uLightDirW);
    
    // Diffuse lighting
    float ndl = max(dot(N, L), 0.0);
    
    // Cel shading: quantize lighting into discrete levels
    float toonLevels = 4.0; // Number of shading levels
    float toonIntensity = floor(ndl * toonLevels) / toonLevels;
    
    // Add ambient
    float intensity = uAmbient + uDiffuse * toonIntensity;
    intensity = clamp(intensity, 0.0, 1.0);
    
    // Specular highlight (toon style)
    vec3 V = normalize(uCameraPos - vPosW);
    vec3 H = normalize(L + V);
    float specAngle = max(dot(N, H), 0.0);
    float specular = pow(specAngle, 32.0);
    
    // Quantize specular
    if (specular > 0.8) {
        specular = 1.0;
    } else {
        specular = 0.0;
    }
    
    // Rim lighting (Fresnel-like edge glow)
    float rimDot = 1.0 - max(dot(V, N), 0.0);
    float rimIntensity = rimDot * rimDot;
    rimIntensity = smoothstep(0.6, 1.0, rimIntensity);
    
    // Combine
    vec3 col = uBaseColor * intensity;
    col += vec3(0.3) * specular; // White specular highlight
    col += uBaseColor * 0.5 * rimIntensity; // Rim light
    
    FragColor = vec4(col, 1.0);
}
"""

# Outline pass shader (for OUTLINE mode)
OUTLINE_VERT = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
uniform float uOutlineWidth;

void main(){
    // Transform to view space
    mat4 modelView = uView * uModel;
    vec4 viewPos = modelView * vec4(aPos, 1.0);
    
    // Transform normal to view space
    mat3 normalMatrix = mat3(transpose(inverse(modelView)));
    vec3 viewNormal = normalize(normalMatrix * aNormal);
    
    // Expand in view space (screen-consistent outline width)
    viewPos.xyz += viewNormal * uOutlineWidth;
    
    // Project to clip space
    gl_Position = uProj * viewPos;
}
"""

OUTLINE_FRAG = """
#version 330 core
out vec4 FragColor;

uniform vec3 uOutlineColor;

void main(){
    FragColor = vec4(uOutlineColor, 1.0);
}
"""


# ==================== Helper Functions ====================

def perspective_matrix(fov_y_deg, aspect, near, far):
    """
    Standard OpenGL perspective projection matrix
    """
    fov_rad = np.radians(fov_y_deg)
    f = 1.0 / np.tan(fov_rad / 2.0)
    
    P = np.zeros((4, 4), dtype=DTYPE)
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 2] = (far + near) / (near - far)
    P[2, 3] = (2.0 * far * near) / (near - far)
    P[3, 2] = -1.0
    
    return P


def perspective_from_focal(focal_px, w, h, near=0.1, far=5000.0):
    """
    Convert pixel focal length to OpenGL perspective matrix
    Improved calculation to match your existing projection
    """
    f = float(focal_px)
    width = float(w)
    height = float(h)
    
    # Calculate field of view from focal length
    # For pixel coordinates: x_screen = f * (X/Z) + width/2
    # This means: tan(fov_x/2) = (width/2) / f
    fov_x = 2.0 * np.arctan(width / (2.0 * f))
    fov_y = 2.0 * np.arctan(height / (2.0 * f))
    
    # Use fov_y for standard perspective matrix
    aspect = width / height
    
    P = np.zeros((4, 4), dtype=DTYPE)
    
    # Standard perspective matrix
    tan_half_fov_y = np.tan(fov_y / 2.0)
    
    P[0, 0] = 1.0 / (aspect * tan_half_fov_y)
    P[1, 1] = 1.0 / tan_half_fov_y
    P[2, 2] = -(far + near) / (far - near)
    P[2, 3] = -(2.0 * far * near) / (far - near)
    P[3, 2] = -1.0
    
    return P


def add_axis_with_arrow(p0, p1, col, scale=50.0, head_len_ratio=0.18, head_w_ratio=0.08):
    """
    Create axis line with arrow head
    """
    head_len = float(scale) * float(head_len_ratio)
    head_w = float(scale) * float(head_w_ratio)
    seg_verts = []
    seg_cols = []

    # Main axis line
    seg_verts += [p0, p1]
    seg_cols += [col, col]

    # Arrow head
    d = p1 - p0
    dn = d / (np.linalg.norm(d) + 1e-9)

    # Choose perpendicular vector
    up = np.array([0, 0, 1], dtype=np.float32)
    if abs(float(np.dot(dn, up))) > 0.9:
        up = np.array([0, 1, 0], dtype=np.float32)

    s = np.cross(dn, up)
    s = s / (np.linalg.norm(s) + 1e-9)

    base = p1 - dn * head_len
    a = base + s * head_w
    b = base - s * head_w

    seg_verts += [p1, a, p1, b]
    seg_cols += [col, col, col, col]

    return seg_verts, seg_cols


# ==================== OpenGL Objects ====================

class GLGrid:
    def __init__(self, grid_size=200, step=20, z0=0.0):
        base = np.array([90, 90, 90], dtype=np.float32) / 255.0
        xcol = np.array([180, 80, 80], dtype=np.float32) / 255.0
        ycol = np.array([80, 180, 80], dtype=np.float32) / 255.0

        verts = []
        colors = []

        for i in range(-grid_size, grid_size + 1, step):
            # Parallel to Y axis (X=i)
            a1 = [i, -grid_size, z0]
            b1 = [i, grid_size, z0]
            # Parallel to X axis (Y=i)
            a2 = [-grid_size, i, z0]
            b2 = [grid_size, i, z0]

            if i == 0:
                # X=0 is Y-axis (green)
                verts += [a1, b1]
                colors += [ycol, ycol]
                # Y=0 is X-axis (red)
                verts += [a2, b2]
                colors += [xcol, xcol]
            else:
                verts += [a1, b1, a2, b2]
                colors += [base, base, base, base]

        inter = np.hstack([
            np.asarray(verts, np.float32),
            np.asarray(colors, np.float32)
        ])

        self.count = inter.shape[0]
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        
        glBindVertexArray(0)


class GLMeshGPU:
    def __init__(self, mesh):
        """
        Upload mesh data to GPU
        """
        # Vertices
        v = np.asarray(mesh.vertices, dtype=DTYPE)
        if v.shape[1] >= 3:
            pos = v[:, :3].astype(DTYPE)
        else:
            raise ValueError("mesh.vertices dimension incorrect")

        # Normals
        nrm = np.asarray(mesh.vertex_normals, dtype=DTYPE)
        if nrm.shape[0] != pos.shape[0]:
            raise ValueError("vertex_normals count must match vertices")

        # Indices
        idx = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1)

        # Interleave: pos(3) + normal(3)
        inter = np.concatenate([pos, nrm], axis=1).astype(DTYPE)

        self.count = idx.size

        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        self.ebo = glGenBuffers(1)

        glBindVertexArray(self.vao)

        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)

        stride = 6 * 4

        # Position attribute
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))

        # Normal attribute
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        glBindVertexArray(0)


# ==================== Main Renderer ====================

class GLRenderer:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        
        # Render mode setting
        self.render_mode = RENDER_MODE  # "REALISTIC", "TOON", or "OUTLINE"

        # Main mesh shader (realistic)
        self.program = compileProgram(
            compileShader(VERT_SRC, GL_VERTEX_SHADER),
            compileShader(FRAG_SRC, GL_FRAGMENT_SHADER),
        )

        # Get uniform locations
        self.locModel = glGetUniformLocation(self.program, "uModel")
        self.locView = glGetUniformLocation(self.program, "uView")
        self.locProj = glGetUniformLocation(self.program, "uProj")
        self.locBase = glGetUniformLocation(self.program, "uBaseColor")
        self.locLdir = glGetUniformLocation(self.program, "uLightDirW")
        self.locAmb = glGetUniformLocation(self.program, "uAmbient")
        self.locDif = glGetUniformLocation(self.program, "uDiffuse")
        
        # Toon shader
        self.toon_program = compileProgram(
            compileShader(VERT_SRC, GL_VERTEX_SHADER),
            compileShader(TOON_FRAG, GL_FRAGMENT_SHADER),
        )
        self.toon_locModel = glGetUniformLocation(self.toon_program, "uModel")
        self.toon_locView = glGetUniformLocation(self.toon_program, "uView")
        self.toon_locProj = glGetUniformLocation(self.toon_program, "uProj")
        self.toon_locBase = glGetUniformLocation(self.toon_program, "uBaseColor")
        self.toon_locLdir = glGetUniformLocation(self.toon_program, "uLightDirW")
        self.toon_locAmb = glGetUniformLocation(self.toon_program, "uAmbient")
        self.toon_locDif = glGetUniformLocation(self.toon_program, "uDiffuse")
        self.toon_locCamPos = glGetUniformLocation(self.toon_program, "uCameraPos")
        
        # Outline shader
        self.outline_program = compileProgram(
            compileShader(OUTLINE_VERT, GL_VERTEX_SHADER),
            compileShader(OUTLINE_FRAG, GL_FRAGMENT_SHADER),
        )
        self.outline_locModel = glGetUniformLocation(self.outline_program, "uModel")
        self.outline_locView = glGetUniformLocation(self.outline_program, "uView")
        self.outline_locProj = glGetUniformLocation(self.outline_program, "uProj")
        self.outline_locWidth = glGetUniformLocation(self.outline_program, "uOutlineWidth")
        self.outline_locColor = glGetUniformLocation(self.outline_program, "uOutlineColor")

        # Line shader
        self.line_program = compileProgram(
            compileShader(LINE_VERT, GL_VERTEX_SHADER),
            compileShader(LINE_FRAG, GL_FRAGMENT_SHADER),
        )
        self.line_locView = glGetUniformLocation(self.line_program, "uView")
        self.line_locProj = glGetUniformLocation(self.line_program, "uProj")

        # Screen line shader
        self.screen_line_program = compileProgram(
            compileShader(SCREEN_LINE_VERT, GL_VERTEX_SHADER),
            compileShader(SCREEN_LINE_FRAG, GL_FRAGMENT_SHADER),
        )

        # OpenGL state
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glFrontFace(GL_CCW)  # Counter-clockwise winding
        
        # Enable MSAA if available
        glEnable(GL_MULTISAMPLE)

        # GPU cache
        self.gpu_cache = {}

        # Grid
        self.grid = GLGrid(grid_size=200, step=20, z0=0.0)

        # Dynamic buffers
        self.screen_line_vao = glGenVertexArrays(1)
        self.screen_line_vbo = glGenBuffers(1)
        self.axes_vao = glGenVertexArrays(1)
        self.axes_vbo = glGenBuffers(1)

        self.resize(width, height)
        
        print(f"Renderer initialized in {self.render_mode} mode")

    def resize(self, width, height):
        self.w = max(1, int(width))
        self.h = max(1, int(height))
        glViewport(0, 0, self.w, self.h)

    def _get_gpu(self, mesh):
        key = id(mesh)
        if key not in self.gpu_cache:
            self.gpu_cache[key] = GLMeshGPU(mesh)
        return self.gpu_cache[key]

    def render(self, scene, camera):
        # Clear
        glClearColor(30/255, 30/255, 35/255, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # Camera owns a standard OpenGL view/projection (Y-up, -Z forward).
        # Read viewport aspect every frame, including after a window resize.
        V = camera.view_matrix.astype(DTYPE)
        P = camera.projection_matrix(self.w / self.h).astype(DTYPE)
        cam_pos = camera.position

        # ==================== Render Based on Mode ====================
        entities = scene.get_flat_render_list()
        imported = [e for e in entities if getattr(e.model, "material", None) is not None]
        entities = [e for e in entities if getattr(e.model, "material", None) is None]
        
        if self.render_mode == "OUTLINE":
            # Two-pass rendering: outline + toon shading
            self._render_outline_pass(entities, V, P, scene)
            self._render_toon_pass(entities, V, P, scene, cam_pos)
        elif self.render_mode == "TOON":
            # Single-pass toon shading
            self._render_toon_pass(entities, V, P, scene, cam_pos)
        else:  # REALISTIC
            # Standard realistic rendering
            self._render_realistic_pass(entities, V, P, scene)

        if imported:
            if not hasattr(self, "material_renderer"):
                from .material_renderer import MaterialRenderer
                self.material_renderer = MaterialRenderer()
            self.material_renderer.render(imported, camera, scene, self.w, self.h,
                                          mode=getattr(scene, "render_mode", "Lit"))

        # ==================== Render Grid ====================
        glUseProgram(self.line_program)
        grid_scale = getattr(scene, "grid_scale", 1.0)
        grid_transform = np.diag([grid_scale, grid_scale, 1., 1.])
        if getattr(scene, "ground", None) is not None:
            # Bias only the editor guide lines above the built-in surface.
            # Ground geometry and placement remain exactly at world Z=0.
            grid_transform[2, 3] = grid_scale * .02
        grid_view = V @ grid_transform
        glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, grid_view.astype(DTYPE))
        glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

        glBindVertexArray(self.grid.vao)
        glLineWidth(1.0)
        if getattr(scene, "show_grid", True):
            glDrawArrays(GL_LINES, 0, self.grid.count)
        glBindVertexArray(0)

        # ==================== Render Axes ====================
        glDisable(GL_DEPTH_TEST)
        
        # World axes
        if getattr(scene, "show_axes", True):
            self.draw_axes_world(V, P, origin=(0, 0, 0), scale=60.0)
        
        # Entity axes
        for ent in entities:
            if getattr(ent, "isaxes", False):
                self.draw_axes_at_matrix(V, P, ent.world_matrix, scale=30.0)
        
        glEnable(GL_DEPTH_TEST)
    
    def _render_realistic_pass(self, entities, V, P, scene):
        """Standard realistic rendering"""
        glUseProgram(self.program)
        
        # Set view and projection
        glUniformMatrix4fv(self.locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.locProj, 1, GL_TRUE, P)

        # Set lighting
        ldir = np.asarray(scene.light_dir, dtype=DTYPE)
        glUniform3f(self.locLdir, float(ldir[0]), float(ldir[1]), float(ldir[2]))
        glUniform1f(self.locAmb, float(scene.ambient))
        glUniform1f(self.locDif, float(scene.diffuse))

        # Render entities
        for ent in entities:
            if not ent.model:
                continue

            gpu = self._get_gpu(ent.model)

            # Set model matrix
            M = ent.world_matrix.astype(DTYPE)
            glUniformMatrix4fv(self.locModel, 1, GL_TRUE, M)

            # Set base color
            if hasattr(ent.model, "base_color"):
                bc = np.asarray(ent.model.base_color, dtype=np.float32) / 255.0
            else:
                bc = np.asarray(ent.model.colors[0], dtype=np.float32) / 255.0

            glUniform3f(self.locBase, float(bc[0]), float(bc[1]), float(bc[2]))

            # Draw
            glBindVertexArray(gpu.vao)
            glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
    
    def _render_toon_pass(self, entities, V, P, scene, cam_pos):
        """Toon/cel-shading rendering"""
        glUseProgram(self.toon_program)
        
        # Set view and projection
        glUniformMatrix4fv(self.toon_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.toon_locProj, 1, GL_TRUE, P)

        # Set lighting
        ldir = np.asarray(scene.light_dir, dtype=DTYPE)
        glUniform3f(self.toon_locLdir, float(ldir[0]), float(ldir[1]), float(ldir[2]))
        glUniform1f(self.toon_locAmb, float(scene.ambient))
        glUniform1f(self.toon_locDif, float(scene.diffuse))
        
        # Set camera position
        glUniform3f(self.toon_locCamPos, float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2]))

        # Render entities
        for ent in entities:
            if not ent.model:
                continue

            gpu = self._get_gpu(ent.model)

            # Set model matrix
            M = ent.world_matrix.astype(DTYPE)
            glUniformMatrix4fv(self.toon_locModel, 1, GL_TRUE, M)

            # Set base color
            if hasattr(ent.model, "base_color"):
                bc = np.asarray(ent.model.base_color, dtype=np.float32) / 255.0
            else:
                bc = np.asarray(ent.model.colors[0], dtype=np.float32) / 255.0

            glUniform3f(self.toon_locBase, float(bc[0]), float(bc[1]), float(bc[2]))

            # Draw
            glBindVertexArray(gpu.vao)
            glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
    
    def _render_outline_pass(self, entities, V, P, scene):
        """Render black outlines (first pass for outline mode)"""
        glUseProgram(self.outline_program)
        
        # Set view and projection
        glUniformMatrix4fv(self.outline_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.outline_locProj, 1, GL_TRUE, P)
        
        # Outline settings - REDUCED for better visibility
        outline_width = 0.15  # Much thinner! (was 0.5)
        outline_color = np.array([0.0, 0.0, 0.0], dtype=DTYPE)  # Black outlines
        
        glUniform1f(self.outline_locWidth, outline_width)
        glUniform3f(self.outline_locColor, outline_color[0], outline_color[1], outline_color[2])
        
        # AGGRESSIVE FIX for spheres: Much stronger depth offset
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(10.0, 10.0)  # Even stronger offset
        
        # Also disable depth write for outline pass
        glDepthMask(GL_FALSE)  # Don't write to depth buffer
        
        # Render front faces as outlines (inverted culling)
        glCullFace(GL_FRONT)

        # Render entities
        for ent in entities:
            if not ent.model:
                continue

            gpu = self._get_gpu(ent.model)

            # Set model matrix
            M = ent.world_matrix.astype(DTYPE)
            glUniformMatrix4fv(self.outline_locModel, 1, GL_TRUE, M)

            # Draw
            glBindVertexArray(gpu.vao)
            glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
            glBindVertexArray(0)
        
        # Restore normal state
        glCullFace(GL_BACK)
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDepthMask(GL_TRUE)  # Re-enable depth writes

    def draw_axes_world(self, V, P, origin=(0.0, 0.0, 0.0), scale=50.0,
                        head_len_ratio=0.18, head_w_ratio=0.08):
        """
        Draw world coordinate axes: X(red), Y(green), Z(blue)
        """
        o = np.array(origin, dtype=np.float32)

        # Axis endpoints
        x = o + np.array([scale, 0, 0], dtype=np.float32)
        y = o + np.array([0, scale, 0], dtype=np.float32)
        z = o + np.array([0, 0, scale], dtype=np.float32)

        # Colors
        R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
        G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
        B = np.array([0.2, 0.2, 1.0], dtype=np.float32)

        verts = []
        cols = []

        v, c = add_axis_with_arrow(o, x, R, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, y, G, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, z, B, scale)
        verts += v
        cols += c

        verts = np.asarray(verts, dtype=np.float32)
        cols = np.asarray(cols, dtype=np.float32)

        inter = np.hstack([verts, cols]).astype(np.float32)

        prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

        glUseProgram(self.line_program)
        glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

        glBindVertexArray(self.axes_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        glLineWidth(2.0)
        glDrawArrays(GL_LINES, 0, verts.shape[0])

        glBindVertexArray(0)
        glUseProgram(prev_prog)

    def draw_axes_at_matrix(self, V, P, T_w, scale=30.0):
        """
        Draw local coordinate axes at given transform matrix
        """
        T = np.asarray(T_w, dtype=np.float32)

        o = T[:3, 3]
        ex = T[:3, 0]
        ex = ex / (np.linalg.norm(ex) + 1e-9)
        ey = T[:3, 1]
        ey = ey / (np.linalg.norm(ey) + 1e-9)
        ez = T[:3, 2]
        ez = ez / (np.linalg.norm(ez) + 1e-9)

        x = o + ex * scale
        y = o + ey * scale
        z = o + ez * scale

        R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
        G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
        B = np.array([0.2, 0.2, 1.0], dtype=np.float32)

        verts = []
        cols = []

        v, c = add_axis_with_arrow(o, x, R, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, y, G, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, z, B, scale)
        verts += v
        cols += c

        verts = np.asarray(verts, dtype=np.float32)
        cols = np.asarray(cols, dtype=np.float32)

        inter = np.hstack([verts, cols]).astype(np.float32)

        prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

        glUseProgram(self.line_program)
        glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

        glBindVertexArray(self.axes_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        glLineWidth(2.0)
        glDrawArrays(GL_LINES, 0, verts.shape[0])

        glBindVertexArray(0)
        glUseProgram(prev_prog)

    def draw_screen_lines(self, segments_px, colors_rgb, widths=None):
        """
        Draw 2D lines in screen space (pixel coordinates)
        """
        if len(segments_px) == 0:
            return

        seg = np.asarray(segments_px, np.float32)
        col = np.asarray(colors_rgb, np.float32) / 255.0

        W, H = float(self.w), float(self.h)

        # Convert pixel coords to NDC
        x = seg[..., 0]
        y = seg[..., 1]
        x_ndc = 2.0 * (x / (W + 1e-9)) - 1.0
        y_ndc = 1.0 - 2.0 * (y / (H + 1e-9))

        # Flatten to vertex stream
        pos = np.stack([x_ndc, y_ndc], axis=-1).reshape(-1, 2)

        # Repeat colors
        col2 = np.repeat(col, 2, axis=0)

        inter = np.hstack([pos, col2]).astype(np.float32)

        glUseProgram(self.screen_line_program)
        glBindVertexArray(self.screen_line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.screen_line_vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

        stride = 5 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

        if widths is not None:
            glLineWidth(float(np.max(widths)))
        else:
            glLineWidth(1.0)

        glDrawArrays(GL_LINES, 0, inter.shape[0])
        glBindVertexArray(0)

    def draw_grid_cpu_like(self, camera, grid_size=200, step=20, z0=0.0, near=None):
        """
        Fallback: CPU-side grid rendering (for compatibility)
        """
        near = camera.near if near is None else near
        focal = self.h / (2 * np.tan(np.deg2rad(camera.fov_y) / 2))
        base_color = (90, 90, 90)
        x_axis_color = (180, 80, 80)
        y_axis_color = (80, 180, 80)

        lines = []
        colors = []
        widths = []

        for i in range(-grid_size, grid_size + 1, step):
            a1 = [i, -grid_size, z0, 1]
            b1 = [i, grid_size, z0, 1]
            a2 = [-grid_size, i, z0, 1]
            b2 = [grid_size, i, z0, 1]

            if i == 0:
                lines.append([a1, b1])
                colors.append(y_axis_color)
                widths.append(2)
                lines.append([a2, b2])
                colors.append(x_axis_color)
                widths.append(2)
            else:
                lines.append([a1, b1])
                colors.append(base_color)
                widths.append(1)
                lines.append([a2, b2])
                colors.append(base_color)
                widths.append(1)

        lines = np.asarray(lines, dtype=np.float32)

        # Transform to camera space
        flat = lines.reshape(-1, 4)
        flat_cam = flat @ camera.T_w_to_c.T
        lines_cam = flat_cam.reshape(-1, 2, 4)

        # Project
        seg2d = []
        segcol = []
        segw = []

        for seg, col, w in zip(lines_cam, colors, widths):
            p0 = seg[0]
            p1 = seg[1]

            if p0[2] <= near or p1[2] <= near:
                continue

            x0 = focal * (p0[0] / p0[2]) + self.w / 2.0
            y0 = focal * (p0[1] / p0[2]) + self.h / 2.0
            x1 = focal * (p1[0] / p1[2]) + self.w / 2.0
            y1 = focal * (p1[1] / p1[2]) + self.h / 2.0

            seg2d.append([[x0, y0], [x1, y1]])
            segcol.append(col)
            segw.append(w)

        self.draw_screen_lines(seg2d, segcol, segw)
