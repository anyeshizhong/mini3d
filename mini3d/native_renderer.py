"""Shared native scene renderer borrowing the editor's GL context.

Scene resources cross the boundary when edited; camera motion reuses them.
Python retains the existing UI, lens controls, depth post-process and PNG writer.
"""
import copy
import ctypes
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import time

import numpy as np


class NativeRenderError(ValueError):
    pass


def backend_policy(workspace):
    """Workspace overrides preserve existing Shot settings; native is strict."""
    if workspace not in ('arrange', 'shot'):
        raise ValueError('Unknown render workspace: ' + str(workspace))
    variable = 'MINI3D_PHOTO_BACKEND' if workspace == 'shot' else 'MINI3D_ARRANGE_BACKEND'
    mode = os.environ.get(variable, os.environ.get('MINI3D_RENDER_BACKEND', 'auto')).lower()
    if mode not in ('auto', 'native', 'python'):
        raise ValueError(variable + ' must be auto, native or python')
    required = (mode == 'native' or os.environ.get('MINI3D_REQUIRE_NATIVE_RENDER') == '1' or
                (workspace == 'shot' and os.environ.get('MINI3D_REQUIRE_NATIVE_PHOTO') == '1'))
    if required and mode == 'python':
        raise NativeRenderError('Python backend conflicts with required native rendering')
    return mode, required


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


class NativeSceneRenderer:
    def __init__(self, owner):
        self.owner = owner
        self.root = Path(__file__).resolve().parents[1] / 'native'
        self.library = None
        self.handle = None
        self.resource_key = self.parameter_key = self.failed_key = None
        self.scene_revision = self.failed_scene_revision = None
        self.last_reason = None
        self.bundle_builds = self.parameter_updates = self.frames = 0
        self.size = None
        self.directory = None
        self.last_camera = None
        self.entity_bindings = []
        self.entity_matrices = []
        self.transform_updates = 0
        self._messages = set()
        self._preparation = None
        self._preparing_key = None
        self.preparation_message = None

    def _load(self):
        if self.library is not None:
            return
        library = ctypes.CDLL(str(self.root / 'spqr_photo.dll'))
        pointer = ctypes.c_void_p
        doubles = ctypes.POINTER(ctypes.c_double)
        library.spqr_photo_abi_version.restype = ctypes.c_uint32
        library.spqr_photo_abi_version.argtypes = []
        if library.spqr_photo_abi_version() != 1:
            raise NativeRenderError('Unsupported native photo ABI')
        library.spqr_photo_last_error.restype = ctypes.c_char_p
        library.spqr_photo_last_error.argtypes = []
        library.spqr_photo_create.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        library.spqr_photo_create.restype = pointer
        shared_create = getattr(library, 'spqr_photo_create_shared', None)
        if shared_create is None:
            raise NativeRenderError('Rebuild spqr_photo.dll: shared texture API is missing')
        shared_create.argtypes = library.spqr_photo_create.argtypes
        shared_create.restype = pointer
        transforms = getattr(library, 'spqr_photo_transforms', None)
        if transforms is None:
            raise NativeRenderError('Rebuild spqr_photo.dll: transform update API is missing')
        uints = ctypes.POINTER(ctypes.c_uint32)
        transforms.argtypes = [pointer, uints, doubles, ctypes.POINTER(ctypes.c_float), uints, ctypes.c_size_t]
        transforms.restype = ctypes.c_int
        library.spqr_photo_resize.argtypes = [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        library.spqr_photo_resize.restype = ctypes.c_int
        library.spqr_photo_globals.argtypes = [pointer, pointer, ctypes.c_size_t, doubles,
                                               ctypes.c_uint32, ctypes.c_float, ctypes.c_int, ctypes.c_double]
        library.spqr_photo_globals.restype = ctypes.c_int
        library.spqr_photo_render.argtypes = [pointer, doubles, ctypes.c_uint32, doubles]
        library.spqr_photo_render.restype = ctypes.c_int
        library.spqr_photo_destroy.argtypes = [pointer]
        library.spqr_photo_destroy.restype = ctypes.c_int
        begin = getattr(library, 'spqr_photo_begin_shared', None)
        step = getattr(library, 'spqr_photo_prepare_step', None)
        if begin is not None and step is not None:
            begin.argtypes = library.spqr_photo_create.argtypes
            begin.restype = pointer
            step.argtypes = [pointer, ctypes.POINTER(ctypes.c_int)]
            step.restype = ctypes.c_int
        self.library = library

    def _check(self, result):
        if not result:
            message = self.library.spqr_photo_last_error()
            raise NativeRenderError(message.decode('utf8', 'replace') if message else 'Native render operation failed')
        return result

    def _keys(self, scene, camera=None):
        from .scene_snapshot import snapshot
        from .atmosphere import atmosphere_state
        source = getattr(scene, '_render_source', getattr(scene, '_native_photo_source', scene))
        geometry = snapshot(source)
        self.scene_revision = geometry.geometry_revision
        atmosphere = atmosphere_state(scene)
        # Material revision also covers render-list membership/order and mesh
        # identity/bounds. World matrices travel through the instance-update API.
        resource = (id(source), id(geometry), geometry.material_revision,
                    atmosphere['enabled'], atmosphere['ground'], atmosphere['ground_texture'],
                    atmosphere['sky_texture'], bool(getattr(scene, 'environment_enabled', False)),
                    getattr(scene, 'render_mode', 'Lit'))
        parameters = tuple(_value(getattr(scene, name, None)) for name in (
            'light_dir', 'ambient', 'diffuse', 'lighting_mode', 'shadows_enabled',
            'shadow_resolution', 'shadow_bias', 'shadow_pcf', 'environment_enabled',
            'environment_intensity', 'material_light_intensity', 'material_ambient_intensity',
            '_atmosphere', '_photo_color'))
        # Studio lights are camera-relative; Scene lights remain world-relative.
        if getattr(scene, 'lighting_mode', 'Studio') == 'Studio' and camera is not None:
            parameters += (_value(camera.rotation),)
        return resource, parameters

    def _sync_transforms(self):
        from .geometry_cache import normal_transform
        changed, worlds, normals, mirrored, keys = [], [], [], [], []
        cache = {}
        for index, entity in enumerate(self.entity_bindings):
            if entity is None:
                continue
            world = np.asarray(entity.world_matrix, dtype=np.float64)
            if world.shape != (4, 4) or not np.isfinite(world).all():
                raise NativeRenderError('Invalid entity world matrix during transform update')
            key = world.tobytes()
            if key == self.entity_matrices[index]:
                continue
            normal, mirror = normal_transform(world, cache)
            changed.append(index)
            worlds.append(world)
            normals.append(normal)
            mirrored.append(mirror)
            keys.append(key)
        if not changed:
            return
        indices = np.ascontiguousarray(changed, dtype=np.uint32)
        matrices = np.ascontiguousarray(worlds, dtype=np.float64)
        normal_matrices = np.ascontiguousarray(normals, dtype=np.float32)
        winding = np.ascontiguousarray(mirrored, dtype=np.uint32)
        uints = ctypes.POINTER(ctypes.c_uint32)
        self._check(self.library.spqr_photo_transforms(self.handle,
            indices.ctypes.data_as(uints), matrices.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            normal_matrices.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            winding.ctypes.data_as(uints), len(changed)))
        for index, key in zip(changed, keys):
            self.entity_matrices[index] = key
        self.transform_updates += 1

    def cancel_preparation(self):
        if self._preparation is not None:
            with preserved_native_state():
                self._preparation.close()
            self._preparation = None
        self._preparing_key = None
        self.preparation_message = None

    def _prepare_resources(self, scene, camera, size, samples, resource):
        """One GL job per yield, always resumed with the owning context current."""
        from . import native_photo_bundle as bundle
        if not hasattr(self.owner, 'material_renderer'):
            from .material_renderer import MaterialRenderer
            self.owner.material_renderer = MaterialRenderer()
            yield 'Material shader ready'
        if not hasattr(self.owner, 'sky_renderer'):
            from .sky_renderer import SkyRenderer
            self.owner.sky_renderer = SkyRenderer()
            yield 'Sky shader ready'
        prepared, ground, atmosphere = bundle._prepare_photo_scene(scene, camera, self.owner)
        rows = bundle._flatten_or_raise(bundle._export_helpers(), prepared, ground)
        yield 'Scene validated'
        seen = set()
        material = self.owner.material_renderer
        for row in rows:
            for texture in row['material'].get('textures', {}).values():
                key = (id(texture['image']), tuple(sorted(texture.get('sampler', {}).items())))
                if key not in seen:
                    seen.add(key)
                    material._texture(texture)
                    yield 'Preparing material textures'
        bundle._collect_globals_prepared(prepared, camera, self.owner, atmosphere)
        yield 'Lighting resources ready'
        runtime = self.root.parent / '.runtime'
        runtime.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix='native-scene-', dir=str(runtime))
        handle = None
        try:
            exported = bundle.export_live_bundle(scene, camera, self.owner, Path(directory.name),
                                                 self.root, shared_textures=True)
            # Transform changes during later GL jobs must still reach C++.
            # These keys describe the exported bundle, not the eventual live scene.
            exported_matrices = [None if entity is None else
                np.asarray(entity.world_matrix, dtype=np.float64).tobytes()
                for entity in exported['entity_bindings']]
            yield 'Native scene bundle ready'
            handle = self._check(self.library.spqr_photo_begin_shared(directory.name, *size, samples))
            yield 'Native scene loaded'
            ready = ctypes.c_int()
            while not ready.value:
                self._check(self.library.spqr_photo_prepare_step(handle, ctypes.byref(ready)))
                yield 'Preparing native GPU resources'
            if self.handle:
                self._check(self.library.spqr_photo_destroy(self.handle))
            if self.directory:
                self.directory.cleanup()
            self.handle, handle = handle, None
            self.directory, directory = directory, None
            self.entity_bindings = exported['entity_bindings']
            self.entity_matrices = exported_matrices
            self.resource_key, self.parameter_key = resource, None
            self.size = (*size, samples)
            self.bundle_builds += 1
        finally:
            if handle:
                self._check(self.library.spqr_photo_destroy(handle))
            if directory:
                directory.cleanup()

    def prepare_step(self, scene, camera, size, samples=1, *, workspace='arrange', budget_seconds=0):
        """Advance initialization within an optional time budget; do not render."""
        mode, required = backend_policy(workspace)
        resource, parameters = self._keys(scene, camera)
        if mode == 'python' or getattr(scene, 'render_mode', 'Lit').lower() == 'wireframe':
            self.cancel_preparation()
            return True
        failure_key = (resource, parameters, tuple(size), samples)
        if resource == self.resource_key or (self.failed_key == failure_key and
                                             self.failed_scene_revision == self.scene_revision):
            self.cancel_preparation()
            return True
        if resource != self._preparing_key:
            self.cancel_preparation()
        try:
            with preserved_native_state():
                self._load()
                if not all(hasattr(self.library, name) for name in ('spqr_photo_begin_shared', 'spqr_photo_prepare_step')):
                    # Legacy DLLs retain their synchronous, supported path.
                    return True
                if self._preparation is None:
                    self._preparing_key = resource
                    self._preparation = self._prepare_resources(scene, camera, tuple(size), samples, resource)
                deadline = time.perf_counter() + max(0, budget_seconds)
                # Cold driver operations may exceed the budget. Warm cached jobs
                # share one frame instead of each adding another 60 Hz delay.
                for _ in range(64):
                    self.preparation_message = next(self._preparation)
                    if time.perf_counter() >= deadline:
                        break
            return False
        except StopIteration:
            self._preparation = None
            self._preparing_key = None
            self.preparation_message = None
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            self.cancel_preparation()
            if required:
                raise NativeRenderError(str(exc)) from exc
            self.failed_key = failure_key
            self.failed_scene_revision = self.scene_revision
            self.last_reason = str(exc)
            return True

    def render(self, scene, camera, target, size, samples, *, workspace='shot', required=None):
        """Return False only with a reported fallback; never show a stale native scene."""
        from OpenGL import GL as gl
        from .native_photo_bundle import export_live_bundle, collect_live_globals, pack_globals
        from .atmosphere import atmosphere_state
        from .lighting import scene_light_direction
        if required is None:
            _mode, required = backend_policy(workspace)
        self.cancel_preparation()
        resource, parameters = self._keys(scene, camera)
        failure_key = (resource, parameters, tuple(size), samples)
        if self.failed_key == failure_key and self.failed_scene_revision == self.scene_revision:
            if required:
                raise NativeRenderError(self.last_reason)
            return False
        try:
            with preserved_native_state():
                self._load()
                if resource != self.resource_key:
                    runtime = self.root.parent / '.runtime'
                    runtime.mkdir(exist_ok=True)
                    directory = tempfile.TemporaryDirectory(prefix='native-scene-', dir=str(runtime))
                    try:
                        exported = export_live_bundle(scene, camera, self.owner, Path(directory.name), self.root,
                                                      shared_textures=True)
                        handle = self._check(self.library.spqr_photo_create_shared(directory.name, *size, samples))
                    except BaseException:
                        directory.cleanup()
                        raise
                    if self.handle:
                        self._check(self.library.spqr_photo_destroy(self.handle))
                    if self.directory:
                        self.directory.cleanup()
                    self.handle, self.directory = handle, directory
                    self.entity_bindings = exported['entity_bindings']
                    self.entity_matrices = [None if entity is None else
                        np.asarray(entity.world_matrix, dtype=np.float64).tobytes()
                        for entity in self.entity_bindings]
                    self.resource_key, self.parameter_key = resource, None
                    self.size = (*size, samples)
                    self.bundle_builds += 1
                self._sync_transforms()
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
                        int(bool(getattr(scene, 'shadows_enabled', False)) and
                            getattr(scene, 'lighting_mode', 'Studio') == 'Scene' and
                            getattr(scene, 'render_mode', 'Lit').lower() == 'lit'),
                        atmosphere_state(scene)['ground_z']))
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
            self.owner.last_render_plan = None
            self.owner.render_stats = dict(backend='native-photo' if workspace == 'shot' else 'native-arrange',
                workspace=workspace, color_draw_calls=int(stats[2]),
                shadow_draw_calls=int(stats[3]), color_triangles=int(stats[4]), shadow_triangles=int(stats[5]),
                draw_calls=int(stats[2] + stats[3]), submitted_triangles=int(stats[4] + stats[5]),
                native_bundle_builds=self.bundle_builds, native_parameter_updates=self.parameter_updates,
                native_transform_updates=self.transform_updates,
                native_frames=self.frames, effective_near=float(stats[0]), samples=samples,
                shadow_mode='stable-near-4096-plus-far', width=size[0], height=size[1])
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            if required:
                raise NativeRenderError(str(exc)) from exc
            self.failed_key = failure_key
            self.failed_scene_revision = self.scene_revision
            self.last_reason = str(exc)
            if self.last_reason not in self._messages:
                print('Native scene unavailable; using Python renderer: ' + self.last_reason, flush=True)
                self._messages.add(self.last_reason)
            return False

    def close(self):
        self.cancel_preparation()
        if self.handle:
            with preserved_native_state():
                self._check(self.library.spqr_photo_destroy(self.handle))
            self.handle = None
        if self.directory:
            self.directory.cleanup()
            self.directory = None
        self.resource_key = self.parameter_key = self.failed_key = None
        self.scene_revision = self.failed_scene_revision = None
        self.size = self.last_camera = None
        self.entity_bindings = []
        self.entity_matrices = []


def scene_backend(renderer, workspace='shot'):
    mode, required = backend_policy(workspace)
    if mode == 'python':
        return None
    if os.name != 'nt':
        if required:
            raise NativeRenderError('Native rendering requires Windows/WGL')
        return None
    root = Path(__file__).resolve().parents[1] / 'native'
    if mode == 'auto' and not required and not (root / 'spqr_photo.dll').is_file():
        return None
    if not hasattr(renderer, 'native_renderer'):
        renderer.native_renderer = NativeSceneRenderer(renderer)
        # Existing diagnostics and integrations keep referencing the same owner.
        renderer.native_photo = renderer.native_renderer
    return renderer.native_renderer
