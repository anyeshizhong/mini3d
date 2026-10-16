"""Thin in-process scene API. No Editor UI, network service or GL context creation.

State/persistence reuse Editor application state without starting its window loop.
All placement changes delegate to PlacementCommands. Capture requires a caller-
owned GLRenderer and a current desktop OpenGL context on the calling thread.
"""
from contextlib import contextmanager
from copy import deepcopy
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
    def __init__(self, renderer=None, editor=None, screenshot=None):
        """Use an existing Editor, or create the original windowless state.

        The renderer is borrowed. Binding the running editor shares its Scene,
        command history and Shot Camera without another application instance.
        """
        self._app = Editor() if editor is None else editor
        self._commands = self._app.commands
        self._renderer = renderer
        self._screenshot = screenshot

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

    def get_environment(self):
        """Fixed neutral studio IBL settings shared by Scene and Shot Camera."""
        from .environment import environment_state
        return environment_state(self._app.scene)

    def set_environment(self, enabled=None, intensity=None):
        """Atomic update outside placement transactions. Linear intensity, exposure=1."""
        from .environment import update_environment
        if self._commands.active_transaction:
            raise ValueError('Cannot change environment inside a placement transaction')
        self._app.finish_edit()
        return update_environment(self._app.scene, enabled, intensity)

    def set_lighting(self, mode=None, direction=None, diffuse=None, ambient=None):
        """Atomic partial update outside placement transactions; None preserves.

        Mode is Studio or Scene; direction is any finite nonzero numeric 3-vector.
        Strengths are finite and nonnegative. Returns the resulting snapshot.
        Shot Camera always uses Scene lighting, regardless of preview mode.
        """
        return self._app.set_lighting(mode, direction, diffuse, ambient)

    def get_atmosphere(self):
        from .atmosphere import atmosphere_state
        return atmosphere_state(self._app.scene)

    def set_atmosphere(self, enabled=None, ground=None, sun_temperature=None,
                       exposure_ev=None, haze=None, ground_scale=None, ground_z=None,
                       azimuth=None, elevation=None, sky_texture=None, sky_intensity=None,
                       ground_texture=None, sun_size=None, tone_mapping=None, celestial_body=None):
        return self._app.set_atmosphere(enabled=enabled, ground=ground,
            sun_temperature=sun_temperature, exposure_ev=exposure_ev, haze=haze,
            ground_scale=ground_scale, ground_z=ground_z, azimuth=azimuth, elevation=elevation,
            sky_texture=sky_texture,sky_intensity=sky_intensity,ground_texture=ground_texture,
            sun_size=sun_size,tone_mapping=tone_mapping,celestial_body=celestial_body)

    def sky_preset(self, name):
        return self._app.sky_preset(name)

    def sunset_preset(self):
        return self._app.sunset_preset()

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
            environment=self.get_environment(), atmosphere=self.get_atmosphere(),
            history=dict(undo_count=self._commands.undo_count, redo_count=self._commands.redo_count,
                         active_transaction=self._commands.active_transaction))

    def get_editor_camera(self):
        """Live navigation camera, separate from the persisted Shot Camera."""
        camera = self._app.viewer.camera
        navigation = self._app.viewer.controller.snapshot()
        navigation = {key: value.tolist() if isinstance(value, np.ndarray) else value
                      for key, value in navigation.items()}
        return dict(position=camera.position.tolist(), rotation=camera.rotation.tolist(),
                    fov_y=camera.fov_y, near=camera.near, far=camera.far,
                    viewport=list(self._app.viewport_rect), camera_view=bool(self._app.camera_view),
                    navigation=navigation)

    def _view_state(self):
        editor = self.get_editor_camera()
        shot = self.get_shot_camera()
        active = shot if self._app.camera_view else editor
        return dict(workspace=self._app.workspace,
                    view='Camera' if self._app.camera_view else 'Editor',
                    active_camera=deepcopy(active), editor_camera=editor, shot_camera=shot,
                    viewport=list(self._app.viewport_rect), render_mode=self._app.render_mode,
                    selected_ids=list(self._app.scene.selected_ids))

    def get_view_state(self):
        """Current shared view plus the camera/layout of the completed UI frame.

        Live IPC schedules this read after rendering. Independently constructed
        APIs have no displayed frame, rather than claiming to show a window.
        """
        state = self._view_state()
        displayed = deepcopy(self._app.displayed_frame)
        return dict(state, displayed_frame=displayed,
                    view_matches_displayed_frame=(displayed is not None and
                        displayed['view_state'] == state))

    def set_workspace(self, workspace):
        self._outside_transaction()
        self._app.set_workspace(workspace)
        return self.get_view_state()

    def set_view(self, view):
        self._outside_transaction()
        if view not in ('Editor', 'Camera'):
            raise ValueError('Choose Editor or Camera view')
        if view == 'Camera' and self._app.shot_camera is None:
            raise ValueError('Create a Shot Camera before showing Camera view')
        if view == 'Camera':
            self._app.set_workspace('Shot')
        self._app.set_camera_view(view == 'Camera')
        return self.get_view_state()

    def select_entities(self, entity_ids, primary_id=None):
        self._outside_transaction()
        self._commands.set_selection(entity_ids, primary_id=primary_id)
        self._app.sync_selection()
        return self.get_view_state()

    def frame_all(self):
        """Frame the visible scene in the editor camera and display that camera."""
        self._outside_transaction()
        self._app.scene.update()
        if world_bounds(self._app.scene.root_entities, visible_only=True) is None:
            raise ValueError('Cannot frame an empty scene')
        self._app.set_camera_view(False)
        self._app.frame_all()
        return self.get_view_state()

    def focus_entity(self, entity_id):
        self._outside_transaction()
        entity = self._entity(entity_id)
        self._app.scene.update()
        if world_bounds([entity], visible_only=True) is None:
            raise ValueError('Focus entity has no visible geometry')
        self._app.select(entity)
        self._app.set_camera_view(False)
        self._app.focus_selected()
        return self.get_view_state()

    def set_editor_view(self, preset):
        self._outside_transaction()
        if preset not in ('front', 'back', 'left', 'right', 'top', 'bottom'):
            raise ValueError('Unknown editor view preset')
        self._app.set_camera_view(False)
        self._app.set_view(preset)
        return self.get_view_state()

    def set_editor_camera(self, position, target, fov_y=None):
        """Set the live orbit camera, retaining working mouse navigation.

        Validate on an unbound controller first. Clipping remains managed by
        the existing Viewer so the new pose includes current scene geometry.
        """
        self._outside_transaction()
        controller = self._app.viewer.controller
        snapshot = controller.snapshot()
        active = self._app.shot_camera if self._app.camera_view else self._app.viewer.camera
        candidate = Camera(fov_y=active.fov_y if fov_y is None else fov_y)
        candidate.position = position
        candidate.look_at(target)
        target = np.asarray(target, dtype=float)
        offset = candidate.position - target
        distance = float(np.linalg.norm(offset))
        snapshot.update(target=target, distance=distance,
                        yaw=float(np.arctan2(offset[1], offset[0])),
                        pitch=float(np.arctan2(offset[2], np.linalg.norm(offset[:2]))),
                        fov_y=candidate.fov_y,
                        min_distance=min(snapshot['min_distance'], distance),
                        max_distance=max(snapshot['max_distance'], distance))
        if self._app.camera_view:
            snapshot['min_far'] = max(snapshot['min_far'], self._app.shot_camera.far)
        probe = OrbitController(Camera())
        probe.restore(snapshot)
        self._app.set_camera_view(False)
        controller.restore(snapshot)
        return self.get_view_state()

    def set_view_lens(self, focal_mm):
        self._outside_transaction()
        self._app.set_view_lens(focal_mm)
        return self.get_view_state()

    def set_view_aspect(self, aspect):
        self._outside_transaction()
        self._app.set_view_aspect(aspect)
        return self.get_view_state()

    def create_camera_from_view(self):
        """Use exactly the navigation pose visible in Editor view, like the UI button."""
        self._outside_transaction()
        if self._app.camera_view:
            raise ValueError('Switch to Editor view before copying its camera')
        self._app.create_camera_from_view()
        return self.get_shot_camera()

    def screenshot(self, path):
        """Read the current editor frame via its runtime; no extra GL context."""
        if self._screenshot is None:
            raise RuntimeError('Screenshot requires the running Editor runtime')
        destination = Path(path).expanduser().resolve()
        if destination.suffix.lower() != '.png':
            raise ValueError('Screenshot output must have a .png extension')
        return self._screenshot(destination)

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

    def align_adjacent(self, entity_ids, reference_id, axis='x', side=1, gap=0.0):
        entities = self._commands.align_adjacent(entity_ids, reference_id, axis, side, gap)
        self._app.sync_selection()
        return [self.get_entity(entity.entity_id) for entity in entities]

    def create_roman_street(self, segments=6, road_width=6.0, origin=None, facing=0.0,
                            variation=False, seed=0, extension_segments=0):
        """Append a grouped, editable street without changing the current view."""
        self._outside_transaction()
        result = self._commands.create_roman_street(segments, road_width, origin, facing, variation, seed, extension_segments)
        self._app.sync_selection()
        return result

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
                           near=.01, far=1000, dof_enabled=False,
                           focus_distance=None, f_number=2.8):
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
        if focus_distance is None:
            if target is not None:
                depth = -float((shot.view_matrix @ np.r_[target, 1])[2])
                shot.set_depth_of_field(focus_distance=max(.1, depth))
            elif position is None:
                depth = -float((shot.view_matrix @ np.r_[controller.target, 1])[2])
                shot.set_depth_of_field(focus_distance=max(.1, depth))
        shot.set_depth_of_field(enabled=dof_enabled, focus_distance=focus_distance, f_number=f_number)
        self._app.shot_camera = shot
        self._app._editing_shot = False
        return self.get_shot_camera()

    def set_shot_camera_pose(self, position, target=None, rotation=None):
        """Move the existing Shot Camera without resetting its photographic setup.

        Specify exactly one of target (look-at) or rotation (camera-to-world 3x3).
        The change is atomic, and any stored world focus point is reprojected
        onto the new pose; a point behind the camera clears its focus marker.
        """
        self._outside_transaction()
        original = self._app.shot_camera
        if original is None:
            raise ValueError('Create a Shot Camera before moving it')
        if (target is None) == (rotation is None):
            raise ValueError('Supply exactly one of target or rotation')
        candidate = Camera(position, original.rotation, original.fov_y,
                           original.near, original.far)
        if target is not None:
            candidate.look_at(target)
        else:
            candidate.rotation = rotation
        updated = deepcopy(original)
        updated.position, updated.rotation = candidate.position, candidate.rotation
        if updated.focus_point is not None:
            point = updated.focus_point.copy()
            try:
                updated.focus_at(point)
            except ValueError:
                updated.focus_point = None
        self._app.shot_camera = updated
        self._app._editing_shot = False
        return self.get_shot_camera()

    def set_depth_of_field(self, enabled=None, focus_distance=None, f_number=None):
        self._outside_transaction()
        self._app.set_shot_depth_of_field(enabled, focus_distance, f_number)
        return self.get_shot_camera()

    def focus_at(self, point):
        self._outside_transaction()
        if self._app.shot_camera is None:
            raise ValueError('Create a Shot Camera before focusing')
        self._app.shot_camera.focus_at(point)
        return self.get_shot_camera()

    def focus_on(self, entity_id):
        self._outside_transaction()
        entity = self._entity(entity_id)
        self._app.scene.update()
        bounds = world_bounds([entity])
        if bounds is None:
            raise ValueError('Focus entity has no visible geometry')
        return self.focus_at((bounds[0] + bounds[1]) * .5)

    def focus_screen(self, screen_pos):
        self._outside_transaction()
        focused = self._app.focus_photo_screen(screen_pos)
        return dict(focused=focused, shot_camera=self.get_shot_camera())

    def set_photo_color(self, white_balance_kelvin=None, preset=None):
        self._outside_transaction()
        self._app.set_shot_photo_color(white_balance_kelvin, preset)
        return self.get_shot_camera()

    def reset_photo_color(self):
        return self.set_photo_color(6500., 'Original')

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

    def set_antialiasing(self, samples=1):
        """Choose 1x or 4x MSAA for Shot preview and PNG; saved with the camera."""
        self._outside_transaction()
        if self._app.shot_camera is None:
            raise ValueError('Create a Shot Camera before setting antialiasing')
        self._app.shot_camera.set_samples(samples)
        return self.get_shot_camera()
