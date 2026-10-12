"""Pygame/ImGui/GL lifecycle and frame loop for the unified editor."""
import math
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
import pygame
from .scene import Scene
from .gl_state import read_rgb
from .shot_camera import render_shot, render_scene_view, capture_png


def run(editor_class, initial_asset="auto", frames=None, screenshot=None, hidden=False,
        capture_png=capture_png, render_shot=render_shot, ipc=True, ipc_directory=None, scene_path=None):
    import imgui
    from imgui.integrations.opengl import ProgrammablePipelineRenderer
    from imgui.integrations.pygame import PygameRenderer
    from OpenGL import GL as gl
    from .editor_ui import EditorUI
    from .gl_renderer import GLRenderer
    from .render_target import RenderTarget
    from .viewport_cache import viewport_key

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

    with ExitStack() as cleanup:
        pygame.init()
        cleanup.callback(pygame.quit)
        pygame.display.set_mode((1440, 900), pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE |
                                (pygame.HIDDEN if hidden else 0))
        pygame.display.set_caption("Mini3D Editor 0.1")
        context = imgui.create_context()
        cleanup.callback(imgui.destroy_context, context)
        imgui.get_io().ini_file_name = None
        imgui.get_io().display_size = (1440, 900)
        font_path = Path("C:/Windows/Fonts/segoeui.ttf")
        if font_path.is_file():
            imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 16)
        backend = Backend()
        cleanup.callback(backend.shutdown)
        target = RenderTarget()
        cleanup.callback(target.close)
        display_target = target
        rendered_photo = None
        from .photo_focus import read_focus_point, PhotoPreviewQuality
        from .camera import Camera
        quality = PhotoPreviewQuality()
        previous_viewport_key = None
        # Compose the exact displayed editor frame into an owned FBO. Windows
        # may discard default-framebuffer pixels when the window is occluded or
        # minimized; IPC screenshots must not depend on window pixel ownership.
        editor_frame = RenderTarget()
        cleanup.callback(editor_frame.close)
        frame_ready = False
        renderer = GLRenderer(800, 700)
        cleanup.callback(renderer.close)
        app = editor_class(800, 700)
        cleanup.callback(app.model_dialog.close)
        from .api import Mini3DAPI
        def editor_screenshot(path):
            if not frame_ready:
                raise RuntimeError('No completed editor frame is available yet')
            width, height = editor_frame.width, editor_frame.height
            previous_framebuffer = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
            previous_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))
            try:
                gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, editor_frame.framebuffer)
                gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
                pixels = read_rgb(0, 0, width, height)
            finally:
                gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, previous_framebuffer)
                gl.glReadBuffer(previous_buffer)
            if not any(pixels):
                raise RuntimeError('Editor frame readback returned only black pixels')
            image = pygame.image.fromstring(pixels, (width, height), 'RGB', True)
            path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(image, str(path))
            from copy import deepcopy
            return dict(path=str(path), format='PNG', width=width, height=height,
                        displayed_frame=deepcopy(app.displayed_frame))
        app.api = Mini3DAPI(renderer, editor=app, screenshot=editor_screenshot)
        def photo_focus_reader(point, rect):
            if rendered_photo is None:
                raise ValueError('Wait for the first photo frame')
            pose, camera, photo_target = rendered_photo
            if pose != photo_pose(app.shot_camera):
                raise ValueError('Wait for the updated camera frame before focusing')
            return read_focus_point(photo_target, camera, point, rect)
        def photo_pose(camera):
            return (camera.position.tobytes(), camera.rotation.tobytes(), camera.fov_y,
                    camera.near, camera.far, camera.aspect_name)
        app.photo_focus_reader = photo_focus_reader
        ui = EditorUI(app)
        previews = []
        cleanup.callback(lambda: gl.glDeleteTextures(previews) if previews else None)
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
        if scene_path is not None:
            app.scene_path = Path(scene_path).expanduser().resolve()
            app.load_scene()
            initial_asset = None
            if app.shot_camera is not None:
                app.set_camera_view(True)
                ui.workspace = 'Shot'
                ui.assets_visible = False
        if initial_asset == "auto":
            initial_asset = next((i for i, asset in enumerate(app.assets)
                                  if Path(asset["path"]).stem == "roman_legionnaire"),
                                 0 if app.assets else None)
        if initial_asset is not None:
            if not 0 <= initial_asset < len(app.assets):
                raise ValueError("Asset number is not available; choose from 1 to {}".format(len(app.assets)))
            app.add_asset(initial_asset)
            ui.selected_asset = initial_asset
        bridge = None
        if ipc:
            from .editor_ipc import EditorIPC
            try:
                bridge = EditorIPC(app.api, directory=ipc_directory)
                cleanup.callback(bridge.close)
                # Token is deliberately omitted from logs/window UI.
                print('Mini3D IPC: instance={} pid={} port={}'.format(
                    bridge.instance_id, bridge.info['pid'], bridge.info['port']), flush=True)
            except OSError as exc:
                app.status = 'IPC unavailable: ' + str(exc)
                print(app.status, flush=True)
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
            # Apply external edits before building the UI layout, so API view
            # switches and the rendered texture belong to the same workspace.
            if bridge is not None:
                bridge.pump()
                app.sync_selection()
            imgui.new_frame()
            rect = ui.draw(width, height, display_target.texture)
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
            photo_preview = ui.workspace == 'Shot' and app.shot_camera is not None
            current_viewport_key = viewport_key(app, rect[2:], photo_preview, renderer.render_mode)
            photo_size = None
            if app.camera_view or photo_preview:
                photo_size = quality.size(current_viewport_key, app.shot_camera.size,
                    imgui.is_any_item_active() or app._orbiting, time.monotonic())
            render_key = (current_viewport_key, photo_size)
            viewport_redrawn = render_key != previous_viewport_key
            if viewport_redrawn:
                if app.camera_view:
                    # Keep the ImGui image texture stable across quality changes:
                    # UI commands are built before this frame's scene is rendered.
                    current_target = target
                    render_scene_view(app.scene, app.shot_camera, renderer, current_target,
                                      photo_size, app.shot_camera.samples)
                    shot = app.shot_camera
                    camera = Camera(shot.position.copy(), shot.rotation.copy(), shot.fov_y, shot.near, shot.far)
                    rendered_photo = (photo_pose(shot), camera, current_target)
                    display_target = current_target
                elif photo_preview:
                    render_scene_view(app.scene, app.viewer.camera, renderer, target, photo_size,
                                      app.shot_camera.samples, photo_camera=app.shot_camera)
                    display_target = target
                    rendered_photo = None
                else:
                    display_target = target
                    rendered_photo = None
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
                previous_viewport_key = render_key
            renderer.render_stats['viewport_redrawn'] = viewport_redrawn
            editor_frame.resize(width, height)
            editor_frame.bind()
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glClearColor(.06, .07, .09, 1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            imgui.render()
            backend.render(imgui.get_draw_data())
            frame_ready = True
            app.displayed_frame = dict(frame_id=frame + 1, width=width, height=height,
                                       view_state=app.api._view_state())
            if bridge is not None:
                bridge.pump('frame')
            frame += 1
            if screenshot and frames is not None and frame >= frames:
                editor_screenshot(Path(screenshot))
            # Present the same frame that screenshot() reads, without another
            # scene render or another GL context. Disable clipping for the blit.
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, editor_frame.framebuffer)
            gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, 0)
            gl.glDrawBuffer(gl.GL_BACK)
            gl.glBlitFramebuffer(0, 0, width, height, 0, 0, width, height,
                                 gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
            pygame.display.flip()
            if frames is not None and frame >= frames:
                running = False
