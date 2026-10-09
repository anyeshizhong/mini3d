"""Scene framing and Pygame input for a Z-up orbit camera."""
from itertools import product

import numpy as np
import pygame

from .camera import Camera
from .orbit_controller import OrbitController


def _world_boxes(entities, visible_only=False):
    """Eight corners per instance, reusing immutable mesh-local AABBs."""
    pending = list(entities)
    while pending:
        entity = pending.pop()
        if visible_only and not getattr(entity, 'visible', True):
            continue
        pending.extend(getattr(entity, 'children', ()))
        model = getattr(entity, 'model', None)
        if model is None:
            continue
        if not hasattr(model, 'bounds'):
            # Compatibility with old demo meshes. Scan ONCE, not each frame.
            # Geometry edits must refresh bounds, like the renderer's GPU cache.
            points = np.asarray(model.vertices)[:, :3]
            model.bounds = (points.min(axis=0), points.max(axis=0)) if len(points) else None
        if model.bounds is None:
            continue
        corners = np.array(list(product(*zip(*model.bounds))), dtype=np.float64)
        transform = np.asarray(entity.world_matrix, dtype=np.float64)
        yield corners @ transform[:3, :3].T + transform[:3, 3]


def world_bounds(entities, visible_only=False):
    """World AABB of complete entity subtrees, including URDF visual children.

    The scene must update world matrices before calling this function. Transform
    local box corners so rotation, parent transforms and scale are included.
    Empty containers and meshes contribute no bounds.
    """
    lower = upper = None
    for points in _world_boxes(entities, visible_only):
        lo, hi = points.min(axis=0), points.max(axis=0)
        lower = lo if lower is None else np.minimum(lower, lo)
        upper = hi if upper is None else np.maximum(upper, hi)
    return None if lower is None else (lower, upper)


class Viewer:
    """Own camera interaction; the application still owns its scene/render loop.

    Left/middle drag: orbit. Shift+drag or right drag: pan. Wheel: dolly.
    F: focus selected_entity, Home: frame all, R: restore startup view.
    1/3/7: front/right/top (2 is also top); Ctrl gives opposite views.
    These bindings apply only with input_enabled=True. Editor creates this
    object with input_enabled=False and calls controller/framing methods itself.
    """

    def __init__(self, scene, width, height, camera=None, input_enabled=True):
        self.scene = scene
        # Standalone demos opt into these bindings; the editor owns arbitration.
        self.input_enabled = input_enabled
        self.camera = camera if camera is not None else Camera()
        self.controller = OrbitController(self.camera, clip_depth_provider=self._clip_depth_range)
        self.selected_entity = None
        self._drag_button = None
        self.resize(width, height)
        self.frame_all()
        self.save_camera()

    @property
    def aspect(self):
        return self.width / self.height

    def resize(self, width, height):
        self.width = max(1, int(width))
        self.height = max(1, int(height))

    def _clip_depth_range(self):
        """Current visible geometry depths; separate from the focus bounds.

        Project each transformed box before unioning depths to avoid widening a
        rotated scene's range unnecessarily. Entirely rearward boxes are ignored.
        """
        self.scene.update()
        minimum = maximum = None
        eye, forward = self.camera.position, self.camera.forward
        for points in _world_boxes(self.scene.root_entities, visible_only=True):
            depths = (points-eye) @ forward
            lo, hi = float(depths.min()), float(depths.max())
            if hi <= 0:
                continue
            minimum = lo if minimum is None else min(minimum, lo)
            maximum = hi if maximum is None else max(maximum, hi)
        return None if maximum is None else (minimum, maximum)

    def update_clipping(self):
        """Refresh before rendering after scene edits, without moving the camera."""
        self.controller.update_clipping()

    def focus(self, entity):
        """Frame an entity and all its descendants at their current pose."""
        if entity is None:
            return False
        self.scene.update()
        bounds = world_bounds([entity], visible_only=True)
        if bounds is None:
            return False
        self.controller.focus_bounds(*bounds, aspect=self.aspect)
        return True

    def frame_all(self):
        self.scene.update()
        bounds = world_bounds(self.scene.root_entities, visible_only=True)
        if bounds is None:
            return False
        self.controller.focus_bounds(*bounds, aspect=self.aspect)
        return True

    def set_view(self, name):
        self.controller.set_view(name)

    def save_camera(self):
        """Make the current view the reset destination."""
        self._saved_camera = self.controller.snapshot()

    def reset_camera(self):
        self._drag_button = None
        self.controller.restore(self._saved_camera)

    def handle_event(self, event):
        """Consume navigation events. Relative mouse deltas do not use dt."""
        if not self.input_enabled:
            return False
        if event.type == pygame.VIDEORESIZE:
            self.resize(event.w, event.h)
            return False  # The application must also resize its renderer.
        if event.type == pygame.WINDOWFOCUSLOST:
            self._drag_button = None
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 2, 3):
            self._drag_button = event.button
            return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == self._drag_button:
            self._drag_button = None
            return True
        elif event.type == pygame.MOUSEMOTION and self._drag_button is not None:
            buttons = getattr(event, "buttons", None)
            if buttons is not None and not buttons[self._drag_button - 1]:
                self._drag_button = None
                return False
            dx, dy = event.rel
            mods = getattr(event, "mod", None)
            if mods is None:
                mods = pygame.key.get_mods()
            if self._drag_button == 3 or mods & pygame.KMOD_SHIFT:
                self.controller.pan(dx, dy, self.height)
            else:
                self.controller.orbit(dx, dy)
            return True
        elif event.type == pygame.MOUSEWHEEL:
            self.controller.zoom(event.y)
            return True
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_f:
                self.focus(self.selected_entity)
            elif event.key == pygame.K_HOME:
                self.frame_all()
            elif event.key == pygame.K_r:
                self.reset_camera()
            else:
                views = {
                    pygame.K_1: ("front", "back"),
                    pygame.K_KP1: ("front", "back"),
                    pygame.K_3: ("right", "left"),
                    pygame.K_KP3: ("right", "left"),
                    pygame.K_7: ("top", "bottom"),
                    pygame.K_KP7: ("top", "bottom"),
                    pygame.K_2: ("top", "bottom"),
                }
                if event.key not in views:
                    return False
                opposite = bool(getattr(event, "mod", 0) & pygame.KMOD_CTRL)
                self.set_view(views[event.key][opposite])
            return True
        return False
