"""Pygame/ImGui/GL lifecycle and frame loop for the unified editor."""
import math
from datetime import datetime
from pathlib import Path
import pygame
from .scene import Scene
from .shot_camera import render_shot, capture_png


def run(editor_class, initial_asset="auto", frames=None, screenshot=None, hidden=False):
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
    app = editor_class(800, 700)
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
                target.resize(rect[2], rect[3], samples=1)
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
