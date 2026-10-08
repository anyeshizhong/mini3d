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

    def _entities(self):
        entities = getattr(self.app, 'editable_selection', None)
        if entities is None:
            entity = self.app.selection
            entities = [] if entity is None else [entity]
        # Visibility is not a transform lock for an explicitly selected group.
        multi = len(getattr(self.app, 'selected_entities', entities)) > 1
        return [entity for entity in entities if not entity.locked and (multi or entity.visible)]

    def _space(self, entities):
        selected = getattr(self.app, 'selected_entities', entities)
        return 'world' if len(selected) > 1 else self.app.transform_space

    def geometry(self, rect):
        entities = self._entities()
        self.handles = []
        if not entities or self.app.tool not in ('move', 'rotate', 'scale'):
            return None
        camera = self.app.viewer.camera
        origin = np.mean([entity.pos for entity in entities], axis=0)
        center = project_point(camera, origin, rect)
        if center is None:
            return None
        distance = max(np.dot(origin - camera.position, camera.forward), camera.near)
        length = 95 * 2 * distance * math.tan(math.radians(camera.fov_y) / 2) / rect[3]
        basis = rotation_xyz(entities[0].rot) if self._space(entities) == "local" else np.eye(3)
        for axis in range(3):
            direction = basis[:, axis]
            if self.app.tool == "rotate":
                u, v = basis[:, (axis + 1) % 3], basis[:, (axis + 2) % 3]
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
        if self.drag is not None or self.app.commands.active_transaction:
            return False
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
        entities = self._entities()
        ent = entities[0]
        space = self._space(entities)
        basis = rotation_xyz(ent.rot) if space == "local" else np.eye(3)
        normal = self.app.viewer.camera.forward if choice == "free" else basis[:, choice]
        self.app.commands.begin_transaction("Gizmo " + self.app.tool)
        self.drag = dict(entity=ent, tool=self.app.tool, axis=choice, start=np.array(position),
                         origin=origin, center=center, length=length, rect=rect,
                         basis=basis, space=space, entities=entities,
                         initial={e.entity_id: dict(position=e.pos.copy(), rotation=e.rot.copy(),
                                                    scale=e.scale.copy()) for e in entities},
                         transaction=self.app.commands._transaction,
                         pos=ent.pos.copy(), rot=ent.rot.copy(), scale=ent.scale.copy(),
                         plane_start=plane_point(screen_ray(self.app.viewer.camera, position, rect), origin, normal))
        return True

    def update(self, position):
        if self.drag is None:
            return
        d = self.drag
        ent, axis, tool = d['entity'], d['axis'], d['tool']
        if self.app.commands._transaction is not d['transaction']:
            self.drag = None
            return
        if not any(not e.locked and e in self.app.commands.scene.root_entities for e in d['entities']):
            self.finish()
            return
        delta = np.asarray(position) - d['start']
        camera, rect = self.app.viewer.camera, d['rect']
        multi = len(d['entities']) > 1

        def apply_many(**delta):
            self.app.commands.transform_many([e.entity_id for e in d['entities']
                                              if e in self.app.commands.scene.root_entities],
                                             pivot=d['origin'], initial=d['initial'], **delta)

        if tool == "move" and axis == "free":
            point = plane_point(screen_ray(camera, position, rect), d['origin'], camera.forward)
            if point is not None and d['plane_start'] is not None:
                offset = point - d['plane_start']
                if multi:
                    apply_many(translation=offset)
                else:
                    self.app.commands.set_transform(ent, position=d['pos'] + offset)
        elif tool == "rotate":
            normal = d['basis'][:, axis]
            point = plane_point(screen_ray(camera, position, rect), d['origin'], normal)
            if point is None or d['plane_start'] is None:
                angle = (delta[0] - delta[1]) * .01
            else:
                a, b = d['plane_start'] - d['origin'], point - d['origin']
                angle = math.atan2(np.dot(normal, np.cross(a, b)), np.dot(a, b))
            angles = np.eye(3)[axis] * angle
            if multi:
                apply_many(rotation=angles)
                return
            start_rotation = rotation_xyz(d['rot'])
            rotation = (start_rotation @ rotation_xyz(angles) if d['space'] == "local"
                        else rotation_xyz(angles) @ start_rotation)
            self.app.commands.set_transform(ent, rotation=euler_xyz(rotation))
        elif axis == "free":
            factor = math.exp(float(np.clip((delta[0] - delta[1]) * .01, -8, 8)))
            if multi:
                apply_many(scale=np.full(3, factor))
            else:
                self.app.commands.set_transform(ent, scale=np.maximum(.001, d['scale'] * factor))
        else:
            direction_world = d['basis'][:, axis]
            end = project_point(camera, d['origin'] + direction_world * d['length'], rect)
            if end is None:
                return
            direction = np.asarray(end) - d['center']
            amount = np.dot(delta, direction) / max(np.dot(direction, direction), 25)
            if tool == "move":
                offset = direction_world * amount * d['length']
                if multi:
                    apply_many(translation=offset)
                else:
                    self.app.commands.set_transform(ent, position=d['pos'] + offset)
            else:
                if multi:
                    apply_many(scale=np.exp(np.clip(amount * np.eye(3)[axis], -8, 8)))
                    return
                # TRS cannot represent world-axis shear. Distribute the drag
                # across local scale components using squared axis projections.
                weights = (np.eye(3)[axis] if d['space'] == "local" else
                           (rotation_xyz(d['rot']).T @ direction_world) ** 2)
                scale = np.maximum(.001, d['scale'] * np.exp(np.clip(amount * weights, -8, 8)))
                self.app.commands.set_transform(ent, scale=scale)

    def finish(self, cancel=False):
        if self.drag is not None and self.app.commands._transaction is self.drag['transaction']:
            unchanged_members = all(not e.locked and e in self.app.commands.scene.root_entities
                                    for e in self.drag['entities'])
            if cancel and unchanged_members:
                self.app.commands.cancel_transaction()
            else:
                self.app.commands.commit_transaction()
        self.drag = None
