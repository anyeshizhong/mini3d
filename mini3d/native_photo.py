"""One native render call per Shot frame, borrowing the editor's GL context.

Scene resources cross the boundary when edited; camera motion reuses them.
Python retains the existing UI, lens controls, depth post-process and PNG writer.
"""
import copy
import ctypes
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

import numpy as np


class NativePhotoError(ValueError):
    pass


@contextmanager
def preserved_native_state():
    from OpenGL import GL as gl
    from .gl_state import save_state, restore_state, preserved_pixel_pack
    state = save_state(texture_units=15, all_cubemaps=True)
    read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    draw = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
    read_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))
    draw_buffer = int(gl.glGetIntegerv(gl.GL_DRAW_BUFFER))
    viewport = np.array(gl.glGetIntegerv(gl.GL_VIEWPORT))
    renderbuffer = int(gl.glGetIntegerv(gl.GL_RENDERBUFFER_BINDING))
    multisample = bool(gl.glIsEnabled(gl.GL_MULTISAMPLE))
    clear_color = np.array(gl.glGetFloatv(gl.GL_COLOR_CLEAR_VALUE))
    clear_depth = float(gl.glGetDoublev(gl.GL_DEPTH_CLEAR_VALUE))
    depth_range = np.array(gl.glGetDoublev(gl.GL_DEPTH_RANGE))
    unpack_names = ('ALIGNMENT', 'ROW_LENGTH', 'SKIP_ROWS', 'SKIP_PIXELS',
                    'IMAGE_HEIGHT', 'SKIP_IMAGES', 'SWAP_BYTES', 'LSB_FIRST')
    unpack = {name: int(gl.glGetIntegerv(getattr(gl, 'GL_UNPACK_' + name)))
              for name in unpack_names}
    unpack_buffer = int(gl.glGetIntegerv(gl.GL_PIXEL_UNPACK_BUFFER_BINDING))
    try:
        with preserved_pixel_pack(reset=True):
            gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, 0)
            for name in unpack_names:
                gl.glPixelStorei(getattr(gl, 'GL_UNPACK_' + name), 1 if name == 'ALIGNMENT' else 0)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            yield
    finally:
        for name, value in unpack.items():
            gl.glPixelStorei(getattr(gl, 'GL_UNPACK_' + name), value)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER, unpack_buffer)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read)
        gl.glReadBuffer(read_buffer)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, draw)
        gl.glDrawBuffer(draw_buffer)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, renderbuffer)
        gl.glViewport(*viewport)
        gl.glClearColor(*clear_color)
        gl.glClearDepth(clear_depth)
        gl.glDepthRange(*depth_range)
        (gl.glEnable if multisample else gl.glDisable)(gl.GL_MULTISAMPLE)
        restore_state(state)


def _value(value):
    from .viewport_cache import _value as detached
    return detached(value)


class NativePhotoRenderer:
    def __init__(self, owner):
        self.owner = owner
        self.root = Path(__file__).resolve().parents[1] / 'native'
        self.library = None
        self.handle = None
        self.resource_key = self.parameter_key = self.failed_key = None
        self.last_reason = None
        self.bundle_builds = self.parameter_updates = self.frames = 0
        self.size = None
        self.directory = None
        self.last_camera = None
        self._messages = set()

    def _load(self):
        if self.library is not None:
            return
        library = ctypes.CDLL(str(self.root / 'spqr_photo.dll'))
        pointer = ctypes.c_void_p
        doubles = ctypes.POINTER(ctypes.c_double)
        library.spqr_photo_abi_version.restype = ctypes.c_uint32
        library.spqr_photo_abi_version.argtypes = []
        if library.spqr_photo_abi_version() != 1:
            raise NativePhotoError('Unsupported native photo ABI')
        library.spqr_photo_last_error.restype = ctypes.c_char_p
        library.spqr_photo_last_error.argtypes = []
        library.spqr_photo_create.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        library.spqr_photo_create.restype = pointer
        library.spqr_photo_resize.argtypes = [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        library.spqr_photo_resize.restype = ctypes.c_int
        library.spqr_photo_globals.argtypes = [pointer, pointer, ctypes.c_size_t, doubles,
                                               ctypes.c_uint32, ctypes.c_float, ctypes.c_int, ctypes.c_double]
        library.spqr_photo_globals.restype = ctypes.c_int
        library.spqr_photo_render.argtypes = [pointer, doubles, ctypes.c_uint32, doubles]
        library.spqr_photo_render.restype = ctypes.c_int
        library.spqr_photo_destroy.argtypes = [pointer]
        library.spqr_photo_destroy.restype = ctypes.c_int
        self.library = library

    def _check(self, result):
        if not result:
            message = self.library.spqr_photo_last_error()
            raise NativePhotoError(message.decode('utf8', 'replace') if message else 'Native photo operation failed')
        return result

    def _keys(self, scene):
        from .scene_snapshot import snapshot
        from .atmosphere import atmosphere_state
        source = getattr(scene, '_native_photo_source', scene)
        geometry = snapshot(source)
        atmosphere = atmosphere_state(scene)
        resource = (id(source), id(geometry), geometry.geometry_revision, geometry.material_revision,
                    atmosphere['enabled'], atmosphere['ground'], atmosphere['ground_texture'],
                    atmosphere['sky_texture'], bool(getattr(scene, 'environment_enabled', False)))
        parameters = tuple(_value(getattr(scene, name, None)) for name in (
            'light_dir', 'ambient', 'diffuse', 'lighting_mode', 'shadows_enabled',
            'shadow_resolution', 'shadow_bias', 'shadow_pcf', 'environment_enabled',
            'environment_intensity', 'material_light_intensity', 'material_ambient_intensity',
            '_atmosphere', '_photo_color'))
        return resource, parameters

    def render(self, scene, camera, target, size, samples):
        """Return False only with a reported fallback; never show a stale native scene."""
        from OpenGL import GL as gl
        from .native_photo_bundle import export_live_bundle, collect_live_globals, pack_globals
        from .atmosphere import atmosphere_state
        from .lighting import scene_light_direction
        resource, parameters = self._keys(scene)
        failure_key = (resource, parameters, tuple(size), samples)
        if self.failed_key == failure_key:
            return False
        try:
            with preserved_native_state():
                self._load()
                if resource != self.resource_key:
                    runtime = self.root.parent / '.runtime'
                    runtime.mkdir(exist_ok=True)
                    directory = tempfile.TemporaryDirectory(prefix='native-photo-', dir=str(runtime))
                    try:
                        export_live_bundle(scene, camera, self.owner, Path(directory.name),
                                           self.root.parent / 'spqr-native')
                        handle = self._check(self.library.spqr_photo_create(directory.name, *size, samples))
                    except BaseException:
                        directory.cleanup()
                        raise
                    if self.handle:
                        self._check(self.library.spqr_photo_destroy(self.handle))
                    if self.directory:
                        self.directory.cleanup()
                    self.handle, self.directory = handle, directory
                    self.resource_key, self.parameter_key = resource, None
                    self.size = (*size, samples)
                    self.bundle_builds += 1
                if self.size != (*size, samples):
                    self._check(self.library.spqr_photo_resize(self.handle, *size, samples))
                    self.size = (*size, samples)
                if parameters != self.parameter_key:
                    records = collect_live_globals(scene, camera, self.owner)
                    payload = pack_globals(*records)
                    buffer = ctypes.create_string_buffer(payload)
                    direction = np.ascontiguousarray(scene_light_direction(scene), dtype=np.float64)
                    self._check(self.library.spqr_photo_globals(
                        self.handle, buffer, len(payload), direction.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                        int(getattr(scene, 'shadow_resolution', 2048)), float(getattr(scene, 'shadow_bias', .0003)),
                        int(bool(getattr(scene, 'shadows_enabled', False))), atmosphere_state(scene)['ground_z']))
                    self.parameter_key = parameters
                    self.parameter_updates += 1
                values = np.ascontiguousarray(np.concatenate((
                    np.asarray(camera.position).reshape(-1), np.asarray(camera.rotation).reshape(-1),
                    np.asarray(camera.view_matrix).reshape(-1),
                    np.asarray(camera.projection_matrix(size[0] / size[1])).reshape(-1),
                    [camera.near, camera.far])), dtype=np.float64)
                stats = np.zeros(8, dtype=np.float64)
                self._check(self.library.spqr_photo_render(self.handle,
                    values.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), int(target.framebuffer),
                    stats.ctypes.data_as(ctypes.POINTER(ctypes.c_double))))
            self.last_camera = copy.copy(camera)
            self.last_camera.near = float(stats[0])
            self.last_camera.far = float(stats[1])
            target.render_camera = self.last_camera
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target.framebuffer)
            gl.glViewport(0, 0, *size)
            self.frames += 1
            self.last_reason = None
            self.owner.render_stats = dict(backend='native-photo', color_draw_calls=int(stats[2]),
                shadow_draw_calls=int(stats[3]), color_triangles=int(stats[4]), shadow_triangles=int(stats[5]),
                draw_calls=int(stats[2] + stats[3]), submitted_triangles=int(stats[4] + stats[5]),
                native_bundle_builds=self.bundle_builds, native_parameter_updates=self.parameter_updates,
                native_frames=self.frames, effective_near=float(stats[0]), samples=samples,
                shadow_mode='stable-near-4096-plus-far', width=size[0], height=size[1])
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            if os.environ.get('MINI3D_REQUIRE_NATIVE_PHOTO') == '1':
                raise NativePhotoError(str(exc)) from exc
            self.failed_key = failure_key
            self.last_reason = str(exc)
            if self.last_reason not in self._messages:
                print('Native photo unavailable; using existing renderer: ' + self.last_reason, flush=True)
                self._messages.add(self.last_reason)
            return False

    def close(self):
        if self.handle:
            with preserved_native_state():
                self._check(self.library.spqr_photo_destroy(self.handle))
            self.handle = None
        if self.directory:
            self.directory.cleanup()
            self.directory = None


def photo_backend(renderer):
    mode = os.environ.get('MINI3D_PHOTO_BACKEND', 'auto').lower()
    if mode == 'python':
        return None
    if mode not in ('auto', 'native'):
        raise ValueError('MINI3D_PHOTO_BACKEND must be auto, native or python')
    if os.name != 'nt':
        return None
    root = Path(__file__).resolve().parents[1] / 'native'
    if mode == 'auto' and not (root / 'spqr_photo.dll').is_file():
        return None
    if not hasattr(renderer, 'native_photo'):
        renderer.native_photo = NativePhotoRenderer(renderer)
    return renderer.native_photo
