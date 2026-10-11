"""A box moving in an XZ circle with an orbit camera."""
import math
import numpy as np
import pygame
from pygame.locals import OPENGL, DOUBLEBUF, RESIZABLE
from mini3d.geometry import make_box
from mini3d.gl_renderer import GLRenderer
from mini3d.math3d import normalize
from mini3d.viewer import Viewer, world_bounds
from .legacy_scene import DTYPE, PROJECT, Entity, Mesh, Scene, STLModel


def main():
    pygame.init()
    width, height = 1200, 800
    pygame.display.set_mode((width, height), OPENGL | DOUBLEBUF | RESIZABLE)
    pygame.display.set_caption("Mini3D | Drag: orbit | Shift+drag: pan | Wheel: zoom | F/Home/R")
    renderer = GLRenderer(width, height)
    clock = pygame.time.Clock()
    scene = Scene()
    scene.light_dir = normalize(np.array([0.0, 1.0, 1.0], dtype=DTYPE))
    asset_dir = PROJECT
    cube_model = STLModel(str(asset_dir / "model" / "06_stl_cube" / "cube.STL"), color=np.array([100, 200, 100]))
    model = Entity(cube_model, pos=[45, 0, 0], name="STL cube")
    model.isaxes = True
    scene.add(model)

    box_model = Mesh(*make_box(w=10, h=10, d=10), color=np.array([100, 100, 255]))
    entity_box = Entity(box_model, pos=[50, 0, 0], name="Box")
    scene.add(entity_box)
    viewer = Viewer(scene, width, height)
    controllable_entities = [entity_box, model]
    control_target_idx = 0
    viewer.selected_entity = controllable_entities[control_target_idx]
    print("Camera: drag to orbit; Shift+drag/right drag to pan; wheel to zoom")
    print("F: focus selection; Home: frame all; 1/3/7: front/right/top; Ctrl: opposite; R: reset")
    print("Tab: select focus target; box moves automatically; Esc: exit")
    # The moving box completes its circle around the origin in the XZ plane.
    # Frame the whole path once at startup so it remains visible while moving.
    lo, hi = world_bounds(scene.root_entities)
    viewer.controller.focus_bounds(np.minimum(lo, [-55, -5, -55]),
                                   np.maximum(hi, [55, 5, 55]), viewer.aspect)
    viewer.save_camera()
    angle = 0.0
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.VIDEORESIZE:
                renderer.resize(max(1, event.w), max(1, event.h))
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                control_target_idx = (control_target_idx + 1) % len(controllable_entities)
                viewer.selected_entity = controllable_entities[control_target_idx]
                print("Selected:", viewer.selected_entity.name)
            viewer.handle_event(event)
        angle += dt
        entity_box.pos[:] = [50 * math.cos(angle), 0, 50 * math.sin(angle)]
        scene.update()
        renderer.render(scene, viewer.camera)
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
