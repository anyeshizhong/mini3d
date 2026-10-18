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
        self.dof_enabled = False
        self.focus_distance = 5.0
        self.f_number = 2.8
        self.focus_point = None
        self.white_balance_kelvin = 6500.
        self.color_preset = 'Original'

    def set_photo_color(self, white_balance_kelvin=None, preset=None):
        from .photo_color import validate_color
        temperature = self.white_balance_kelvin if white_balance_kelvin is None else white_balance_kelvin
        style = self.color_preset if preset is None else preset
        self.white_balance_kelvin, self.color_preset = validate_color(temperature, style)

    def set_depth_of_field(self, enabled=None, focus_distance=None, f_number=None):
        """Atomic lens settings. Scene distances use metres for photography."""
        enabled = self.dof_enabled if enabled is None else enabled
        focus = self.focus_distance if focus_distance is None else focus_distance
        aperture = self.f_number if f_number is None else f_number
        if not isinstance(enabled, bool):
            raise ValueError('Depth of field enabled must be boolean')
        for name, value, low, high in (('focus_distance', focus, .1, 1e6),
                                       ('f_number', aperture, .7, 64)):
            if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                    or not low <= value <= high or not math.isfinite(value)):
                raise ValueError('{} must be finite and between {} and {}'.format(name, low, high))
        if enabled and focus <= self.focal_mm / 1000:
            raise ValueError('Focus distance must exceed focal length')
        self.dof_enabled, self.focus_distance, self.f_number = enabled, float(focus), float(aperture)
        if focus_distance is not None:
            self.focus_point = None

    def focus_at(self, point):
        raw = np.asarray(point, dtype=object)
        if raw.shape != (3,) or any(isinstance(v, (bool, np.bool_)) or
                not isinstance(v, Real) for v in raw.flat):
            raise ValueError('Focus point must be three finite numbers')
        point = np.asarray(raw, dtype=float)
        if not np.isfinite(point).all():
            raise ValueError('Focus point must be three finite numbers')
        depth = -float((self.view_matrix @ np.r_[point, 1])[2])
        self.set_depth_of_field(focus_distance=depth)
        self.focus_point = point.copy()
        return self.focus_distance

    def circle_of_confusion(self, depth, width=None):
        """Signed thin-lens blur radius in pixels (negative in front of focus)."""
        depth = np.asarray(depth, dtype=float)
        if not np.isfinite(depth).all() or np.any(depth <= 0):
            raise ValueError('Depth must be positive and finite')
        focal = self.focal_mm / 1000
        scale = .5 * (self.size[0] if width is None else width) * focal**2
        return scale * (depth - self.focus_distance) / (
            self.f_number * .036 * depth * max(self.focus_distance - focal, 1e-6))

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
        if (isinstance(focal_mm, (bool, np.bool_)) or not isinstance(focal_mm, Real)
                or not math.isfinite(focal_mm)):
            raise ValueError('Choose 24mm, 35mm, 50mm or 85mm')
        preset = next((value for value in (24, 35, 50, 85)
                       if math.isclose(focal_mm, value, rel_tol=0, abs_tol=1e-6)), None)
        if preset is None:
            raise ValueError('Choose 24mm, 35mm, 50mm or 85mm')
        self._set_focal(preset)

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
                    near=self.near, far=self.far, samples=self.samples,
                    dof_enabled=self.dof_enabled, focus_distance=self.focus_distance,
                    f_number=self.f_number, focus_point=None if self.focus_point is None else self.focus_point.tolist(),
                    white_balance_kelvin=self.white_balance_kelvin, color_preset=self.color_preset)

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
                if any(name in data and data[name] is None for name in
                       ('dof_enabled', 'focus_distance', 'f_number')):
                    raise ValueError('Depth of field parameters cannot be null')
                shot.set_depth_of_field(enabled=data.get('dof_enabled', False),
                    focus_distance=data.get('focus_distance', 5.0),
                    f_number=data.get('f_number', 2.8))
                if any(name in data and data[name] is None for name in ('white_balance_kelvin', 'color_preset')):
                    raise ValueError('Photo color parameters cannot be null')
                shot.set_photo_color(data.get('white_balance_kelvin', 6500.), data.get('color_preset', 'Original'))
                if data.get('focus_point') is not None:
                    stored_distance = shot.focus_distance
                    shot.focus_at(data['focus_point'])
                    if not math.isclose(shot.focus_distance, stored_distance, rel_tol=1e-6, abs_tol=1e-6):
                        raise ValueError('Focus point must match saved focus distance')
                    shot.focus_distance = stored_distance
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
    render_scene_view(scene, camera, renderer, target, camera.size, camera.samples)


def prepare_scene_view(scene, camera, photo_camera=None):
    """Build the identical clean scene for staged preparation and rendering."""
    clean = copy.copy(scene)
    clean._render_source = scene
    clean.show_grid, clean.show_axes, clean.render_mode = False, False, 'Lit'
    clean._hide_entity_axes = True
    clean.lighting_mode = 'Scene'
    settings_camera = camera if photo_camera is None else photo_camera
    clean._photo_color = (getattr(settings_camera, 'white_balance_kelvin', 6500.),
                          getattr(settings_camera, 'color_preset', 'Original'))
    return clean


def render_scene_view(scene, camera, renderer, target, size, samples=1, photo_camera=None):
    """Clean Scene-lit preview, shared by both views in the Shot workspace."""
    clean = prepare_scene_view(scene, camera, photo_camera)
    from .scene_renderer import render_scene
    render_scene(clean, camera, renderer, target, size, samples, workspace='shot')
    if getattr(camera, 'dof_enabled', False):
        if not hasattr(renderer, 'depth_of_field'):
            from .depth_of_field import DepthOfField
            renderer.depth_of_field = DepthOfField()
        renderer.depth_of_field.apply(target, target.render_camera)


def capture_png(scene, camera, renderer, path):
    from .gl_state import preserved_pixel_pack
    with preserved_pixel_pack():
        return _capture_png(scene, camera, renderer, path)


def _capture_png(scene, camera, renderer, path):
    import io
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
        from .gl_state import read_rgb
        pixels = read_rgb(0, 0, *camera.size)
        picture = pygame.image.fromstring(pixels, camera.size, 'RGB', True)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Encode fully before exposing the destination to previews/file watchers.
        output=io.BytesIO()
        pygame.image.save(picture,output,'capture.png')
        payload=output.getvalue()
        if not payload.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82'):
            raise OSError('PNG encoder returned incomplete data')
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_bytes(payload)
        temporary.replace(path)
        return path
    finally:
        target.close()
        renderer.resize(*old_size)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read_framebuffer)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, draw_framebuffer)
        gl.glViewport(*viewport)
