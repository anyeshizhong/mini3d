"""Scene v1/v2/v3 persistence with validation before live editor replacement.

The Editor supplies project root, cache and transaction hooks. Public methods
remain on Editor; the scene schema and exception behavior are unchanged.
"""
import json
from pathlib import Path
import numpy as np
from .scene import Scene, SceneGroup
from .viewer import Viewer
from .commands import PlacementCommands
from .placement_plane import PlacementPlane
from .shot_camera import ShotCamera


def save_scene(self, path=None, project=None):
    self.finish_edit()
    path = Path(path) if path is not None else self.scene_path
    records = []
    for root in self.scene.root_entities:
        source = root.asset_path
        if not str(source).startswith('builtin:'):
            source = Path(source)
            try:
                source = source.relative_to(project)
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
    from .environment import environment_state
    from .atmosphere import atmosphere_state
    document = dict(shadows=shadow_state(self.scene), version=3, objects=records, camera=snapshot,
                    environment=environment_state(self.scene), atmosphere=atmosphere_state(self.scene),
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

def load_scene(self, path=None, project=None):
    path = Path(path) if path is not None else self.scene_path
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("version") not in (1, 2, 3):
        raise ValueError("Unsupported scene format")
    # Missing/null means this project has no Shot Camera, even if the
    # previously open project had one. Validate before any live mutation.
    shot_data = document.get('shot_camera')
    shot = None if shot_data is None else ShotCamera.from_dict(shot_data)
    loaded = Scene()
    from .environment import environment_state, update_environment
    environment = document.get('environment', {})
    if not isinstance(environment, dict) or any(v is None for v in environment.values()):
        raise ValueError('Invalid environment document')
    update_environment(loaded, **environment)
    lighting = document.get('lighting', {})
    # JSON null is invalid in saved parameters (API None means "unchanged").
    if not isinstance(lighting, dict) or any(value is None for value in lighting.values()):
        raise ValueError('Invalid lighting document')
    from .lighting import update_lighting
    update_lighting(loaded, lighting.get('mode'), lighting.get('light_dir'),
                    lighting.get('diffuse'), lighting.get('ambient'))
    from .atmosphere import update_atmosphere, atmosphere_state
    atmosphere = document.get('atmosphere', {})
    if not isinstance(atmosphere, dict) or any(v is None for v in atmosphere.values()):
        raise ValueError('Invalid atmosphere document')
    update_atmosphere(loaded, **atmosphere)
    from .lighting import update_shadows
    shadows = document.get('shadows', {})
    if not isinstance(shadows, dict) or any(v is None for v in shadows.values()):
        raise ValueError('Invalid shadows document')
    update_shadows(loaded, **shadows)
    loaded.placement_plane = PlacementPlane(**document.get('placement_plane', {}))
    for record in document["objects"]:
        source = record["asset"]
        if not str(source).startswith('builtin:'):
            source = Path(source)
            if not source.is_absolute():
                source = project / source
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
    update_environment(self.scene, **environment_state(loaded))
    update_atmosphere(self.scene, **atmosphere_state(loaded))
    self.commands.clear_history()
    self.scene.update()
    self.commands.set_selection(loaded.selected_ids, primary_id=loaded.primary_selection_id,
                                group_id=loaded.selected_group_id)
    self.sync_selection()
    self.place_selected_mode = False
    self.viewer.controller.restore(document["camera"])
    self.viewer.save_camera()
    self.shot_camera = shot
    self._editing_shot = False
    self.camera_view = self.camera_view and shot is not None
    self.capture_requested = False
    self.last_capture = None
    self.render_mode, self.show_grid = mode, bool(document.get("show_grid", True))
    self.status = "Loaded: " + str(path)

