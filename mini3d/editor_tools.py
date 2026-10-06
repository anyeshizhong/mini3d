"""Viewport transform handles. Mouse deltas are converted to world units."""
import math
import numpy as np

from .picking import project_point, screen_ray
from .scene import rotation_xyz


def segment_distance(point, a, b):
    point, a, b = np.asarray(point), np.asarray(a), np.asarray(b)
    ab = b - a
    t = np.clip(np.dot(point - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
    return np.linalg.norm(point - a - t * ab)


def plane_point(ray, origin, normal):
    eye, direction = ray
    denominator = np.dot(direction, normal)
    if abs(denominator) < 1e-6:
        return None
    t = np.dot(origin - eye, normal) / denominator
    return eye + t * direction if t > 0 else None


def euler_xyz(matrix):
    y = math.asin(float(np.clip(-matrix[2, 0], -1, 1)))
    if abs(math.cos(y)) > 1e-7:
        return np.array([math.atan2(matrix[2, 1], matrix[2, 2]), y,
                         math.atan2(matrix[1, 0], matrix[0, 0])])
    return np.array([math.atan2(-matrix[1, 2], matrix[1, 1]), y, 0.0])


class TransformGizmo:
    def __init__(self, app):
        self.app = app
        self.drag = None
        self.handles = []

    def geometry(self, rect):
        entity = self.app.selection
        self.handles = []
        if entity is None or not entity.visible or self.app.tool == "select":
            return None
        camera = self.app.viewer.camera
        origin = entity.pos.copy()
        center = project_point(camera, origin, rect)
        if center is None:
            return None
        distance = max(np.dot(origin - camera.position, camera.forward), camera.near)
        length = 95 * 2 * distance * math.tan(math.radians(camera.fov_y) / 2) / rect[3]
        for axis in range(3):
            direction = np.eye(3)[axis]
            if self.app.tool == "rotate":
                u, v = np.eye(3)[(axis + 1) % 3], np.eye(3)[(axis + 2) % 3]
                points = [project_point(camera, origin + length * (u * math.cos(a) + v * math.sin(a)), rect)
                          for a in np.linspace(0, math.tau, 65)]
            else:
                points = [center, project_point(camera, origin + direction * length, rect)]
            self.handles.append((axis, points))
        return origin, np.array(center), length

    def draw(self, draw_list, rect):
        import imgui
        geometry = self.geometry(rect)
        if geometry is None:
            return
        origin, center, length = geometry
        colors = [imgui.get_color_u32_rgba(1, .3, .3, 1),
                  imgui.get_color_u32_rgba(.35, .9, .4, 1),
                  imgui.get_color_u32_rgba(.35, .65, 1, 1)]
        draw_list.push_clip_rect(rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3], True)
        for axis, points in self.handles:
            color = colors[axis]
            for a, b in zip(points, points[1:]):
                if a is not None and b is not None:
                    draw_list.add_line(*a, *b, color, 2.5)
            if self.app.tool != "rotate" and points[-1] is not None:
                x, y = points[-1]
                draw_list.add_circle_filled(x, y, 5, color)
                draw_list.add_text(x + 6, y - 8, color, "XYZ"[axis])
        color = imgui.get_color_u32_rgba(1, .8, .3, 1)
        if self.app.tool == "move":
            # The square at the pivot is a camera-plane free-move handle.
            draw_list.add_rect(center[0] - 6, center[1] - 6, center[0] + 6, center[1] + 6, color)
        elif self.app.tool == "scale":
            draw_list.add_circle_filled(*center, 6, color)
        draw_list.pop_clip_rect()

    def begin(self, position, rect):
        geometry = self.geometry(rect)
        if geometry is None:
            return False
        origin, center, length = geometry
        choice, best = None, 9.0
        if self.app.tool != "rotate" and np.linalg.norm(np.asarray(position) - center) < 9:
            choice = "free"
        else:
            for axis, points in self.handles:
                for a, b in zip(points, points[1:]):
                    if a is not None and b is not None:
                        d = segment_distance(position, a, b)
                        if d < best:
                            choice, best = axis, d
        if choice is None:
            return False
        ent = self.app.selection
        normal = self.app.viewer.camera.forward if choice == "free" else np.eye(3)[choice]
        self.drag = dict(entity=ent, tool=self.app.tool, axis=choice, start=np.array(position),
                         origin=origin, center=center, length=length, rect=rect,
                         pos=ent.pos.copy(), rot=ent.rot.copy(), scale=ent.scale.copy(),
                         plane_start=plane_point(screen_ray(self.app.viewer.camera, position, rect), origin, normal))
        return True

    def update(self, position):
        if self.drag is None:
            return
        d = self.drag
        ent, axis, tool = d['entity'], d['axis'], d['tool']
        delta = np.asarray(position) - d['start']
        camera, rect = self.app.viewer.camera, d['rect']
        if tool == "move" and axis == "free":
            point = plane_point(screen_ray(camera, position, rect), d['origin'], camera.forward)
            if point is not None and d['plane_start'] is not None:
                ent.pos = d['pos'] + point - d['plane_start']
        elif tool == "rotate":
            normal = np.eye(3)[axis]
            point = plane_point(screen_ray(camera, position, rect), d['origin'], normal)
            if point is None or d['plane_start'] is None:
                angle = (delta[0] - delta[1]) * .01
            else:
                a, b = d['plane_start'] - d['origin'], point - d['origin']
                angle = math.atan2(np.dot(normal, np.cross(a, b)), np.dot(a, b))
            angles = np.eye(3)[axis] * angle
            ent.rot = euler_xyz(rotation_xyz(angles) @ rotation_xyz(d['rot']))
        elif axis == "free":
            ent.scale = np.maximum(.001, d['scale'] * math.exp(float(np.clip((delta[0] - delta[1]) * .01, -8, 8))))
        else:
            end = project_point(camera, d['origin'] + np.eye(3)[axis] * d['length'], rect)
            if end is None:
                return
            direction = np.asarray(end) - d['center']
            amount = np.dot(delta, direction) / max(np.dot(direction, direction), 25)
            if tool == "move":
                ent.pos = d['pos'] + np.eye(3)[axis] * amount * d['length']
            else:
                ent.scale = d['scale'].copy()
                ent.scale[axis] = max(.001, d['scale'][axis] * math.exp(float(np.clip(amount, -8, 8))))

    def finish(self, cancel=False):
        if cancel and self.drag is not None:
            d = self.drag
            d['entity'].pos, d['entity'].rot, d['entity'].scale = d['pos'], d['rot'], d['scale']
        self.drag = None
