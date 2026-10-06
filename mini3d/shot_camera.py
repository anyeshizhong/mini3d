"""Independent photo camera and a clean offscreen PNG pass using GLRenderer."""
import copy
import math
from pathlib import Path

from .camera import Camera


class ShotCamera(Camera):
    ASPECTS = {'16:9': (1920, 1080), '3:2': (1920, 1280),
               '4:3': (1920, 1440), '1:1': (1920, 1920)}

    def __init__(self, view):
        super().__init__(view.position, view.rotation, view.fov_y, view.near, view.far)
        self.aspect_name = '16:9'

    @property
    def size(self):
        return self.ASPECTS[self.aspect_name]

    @property
    def aspect(self):
        width, height = self.size
        return width / height

    @property
    def focal_mm(self):
        # A 36 mm horizontal film gate; changing aspect changes its height.
        return 36 / (2 * self.aspect * math.tan(math.radians(self.fov_y) / 2))

    def set_lens(self, focal_mm):
        if focal_mm not in (24, 35, 50, 85):
            raise ValueError('Choose 24mm, 35mm, 50mm or 85mm')
        self._set_focal(focal_mm)

    def _set_focal(self, focal_mm):
        self.fov_y = math.degrees(2 * math.atan(36 / (2 * self.aspect * focal_mm)))

    def set_aspect(self, name):
        if name not in self.ASPECTS:
            raise ValueError('Unknown shot aspect ratio')
        focal = self.focal_mm
        self.aspect_name = name
        self._set_focal(focal)

    def fit_rect(self, rect):
        x, y, width, height = rect
        scale = min(width / self.size[0], height / self.size[1])
        w, h = max(1, int(self.size[0] * scale)), max(1, int(self.size[1] * scale))
        return int(x + (width - w) / 2), int(y + (height - h) / 2), w, h


def render_shot(scene, camera, renderer, target):
    """The identical clean render pass for Camera View and the exported PNG."""
    from OpenGL import GL as gl
    clean = copy.copy(scene)
    clean.show_grid, clean.show_axes, clean.render_mode = False, False, 'Lit'
    target.resize(*camera.size)
    target.bind()
    gl.glDisable(gl.GL_SCISSOR_TEST)
    gl.glDepthMask(True)
    renderer.resize(*camera.size)
    renderer.render(clean, camera)


def capture_png(scene, camera, renderer, path):
    import pygame
    from OpenGL import GL as gl
    from .render_target import RenderTarget

    framebuffer = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
    viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
    old_size = renderer.w, renderer.h
    target = RenderTarget()
    try:
        scene.update()
        render_shot(scene, camera, renderer, target)
        pixels = gl.glReadPixels(0, 0, *camera.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        picture = pygame.image.fromstring(pixels, camera.size, 'RGB', True)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(picture, str(path))
        return path
    finally:
        target.close()
        renderer.resize(*old_size)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, framebuffer)
        gl.glViewport(*viewport)
