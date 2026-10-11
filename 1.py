"""Compatibility entry; use python -m examples.primitives."""
from pathlib import Path
from mini3d.viewer import Viewer
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
from examples.primitives import Entity, Mesh, Scene, STLModel, main

if __name__ == "__main__":
    main()
