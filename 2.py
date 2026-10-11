"""Compatibility entry; use python -m examples.urdf_car."""
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
from examples.urdf_car import Entity, Mesh, Scene, STLModel, main

if __name__ == "__main__":
    main()
