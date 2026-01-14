# geometry.py
import numpy as np
DTYPE = np.float32

def make_box(w=20.0, h=20.0, d=20.0):
    """创建立方体，确保正确的法线和索引顺序"""
    hx, hy, hz = w/2, h/2, d/2
    
    # 创建 8 个顶点
    vertices = np.array([
        [-hx, -hy, -hz],  # 0: 左后下
        [ hx, -hy, -hz],  # 1: 右后下
        [ hx,  hy, -hz],  # 2: 右前下
        [-hx,  hy, -hz],  # 3: 左前下
        [-hx, -hy,  hz],  # 4: 左后上
        [ hx, -hy,  hz],  # 5: 右后上
        [ hx,  hy,  hz],  # 6: 右前上
        [-hx,  hy,  hz],  # 7: 左前上
    ], dtype=DTYPE)
    
    # 重要：每个面使用独立的顶点（24个顶点），以便每个顶点有正确的法线方向
    # 对于立方体，顶点法线应该垂直于面，所以需要重复顶点
    vertices_full = []
    
    # 前面 (Z+)
    vertices_full.extend([
        [-hx, -hy, hz],  # 左后上 (对应顶点4)
        [ hx, -hy, hz],  # 右后上 (对应顶点5)
        [ hx,  hy, hz],  # 右前上 (对应顶点6)
        [-hx,  hy, hz],  # 左前上 (对应顶点7)
    ])
    
    # 后面 (Z-)
    vertices_full.extend([
        [ hx, -hy, -hz],  # 右后下 (对应顶点1)
        [-hx, -hy, -hz],  # 左后下 (对应顶点0)
        [-hx,  hy, -hz],  # 左前下 (对应顶点3)
        [ hx,  hy, -hz],  # 右前下 (对应顶点2)
    ])
    
    # 右面 (X+)
    vertices_full.extend([
        [ hx, -hy, -hz],  # 右后下 (对应顶点1)
        [ hx,  hy, -hz],  # 右前下 (对应顶点2)
        [ hx,  hy,  hz],  # 右前上 (对应顶点6)
        [ hx, -hy,  hz],  # 右后上 (对应顶点5)
    ])
    
    # 左面 (X-)
    vertices_full.extend([
        [-hx, -hy,  hz],  # 左后上 (对应顶点4)
        [-hx,  hy,  hz],  # 左前上 (对应顶点7)
        [-hx,  hy, -hz],  # 左前下 (对应顶点3)
        [-hx, -hy, -hz],  # 左后下 (对应顶点0)
    ])
    
    # 上面 (Y+)
    vertices_full.extend([
        [-hx, hy,  hz],  # 左前上 (对应顶点7)
        [ hx, hy,  hz],  # 右前上 (对应顶点6)
        [ hx, hy, -hz],  # 右前下 (对应顶点2)
        [-hx, hy, -hz],  # 左前下 (对应顶点3)
    ])
    
    # 下面 (Y-)
    vertices_full.extend([
        [-hx, -hy, -hz],  # 左后下 (对应顶点0)
        [ hx, -hy, -hz],  # 右后下 (对应顶点1)
        [ hx, -hy,  hz],  # 右后上 (对应顶点5)
        [-hx, -hy,  hz],  # 左后上 (对应顶点4)
    ])
    
    vertices = np.array(vertices_full, dtype=DTYPE)
    
    # 索引 - 每个面2个三角形（逆时针）
    indices = []
    for i in range(6):
        base = i * 4
        # 第一个三角形
        indices.append([base, base + 1, base + 2])
        # 第二个三角形
        indices.append([base, base + 2, base + 3])
    
    indices = np.array(indices, dtype=np.int32)
    
    return vertices, indices

def make_sphere(radius=20.0, rings=12, sectors=16):
    """
    创建球体网格
    ✅ 修复：确保法线朝外 (顶点顺序为逆时针)
    ✅ 修复：返回值与其他函数一致 (vertices, indices)
    """
    vertices = []
    indices = []
    
    R = 1.0 / (rings - 1)
    S = 1.0 / (sectors - 1)
    
    # 1. 生成顶点池
    for r in range(rings):
        for s in range(sectors):
            y = np.sin(-np.pi/2 + np.pi * r * R)
            x = np.cos(2 * np.pi * s * S) * np.sin(np.pi * r * R)
            z = np.sin(2 * np.pi * s * S) * np.sin(np.pi * r * R)
            vertices.append([x * radius, y * radius, z * radius])
            
    # 2. 生成索引 - 关键修复：反转卷曲顺序让法线朝外
    for r in range(rings - 1):
        for s in range(sectors - 1):
            # 找到网格中四个点的索引
            cur = r * sectors + s
            nxt = (r + 1) * sectors + s
            
            # 🔧 修复：反转三角形顶点顺序，让法线朝外
            # 原来: [cur, cur + 1, nxt + 1], [cur, nxt + 1, nxt]
            # 修复后: 逆时针卷曲
            indices.append([cur, nxt + 1, cur + 1])  # 反转
            indices.append([cur, nxt, nxt + 1])      # 反转
            
    return np.array(vertices, dtype=DTYPE), np.array(indices, dtype=np.int32)

def make_cylinder(radius=15.0, height=40.0, sectors=16):
    """
    创建圆柱体网格
    ✅ 确保法线朝外
    """
    vertices = []
    indices = []
    half_h = height / 2.0
    
    # --- 顶点生成 ---
    # 0 到 sectors-1: 顶圆
    # sectors 到 2*sectors-1: 底圆
    # 最后两个: 顶圆心, 底圆心
    
    # 侧面点
    for i in range(sectors):
        theta = 2 * np.pi * i / sectors
        x = radius * np.cos(theta)
        z = radius * np.sin(theta)
        vertices.append([x, half_h, z])  # 顶圈点 idx = i
    
    for i in range(sectors):
        theta = 2 * np.pi * i / sectors
        x = radius * np.cos(theta)
        z = radius * np.sin(theta)
        vertices.append([x, -half_h, z]) # 底圈点 idx = i + sectors
        
    # 圆心点
    top_center_idx = 2 * sectors
    bot_center_idx = 2 * sectors + 1
    vertices.append([0, half_h, 0])
    vertices.append([0, -half_h, 0])
    
    # --- 索引生成 ---
    for i in range(sectors):
        nxt = (i + 1) % sectors
        
        # 顶圈点索引
        t1, t2 = i, nxt
        # 底圈点索引
        b1, b2 = i + sectors, nxt + sectors
        
        # 侧面 - 确保逆时针
        indices.append([b1, t1, t2])
        indices.append([b1, t2, b2])
        
        # 顶盖 - 从上往下看逆时针
        indices.append([top_center_idx, t2, t1])
        
        # 底盖 - 从下往上看逆时针
        indices.append([bot_center_idx, b1, b2])

    return np.array(vertices, dtype=DTYPE), np.array(indices, dtype=np.int32)