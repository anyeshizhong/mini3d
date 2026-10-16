"""Editor application state and window loop, separate from ImGui presentation."""
import json
import math
import copy
from datetime import datetime
from pathlib import Path

import numpy as np
import pygame

from .scene import Scene, SceneGroup, rotation_xyz, euler_xyz
from .viewer import Viewer, world_bounds
from .gltf_loader import AssetCache
from .picking import pick_entity
from .commands import PlacementCommands
from .placement import raycast_surface, SurfaceHit
from .placement_plane import PlacementPlane
from .editor_tools import TransformGizmo
from .model_dialog import ModelFileDialog
from .shot_camera import ShotCamera, render_shot, capture_png


PROJECT = Path(__file__).resolve().parents[1]


class Editor:
    def __init__(self, width=1280, height=800):
        self.scene = Scene()
        self.cache = AssetCache()
        self.commands = PlacementCommands(self.scene, self.cache)
        manifest = json.loads((PROJECT / "model/manifest.json").read_text(encoding="utf-8"))
        self.assets = [dict(info, path=str(PROJECT / "model" / key / info["entry"]))
                       for key, info in sorted(manifest.items())
                       if info.get("status") == "downloaded" and
                       (PROJECT / "model" / key / info["entry"]).is_file()]
        self.assets.insert(0, dict(path='builtin:roman-soldier', name='Roman Soldier (built-in study)',
                                   format='procedural', entry='builtin:roman-soldier', status='builtin'))
        from .roman_assets import ROMAN_ASSETS
        self.assets.extend(dict(record) for record in ROMAN_ASSETS)
        self.viewer = Viewer(self.scene, width, height, input_enabled=False)
        self.viewer.controller.yaw = -.9
        self.viewer.controller.pitch = .25
        self.viewer.controller.update()
        self.surface_drag = None
        self.tool = "move"
        self.transform_space = "world"
        self.placement_anchor = "bounds_bottom"
        self.place_selected_mode = False
        self.render_mode = "Lit"
        self.show_grid = True
        self.status = "Double-click or drag an asset to add it. Middle drag orbits."
        self.scene_path = PROJECT / "scenes/editor_scene.json"
        self.viewport_rect = (0, 0, width, height)
        self.gizmo = TransformGizmo(self)
        self._orbiting = False
        self._instance_number = 0
        self.model_dialog = ModelFileDialog(PROJECT / "model")
        self.shot_camera = None
        self.camera_view = False
        self.workspace = 'Arrange'
        self.assets_visible = True
        self.displayed_frame = None
        self._editing_shot = False
        self.composition_grid = True
        self.capture_requested = False
        self.capture_directory = PROJECT / "captures"
        self.last_capture = None
        self.photo_focus_reader = None

    def create_camera_from_view(self):
        if self.camera_view:
            raise ValueError('Use Editor View to update framing')
        self.viewer.update_clipping()
        view = self.viewer.camera
        old = self.shot_camera
        shot = ShotCamera(view) if old is None else copy.deepcopy(old)
        shot.position, shot.rotation = view.position, view.rotation
        shot.fov_y, shot.near, shot.far = view.fov_y, view.near, view.far
        if old is None:
            depth = -float((shot.view_matrix @ np.r_[self.viewer.controller.target, 1])[2])
            shot.set_depth_of_field(focus_distance=max(.1, depth))
        elif shot.focus_point is not None:
            point = shot.focus_point.copy()
            try:
                shot.focus_at(point)
            except ValueError:
                shot.focus_point = None
        self.shot_camera = shot
        self._editing_shot = False
        self.status = 'Photo framing updated from Editor View'

    def _edit_photo_framing(self):
        shot = self.shot_camera
        controller = self.viewer.controller
        distance = max(shot.focus_distance, shot.near * 2, .1)
        target = shot.position + shot.forward * distance
        backward = -shot.forward
        state = controller.snapshot()
        state.update(target=target, distance=distance,
                     yaw=float(np.arctan2(backward[1], backward[0])),
                     pitch=float(np.arctan2(backward[2], np.linalg.norm(backward[:2]))),
                     fov_y=shot.fov_y, min_far=shot.far,
                     min_distance=min(state['min_distance'], distance),
                     max_distance=max(state['max_distance'], distance))
        controller.restore(state)
        # Preserve the exact initial pose, including imported roll.
        self.viewer.camera.position = shot.position
        self.viewer.camera.rotation = shot.rotation
        self.viewer.camera.near, self.viewer.camera.far = shot.near, shot.far
        self._editing_shot = True

    def set_shot_depth_of_field(self, enabled=None, focus_distance=None, f_number=None):
        if self.shot_camera is None:
            raise ValueError('Create Camera From View first')
        self.shot_camera.set_depth_of_field(enabled, focus_distance, f_number)

    def set_shot_photo_color(self, white_balance_kelvin=None, preset=None):
        if self.shot_camera is None:
            raise ValueError('Create a Shot Camera first')
        self.shot_camera.set_photo_color(white_balance_kelvin, preset)

    def focus_photo_screen(self, screen_pos):
        if self.commands.active_transaction:
            raise ValueError('Complete the placement transaction before focusing')
        if not self.camera_view or self.shot_camera is None:
            raise ValueError('Use Camera View to click a focus point')
        if self.photo_focus_reader is None:
            raise ValueError('A displayed photo frame is required for click focus')
        point = self.photo_focus_reader(screen_pos, self.viewport_rect)
        if point is None:
            self.status = 'No photo surface here; focus unchanged'
            return False
        self.shot_camera.focus_at(point)
        self.status = 'Focused at {:.3f} m'.format(self.shot_camera.focus_distance)
        return True

    def focus_shot_selection(self):
        if self.shot_camera is None or self.selection is None:
            raise ValueError('Create a Shot Camera and select a subject first')
        self.scene.update()
        bounds = world_bounds([self.selection])
        if bounds is None:
            raise ValueError('Selected subject has no visible geometry')
        self.shot_camera.focus_at((bounds[0] + bounds[1]) * .5)
        self.status = 'Focused on {} at {:.3f} m'.format(self.selection.name, self.shot_camera.focus_distance)

    def set_camera_view(self, enabled):
        if enabled and self.shot_camera is None:
            raise ValueError("Create Camera From View first")
        self._orbiting = False
        self.finish_edit()
        if not enabled and self.camera_view and self.shot_camera is not None:
            self._edit_photo_framing()
        elif enabled and not self.camera_view and self._editing_shot:
            self.create_camera_from_view()
        self.camera_view = enabled

    def set_view_lens(self, focal_mm):
        if self.shot_camera is None or self.camera_view:
            return self.set_shot_lens(focal_mm)
        probe = ShotCamera(self.viewer.camera)
        probe.aspect_name = self.shot_camera.aspect_name
        probe.set_lens(focal_mm)
        self.viewer.camera.fov_y = probe.fov_y
        self.viewer.controller.update()
        self._editing_shot = True

    def set_view_aspect(self, name):
        if self.shot_camera is None or self.camera_view:
            return self.set_shot_aspect(name)
        focal = 36 / (2 * self.shot_camera.aspect * math.tan(math.radians(self.viewer.camera.fov_y) / 2))
        self.shot_camera.set_aspect(name)
        self.viewer.camera.fov_y = math.degrees(2 * math.atan(36 / (2 * self.shot_camera.aspect * focal)))
        self.viewer.controller.update()
        self._editing_shot = True

    def set_workspace(self, workspace):
        if workspace not in ('Arrange', 'Lighting', 'Shot'):
            raise ValueError('Choose Arrange, Lighting or Shot')
        if workspace == self.workspace:
            return
        self.finish_edit()
        if workspace != 'Shot' and self.camera_view:
            self.set_camera_view(False)
        self.workspace = workspace
        self.assets_visible = workspace == 'Arrange'

    def set_shot_lens(self, focal_mm):
        if self.shot_camera is None:
            raise ValueError("Create Camera From View first")
        self.shot_camera.set_lens(focal_mm)

    def set_shot_aspect(self, name):
        if self.shot_camera is None:
            raise ValueError("Create Camera From View first")
        self.shot_camera.set_aspect(name)

    def request_capture(self):
        if self.shot_camera is None:
            raise ValueError("Create Camera From View first")
        self.capture_requested = True

    def browse_model(self):
        if self.model_dialog.open():
            self._orbiting = False
            self.gizmo.finish(cancel=True)
            self.finish_surface_drag(cancel=True)
            self.status = "Choose a GLB / glTF / STL file. The editor remains available."

    def cancel_model_dialog(self):
        self.model_dialog.close()
        self.status = "Model import cancelled"

    def poll_model_dialog(self):
        result = self.model_dialog.poll()
        if result is None:
            return None
        if result.get("error"):
            self.status = "File picker: {}. Use File > Import from path instead.".format(result["error"])
        elif not result["path"]:
            self.status = "Model import cancelled"
        else:
            try:
                return self.import_asset(result["path"])
            except Exception as exc:
                self.status = "Import failed: {}".format(exc)
        return None

    @property
    def selection(self):
        """Compatibility alias: outline and Inspector use the primary instance."""
        return self.commands.primary_selection

    @property
    def primary_selection(self):
        return self.commands.primary_selection

    @property
    def selected_entities(self):
        return self.commands.selected_entities

    @property
    def editable_selection(self):
        return self.commands.editable_selection

    def sync_selection(self):
        self.scene.clean_selection()
        self.viewer.selected_entity = self.selection

    def finish_surface_drag(self, cancel=False):
        if self.surface_drag is not None:
            self.surface_drag.finish(cancel=cancel)
            self.surface_drag = None

    def finish_edit(self):
        self.finish_surface_drag()
        self.gizmo.finish()
        if self.commands.active_transaction:
            self.commands.commit_transaction()

    def select(self, entity, toggle=False):
        self.finish_edit()
        self.place_selected_mode = False
        ids = list(self.scene.selected_ids) if toggle and entity is not None else []
        if entity is not None:
            if entity.entity_id in ids:
                ids.remove(entity.entity_id)
            else:
                ids.append(entity.entity_id)
        self.commands.set_selection(ids, primary_id=ids[-1] if ids else None)
        self.sync_selection()
        if entity is not None:
            self.status = "Selected: " + entity.name

    def add_asset(self, index, position=None):
        self.finish_edit()
        record = self.assets[index]
        self._instance_number += 1
        with self.commands.transaction("Add asset"):
            root = self.commands.spawn(record["path"],
                name="{}_{:03d}".format(record["name"], self._instance_number),
                position=position, placement_type=record.get("placement_type"),
                anchor=self.placement_anchor, keep_upright=record.get("keep_upright"))
            if position is None:
                self.commands.place_on_surface(root, SurfaceHit(
                    self.scene.placement_plane.point(0, 0), np.array([0., 0., 1.])))
            self.commands.set_selection([root.entity_id])
        self.select(root)
        if position is None:
            self.focus_selected()
            self.viewer.save_camera()
        self.status = "Added {} | original asset scale | {} triangles".format(
            record["name"], record.get("triangles", "?"))
        return root

    def drop_asset(self, index, screen_pos):
        self.finish_edit()
        self.scene.update()
        hit = raycast_surface(self.scene, self.viewer.camera, screen_pos, self.viewport_rect,
                              fallback=self.viewer.controller.target)
        record = self.assets[index]
        self._instance_number += 1
        with self.commands.transaction("Drop asset"):
            root = self.commands.spawn(record["path"],
                name="{}_{:03d}".format(record["name"], self._instance_number),
                placement_type=record.get("placement_type"),
                anchor=self.placement_anchor, keep_upright=record.get("keep_upright"))
            self.commands.place_on_surface(root, hit)
            self.commands.set_selection([root.entity_id])
        self.select(root)
        # Dolly distance stays unchanged during a drop. Focus is explicit with F.
        return root

    def import_asset(self, path):
        path = str(Path(path).expanduser().resolve())
        asset = self.cache.load(path)  # Validate before adding the UI entry.
        existing = next((i for i, item in enumerate(self.assets) if item["path"] == path), None)
        if existing is None:
            self.assets.append(dict(name=asset.name, path=path, license="See the source asset's license"))
            existing = len(self.assets) - 1
        return self.add_asset(existing)

    def duplicate_selected(self):
        self.finish_edit()
        if self.selection is None:
            return None
        with self.commands.transaction("Duplicate selection"):
            copies = [self.commands.duplicate(entity) for entity in self.selected_entities]
            self.commands.set_selection([entity.entity_id for entity in copies])
        self.sync_selection()
        return self.selection

    def delete_selected(self):
        self.finish_edit()
        if self.editable_selection:
            with self.commands.transaction("Delete selection"):
                for entity in list(self.editable_selection):
                    self.commands.delete(entity)
            self.sync_selection()
            self.status = "Object removed from the scene"

    def lock_selected(self):
        self.finish_edit()
        if self.selection is not None:
            with self.commands.transaction("Lock selection"):
                for entity in self.selected_entities:
                    self.commands.lock(entity)
            self.place_selected_mode = False
            self.status = "Locked: " + self.selection.name

    def unlock_selected(self):
        self.finish_edit()
        if self.selection is not None:
            with self.commands.transaction("Unlock selection"):
                for entity in self.selected_entities:
                    self.commands.unlock(entity)
            self.status = "Unlocked: " + self.selection.name

    def set_entity_metadata(self, entity, **kwargs):
        self.finish_edit()
        return self.commands.set_metadata(entity, **kwargs)

    def apply_inspector_transform(self, primary, attribute, value):
        if len(self.selected_entities) <= 1:
            return self.commands.set_transform(primary, **{attribute: value})
        if attribute == "position":
            delta = dict(translation=value - primary.pos)
        elif attribute == "rotation":
            delta = dict(rotation=euler_xyz(rotation_xyz(value) @ rotation_xyz(primary.rot).T))
        else:
            delta = dict(scale=value / primary.scale)
        return self.commands.transform_many(self.scene.selected_ids, **delta)

    def add_ground_mesh(self):
        self.finish_edit()
        root = self.commands.spawn('builtin:ground', name='Ground Mesh')
        self.select(root)
        self.status = 'Added ordinary Ground Mesh (10 x 10); transform or lock in Inspector'
        return root

    def _history_step(self, redo=False):
        self.finish_edit()
        changed = self.commands.redo() if redo else self.commands.undo()
        self.place_selected_mode = False
        self.sync_selection()
        self.status = ("Redo" if redo else "Undo") + (" complete" if changed else ": history is empty")
        return changed

    def undo(self):
        return self._history_step()

    def redo(self):
        return self._history_step(redo=True)

    def select_group(self, group_id):
        self.finish_edit()
        self.place_selected_mode = False
        self.commands.select_group(group_id)
        self.sync_selection()

    def group_selected(self):
        self.finish_edit()
        group = self.commands.create_group(self.scene.selected_ids)
        self.sync_selection()
        return group

    def ungroup_selected(self):
        self.finish_edit()
        if self.scene.selected_group_id is not None:
            self.commands.ungroup(self.scene.selected_group_id)
            self.sync_selection()

    def rename_group(self, name):
        self.finish_edit()
        if self.scene.selected_group_id is not None:
            self.commands.rename_group(self.scene.selected_group_id, name)

    def create_formation(self, rows=5, columns=8, spacing_x=1.2, spacing_y=1.4):
        self.finish_edit()
        if len(self.selected_entities) != 1 or self.selection.locked:
            raise ValueError("Select one unlocked source for Formation")
        group = self.commands.create_rectangular_formation(self.selection.entity_id,
            rows, columns, spacing_x, spacing_y)
        self.sync_selection()
        self.status = "Created {}: {} members".format(group.name, len(group.member_ids))
        return group

    def align_selected_adjacent(self, axis='x', side=1, gap=0.0):
        self.finish_edit()
        if self.selection is None or len(self.selected_entities) < 2:
            raise ValueError('Select modules; the last selected is the fixed reference')
        entities = self.commands.align_adjacent(self.scene.selected_ids,
            self.selection.entity_id, axis, side, gap)
        self.sync_selection()
        self.status = 'Aligned {} modules beside {}'.format(len(entities), self.selection.name)
        return entities

    def create_roman_street(self, segments=6, road_width=6.0, origin=None, facing=0.0,
                            variation=False, seed=0, extension_segments=0):
        """Append the street through Commands; only the UI wrapper reframes."""
        self.finish_edit()
        result = self.commands.create_roman_street(segments, road_width, origin, facing, variation, seed, extension_segments)
        self.sync_selection()
        self.place_selected_mode = False
        self.set_workspace('Arrange')
        self.assets_visible = True
        self.focus_selected()
        self.status = 'Roman street: {:g} m, {} editable modules | Ctrl+Z undoes the whole street'.format(
            result['length'], result['entity_count'])
        return result

    def begin_surface_placement(self):
        self.finish_edit()
        if self.camera_view:
            raise ValueError("Switch to Editor View to place objects")
        if len(self.selected_entities) != 1 or self.selection.locked:
            raise ValueError("Select one unlocked object first")
        self.place_selected_mode = True
        self.status = "Click a surface to place the selected object; Esc cancels"

    def set_shadows(self, enabled=None, resolution=None, bias=None, pcf=None):
        from .lighting import update_shadows
        if self.commands.active_transaction:
            raise ValueError('Shadow changes require a completed placement transaction')
        return update_shadows(self.scene, enabled, resolution, bias, pcf)

    def set_lighting(self, mode=None, direction=None, diffuse=None, ambient=None):
        from .lighting import update_lighting
        if self.commands.active_transaction:
            raise ValueError('Lighting changes require a completed placement transaction')
        return update_lighting(self.scene, mode, direction, diffuse, ambient)

    def set_atmosphere(self, **changes):
        from .atmosphere import update_atmosphere
        if self.commands.active_transaction:
            raise ValueError('Atmosphere changes require a completed placement transaction')
        return update_atmosphere(self.scene, **changes)

    def sky_preset(self, name):
        from .atmosphere import sky_preset
        if self.commands.active_transaction:
            raise ValueError('Finish placement before changing sky')
        return sky_preset(self.scene, name)

    def sunset_preset(self):
        from .atmosphere import sunset_preset
        if self.commands.active_transaction:
            raise ValueError('Atmosphere changes require a completed placement transaction')
        return sunset_preset(self.scene)

    def focus_selected(self):
        self.scene.update()
        bounds = world_bounds(self.selected_entities, visible_only=True)
        if bounds is not None:
            self.viewer.controller.focus_bounds(*bounds, aspect=self.viewer.aspect)

    def frame_all(self):
        self.scene.update()
        bounds = world_bounds(self.scene.root_entities, visible_only=True)
        if bounds is not None:
            self.viewer.controller.focus_bounds(*bounds, aspect=self.viewer.aspect)

    def reset_camera(self):
        self.viewer.reset_camera()

    def set_view(self, name):
        self.viewer.set_view(name)

    def save_scene(self, path=None):
        from .scene_io import save_scene
        return save_scene(self, path, PROJECT)

    def load_scene(self, path=None):
        try:
            self._load_scene(path)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ValueError("Invalid scene document: {}".format(exc)) from exc

    def _load_scene(self, path=None):
        from .scene_io import load_scene
        return load_scene(self, path, PROJECT)

    def draw_viewport_overlay(self, draw_list, rect):
        # The UI provides the current image rectangle before overlay/drop events.
        self.viewport_rect = rect
        if self.camera_view:
            if self.shot_camera.focus_point is not None:
                from .picking import project_point
                import imgui
                screen = project_point(self.shot_camera, self.shot_camera.focus_point, rect)
                if screen is not None:
                    sx, sy = screen
                    color = imgui.get_color_u32_rgba(.4, 1., .65, 1.)
                    draw_list.add_circle(sx, sy, 9, color, 24, 2)
                    draw_list.add_line(sx-13, sy, sx+13, sy, color, 1)
                    draw_list.add_line(sx, sy-13, sx, sy+13, color, 1)
                    draw_list.add_text(sx+14, sy-9, color, '{:.3f} m'.format(self.shot_camera.focus_distance))
            if self.composition_grid:
                import imgui
                x, y, width, height = rect
                color = imgui.get_color_u32_rgba(1, 1, 1, .5)
                for fraction in (1 / 3, 2 / 3):
                    draw_list.add_line(x + width * fraction, y, x + width * fraction, y + height, color, 1)
                    draw_list.add_line(x, y + height * fraction, x + width, y + height * fraction, color, 1)
            return
        self.viewer.resize(rect[2], rect[3])
        self.gizmo.draw(draw_list, rect)

    def handle_event(self, event, ui):
        """The editor's only input router; never forward raw events to Viewer.

        Releases/focus loss always clear gestures. UI capture takes precedence;
        then a gesture owns either the gizmo (left) or the camera (middle).
        """
        if event.type == pygame.WINDOWFOCUSLOST:
            self._orbiting = False
            self.finish_edit()
            return
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._orbiting = False
            if event.button == 1:
                self.gizmo.finish()
                self.finish_surface_drag()
            return
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and
                (self.surface_drag is not None or self.gizmo.drag is not None)):
            # A gesture still owns cancellation after crossing an ImGui panel.
            self.gizmo.finish(cancel=True)
            self.finish_surface_drag(cancel=True)
            self.place_selected_mode = False
            return
        if self.camera_view:
            navigate = (not getattr(ui, 'modal_open', False)
                        and not getattr(ui, 'mouse_captured', False)
                        and not getattr(ui, 'asset_dragging', False)
                        and getattr(ui, 'viewport_hovered', False)
                        and (event.type == pygame.MOUSEWHEEL or
                             (event.type == pygame.MOUSEBUTTONDOWN and event.button == 2)))
            if navigate:
                self.set_camera_view(False)
            else:
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and not ui.modal_open and not ui.mouse_captured and not ui.asset_dragging
                        and ui.viewport_hovered):
                    self.focus_photo_screen(event.pos)
                return
        mouse_event = event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL)
        if ui.modal_open:
            self._orbiting = False
            self.gizmo.finish()
            return
        if mouse_event and (ui.mouse_captured or ui.asset_dragging):
            self._orbiting = False
            # Both placement gestures retain ownership across ordinary panels.
            # Pause geometry updates until return, release or Escape. Recover
            # a missed release even when its next motion is over captured UI.
            if event.type == pygame.MOUSEMOTION and not getattr(event, 'buttons', (True,))[0]:
                self.gizmo.finish()
                self.finish_surface_drag()
            return
        if event.type == pygame.MOUSEMOTION:
            if self.surface_drag is not None:
                if getattr(event, "buttons", (True, False, False))[0]:
                    self.surface_drag.update(self.viewer.camera, event.pos, self.viewport_rect)
                else:
                    self.finish_surface_drag()
            elif self.gizmo.drag is not None:
                if getattr(event, "buttons", (True, False, False))[0]:
                    self.gizmo.update(event.pos)
                else:
                    self.gizmo.finish()
            elif self._orbiting:
                if not getattr(event, "buttons", (False, True, False))[1]:
                    self._orbiting = False
                    return
                mods = getattr(event, "mod", None)
                if mods is None:
                    mods = pygame.key.get_mods() if pygame.display.get_init() else 0
                if mods & pygame.KMOD_SHIFT:
                    self.viewer.controller.pan(*event.rel, self.viewer.height)
                else:
                    self.viewer.controller.orbit(*event.rel)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and ui.viewport_hovered and not ui.asset_dragging:
            x, y, width, height = self.viewport_rect
            if not (x <= event.pos[0] < x + width and y <= event.pos[1] < y + height):
                return
            if event.button == 2 and self.gizmo.drag is None and self.surface_drag is None:
                self._orbiting = True
            elif event.button == 1 and not self._orbiting:
                mods = getattr(event, "mod", None)
                if mods is None:
                    mods = pygame.key.get_mods() if pygame.display.get_init() else 0
                if mods & pygame.KMOD_SHIFT:
                    entity, _ = pick_entity(self.scene, self.viewer.camera, event.pos, self.viewport_rect)
                    self.select(entity, toggle=True)
                elif self.tool == "surface" and not self.place_selected_mode:
                    if len(self.selected_entities) != 1 or self.selection.locked:
                        self.status = "Surface Move requires one unlocked selection"
                    else:
                        self.finish_edit()
                        self.surface_drag = self.commands.begin_surface_drag(self.selection.entity_id)
                        self.surface_drag.update(self.viewer.camera, event.pos, self.viewport_rect)
                elif self.place_selected_mode:
                    self.finish_edit()
                    hit = raycast_surface(self.scene, self.viewer.camera, event.pos, self.viewport_rect,
                        exclude=self.selection, fallback=self.viewer.controller.target)
                    self.commands.place_on_surface(self.selection, hit)
                    self.place_selected_mode = False
                    self.status = "Placed: " + self.selection.name
                elif not self.gizmo.begin(event.pos, self.viewport_rect):
                    entity, _ = pick_entity(self.scene, self.viewer.camera, event.pos, self.viewport_rect)
                    self.select(entity)
            return
        if (event.type == pygame.MOUSEWHEEL and ui.viewport_hovered and
                self.gizmo.drag is None and self.surface_drag is None):
            if self.workspace == 'Shot':
                mods = getattr(event, 'mod', None)
                if mods is None:
                    mods = pygame.key.get_mods() if pygame.display.get_init() else 0
                step = .1 if mods & pygame.KMOD_CTRL else 5. if mods & pygame.KMOD_SHIFT else 1.
                self.viewer.controller.dolly(float(getattr(event, 'precise_y', event.y)) * step)
            else:
                self.viewer.controller.zoom(event.y)
        if event.type != pygame.KEYDOWN or ui.keyboard_captured:
            return
        control = bool(event.mod & pygame.KMOD_CTRL)
        if control and event.key == pygame.K_z:
            self.redo() if event.mod & pygame.KMOD_SHIFT else self.undo()
        elif control and event.key == pygame.K_y:
            self.redo()
        elif control and event.key == pygame.K_s:
            self.save_scene()
        elif control and event.key == pygame.K_o:
            self.load_scene()
        elif control and event.key == pygame.K_d:
            self.duplicate_selected()
        elif event.key == pygame.K_DELETE:
            self.delete_selected()
        elif event.key == pygame.K_f:
            self.focus_selected()
        elif event.key == pygame.K_HOME:
            self.frame_all()
        elif event.key in (pygame.K_q, pygame.K_g, pygame.K_r, pygame.K_s):
            self.finish_edit()
            self.tool = {pygame.K_q: "select", pygame.K_g: "move", pygame.K_r: "rotate", pygame.K_s: "scale"}[event.key]
        elif event.key == pygame.K_ESCAPE:
            self.gizmo.finish(cancel=True)
            self.finish_surface_drag(cancel=True)
            self.place_selected_mode = False
        elif event.key in (pygame.K_1, pygame.K_KP1, pygame.K_3, pygame.K_KP3, pygame.K_7, pygame.K_KP7):
            key = event.key
            pair = (("front", "back") if key in (pygame.K_1, pygame.K_KP1) else
                    ("right", "left") if key in (pygame.K_3, pygame.K_KP3) else ("top", "bottom"))
            self.set_view(pair[control])


def run(initial_asset="auto", frames=None, screenshot=None, hidden=False, ipc=True, scene_path=None):
    from .editor_runtime import run as run_editor
    return run_editor(Editor, initial_asset, frames, screenshot, hidden,
                      capture_png=capture_png, render_shot=render_shot, ipc=ipc, scene_path=scene_path)
