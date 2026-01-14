# math3d.py
import pygame
import numpy as np

DTYPE = np.float32

# --- 辅助函数 ---
def normalize(v):
    norm = np.linalg.norm(v)
    return v / norm if norm != 0 else v

def get_rotation_matrix(pitch, yaw, roll):
    """生成欧拉角旋转矩阵 (Z-X-Y顺序)"""
    cx, sx = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    cz, sz = np.cos(roll), np.sin(roll)

    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=DTYPE)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=DTYPE)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=DTYPE)
    
    # 这里的乘法顺序决定旋转顺序，通常用 Ry @ Rx @ Rz 或类似组合
    return ry @ rx @ rz 

def xyzrpy_to_T(xyz, rpy):
    """
    URDF 常用：origin xyz + rpy -> 4x4
    R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    """
    x, y, z = xyz
    r, p, yaw = rpy

    cr, sr = np.cos(r), np.sin(r)
    cp, sp = np.cos(p), np.sin(p)
    cy, sy = np.cos(yaw), np.sin(yaw)

    Rz = np.array([[cy,-sy,0],[sy,cy,0],[0,0,1]], dtype=DTYPE)
    Ry = np.array([[cp,0,sp],[0,1,0],[-sp,0,cp]], dtype=DTYPE)
    Rx = np.array([[1,0,0],[0,cr,-sr],[0,sr,cr]], dtype=DTYPE)

    T = np.eye(4, dtype=DTYPE)
    T[:3,:3] = (Rz @ Ry @ Rx)
    T[:3, 3] = np.array([x,y,z], dtype=DTYPE)
    return T

