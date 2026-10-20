"""ctypes client for the opt-in terrain_lab DLL (not the production ABI)."""
import ctypes as C
from pathlib import Path

import numpy as np


_FRAME_STATS_FIELDS = (
    'input_near', 'color_near', 'color_draws', 'shadow_draws',
    'color_triangles', 'shadow_triangles',
    'near_shadow_depth_span', 'far_shadow_depth_span',
)
_FRAME_STATS_INTEGER_FIELDS = frozenset((
    'color_draws', 'shadow_draws', 'color_triangles', 'shadow_triangles',
))


class NativeTerrain:
    def __init__(self, library, bundle, width=1081, height=662):
        self.dll = C.CDLL(str(Path(library).resolve()))
        u32p, f32p = C.POINTER(C.c_uint32), C.POINTER(C.c_float)
        u64p = C.POINTER(C.c_uint64)
        f64p = C.POINTER(C.c_double)
        u8p = C.POINTER(C.c_uint8)
        signatures = {
            'lab_error': ([], C.c_char_p),
            'lab_create': ([C.c_char_p, C.c_int, C.c_int], C.c_void_p),
            'lab_destroy': ([C.c_void_p], C.c_int),
            'lab_render': ([C.c_void_p, C.c_uint32], C.c_int),
            'lab_enable_gpu_timing': ([C.c_void_p, C.c_int], C.c_int),
            'lab_poll_gpu_timing': ([C.c_void_p, C.c_uint32, u32p, u64p, f64p, u8p,
                                     u32p], C.c_int),
            'lab_capture': ([C.c_void_p, C.c_char_p, C.c_uint32], C.c_int),
            'lab_capture_color': ([C.c_void_p, C.c_char_p], C.c_int),
            'lab_compile_count': ([C.c_void_p], C.c_uint32),
            'lab_mesh_count': ([C.c_void_p], C.c_uint32),
            'lab_entity_mesh_id': ([C.c_void_p, C.c_uint32], C.c_int32),
            'lab_entity_texture_id': ([C.c_void_p, C.c_uint32, C.c_uint32], C.c_int32),
            'lab_mesh_vertex_count': ([C.c_void_p, C.c_uint32], C.c_int),
            'lab_update_batch': ([C.c_void_p, u32p, u32p, f32p, C.c_uint32], C.c_int),
            'lab_read_mesh_vertices': ([C.c_void_p, C.c_uint32, f32p, C.c_uint32], C.c_int),
            'lab_texture_info': ([C.c_void_p, C.c_uint32, u32p, u32p], C.c_int),
            'lab_update_texture_batch': ([C.c_void_p, u32p, u32p, u8p, C.c_uint32], C.c_int),
            'lab_read_texture_rgba8': ([C.c_void_p, C.c_uint32, u8p, C.c_uint64], C.c_int),
            'lab_update_count': ([C.c_void_p], C.c_uint64),
            'lab_uploaded_bytes': ([C.c_void_p], C.c_uint64),
            'lab_texture_update_count': ([C.c_void_p], C.c_uint64),
            'lab_texture_uploaded_bytes': ([C.c_void_p], C.c_uint64),
            'lab_renderer_name': ([C.c_void_p], C.c_char_p),
            'lab_gl_version': ([C.c_void_p], C.c_char_p),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes, function.restype = arguments, result
        self._frame_stats = getattr(self.dll, 'lab_frame_stats', None)
        if self._frame_stats is not None:
            self._frame_stats.argtypes = [C.c_void_p, f64p, C.c_uint32]
            self._frame_stats.restype = C.c_int
        self.handle = self.dll.lab_create(str(Path(bundle).resolve()).encode('utf-8'), width, height)
        if not self.handle:
            raise RuntimeError(self.error())

    def error(self):
        return (self.dll.lab_error() or b'unknown terrain lab error').decode('utf-8', 'replace')

    def check(self, result):
        if result != 1:
            raise RuntimeError(self.error())

    def close(self):
        if self.handle:
            self.check(self.dll.lab_destroy(self.handle))
            self.handle = None

    def render(self, frame=168):
        self.check(self.dll.lab_render(self.handle, frame))

    def frame_stats(self):
        """Return the last rendered frame's near/depth and draw statistics."""
        if self._frame_stats is None:
            raise RuntimeError(
                'terrain_lab DLL does not export optional lab_frame_stats; '
                'frame statistics require a rebuilt experiment DLL'
            )
        values = np.empty(len(_FRAME_STATS_FIELDS), dtype=np.float64)
        self.check(self._frame_stats(
            self.handle, values.ctypes.data_as(C.POINTER(C.c_double)), len(values)))
        return {
            name: int(value) if name in _FRAME_STATS_INTEGER_FIELDS else float(value)
            for name, value in zip(_FRAME_STATS_FIELDS, values)
        }

    def enable_gpu_timing(self, enabled):
        """Opt in to async Terrain color-draw GPU timestamps for subsequent renders."""
        if not isinstance(enabled, bool):
            raise TypeError('enabled must be a bool')
        self.check(self.dll.lab_enable_gpu_timing(self.handle, int(enabled)))

    def poll_gpu_timing(self):
        """Return ready Terrain color-draw timestamps without waiting.

        Each value sums contiguous hasAO Terrain draw regions and excludes marker
        draws, sky, shadows, and resolve. It is not a pure shader/material cost;
        a ring-overflow or failed render is reported with ``dropped=True``.
        """
        capacity = 256
        frames = np.empty(capacity, dtype=np.uint32)
        sample_ids = np.empty(capacity, dtype=np.uint64)
        gpu_ms = np.empty(capacity, dtype=np.float64)
        dropped = np.empty(capacity, dtype=np.uint8)
        written = C.c_uint32()
        self.check(self.dll.lab_poll_gpu_timing(self.handle, capacity,
            frames.ctypes.data_as(C.POINTER(C.c_uint32)),
            sample_ids.ctypes.data_as(C.POINTER(C.c_uint64)),
            gpu_ms.ctypes.data_as(C.POINTER(C.c_double)),
            dropped.ctypes.data_as(C.POINTER(C.c_uint8)), C.byref(written)))
        return [dict(frame=int(frames[i]), sample_id=int(sample_ids[i]),
                     gpu_ms=float(gpu_ms[i]), dropped=bool(dropped[i]))
                for i in range(written.value)]

    def capture(self, stem, frame=168):
        stem = Path(stem).resolve()
        stem.parent.mkdir(parents=True, exist_ok=True)
        self.check(self.dll.lab_capture(self.handle, str(stem).encode('utf-8'), frame))

    def capture_color(self, path):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.check(self.dll.lab_capture_color(self.handle, str(path).encode('utf-8')))

    def mesh_id(self, entity_index):
        result = self.dll.lab_entity_mesh_id(self.handle, entity_index)
        if result < 0:
            raise RuntimeError(self.error())
        return result

    def texture_id(self, entity_index, slot):
        result = self.dll.lab_entity_texture_id(self.handle, entity_index, slot)
        if result < 0:
            raise RuntimeError(self.error())
        return result

    def texture_info(self, texture_id):
        width, height = C.c_uint32(), C.c_uint32()
        self.check(self.dll.lab_texture_info(self.handle, texture_id,
                   C.byref(width), C.byref(height)))
        return int(width.value), int(height.value)

    def read_texture(self, texture_id):
        """Return GL level-zero RGBA8 pixels in OpenGL's bottom-up row order."""
        width, height = self.texture_info(texture_id)
        data = np.empty((height, width, 4), dtype=np.uint8)
        self.check(self.dll.lab_read_texture_rgba8(self.handle, texture_id,
                   data.ctypes.data_as(C.POINTER(C.c_uint8)), data.nbytes))
        return data

    def update_textures(self, rows, *, check=True):
        """Upload rows of (texture_id, x, y, HxWx4 uint8 RGBA), with y=0 at GL's bottom row."""
        if not rows:
            return 1
        texture_ids, rects, payloads = [], [], []
        for texture_id, x, y, rgba in rows:
            texture_id, x, y = int(texture_id), int(x), int(y)
            if min(texture_id, x, y) < 0 or max(texture_id, x, y) > 0xffffffff:
                raise ValueError('Texture ID and rectangle origin must fit uint32')
            pixels = np.asarray(rgba)
            if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 4:
                raise ValueError('Expected an H by W by 4 uint8 RGBA array')
            pixels = np.ascontiguousarray(pixels)
            height, width = pixels.shape[:2]
            if width > 0xffffffff or height > 0xffffffff:
                raise ValueError('Texture update rectangle dimensions must fit uint32')
            texture_ids.append(texture_id)
            rects.append((x, y, width, height))
            payloads.append(pixels.reshape(-1))

        ids = np.ascontiguousarray(texture_ids, dtype=np.uint32)
        rects = np.ascontiguousarray(rects, dtype=np.uint32)
        payload = np.ascontiguousarray(np.concatenate(payloads), dtype=np.uint8)
        result = self.dll.lab_update_texture_batch(self.handle,
            ids.ctypes.data_as(C.POINTER(C.c_uint32)),
            rects.ctypes.data_as(C.POINTER(C.c_uint32)),
            payload.ctypes.data_as(C.POINTER(C.c_uint8)), len(rows))
        if check:
            self.check(result)
        return result

    def read(self, mesh_id):
        count = self.dll.lab_mesh_vertex_count(self.handle, mesh_id)
        if count < 0:
            raise RuntimeError(self.error())
        data = np.empty((count, 12), dtype='float32')
        self.check(self.dll.lab_read_mesh_vertices(self.handle, mesh_id,
                   data.ctypes.data_as(C.POINTER(C.c_float)), data.size))
        return data

    def update(self, rows, *, check=True):
        if not rows:
            return 1
        if any(np.ndim(vertices) != 2 or np.shape(vertices)[1] != 12 for _, vertices in rows):
            raise ValueError('Expected an N by 12 vertex array for each mesh')
        ids = np.ascontiguousarray([row[0] for row in rows], dtype='uint32')
        counts = np.ascontiguousarray([len(row[1]) for row in rows], dtype='uint32')
        payload = np.ascontiguousarray(np.concatenate([row[1].reshape(-1) for row in rows]), dtype='float32')
        result = self.dll.lab_update_batch(self.handle,
            ids.ctypes.data_as(C.POINTER(C.c_uint32)), counts.ctypes.data_as(C.POINTER(C.c_uint32)),
            payload.ctypes.data_as(C.POINTER(C.c_float)), len(rows))
        if check:
            self.check(result)
        return result

    def stats(self):
        return dict(shader_compiles=int(self.dll.lab_compile_count(self.handle)),
                    updates=int(self.dll.lab_update_count(self.handle)),
                    uploaded_bytes=int(self.dll.lab_uploaded_bytes(self.handle)),
                    texture_updates=int(self.dll.lab_texture_update_count(self.handle)),
                    texture_uploaded_bytes=int(self.dll.lab_texture_uploaded_bytes(self.handle)),
                    meshes=int(self.dll.lab_mesh_count(self.handle)),
                    renderer=self.dll.lab_renderer_name(self.handle).decode(),
                    gl_version=self.dll.lab_gl_version(self.handle).decode())
