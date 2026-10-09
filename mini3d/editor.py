"""Editor application state and window loop, separate from ImGui presentation."""
import json
import math
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
        self.composition_grid = True
        self.capture_requested = False
        self.capture_directory = PROJECT / "captures"
        self.last_capture = None

    def create_camera_from_view(self):
        self.viewer.update_clipping()
        self.shot_camera = ShotCamera(self.viewer.camera)
        self.status = "Shot Camera created from Editor View"

    def set_camera_view(self, enabled):
        if enabled and self.shot_camera is None:
            raise ValueError("Create Camera From View first")
        self._orbiting = False
        self.finish_edit()
        self.camera_view = enabled

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
        self.finish_edit()
        path = Path(path) if path is not None else self.scene_path
        records = []
        for root in self.scene.root_entities:
            source = root.asset_path
            if source != 'builtin:ground':
                source = Path(source)
                try:
                    source = source.relative_to(PROJECT)
                except ValueError:
                    pass
            records.append(dict(asset=str(source), name=root.name, entity_id=root.entity_id,
                                position=root.pos.tolist(), rotation=root.rot.tolist(),
                                scale=root.scale.tolist(), visible=root.visible, locked=root.locked,
                                placement_type=root.placement_type, placement_anchor=root.placement_anchor,
                                keep_upright=root.keep_upright))
        snapshot = self.viewer.controller.snapshot()
        snapshot = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in snapshot.items()}
        from .lighting import shadow_state
        document = dict(shadows=shadow_state(self.scene), version=3, objects=records, camera=snapshot,
                        shot_camera=None if self.shot_camera is None else self.shot_camera.to_dict(),
                        render_mode=self.render_mode, show_grid=self.show_grid,
                        lighting=dict(mode=self.scene.lighting_mode,
                                      light_dir=np.asarray(self.scene.light_dir).tolist(),
                                      ambient=float(self.scene.ambient), diffuse=float(self.scene.diffuse)),
                        placement_plane=self.scene.placement_plane.to_dict(),
                        next_entity_id=self.scene._next_entity_id,
                        groups=[dict(group_id=g.group_id, name=g.name, member_ids=list(g.member_ids))
                                for g in self.scene.groups],
                        next_group_id=self.scene._next_group_id,
                        selected_ids=list(self.scene.selected_ids),
                        primary_selection_id=self.scene.primary_selection_id,
                        selected_group_id=self.scene.selected_group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        self.status = "Saved: " + str(path)

    def load_scene(self, path=None):
        try:
            self._load_scene(path)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ValueError("Invalid scene document: {}".format(exc)) from exc

    def _load_scene(self, path=None):
        path = Path(path) if path is not None else self.scene_path
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("version") not in (1, 2, 3):
            raise ValueError("Unsupported scene format")
        # Missing/null means this project has no Shot Camera, even if the
        # previously open project had one. Validate before any live mutation.
        shot_data = document.get('shot_camera')
        shot = None if shot_data is None else ShotCamera.from_dict(shot_data)
        loaded = Scene()
        lighting = document.get('lighting', {})
        # JSON null is invalid in saved parameters (API None means "unchanged").
        if not isinstance(lighting, dict) or any(value is None for value in lighting.values()):
            raise ValueError('Invalid lighting document')
        from .lighting import update_lighting
        update_lighting(loaded, lighting.get('mode'), lighting.get('light_dir'),
                        lighting.get('diffuse'), lighting.get('ambient'))
        from .lighting import update_shadows
        shadows = document.get('shadows', {})
        if not isinstance(shadows, dict) or any(v is None for v in shadows.values()):
            raise ValueError('Invalid shadows document')
        update_shadows(loaded, **shadows)
        loaded.placement_plane = PlacementPlane(**document.get('placement_plane', {}))
        for record in document["objects"]:
            source = record["asset"]
            if source != 'builtin:ground':
                source = Path(source)
                if not source.is_absolute():
                    source = PROJECT / source
            root = self.cache.load(source).instantiate()
            for key, field in (("position", "pos"), ("rotation", "rot"), ("scale", "scale")):
                vector = np.asarray(record[key], dtype=float)
                if vector.shape != (3,) or not np.all(np.isfinite(vector)):
                    raise ValueError("Invalid object transform")
                if key == "scale" and np.any(vector <= 0):
                    raise ValueError("Scale must be positive")
                setattr(root, field, vector)
            root.name, root.visible = str(record["name"]), bool(record.get("visible", True))
            if document["version"] >= 2:
                root.entity_id = record["entity_id"]
                if root.entity_id is None:
                    raise ValueError("Missing entity ID")
            root.placement_type = record.get("placement_type",
                "character" if Path(source).stem == "roman_legionnaire" else "prop")
            root.placement_anchor = record.get("placement_anchor", "bounds_bottom")
            root.keep_upright = record.get("keep_upright", root.placement_type == "character")
            root.locked = record.get("locked", False)
            if (root.placement_type not in ("character", "prop") or
                    root.placement_anchor not in ("pivot", "bounds_bottom") or
                    not isinstance(root.keep_upright, bool) or not isinstance(root.locked, bool)):
                raise ValueError("Invalid placement metadata")
            loaded.add(root)
        for record in document.get("groups", []):
            if record["group_id"] is None:
                raise ValueError("Missing group ID")
            loaded.add_group(SceneGroup(record["group_id"], record["name"], record["member_ids"]))
        next_group = document.get("next_group_id", loaded._next_group_id)
        if isinstance(next_group, bool) or not isinstance(next_group, int) or next_group < loaded._next_group_id:
            raise ValueError("Invalid next group ID")
        selected_ids = document.get("selected_ids", [loaded.root_entities[0].entity_id]
                                   if loaded.root_entities else [])
        PlacementCommands(loaded, self.cache).set_selection(selected_ids,
            primary_id=document.get("primary_selection_id"), group_id=document.get("selected_group_id"))
        # Validate camera data on a temporary Viewer before replacing the scene.
        probe = Viewer(Scene(), self.viewer.width, self.viewer.height)
        camera_state = document["camera"]
        limits = [float(camera_state[key]) for key in
                  ("bounds_radius", "min_distance", "max_distance")]
        if not all(np.isfinite(value) and value > 0 for value in limits) or limits[1] > limits[2]:
            raise ValueError("Invalid camera bounds or distance limits")
        probe.controller.restore(document["camera"])
        probe.camera.projection_matrix(self.viewer.aspect)
        mode = document.get("render_mode", "Lit")
        if mode not in ("Lit", "Wireframe", "Unlit"):
            raise ValueError("Unknown render mode")
        next_id = document.get("next_entity_id", loaded._next_entity_id)
        if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id < loaded._next_entity_id:
            raise ValueError("Invalid next entity ID")
        self.finish_edit()
        self.scene.root_entities[:] = loaded.root_entities
        self.scene.groups[:] = loaded.groups
        self.scene._next_group_id = max(self.scene._next_group_id, loaded._next_group_id, next_group)
        self.scene._next_entity_id = max(self.scene._next_entity_id, loaded._next_entity_id, next_id)
        # Old ground_visible was an editor helper, never a serialized object.
        # Ignore it; preserve only explicit objects and query-plane settings.
        self.scene.ground = None
        self.scene.placement_plane = loaded.placement_plane
        from .lighting import shadow_state, update_shadows
        update_shadows(self.scene, **shadow_state(loaded))
        self.scene.lighting_mode = loaded.lighting_mode
        self.scene.light_dir = loaded.light_dir.copy()
        self.scene.ambient, self.scene.diffuse = loaded.ambient, loaded.diffuse
        self.commands.clear_history()
        self.scene.update()
        self.commands.set_selection(loaded.selected_ids, primary_id=loaded.primary_selection_id,
                                    group_id=loaded.selected_group_id)
        self.sync_selection()
        self.place_selected_mode = False
        self.viewer.controller.restore(document["camera"])
        self.viewer.save_camera()
        self.shot_camera = shot
        self.camera_view = self.camera_view and shot is not None
        self.capture_requested = False
        self.last_capture = None
        self.render_mode, self.show_grid = mode, bool(document.get("show_grid", True))
        self.status = "Loaded: " + str(path)

    def draw_viewport_overlay(self, draw_list, rect):
        # The UI provides the current image rectangle before overlay/drop events.
        self.viewport_rect = rect
        if self.camera_view:
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
            return  # Photo preview is fixed; scene placement/navigation uses Editor View.
        mouse_event = event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL)
        if ui.modal_open or (mouse_event and (ui.mouse_captured or ui.asset_dragging)):
            self._orbiting = False
            self.gizmo.finish()
            # A Surface Drag owns one transaction until release/Esc, including
            # excursions across a panel. Captured input must not move geometry.
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


def run(initial_asset="auto", frames=None, screenshot=None, hidden=False):
    import imgui
    from imgui.integrations.opengl import ProgrammablePipelineRenderer
    from imgui.integrations.pygame import PygameRenderer
    from OpenGL import GL as gl
    from .editor_ui import EditorUI
    from .gl_renderer import GLRenderer
    from .render_target import RenderTarget

    class Backend(ProgrammablePipelineRenderer):
        _custom_key = PygameRenderer._custom_key
        _map_keys = PygameRenderer._map_keys
        process_inputs = PygameRenderer.process_inputs

        def __init__(self):
            super().__init__()
            self.custom_key_map, self._gui_time = {}, None
            self._map_keys()

        def process_event(self, event):
            if event.type == pygame.WINDOWFOCUSLOST:
                for index in range(3):
                    self.io.mouse_down[index] = False
                for index in range(len(self.io.keys_down)):
                    self.io.keys_down[index] = False
                self.io.key_ctrl = self.io.key_shift = self.io.key_alt = self.io.key_super = False
                return
            if event.type == pygame.VIDEORESIZE:
                return  # SDL2 resizes in place; preserve the GL context/resources.
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                index = {1: 0, 2: 2, 3: 1}.get(event.button)
                if index is not None:
                    self.io.mouse_down[index] = event.type == pygame.MOUSEBUTTONDOWN
                return
            if event.type == pygame.MOUSEWHEEL:
                self.io.mouse_wheel += event.y
                self.io.mouse_wheel_horizontal += event.x
                return
            return PygameRenderer.process_event(self, event)

    pygame.init()
    pygame.display.set_mode((1440, 900), pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE |
                            (pygame.HIDDEN if hidden else 0))
    pygame.display.set_caption("Mini3D Editor 0.1")
    context = imgui.create_context()
    imgui.get_io().ini_file_name = None
    imgui.get_io().display_size = (1440, 900)
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.is_file():
        imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 16)
    backend = Backend()
    target = RenderTarget()
    renderer = GLRenderer(800, 700)
    app = Editor(800, 700)
    ui = EditorUI(app)
    previews = []
    try:
        for asset in app.assets:
            candidates = list(Path(asset["path"]).parent.glob("preview.*"))
            if candidates:
                surface = pygame.image.load(str(candidates[0]))
                texture = gl.glGenTextures(1)
                previews.append(texture)
                gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
                gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, *surface.get_size(), 0,
                                gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pygame.image.tostring(surface, "RGBA", False))
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
                asset['preview_texture'], asset['preview_size'] = texture, surface.get_size()
        if initial_asset == "auto":
            initial_asset = next((i for i, asset in enumerate(app.assets)
                                  if Path(asset["path"]).stem == "roman_legionnaire"),
                                 0 if app.assets else None)
        if initial_asset is not None:
            if not 0 <= initial_asset < len(app.assets):
                raise ValueError("Asset number is not available; choose from 1 to {}".format(len(app.assets)))
            app.add_asset(initial_asset)
            ui.selected_asset = initial_asset
        clock = pygame.time.Clock()
        running, frame = True, 0
        while running:
            clock.tick(60)
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                backend.process_event(event)
            if not running:
                break
            imported = app.poll_model_dialog()
            if imported is not None:
                ui.selected_asset = next(i for i, item in enumerate(app.assets)
                                         if item["path"] == imported.asset_path)
            width, height = pygame.display.get_window_size()
            backend.io.display_size = (max(1, width), max(1, height))
            backend.process_inputs()
            imgui.new_frame()
            rect = ui.draw(width, height, target.texture)
            for event in events:
                try:
                    app.handle_event(event, ui)
                except (ValueError, OSError) as exc:
                    app.status = str(exc)
            app.scene.update()
            app.viewer.update_clipping()
            app.scene.render_mode, app.scene.show_grid = app.render_mode, app.show_grid
            app.scene.grid_scale = 10 ** math.floor(math.log10(max(app.viewer.controller.distance / 10, 1e-9))) / 20
            if app.capture_requested:
                app.capture_requested = False
                try:
                    path = app.capture_directory / ("shot_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png")
                    app.last_capture = capture_png(app.scene, app.shot_camera, renderer, path)
                    app.status = "Captured: " + str(app.last_capture)
                except (OSError, ValueError, pygame.error) as exc:
                    app.status = "Capture failed: " + str(exc)
            if app.camera_view:
                render_shot(app.scene, app.shot_camera, renderer, target)
            else:
                target.resize(rect[2], rect[3])
                target.bind()
                gl.glDisable(gl.GL_SCISSOR_TEST)
                gl.glDepthMask(True)
                renderer.resize(*rect[2:])
                renderer.render(app.scene, app.viewer.camera)
            if not app.camera_view and app.selection is not None and app.selection.visible and hasattr(renderer, "material_renderer"):
                selected = Scene()
                selected.add(app.selection)
                renderer.material_renderer.render_selection(selected.get_flat_render_list(), app.viewer.camera, *rect[2:])
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(.06, .07, .09, 1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            imgui.render()
            backend.render(imgui.get_draw_data())
            frame += 1
            if screenshot and frames is not None and frame >= frames:
                pixels = gl.glReadPixels(0, 0, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                image = pygame.image.fromstring(pixels, (width, height), "RGB", True)
                path = Path(screenshot)
                path.parent.mkdir(parents=True, exist_ok=True)
                pygame.image.save(image, str(path))
            pygame.display.flip()
            if frames is not None and frame >= frames:
                running = False
    finally:
        app.model_dialog.close()
        renderer.close()
        if previews:
            gl.glDeleteTextures(previews)
        target.close()
        backend.shutdown()
        imgui.destroy_context(context)
        pygame.quit()
