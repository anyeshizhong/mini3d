"""Independent photo camera and a clean offscreen PNG pass using GLRenderer."""
import copy
import math
from numbers import Real
from pathlib import Path

import numpy as np

from .camera import Camera


class ShotCamera(Camera):
    ASPECTS = {'16:9': (1920, 1080), '3:2': (1920, 1280),
               '4:3': (1920, 1440), '1:1': (1920, 1920)}

    def __init__(self, view):
        super().__init__(view.position, view.rotation, view.fov_y, view.near, view.far)
        self.aspect_name = '16:9'
        self.samples = 1

    def set_samples(self, samples):
        from .render_target import RenderTarget
        self.samples = RenderTarget.validate_samples(samples)

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

    def to_dict(self):
        """Detached Scene v3/API parameters; FOV preserves the exact projection."""
        return dict(position=self.position.tolist(), rotation=self.rotation.tolist(),
                    focal_mm=self.focal_mm, aspect=self.aspect_name, fov_y=self.fov_y,
                    near=self.near, far=self.far, samples=self.samples)

    @classmethod
    def from_dict(cls, data):
        """Validate a saved camera without changing any live editor state.

        Keep the original FOV (including non-preset Editor View lenses), and
        check the redundant focal length against the 36 mm horizontal gate.
        Camera owns pose, handedness and clipping validation.
        """
        if not isinstance(data, dict):
            raise ValueError('shot_camera must be an object')
        try:
            aspect = data['aspect']
            if not isinstance(aspect, str) or aspect not in cls.ASPECTS:
                raise ValueError('Unknown shot aspect ratio')
            values = {}
            for name, shape in (('position', (3,)), ('rotation', (3, 3)),
                                ('focal_mm', ()), ('fov_y', ()), ('near', ()), ('far', ())):
                raw = np.asarray(data[name], dtype=object)
                if raw.shape != shape or any(isinstance(v, (bool, np.bool_)) or
                                             not isinstance(v, Real) for v in raw.flat):
                    raise ValueError(name + ' must contain numeric values of the correct shape')
                value = np.asarray(raw, dtype=float)
                if not np.isfinite(value).all():
                    raise ValueError(name + ' must be finite')
                values[name] = float(value) if shape == () else value
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                shot = cls(Camera(values['position'], values['rotation'], values['fov_y'],
                                  values['near'], values['far']))
                shot.aspect_name = aspect
                shot.set_samples(data.get('samples', 1))
                if (values['focal_mm'] <= 0 or not math.isfinite(shot.focal_mm) or
                        not math.isclose(values['focal_mm'], shot.focal_mm, rel_tol=1e-12)):
                    raise ValueError('focal_mm must be positive and match fov_y/aspect')
                if not (np.isfinite(shot.projection_matrix(shot.aspect)).all() and
                        np.isfinite(shot.view_matrix).all()):
                    raise ValueError('Shot camera matrices must be finite')
            return shot
        except (KeyError, TypeError, OverflowError, FloatingPointError) as exc:
            raise ValueError('Invalid shot_camera: {}'.format(exc)) from exc

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
    clean.lighting_mode = 'Scene'
    target.resize(*camera.size, samples=camera.samples)
    target.bind()
    gl.glDisable(gl.GL_SCISSOR_TEST)
    gl.glDepthMask(True)
    renderer.resize(*camera.size)
    multisample = bool(gl.glIsEnabled(gl.GL_MULTISAMPLE))
    try:
        gl.glEnable(gl.GL_MULTISAMPLE)
        renderer.render(clean, camera)
        target.resolve()
    finally:
        if not multisample:
            gl.glDisable(gl.GL_MULTISAMPLE)


def capture_png(scene, camera, renderer, path):
    import pygame
    from OpenGL import GL as gl
    from .render_target import RenderTarget

    read_framebuffer = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    draw_framebuffer = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
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
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read_framebuffer)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, draw_framebuffer)
        gl.glViewport(*viewport)
