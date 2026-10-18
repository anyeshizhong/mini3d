"""Exercise staged native GPU initialization and partial-handle cleanup."""
import argparse
import ctypes
import json
from pathlib import Path
import shutil
import struct
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure_library(path):
    library = ctypes.CDLL(str(path))
    pointer = ctypes.c_void_p
    doubles = ctypes.POINTER(ctypes.c_double)
    uints = ctypes.POINTER(ctypes.c_uint32)
    library.spqr_photo_abi_version.argtypes = []
    library.spqr_photo_abi_version.restype = ctypes.c_uint32
    if library.spqr_photo_abi_version() != 1:
        raise AssertionError('Unsupported native photo ABI')
    library.spqr_photo_last_error.argtypes = []
    library.spqr_photo_last_error.restype = ctypes.c_char_p
    library.spqr_photo_begin_shared.argtypes = [ctypes.c_wchar_p, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_int]
    library.spqr_photo_begin_shared.restype = pointer
    library.spqr_photo_prepare_step.argtypes = [pointer, ctypes.POINTER(ctypes.c_int)]
    library.spqr_photo_prepare_step.restype = ctypes.c_int
    library.spqr_photo_program_compile_count.argtypes = [pointer, ctypes.POINTER(ctypes.c_uint32)]
    library.spqr_photo_program_compile_count.restype = ctypes.c_int
    library.spqr_photo_resize.argtypes = [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    library.spqr_photo_resize.restype = ctypes.c_int
    library.spqr_photo_globals.argtypes = [pointer, pointer, ctypes.c_size_t, doubles,
        ctypes.c_uint32, ctypes.c_float, ctypes.c_int, ctypes.c_double]
    library.spqr_photo_globals.restype = ctypes.c_int
    library.spqr_photo_transforms.argtypes = [pointer, uints, doubles,
        ctypes.POINTER(ctypes.c_float), uints, ctypes.c_size_t]
    library.spqr_photo_transforms.restype = ctypes.c_int
    library.spqr_photo_render.argtypes = [pointer, doubles, ctypes.c_uint32, doubles]
    library.spqr_photo_render.restype = ctypes.c_int
    library.spqr_photo_destroy.argtypes = [pointer]
    library.spqr_photo_destroy.restype = ctypes.c_int
    return library


def error_text(library):
    message = library.spqr_photo_last_error()
    return message.decode('utf8', 'replace') if message else ''


def check(library, result, label):
    if not result:
        raise AssertionError('{} failed: {}'.format(label, error_text(library)))


def prepare(library, handle):
    ready = ctypes.c_int(-1)
    started = time.perf_counter()
    check(library, library.spqr_photo_prepare_step(handle, ctypes.byref(ready)),
          'spqr_photo_prepare_step')
    return bool(ready.value), time.perf_counter() - started


def program_compile_count(library, handle):
    count = ctypes.c_uint32()
    check(library, library.spqr_photo_program_compile_count(handle, ctypes.byref(count)),
          'spqr_photo_program_compile_count')
    return int(count.value)


def make_ground_variant(bundle_dir, output_dir):
    """Copy a live bundle and mark its first entity as ground without changing textures."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(bundle_dir, output_dir)
    path = output_dir / 'scene.bin'
    blob = bytearray(path.read_bytes())
    cursor = 8

    def u32():
        nonlocal cursor
        value = struct.unpack_from('<I', blob, cursor)[0]
        cursor += 4
        return value

    version = u32()
    if version != 2:
        raise AssertionError('ground cache fixture must remain a borrowed-texture v2 bundle')
    for _ in range(u32()):
        cursor += 8  # texture target and borrowed GL handle

    def uniform_block():
        nonlocal cursor
        for _ in range(u32()):
            name_length = u32()
            cursor += name_length
            _uniform_type = u32()
            components = u32()
            cursor += components * 4

    uniform_block()
    uniform_block()
    for _ in range(u32()):
        uniform_block()
        cursor += 4 + 13 * 4  # material flags and texture indices
    for _ in range(u32()):
        _material, vertex_count, index_count = struct.unpack_from('<III', blob, cursor)
        cursor += 12 + 6 * 8 + vertex_count * 12 * 4 + index_count * 4
    entity_count = u32()
    if entity_count == 0:
        raise AssertionError('ground cache fixture has no entities')
    entity_name_length = u32()
    cursor += entity_name_length + 4  # entity ID and mesh index
    flags = u32()
    struct.pack_into('<I', blob, cursor - 4, flags | 1)
    path.write_bytes(blob)
    return output_dir


def run(output):
    from OpenGL import GL as gl
    from mini3d.api import Mini3DAPI
    from mini3d.camera import Camera
    from mini3d.gl_renderer import GLRenderer
    from mini3d.native_photo_bundle import export_live_bundle, pack_globals
    from mini3d.native_renderer import preserved_native_state
    from mini3d.render_target import RenderTarget
    from tools.capture_sunset import desktop_context

    output.mkdir(parents=True, exist_ok=True)
    library = configure_library(ROOT / 'native' / 'spqr_photo.dll')
    report = {'passed': False, 'runs': []}
    with desktop_context():
        renderer = GLRenderer(64, 64)
        renderer.render_mode = 'REALISTIC'
        target = RenderTarget()
        target.resize(64, 64, 1)
        api = Mini3DAPI(renderer=renderer)
        api.set_environment(enabled=True)
        api.spawn('builtin:roman-house', position=[0, 0, 0])
        api.spawn('builtin:roman-column', position=[9, 0, 0])
        scene = api._app.scene
        scene.update()
        camera = Camera([14, -18, 9], near=.1, far=100)
        camera.look_at([0, 0, 0])
        camera_values = np.concatenate((camera.position, camera.rotation.reshape(-1),
            camera.view_matrix.reshape(-1), camera.projection_matrix(1.0).reshape(-1),
            [camera.near, camera.far])).astype(np.float64)
        camera_pointer = camera_values.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
        stats = (ctypes.c_double * 8)()

        def one_run(name, ground, cancel_after_mesh=False):
            api.set_atmosphere(enabled=ground, ground=ground)
            scene.update()
            bundle_dir = output / name
            bundle_dir.mkdir(exist_ok=True)
            exported = export_live_bundle(scene, camera, renderer, bundle_dir,
                                          ROOT / 'spqr-native', shared_textures=True)
            mesh_count = int(exported['counts']['meshes'])
            texture_count = int(exported['counts']['textures'])
            if mesh_count < 2:
                raise AssertionError('fixture must contain at least two native meshes')
            if texture_count < 1:
                raise AssertionError('fixture must borrow at least one GL texture')
            if bool(exported['ground_entity']) != ground:
                raise AssertionError('fixture ground entity did not match requested state')

            owner_handles = set()
            material = renderer.material_renderer
            owner_handles.update(int(handle) for _encoded, handle in material._textures.values())
            if material.environment is not None:
                owner_handles.update(int(handle) for handle in material.environment.handles)
            if not owner_handles:
                raise AssertionError('fixture did not retain an owner-side GL texture')

            elapsed = []
            with preserved_native_state():
                handle = library.spqr_photo_begin_shared(str(bundle_dir), 64, 64, 1)
                if not handle:
                    raise AssertionError('begin_shared failed: ' + error_text(library))
                try:
                    # Every stateful API must reject an unready renderer.
                    result = library.spqr_photo_resize(handle, 64, 64, 1)
                    if result or 'initialization is incomplete' not in error_text(library):
                        raise AssertionError('resize did not reject an unready renderer')
                    globals_bytes = pack_globals(exported['material_globals'],
                                                 exported['sky_globals'])
                    globals_buffer = ctypes.create_string_buffer(globals_bytes)
                    light = np.ascontiguousarray([0.3, -0.5, 0.8], dtype=np.float64)
                    result = library.spqr_photo_globals(handle,
                        ctypes.cast(globals_buffer, ctypes.c_void_p), len(globals_bytes),
                        light.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                        ctypes.c_uint32(2048), ctypes.c_float(.001), ctypes.c_int(1),
                        ctypes.c_double(0.0))
                    if result or 'initialization is incomplete' not in error_text(library):
                        raise AssertionError('globals did not reject an unready renderer')
                    result = library.spqr_photo_transforms(handle, None, None, None, None, 0)
                    if result or 'initialization is incomplete' not in error_text(library):
                        raise AssertionError('transforms did not reject an unready renderer')
                    result = library.spqr_photo_render(handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats)
                    if result or 'initialization is incomplete' not in error_text(library):
                        raise AssertionError('render did not reject an unready renderer')

                    if cancel_after_mesh:
                        for _ in range(6):  # Four shader stages, texture validation, one mesh.
                            ready, seconds = prepare(library, handle)
                            elapsed.append(seconds)
                            if ready:
                                raise AssertionError('renderer became ready before all resources')
                        if mesh_count <= 1:
                            raise AssertionError('cancellation did not leave meshes partially uploaded')
                        check(library, library.spqr_photo_destroy(handle), 'partial destroy')
                        handle = None
                        missing = [value for value in owner_handles if not gl.glIsTexture(value)]
                        if missing:
                            raise AssertionError('partial destroy deleted borrowed GL textures: {}'.format(missing))
                        if gl.glGetError() != gl.GL_NO_ERROR:
                            raise AssertionError('OpenGL error after partial destroy')
                        return dict(name=name, ground=ground, meshes=mesh_count,
                                    borrowed_textures=texture_count, canceled_after=6,
                                    first_steps_seconds=elapsed,
                                    ground_stage_seconds=elapsed[1],
                                    borrowed_textures_survived=True)

                    ready = False
                    while not ready:
                        ready, seconds = prepare(library, handle)
                        elapsed.append(seconds)
                    expected_steps = mesh_count + 6
                    if len(elapsed) != expected_steps:
                        raise AssertionError('expected {} initialization steps, saw {}'.format(
                            expected_steps, len(elapsed)))
                    ready_again, repeat_seconds = prepare(library, handle)
                    if not ready_again:
                        raise AssertionError('ready preparation call was not idempotent')
                    check(library, library.spqr_photo_render(handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'ready render')
                    if not any(float(value) > 0 for value in stats[2:6]):
                        raise AssertionError('ready renderer submitted no geometry')
                    if gl.glGetError() != gl.GL_NO_ERROR:
                        raise AssertionError('OpenGL error after ready render')
                    missing = [value for value in owner_handles if not gl.glIsTexture(value)]
                    if missing:
                        raise AssertionError('ready renderer deleted borrowed GL textures: {}'.format(missing))
                    return dict(name=name, ground=ground, meshes=mesh_count,
                                borrowed_textures=texture_count, prepare_steps=len(elapsed),
                                step_seconds=elapsed, ground_stage_seconds=elapsed[1],
                                repeat_ready_seconds=repeat_seconds,
                                render_stats=list(stats), rendered=True,
                                borrowed_textures_survived=True)
                finally:
                    if handle:
                        check(library, library.spqr_photo_destroy(handle), 'destroy')

        def cache_reuse_run():
            api.set_atmosphere(enabled=True, ground=False)
            scene.update()
            bundle_dir = output / 'shader-cache-source'
            bundle_dir.mkdir(exist_ok=True)
            exported = export_live_bundle(scene, camera, renderer, bundle_dir,
                                          ROOT / 'spqr-native', shared_textures=True)
            ground_bundle = make_ground_variant(bundle_dir, output / 'shader-cache-ground')
            material = renderer.material_renderer
            owner_handles = {int(handle) for _encoded, handle in material._textures.values()}
            if material.environment is not None:
                owner_handles.update(int(handle) for handle in material.environment.handles)
            old_handle = new_handle = ground_handle = None
            old_steps, new_steps, ground_steps = [], [], []
            try:
                with preserved_native_state():
                    old_handle = library.spqr_photo_begin_shared(str(bundle_dir), 64, 64, 1)
                    if not old_handle:
                        raise AssertionError('first cached begin failed: ' + error_text(library))
                    ready = False
                    while not ready:
                        ready, seconds = prepare(library, old_handle)
                        old_steps.append(seconds)
                    old_count = program_compile_count(library, old_handle)
                    if old_count != 3:
                        raise AssertionError('no-ground renderer should compile three programs, got {}'.format(
                            old_count))

                    new_handle = library.spqr_photo_begin_shared(str(bundle_dir), 64, 64, 1)
                    if not new_handle:
                        raise AssertionError('reused begin failed: ' + error_text(library))
                    ready = False
                    while not ready:
                        ready, seconds = prepare(library, new_handle)
                        new_steps.append(seconds)
                    new_count = program_compile_count(library, new_handle)
                    if new_count != 0:
                        raise AssertionError('identical live renderer compiled {} programs again'.format(
                            new_count))

                    changed_sky = []
                    changed_exposure = None
                    for record in exported['sky_globals']:
                        row = dict(record)
                        row['values'] = list(record['values'])
                        if row['name'] == 'exposureEV':
                            changed_exposure = float(row['values'][0]) - 3.0
                            row['values'][0] = changed_exposure
                        changed_sky.append(row)
                    if changed_exposure is None:
                        raise AssertionError('fixture has no sky exposure global')
                    changed_globals = pack_globals(exported['material_globals'], changed_sky)
                    changed_buffer = ctypes.create_string_buffer(changed_globals)
                    light = np.ascontiguousarray([0.3, -0.5, 0.8], dtype=np.float64)
                    check(library, library.spqr_photo_globals(new_handle,
                        ctypes.cast(changed_buffer, ctypes.c_void_p), len(changed_globals),
                        light.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), 2048, .001, 0, 0.0),
                        'set distinct globals on reused handle')

                    def target_pixels():
                        old_read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
                        old_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))
                        try:
                            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
                            gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
                            raw = gl.glReadPixels(0, 0, 64, 64, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
                            if isinstance(raw, (bytes, bytearray, memoryview)):
                                values = np.frombuffer(raw, dtype=np.uint8)
                            else:
                                values = np.asarray(raw, dtype=np.uint8).reshape(-1)
                            if values.size != 64 * 64 * 4:
                                raise AssertionError('shared-program readback has the wrong size')
                            return values.reshape(64, 64, 4).copy()
                        finally:
                            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, old_read)
                            gl.glReadBuffer(old_buffer)

                    check(library, library.spqr_photo_render(old_handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'render old globals')
                    old_pixels = target_pixels()
                    check(library, library.spqr_photo_render(new_handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'render changed globals')
                    changed_pixels = target_pixels()
                    exposure_delta = float(np.mean(np.abs(old_pixels.astype(np.int16) -
                                                          changed_pixels.astype(np.int16))))
                    if exposure_delta < 0.5:
                        raise AssertionError('distinct shared-program exposure did not change rendered pixels')
                    check(library, library.spqr_photo_render(old_handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'restore old globals on render')
                    restored_old_pixels = target_pixels()
                    if not np.array_equal(old_pixels, restored_old_pixels):
                        raise AssertionError('new renderer globals leaked into the old renderer image')
                    check(library, library.spqr_photo_render(new_handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'restore changed globals on render')
                    restored_changed_pixels = target_pixels()
                    if not np.array_equal(changed_pixels, restored_changed_pixels):
                        raise AssertionError('old renderer globals leaked into the new renderer image')

                    check(library, library.spqr_photo_destroy(old_handle), 'destroy old cached handle')
                    old_handle = None
                    check(library, library.spqr_photo_render(new_handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'render after old handle destroy')
                    if gl.glGetError() != gl.GL_NO_ERROR:
                        raise AssertionError('OpenGL error after destroying old shared-program owner')
                    missing = [value for value in owner_handles if not gl.glIsTexture(value)]
                    if missing:
                        raise AssertionError('old handle destroy affected borrowed textures: {}'.format(missing))

                    # Reuse the same source key with one photographic-ground entity.
                    # Only the missing ground program should compile in this handle.
                    ground_handle = library.spqr_photo_begin_shared(str(ground_bundle), 64, 64, 1)
                    if not ground_handle:
                        raise AssertionError('ground cache begin failed: ' + error_text(library))
                    ready = False
                    while not ready:
                        ready, seconds = prepare(library, ground_handle)
                        ground_steps.append(seconds)
                    ground_count = program_compile_count(library, ground_handle)
                    if ground_count != 1:
                        raise AssertionError('ground renderer should compile only its missing program, got {}'.format(
                            ground_count))

                    check(library, library.spqr_photo_destroy(new_handle), 'destroy second cached handle')
                    new_handle = None
                    check(library, library.spqr_photo_render(ground_handle, camera_pointer,
                        ctypes.c_uint32(target.framebuffer), stats), 'render after shared owners destroy')
                    if not any(float(value) > 0 for value in stats[2:6]):
                        raise AssertionError('cached ground renderer submitted no geometry')
                    if gl.glGetError() != gl.GL_NO_ERROR:
                        raise AssertionError('OpenGL error after rendering cached ground handle')
                    missing = [value for value in owner_handles if not gl.glIsTexture(value)]
                    if missing:
                        raise AssertionError('cached renderer destroyed borrowed textures: {}'.format(missing))

                    source_variant = output / 'shader-cache-source-variant'
                    if source_variant.exists():
                        shutil.rmtree(source_variant)
                    shutil.copytree(bundle_dir, source_variant)
                    with (source_variant / 'shaders' / 'sky.frag').open('ab') as shader:
                        shader.write(b'\n// cache-key source variation test\n')
                    source_handle = library.spqr_photo_begin_shared(str(source_variant), 64, 64, 1)
                    if not source_handle:
                        raise AssertionError('changed-source begin failed: ' + error_text(library))
                    try:
                        ready = False
                        while not ready:
                            ready, _seconds = prepare(library, source_handle)
                        source_count = program_compile_count(library, source_handle)
                        if source_count != 3:
                            raise AssertionError('changed shader source reused a different ProgramSet; compiled {}'.format(
                                source_count))
                        check(library, library.spqr_photo_render(source_handle, camera_pointer,
                            ctypes.c_uint32(target.framebuffer), stats), 'render changed-source handle')
                    finally:
                        check(library, library.spqr_photo_destroy(source_handle),
                              'destroy changed-source handle')
                    if gl.glGetError() != gl.GL_NO_ERROR:
                        raise AssertionError('OpenGL error after source-key isolation check')
                    check(library, library.spqr_photo_destroy(ground_handle), 'destroy ground cached handle')
                    ground_handle = None
                    if gl.glGetError() != gl.GL_NO_ERROR:
                        raise AssertionError('OpenGL error after cached handle cleanup')
            finally:
                for handle in (ground_handle, new_handle, old_handle):
                    if handle:
                        check(library, library.spqr_photo_destroy(handle), 'cache cleanup')
            return dict(old_compile_count=old_count, reused_compile_count=new_count,
                        ground_compile_count=ground_count, first_steps_seconds=old_steps,
                        reused_steps_seconds=new_steps, ground_steps_seconds=ground_steps,
                        source_variant_compile_count=source_count,
                        shared_uniform_exposure_delta=exposure_delta,
                        shared_uniform_images_restored_exactly=True,
                        borrowed_textures_survived=True,
                        old_handle_destroyed_before_surviving_renders=True)

        try:
            # Leave one mesh uploaded, then destroy while textures remain owned by Python.
            report['runs'].append(one_run('cancel-no-ground', False, cancel_after_mesh=True))
            # A flagged ground entity exercises the analytic ground shader stage.
            report['runs'].append(one_run('complete-with-ground', True))
            report['shader_cache'] = cache_reuse_run()
            report['passed'] = True
        finally:
            target.close()
            renderer.close()
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='directory for the report and exported bundles')
    run(parser.parse_args().output.expanduser().resolve())
