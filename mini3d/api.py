"""Thin in-process scene API. No Editor UI, network service or GL context creation.

State/persistence reuse Editor application state without starting its window loop.
All placement changes delegate to PlacementCommands. Capture requires a caller-
owned GLRenderer and a current desktop OpenGL context on the calling thread.
"""
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .editor import Editor
from .camera import Camera
from .orbit_controller import OrbitController
from .placement import SurfaceHit, geometry_bounds
from .shot_camera import ShotCamera, capture_png
from .viewer import world_bounds
from .lighting import lighting_state


class Mini3DAPI:
    def __init__(self, renderer=None):
        self._app = Editor()
        self._commands = self._app.commands
        self._renderer = renderer

    def _entity(self, entity_id):
        if not isinstance(entity_id, str):
            raise ValueError('entity_id must be a stable ID string')
        entity = self._app.scene.find_by_id(entity_id)
        if entity is None:
            raise ValueError('Unknown entity ID: ' + entity_id)
        return entity

    def _group(self, group_id):
        if not isinstance(group_id, str):
            raise ValueError('group_id must be a stable ID string')
        group = self._app.scene.find_group_by_id(group_id)
        if group is None:
            raise ValueError('Unknown group ID: ' + group_id)
        return group

    def _outside_transaction(self):
        if self._commands.active_transaction:
            raise ValueError('File/camera operations and Formation require a completed placement transaction')

    def get_entity(self, entity_id, include_bounds=False):
        entity = self._entity(entity_id)
        data = dict(entity_id=entity.entity_id, name=entity.name, asset_path=entity.asset_path,
            position=entity.pos.tolist(), rotation=entity.rot.tolist(), scale=entity.scale.tolist(),
            visible=bool(entity.visible), locked=bool(entity.locked), placement_type=entity.placement_type,
            placement_anchor=entity.placement_anchor, keep_upright=bool(entity.keep_upright))
        if include_bounds:
            bounds = geometry_bounds(entity)
            data['bounds'] = None if bounds is None else dict(minimum=bounds[0].tolist(), maximum=bounds[1].tolist())
        return data

    def list_entities(self, include_bounds=False):
        return [self.get_entity(e.entity_id, include_bounds) for e in self._app.scene.root_entities]

    def get_group(self, group_id):
        group = self._group(group_id)
        return dict(group_id=group.group_id, name=group.name, member_ids=list(group.member_ids))

    def list_groups(self):
        return [self.get_group(g.group_id) for g in self._app.scene.groups]

    def get_shadows(self):
        from .lighting import shadow_state
        return shadow_state(self._app.scene)

    def set_shadows(self, enabled=None, resolution=None, bias=None, pcf=None):
        return self._app.set_shadows(enabled, resolution, bias, pcf)

    def get_lighting(self):
        """Return mode, world surface-to-light direction, diffuse and ambient."""
        return lighting_state(self._app.scene)

    def set_lighting(self, mode=None, direction=None, diffuse=None, ambient=None):
        """Atomic partial update outside placement transactions; None preserves.

        Mode is Studio or Scene; direction is any finite nonzero numeric 3-vector.
        Strengths are finite and nonnegative. Returns the resulting snapshot.
        Shot Camera always uses Scene lighting, regardless of preview mode.
        """
        return self._app.set_lighting(mode, direction, diffuse, ambient)

    def get_scene_state(self, include_bounds=False):
        return dict(entities=self.list_entities(include_bounds), groups=self.list_groups(),
            selected_ids=list(self._app.scene.selected_ids),
            primary_selection_id=self._app.scene.primary_selection_id,
            selected_group_id=self._app.scene.selected_group_id,
            ground=dict(visible=False, z=self._app.scene.placement_plane.z,
                        size=self._app.scene.placement_plane.size),
            placement_plane=self._app.scene.placement_plane.to_dict(),
            shot_camera=self.get_shot_camera(),
            lighting=self.get_lighting(), shadows=self.get_shadows(),
            history=dict(undo_count=self._commands.undo_count, redo_count=self._commands.redo_count,
                         active_transaction=self._commands.active_transaction))

    def spawn(self, asset_path, name=None, position=None, rotation=None, scale=None,
              placement_type=None, anchor='bounds_bottom', keep_upright=None):
        entity = self._commands.spawn(asset_path, name=name, position=position, rotation=rotation,
            scale=scale, placement_type=placement_type, anchor=anchor, keep_upright=keep_upright)
        return self.get_entity(entity.entity_id)

    def delete(self, entity_id):
        self._commands.delete(self._entity(entity_id))
        return dict(entity_id=entity_id, deleted=True)

    def duplicate(self, entity_id, name=None):
        entity = self._commands.duplicate(self._entity(entity_id), name=name)
        return self.get_entity(entity.entity_id)

    def set_transform(self, entity_id, position=None, rotation=None, scale=None):
        self._commands.set_transform(self._entity(entity_id), position=position, rotation=rotation, scale=scale)
        return self.get_entity(entity_id)

    def transform_many(self, entity_ids, translation=None, rotation=None, scale=None, pivot=None):
        entities = self._commands.transform_many(entity_ids, translation=translation,
            rotation=rotation, scale=scale, pivot=pivot)
        return [self.get_entity(entity.entity_id) for entity in entities]

    def place_at(self, entity_id, position, normal=(0, 0, 1), anchor=None, keep_upright=None):
        self._commands.place_on_surface(self._entity(entity_id), SurfaceHit(position, normal),
                                        anchor=anchor, keep_upright=keep_upright)
        return self.get_entity(entity_id)

    def place_on_ground(self, entity_id, x=None, y=None, anchor=None):
        entity = self._entity(entity_id)
        resolved_anchor = entity.placement_anchor if anchor is None else anchor
        bounds = geometry_bounds(entity) if resolved_anchor == 'bounds_bottom' else None
        center = entity.pos if bounds is None else (bounds[0] + bounds[1]) / 2
        x, y = float(center[0] if x is None else x), float(center[1] if y is None else y)
        point = self._app.scene.placement_plane.point(x, y)
        self._commands.place_on_surface(entity, SurfaceHit(point, [0, 0, 1]), anchor=anchor)
        return self.get_entity(entity_id)

    def lock(self, entity_id):
        self._commands.lock(self._entity(entity_id))
        return self.get_entity(entity_id)

    def unlock(self, entity_id):
        self._commands.unlock(self._entity(entity_id))
        return self.get_entity(entity_id)

    def create_group(self, member_ids, name=None):
        group = self._commands.create_group(member_ids, name=name)
        return self.get_group(group.group_id)

    def create_rectangular_formation(self, source_id, rows, columns, spacing_x, spacing_y,
                                     facing=None, include_source=True):
        self._outside_transaction()
        group = self._commands.create_rectangular_formation(source_id, rows, columns,
            spacing_x, spacing_y, facing=facing, include_source=include_source)
        return self.get_group(group.group_id)

    def undo(self):
        return dict(changed=self._commands.undo())

    def redo(self):
        return dict(changed=self._commands.redo())

    @contextmanager
    def transaction(self, label='API placement'):
        with self._commands.transaction(label):
            yield self

    def save_scene(self, path):
        self._outside_transaction()
        destination = Path(path).expanduser().resolve()
        self._app.save_scene(destination)
        return dict(path=str(destination), version=3)

    def load_scene(self, path):
        self._outside_transaction()
        self._app.load_scene(Path(path).expanduser().resolve())
        return self.get_scene_state()

    def create_shot_camera(self, position=None, target=None, focal_mm=50, aspect='16:9',
                           near=.01, far=1000):
        self._outside_transaction()
        if (position is None) != (target is None):
            raise ValueError('Supply both camera position and target, or neither to frame the scene')
        view = Camera(near=near, far=far)
        if position is not None:
            view.position = position
            view.look_at(target)
        shot = ShotCamera(view)
        shot.set_aspect(aspect)
        shot.set_lens(focal_mm)
        if position is None:
            self._app.scene.update()
            bounds = world_bounds([e for e in self._app.scene.root_entities if e.visible])
            if bounds is None:
                raise ValueError('Cannot automatically frame an empty scene')
            controller = OrbitController(shot, yaw=-.9, pitch=.45)
            controller.focus_bounds(*bounds, aspect=shot.aspect)
        self._app.shot_camera = shot
        return self.get_shot_camera()

    def get_shot_camera(self):
        camera = self._app.shot_camera
        if camera is None:
            return None
        return dict(camera.to_dict(), camera_id='shot', width=camera.size[0], height=camera.size[1])

    def set_lens(self, focal_mm):
        self._outside_transaction()
        self._app.set_shot_lens(focal_mm)
        return self.get_shot_camera()

    def set_aspect(self, aspect):
        self._outside_transaction()
        self._app.set_shot_aspect(aspect)
        return self.get_shot_camera()

    def capture(self, path):
        self._outside_transaction()
        if self._app.shot_camera is None:
            raise ValueError('Create a Shot Camera before capture')
        if self._renderer is None:
            raise RuntimeError('Capture requires a caller-owned GLRenderer and current OpenGL context')
        from OpenGL import GL as gl
        if gl.glGetString(gl.GL_VERSION) is None:
            raise RuntimeError('Capture requires a current OpenGL context on this thread')
        path = Path(path).expanduser().resolve()
        if path.suffix.lower() != '.png':
            raise ValueError('Capture output must have a .png extension')
        result = capture_png(self._app.scene, self._app.shot_camera, self._renderer, path)
        return dict(path=str(result), format='PNG', camera=self.get_shot_camera())
