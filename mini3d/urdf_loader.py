# urdf_loader.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import os
import numpy as np
import xml.etree.ElementTree as ET

DTYPE = np.float32


# -------------------------
# Basic math for URDF
# -------------------------
def _parse_vec3(s: Optional[str], default=(0.0, 0.0, 0.0)) -> np.ndarray:
    if s is None or str(s).strip() == "":
        return np.array(default, dtype=DTYPE)
    parts = str(s).strip().split()
    if len(parts) != 3:
        return np.array(default, dtype=DTYPE)
    return np.array([float(parts[0]), float(parts[1]), float(parts[2])], dtype=DTYPE)


def _parse_rgba(s: Optional[str], default=(0.78, 0.78, 0.78, 1.0)) -> Tuple[float, float, float, float]:
    if s is None or str(s).strip() == "":
        return default
    parts = str(s).strip().split()
    if len(parts) != 4:
        return default
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def urdf_rpy_matrix(roll, pitch, yaw) -> np.ndarray:
    """
    URDF fixed-axis RPY:
    R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    """
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)

    Rx = np.array([[1,0,0],[0,cr,-sr],[0,sr,cr]], dtype=DTYPE)
    Ry = np.array([[cp,0,sp],[0,1,0],[-sp,0,cp]], dtype=DTYPE)
    Rz = np.array([[cy,-sy,0],[sy,cy,0],[0,0,1]], dtype=DTYPE)
    return (Rz @ Ry @ Rx).astype(DTYPE)


def rot_axis_angle(axis_xyz, theta) -> np.ndarray:
    axis = np.asarray(axis_xyz, dtype=DTYPE)
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    x, y, z = axis
    c = np.cos(theta).astype(DTYPE)
    s = np.sin(theta).astype(DTYPE)
    C = (1 - c).astype(DTYPE)
    R = np.array([
        [c + x*x*C,     x*y*C - z*s, x*z*C + y*s],
        [y*x*C + z*s,   c + y*y*C,   y*z*C - x*s],
        [z*x*C - y*s,   z*y*C + x*s, c + z*z*C]
    ], dtype=DTYPE)
    return R


def joint_transform(origin_xyz, origin_rpy, axis_xyz, q) -> np.ndarray:
    """
    Parent(link frame) -> Child(link frame) at joint:
    T = T(origin_xyz) * R(origin_rpy) * R_axis(q)
    """
    ox, oy, oz = origin_xyz
    rr, rp, ry = origin_rpy

    T = np.eye(4, dtype=DTYPE)
    T[:3, 3] = np.array([ox, oy, oz], dtype=DTYPE)

    R0 = urdf_rpy_matrix(rr, rp, ry)
    Rq = rot_axis_angle(axis_xyz, q)

    M = np.eye(4, dtype=DTYPE)
    M[:3, :3] = (R0 @ Rq).astype(DTYPE)

    return (T @ M).astype(DTYPE)


# -------------------------
# Path resolver
# -------------------------
def resolve_mesh_filename(filename: str, *, urdf_dir: str, package_map: Optional[Dict[str, str]] = None) -> str:
    """
    Support:
    - package://pkg_name/path/to/file.stl
    - relative path: meshes/a.stl  (relative to urdf_dir)
    - absolute path
    """
    if filename is None:
        raise ValueError("mesh filename is None")

    f = filename.strip()

    if f.startswith("package://"):
        # package://<pkg>/<rest>
        rest = f[len("package://"):]
        parts = rest.split("/", 1)
        pkg = parts[0]
        sub = parts[1] if len(parts) > 1 else ""
        if not package_map or pkg not in package_map:
            raise ValueError(f"package_map missing for package '{pkg}'")
        base = os.path.normpath(package_map[pkg])
        return os.path.normpath(os.path.join(base, sub))

    # Common ROS style sometimes: "file://..."
    if f.startswith("file://"):
        f = f[len("file://"):]
        return os.path.normpath(f)

    # absolute
    if os.path.isabs(f):
        return os.path.normpath(f)

    # relative to urdf
    return os.path.normpath(os.path.join(urdf_dir, f))


# -------------------------
# URDF specs
# -------------------------
@dataclass
class LinkSpec:
    name: str
    mesh_filename: Optional[str] = None
    color_rgba: Optional[Tuple[float, float, float, float]] = None

    # visual origin (offset of mesh inside link frame)
    visual_origin_xyz: np.ndarray = field(default_factory=lambda: np.array([0,0,0], dtype=DTYPE))
    visual_origin_rpy: np.ndarray = field(default_factory=lambda: np.array([0,0,0], dtype=DTYPE))


@dataclass
class JointSpec:
    name: str
    joint_type: str          # revolute / continuous / prismatic / fixed
    parent: str
    child: str
    origin_xyz: np.ndarray
    origin_rpy: np.ndarray
    axis_xyz: np.ndarray


@dataclass
class URDFModel:
    links: Dict[str, LinkSpec]
    joints: Dict[str, JointSpec]
    tree: Dict[str, List[str]]        # parent_link -> [joint_name...]
    parent_of: Dict[str, str]         # child_link -> parent_link
    root_link: str


def load_urdf(urdf_path: str, *, package_map: Optional[Dict[str, str]] = None) -> URDFModel:
    urdf_path = os.path.normpath(urdf_path)
    urdf_dir = os.path.dirname(urdf_path)

    xml_tree = ET.parse(urdf_path)
    robot = xml_tree.getroot()

    # ---- Links ----
    links: Dict[str, LinkSpec] = {}

    for link_el in robot.findall("link"):
        lname = (link_el.attrib.get("name") or "").strip()
        if not lname:
            continue

        mesh_filename = None
        color_rgba = None
        vis_xyz = np.array([0,0,0], dtype=DTYPE)
        vis_rpy = np.array([0,0,0], dtype=DTYPE)

        visual_el = link_el.find("visual")
        if visual_el is not None:
            origin_el = visual_el.find("origin")
            if origin_el is not None:
                vis_xyz = _parse_vec3(origin_el.attrib.get("xyz"))
                vis_rpy = _parse_vec3(origin_el.attrib.get("rpy"))

            geom_el = visual_el.find("geometry")
            if geom_el is not None:
                mesh_el = geom_el.find("mesh")
                if mesh_el is not None:
                    mesh_filename = (mesh_el.attrib.get("filename") or "").strip() or None

            mat_el = visual_el.find("material")
            if mat_el is not None:
                color_el = mat_el.find("color")
                if color_el is not None:
                    color_rgba = _parse_rgba(color_el.attrib.get("rgba"))

        # Resolve mesh path early (optional)
        if mesh_filename:
            try:
                mesh_filename = resolve_mesh_filename(mesh_filename, urdf_dir=urdf_dir, package_map=package_map)
            except Exception as e:
                print(f"[URDF] mesh resolve failed for link '{lname}': {mesh_filename} -> {e}")
                mesh_filename = None

        links[lname] = LinkSpec(
            name=lname,
            mesh_filename=mesh_filename,
            color_rgba=color_rgba,
            visual_origin_xyz=vis_xyz,
            visual_origin_rpy=vis_rpy,
        )

    # ---- Joints ----
    joints: Dict[str, JointSpec] = {}

    for j_el in robot.findall("joint"):
        jname = (j_el.attrib.get("name") or "").strip()
        jtype = (j_el.attrib.get("type") or "fixed").strip()

        parent_el = j_el.find("parent")
        child_el = j_el.find("child")
        if parent_el is None or child_el is None:
            continue

        parent = (parent_el.attrib.get("link") or "").strip()
        child  = (child_el.attrib.get("link") or "").strip()
        if not parent or not child:
            continue

        origin_el = j_el.find("origin")
        origin_xyz = _parse_vec3(origin_el.attrib.get("xyz") if origin_el is not None else None)
        origin_rpy = _parse_vec3(origin_el.attrib.get("rpy") if origin_el is not None else None)

        axis_el = j_el.find("axis")
        axis_xyz = _parse_vec3(axis_el.attrib.get("xyz") if axis_el is not None else None, default=(0.0, 0.0, 1.0))

        joints[jname] = JointSpec(
            name=jname,
            joint_type=jtype,
            parent=parent,
            child=child,
            origin_xyz=origin_xyz,
            origin_rpy=origin_rpy,
            axis_xyz=axis_xyz
        )

    # ---- Tree ----
    tree: Dict[str, List[str]] = {}
    parent_of: Dict[str, str] = {}
    children_set = set()

    for j in joints.values():
        tree.setdefault(j.parent, []).append(j.name)
        parent_of[j.child] = j.parent
        children_set.add(j.child)

    all_links = set(links.keys())
    roots = list(all_links - children_set)
    root_link = roots[0] if roots else (next(iter(all_links)) if all_links else "")

    return URDFModel(links=links, joints=joints, tree=tree, parent_of=parent_of, root_link=root_link)


# -------------------------
# Build Entity tree adapter
# -------------------------
def build_entity_tree(
    urdf: URDFModel,
    *,
    EntityClass,
    model_loader,
    default_color_rgb=(200, 200, 200)
):
    """
    Strategy:
    - Each Link becomes a container Entity (model=None). It represents the link frame.
    - If link has a mesh, create a visual child entity with model + visual offset (extra_local = T_vis).
    - Joints connect parent_link_entity -> child_link_entity.
    - We return:
        link_entities: {link_name: Entity}
        joint_order: DFS order of joints for convenient control
    """
    link_entities: Dict[str, object] = {}
    joint_order: List[str] = []

    # 1) create link entities + visual children
    for lname, lk in urdf.links.items():
        link_ent = EntityClass(name=lname, model=None, pos=[0,0,0], rot=[0,0,0], scale=1.0)

        if not hasattr(link_ent, "extra_local"):
            link_ent.extra_local = np.eye(4, dtype=DTYPE)

        if lk.mesh_filename:
            rgba = lk.color_rgba
            if rgba is None:
                rgba = (default_color_rgb[0]/255.0, default_color_rgb[1]/255.0, default_color_rgb[2]/255.0, 1.0)

            model = model_loader(lk.mesh_filename, rgba)
            if model is not None:
                vis_ent = EntityClass(name=f"{lname}__visual", model=model, pos=[0,0,0], rot=[0,0,0], scale=1.0)

                T_vis = np.eye(4, dtype=DTYPE)
                T_vis[:3, 3] = lk.visual_origin_xyz
                T_vis[:3, :3] = urdf_rpy_matrix(lk.visual_origin_rpy[0], lk.visual_origin_rpy[1], lk.visual_origin_rpy[2])
                vis_ent.extra_local = T_vis

                link_ent.add_child(vis_ent)

        link_entities[lname] = link_ent

    # 2) connect by joints (DFS from root)
    def dfs(parent_link: str):
        if parent_link not in urdf.tree:
            return
        for jname in urdf.tree[parent_link]:
            joint_order.append(jname)
            j = urdf.joints[jname]

            parent_ent = link_entities[j.parent]
            child_ent  = link_entities[j.child]

            parent_ent.add_child(child_ent)

            # initial q=0
            child_ent.extra_local = joint_transform(j.origin_xyz, j.origin_rpy, j.axis_xyz, 0.0)

            dfs(j.child)

    if urdf.root_link:
        dfs(urdf.root_link)

    return link_entities, joint_order