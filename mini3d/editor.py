"""Editor application state and window loop, separate from ImGui presentation."""
import json
import math
from pathlib import Path

import numpy as np
import pygame

from .scene import Scene
from .viewer import Viewer, world_bounds
from .gltf_loader import AssetCache
from .picking import pick_entity, screen_ray, ground_hit
from .editor_tools import TransformGizmo
from .model_dialog import ModelFileDialog


PROJECT = Path(__file__).resolve().parents[1]


class Editor:
    def __init__(self, width=1280, height=800):
        self.scene = Scene()
        self.cache = AssetCache()
        manifest = json.loads((PROJECT / "model/manifest.json").read_text(encoding="utf-8"))
        self.assets = [dict(info, path=str(PROJECT / "model" / key / info["entry"]))
                       for key, info in sorted(manifest.items())
                       if info.get("status") == "downloaded" and
                       (PROJECT / "model" / key / info["entry"]).is_file()]
        self.viewer = Viewer(self.scene, width, height, input_enabled=False)
        self.viewer.controller.yaw = -.9
        self.viewer.controller.pitch = .25
        self.viewer.controller.update()
        self.selection = None
        self.tool = "move"
        self.render_mode = "Lit"
        self.show_grid = True
        self.status = "Double-click or drag an asset to add it. Middle drag orbits."
        self.scene_path = PROJECT / "scenes/editor_scene.json"
        self.viewport_rect = (0, 0, width, height)
        self.gizmo = TransformGizmo(self)
        self._orbiting = False
        self._instance_number = 0
        self.model_dialog = ModelFileDialog(PROJECT / "model")

    def browse_model(self):
        if self.model_dialog.open():
            self._orbiting = False
            self.gizmo.finish(cancel=True)
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

    def select(self, entity):
        self.gizmo.finish()
        self.selection = entity
        self.viewer.selected_entity = entity
        if entity is not None:
            self.status = "Selected: " + entity.name

    def add_asset(self, index, position=None):
        record = self.assets[index]
        asset = self.cache.load(record["path"])
        root = asset.instantiate()
        self._instance_number += 1
        root.name = "{}_{:03d}".format(record["name"], self._instance_number)
        if position is not None:
            root.pos = np.asarray(position, dtype=np.float64)
        self.scene.add(root)
        self.scene.update()
        self.select(root)
        if position is None:
            self.focus_selected()
            self.viewer.save_camera()
        self.status = "Added {} | original asset scale | {} triangles".format(
            record["name"], record.get("triangles", "?"))
        return root

    def drop_asset(self, index, screen_pos):
        self.scene.update()
        _, point = pick_entity(self.scene, self.viewer.camera, screen_pos, self.viewport_rect)
        if point is None:
            point = ground_hit(screen_ray(self.viewer.camera, screen_pos, self.viewport_rect))
        if point is None:
            point = self.viewer.controller.target.copy()
        root = self.add_asset(index, point)
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
        if self.selection is None:
            return None
        duplicate = self.selection.clone()
        self._instance_number += 1
        duplicate.name = self.selection.name + " copy"
        # Keep an exact transform copy; the move handle can place the new instance.
        self.scene.add(duplicate)
        self.scene.update()
        self.select(duplicate)
        return duplicate

    def delete_selected(self):
        if self.selection in self.scene.root_entities:
            self.scene.root_entities.remove(self.selection)
            self.select(None)
            self.status = "Object removed from the scene"

    def focus_selected(self):
        if self.selection is not None and self.selection.visible:
            self.viewer.focus(self.selection)

    def frame_all(self):
        self.scene.update()
        bounds = world_bounds([root for root in self.scene.root_entities if root.visible])
        if bounds is not None:
            self.viewer.controller.focus_bounds(*bounds, aspect=self.viewer.aspect)

    def reset_camera(self):
        self.viewer.reset_camera()

    def set_view(self, name):
        self.viewer.set_view(name)

    def save_scene(self, path=None):
        path = Path(path) if path is not None else self.scene_path
        records = []
        for root in self.scene.root_entities:
            source = Path(root.asset_path)
            try:
                source = source.relative_to(PROJECT)
            except ValueError:
                pass
            records.append(dict(asset=str(source), name=root.name, position=root.pos.tolist(),
                                rotation=root.rot.tolist(), scale=root.scale.tolist(), visible=root.visible))
        snapshot = self.viewer.controller.snapshot()
        snapshot = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in snapshot.items()}
        document = dict(version=1, objects=records, camera=snapshot,
                        render_mode=self.render_mode, show_grid=self.show_grid)
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
        if document.get("version") != 1:
            raise ValueError("Unsupported scene format")
        roots = []
        for record in document["objects"]:
            source = Path(record["asset"])
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
            roots.append(root)
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
        self.scene.root_entities = roots
        self.scene.update()
        self.select(roots[0] if roots else None)
        self.viewer.controller.restore(document["camera"])
        self.viewer.save_camera()
        self.render_mode, self.show_grid = mode, bool(document.get("show_grid", True))
        self.status = "Loaded: " + str(path)

    def draw_viewport_overlay(self, draw_list, rect):
        # The UI provides the current image rectangle before overlay/drop events.
        self.viewport_rect = rect
        self.viewer.resize(rect[2], rect[3])
        self.gizmo.draw(draw_list, rect)

    def handle_event(self, event, ui):
        """The editor's only input router; never forward raw events to Viewer.

        Releases/focus loss always clear gestures. UI capture takes precedence;
        then a gesture owns either the gizmo (left) or the camera (middle).
        """
        if event.type == pygame.WINDOWFOCUSLOST:
            self._orbiting = False
            self.gizmo.finish()
            return
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._orbiting = False
            if event.button == 1:
                self.gizmo.finish()
            return
        mouse_event = event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL)
        if ui.modal_open or (mouse_event and (ui.mouse_captured or ui.asset_dragging)):
            self._orbiting = False
            self.gizmo.finish()
            return
        if event.type == pygame.MOUSEMOTION:
            if self.gizmo.drag is not None:
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
                    mods = pygame.key.get_mods()
                if mods & pygame.KMOD_SHIFT:
                    self.viewer.controller.pan(*event.rel, self.viewer.height)
                else:
                    self.viewer.controller.orbit(*event.rel)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and ui.viewport_hovered and not ui.asset_dragging:
            x, y, width, height = self.viewport_rect
            if not (x <= event.pos[0] < x + width and y <= event.pos[1] < y + height):
                return
            if event.button == 2 and self.gizmo.drag is None:
                self._orbiting = True
            elif event.button == 1 and not self._orbiting and not self.gizmo.begin(event.pos, self.viewport_rect):
                entity, _ = pick_entity(self.scene, self.viewer.camera, event.pos, self.viewport_rect)
                self.select(entity)
            return
        if event.type == pygame.MOUSEWHEEL and ui.viewport_hovered and self.gizmo.drag is None:
            self.viewer.controller.zoom(event.y)
        if event.type != pygame.KEYDOWN or ui.keyboard_captured:
            return
        control = bool(event.mod & pygame.KMOD_CTRL)
        if control and event.key == pygame.K_s:
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
            self.tool = {pygame.K_q: "select", pygame.K_g: "move", pygame.K_r: "rotate", pygame.K_s: "scale"}[event.key]
        elif event.key == pygame.K_ESCAPE:
            self.gizmo.finish(cancel=True)
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
            app.scene.render_mode, app.scene.show_grid = app.render_mode, app.show_grid
            app.scene.grid_scale = 10 ** math.floor(math.log10(max(app.viewer.controller.distance / 10, 1e-9))) / 20
            target.resize(rect[2], rect[3])
            target.bind()
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glDepthMask(True)
            renderer.resize(*rect[2:])
            renderer.render(app.scene, app.viewer.camera)
            if app.selection is not None and app.selection.visible and hasattr(renderer, "material_renderer"):
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
        if hasattr(renderer, "material_renderer"):
            renderer.material_renderer.close()
        if previews:
            gl.glDeleteTextures(previews)
        target.close()
        backend.shutdown()
        imgui.destroy_context(context)
        pygame.quit()
