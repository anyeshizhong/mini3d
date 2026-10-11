"""URDF hierarchy and joint control using the optional local car asset."""
import numpy as np
import pygame
from pygame.locals import OPENGL, DOUBLEBUF, RESIZABLE
from mini3d.geometry import make_box
from mini3d.gl_renderer import GLRenderer
from mini3d.math3d import normalize
from mini3d.urdf_loader import load_urdf, build_entity_tree, joint_transform
from mini3d.viewer import Viewer
from .legacy_scene import DTYPE, PROJECT, Entity, Mesh, Scene, STLModel


def main():
    pygame.init()
    W, H = 1200, 800
    pygame.display.set_mode((W, H), OPENGL | DOUBLEBUF | RESIZABLE)
    pygame.display.set_caption("Mini3D URDF | Drag: orbit | Shift+drag: pan | Wheel: zoom | F/Home/R")

    gl_renderer = GLRenderer(W, H)
    clock = pygame.time.Clock()

    # ---- Load URDF ----
    asset_dir = PROJECT
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
