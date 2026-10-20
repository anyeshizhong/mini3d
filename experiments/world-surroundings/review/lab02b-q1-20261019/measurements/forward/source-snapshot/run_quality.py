"""LAB-02B-Q1: original A, matched sampler control, depth and power height blends.

Serial real SPQR GL measurements. No image generation, editor integration,
tiling reduction, triplanar mapping or geometric scattering is performed here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import run_paint as paint_run
from run_baseline import command, digest, source_hashes, write_json
from run_heightmap import fixture_samples
from run_sculpt import png_from_ppm
from material_maps import MaterialMaps, weight_rgba
from quality_materials import QualityMaps, quality_shader
from heightfield import Heightfield
from paint import PaintSession
from sculpt_native import NativeTerrain
from native.export_scene import BinaryWriter
import baseline_scene as baseline

VARIANTS = {
    'A': None,
    'A_control': dict(method='depth', strength=0., width=.35, sharpness=4.),
    'B_depth': dict(method='depth', strength=.75, width=.35, sharpness=4.),
    'B_power': dict(method='power', strength=.75, width=.35, sharpness=4.),
}
VIEWS = dict(close=24, oblique=168, distant=312, steep=432)
NAV_START = 433


def camera_for(view, terrain):
    camera = paint_run.camera_for(view if view != 'steep' else 'close')
    if view == 'close':
        camera.position = (-1.5, -5.5, terrain.query_surface(0., -3.)['height'] + 2.3)
        camera.look_at((0., -2., terrain.query_surface(0., -2.)['height']))
    if view == 'steep':
        camera.position = (-9., -4., 5.2)
        camera.look_at((0., 1., 3.))
    return camera


def frames_bytes(terrain, samples):
    """Keep original replay frame 168; append a continuous camera orbit."""
    cameras = []
    for view in ('close', 'oblique', 'distant'):
        cameras.extend([camera_for(view, terrain)] * 144)
    cameras.append(camera_for('steep', terrain))
    for index in range(samples):
        phase = index / max(1, samples - 1) * 2. * np.pi
        camera = paint_run.camera_for('oblique')
        camera.position = (12. * np.sin(phase), -13. * np.cos(phase), 8. + np.sin(phase))
        camera.look_at((0., 0., 1.8))
        cameras.append(camera)
    writer = BinaryWriter(); writer.raw(b'SPQRF001'); writer.u32(len(cameras))
    for camera in cameras:
        writer.string('orbit'); writer.f64(0.)
        for values in (camera.position, camera.rotation, camera.view_matrix,
                       camera.projection_matrix(1081. / 662.)):
            writer.f64_array(np.asarray(values, dtype=np.float64))
        writer.f64(float(camera.near)); writer.f64(float(camera.far))
    return bytes(writer.data)


def export(terrain, weights, maps, variant, folder, exporter, frames):
    entities = paint_run.export_state(terrain, weights, maps, 'layered', folder, exporter)
    if VARIANTS[variant] is not None:
        path = folder / 'shaders/material.frag'
        path.write_text(quality_shader(path.read_text(encoding='utf-8'), **VARIANTS[variant]), encoding='utf-8')
    (folder / 'frames.bin').write_bytes(frames)
    return entities


def summary(values):
    values = np.asarray(values, dtype=np.float64)
    return dict(n=int(values.size), **{name: float(np.percentile(values, p))
                for name, p in (('p50', 50), ('p95', 95), ('p99', 99))}, maximum=float(values.max()))


def poll(native):
    return native.poll_gpu_timing()


def gpu_summary(rows, count):
    if len(rows) != count or any(row['dropped'] for row in rows):
        raise RuntimeError('GPU query samples incomplete/dropped: %d of %d' % (len(rows), count))
    return summary([row['gpu_ms'] for row in rows])


def timing_contract_check(native, folder):
    """Exercise disabled mode, bounded-ring overflow, restart and owner checks."""
    import threading
    native.enable_gpu_timing(False); native.render()
    assert poll(native) == []
    before = folder/'timing-before.ppm'; native.capture_color(before)
    native.enable_gpu_timing(True)
    for _ in range(40):
        native.render()
    rows = poll(native)
    assert len(rows) == 40 and any(row['dropped'] for row in rows)
    assert all(row['gpu_ms'] == 0. for row in rows if row['dropped'])
    native.enable_gpu_timing(False)
    after = folder/'timing-after.ppm'; native.capture_color(after)
    assert before.read_bytes() == after.read_bytes(), 'Timing changed rendered pixels'
    native.enable_gpu_timing(True); native.render()
    gpu_summary(poll(native), 1)
    errors = []
    def wrong_thread():
        errors.append((native.dll.lab_enable_gpu_timing(native.handle, 0), native.error()))
    worker = threading.Thread(target=wrong_thread); worker.start(); worker.join(5.)
    assert not worker.is_alive() and errors[0][0] == 0
    native.enable_gpu_timing(False)
    return dict(disabled_empty=True, ring_overflow_explicit=True, restart_valid=True,
                timing_pixels_exact=True, wrong_thread=errors[0][1])


def measure(control, samples, warmup, navigation=False):
    import pygame as pg
    for index in range(warmup):
        control.native.render(NAV_START + index % samples if navigation else 168)
        pg.display.flip()
    control.native.enable_gpu_timing(True)
    rows, gpu = [], []
    for index in range(samples):
        start = time.perf_counter()
        control.events(pg.event.get())
        control.tick(0.)
        update = time.perf_counter()
        control.native.render(NAV_START + index if navigation else 168)
        rendered = time.perf_counter()
        pg.display.flip()
        end = time.perf_counter()
        gpu.extend(poll(control.native))
        rows.append(dict(frame=index, frame_ms=(end-start)*1000.,
                         cpu_and_upload_ms=(update-start)*1000.,
                         render_finish_ms=(rendered-update)*1000., swap_ms=(end-rendered)*1000.))
    # render() already finishes by existing contract. Poll only available results.
    gpu.extend(poll(control.native))
    control.native.enable_gpu_timing(False)
    return dict(frames=rows, timing_ms={key: summary([r[key] for r in rows]) for key in
                ('frame_ms', 'cpu_and_upload_ms', 'render_finish_ms', 'swap_ms')}, gpu=gpu,
                terrain_color_gpu_ms=gpu_summary(gpu, samples))


def diagnostic_weights():
    """Controlled manually editable crossfades, shared by all variants."""
    y, x = np.meshgrid(np.linspace(-13., 13., 257), np.linspace(-18., 18., 257), indexing='ij')
    rock = .5 + .35 * np.sin(x * .3)
    grass = np.clip((y + 1.) / 8., 0., 1.) * .7
    return np.stack(((1.-rock)*(1.-grass), rock*(1.-grass), grass), axis=2).astype(np.float32)


def save_gif(paths, target, duration):
    from PIL import Image
    images = []
    for path in paths:
        with Image.open(path) as source:
            image = source.copy(); image.thumbnail((648, 397)); images.append(image)
    images[0].save(target, save_all=True, append_images=images[1:], duration=duration, loop=0)
    for image in images:
        image.close()


def checkpoint(control, terrain, exporter, library, folder, tag, variant, frames):
    """Same editing transaction as LAB-02B, plus exact full-rebuild comparison."""
    target = folder / 'checkpoints' / tag; target.mkdir(parents=True)
    native = control.native
    for key, array in control.arrays.items():
        assert np.array_equal(native.read_texture(control.texture_ids[key]), array), key
    for mid, vertices in zip(control.mesh_ids, control.payloads):
        assert np.array_equal(native.read(mid), vertices), 'Painting changed terrain geometry'
    native.capture(target / 'dynamic')
    png_from_ppm(target / 'dynamic.ppm', target / 'preview.png')
    fresh_folder = target / 'fresh-bundle'
    export(terrain, control.paint.weights, control.maps, variant, fresh_folder, exporter, frames)
    fresh = NativeTerrain(library, fresh_folder)
    try:
        # Identical oblique shadow history before capture.
        for _ in range(48):
            fresh.render()
        fresh.capture(target / 'fresh')
    finally:
        fresh.close()
    for suffix in ('.rgba', '.depth.f32'):
        assert (target / ('dynamic'+suffix)).read_bytes() == (target / ('fresh'+suffix)).read_bytes(), tag+suffix
    return dict(gpu_textures_exact=True, geometry_unchanged=True,
                fresh_color_far_shadow_exact=True, weight_sha256=paint_run.weights_hash(control.paint.weights))


def capture_views(control, folder):
    target = folder / 'views'; target.mkdir()
    for view, frame in VIEWS.items():
        for _ in range(48):
            control.native.render(frame)
        control.native.capture_color(target / (view+'.ppm'))
        png_from_ppm(target / (view+'.ppm'), target / (view+'.png'))


def gpu_blend_check(shader, options):
    """Compare actual GLSL qBlend float output against independent NumPy reference."""
    from OpenGL import GL as gl
    from OpenGL.GL.shaders import compileProgram, compileShader
    from quality_blend import blend_weights
    random = np.random.RandomState(8219)
    weights = random.randint(0, 256, (512, 3)).astype(np.float32)
    heights = random.randint(0, 256, (512, 3)).astype(np.float32) / 255.
    weights[:5] = ((0, 0, 0), (255, 0, 0), (0, 255, 0), (128, 127, 0), (0, 0, 255))
    totals = weights.sum(axis=1, keepdims=True)
    p = weights / np.maximum(totals, 1.)
    p[totals[:, 0] == 0] = (1., 0., 0.)
    function = shader[shader.index('vec3 qBlend('):shader.index('vec3 qColor;')]
    vertex = '#version 330 core\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0.,1.);}'
    fragment = ('#version 330 core\nuniform sampler2D wp;uniform sampler2D hp;out vec4 color;\n' + function +
                '\nvoid main(){ivec2 uv=ivec2(int(gl_FragCoord.x),0);color=vec4(qBlend(texelFetch(wp,uv,0).rgb,texelFetch(hp,uv,0).rgb),1.);}')
    program = compileProgram(compileShader(vertex, gl.GL_VERTEX_SHADER), compileShader(fragment, gl.GL_FRAGMENT_SHADER))
    textures = gl.glGenTextures(3); fbo = gl.glGenFramebuffers(1); vao = gl.glGenVertexArrays(1)
    old = dict(program=int(gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM)), vao=int(gl.glGetIntegerv(gl.GL_VERTEX_ARRAY_BINDING)),
               draw=int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)), read=int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)),
               viewport=np.array(gl.glGetIntegerv(gl.GL_VIEWPORT)), active=int(gl.glGetIntegerv(gl.GL_ACTIVE_TEXTURE)))
    try:
        for unit, data in enumerate((p, heights)):
            rgba = np.ones((1, 512, 4), dtype=np.float32); rgba[0, :, :3] = data
            gl.glActiveTexture(gl.GL_TEXTURE0+unit); gl.glBindTexture(gl.GL_TEXTURE_2D, int(textures[unit]))
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA32F, 512, 1, 0, gl.GL_RGBA, gl.GL_FLOAT, rgba)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glBindTexture(gl.GL_TEXTURE_2D, int(textures[2]))
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA32F, 512, 1, 0, gl.GL_RGBA, gl.GL_FLOAT, None)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, int(textures[2]), 0)
        assert gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) == gl.GL_FRAMEBUFFER_COMPLETE
        gl.glUseProgram(program); gl.glUniform1i(gl.glGetUniformLocation(program, 'wp'), 0); gl.glUniform1i(gl.glGetUniformLocation(program, 'hp'), 1)
        gl.glActiveTexture(gl.GL_TEXTURE1); gl.glBindTexture(gl.GL_TEXTURE_2D, int(textures[1]))
        gl.glBindVertexArray(vao); gl.glViewport(0, 0, 512, 1)
        depth = bool(gl.glIsEnabled(gl.GL_DEPTH_TEST)); blend = bool(gl.glIsEnabled(gl.GL_BLEND))
        gl.glDisable(gl.GL_DEPTH_TEST); gl.glDisable(gl.GL_BLEND)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        result = np.empty((1, 512, 4), dtype=np.float32)
        gl.glReadPixels(0, 0, 512, 1, gl.GL_RGBA, gl.GL_FLOAT, result)
        expected = blend_weights(p, heights, **options)
        error = float(np.max(np.abs(result[0, :, :3]-expected)))
        assert error < 3.e-6, error
        return dict(samples=512, max_absolute_error=error, tolerance=3.e-6)
    finally:
        if 'depth' in locals():
            (gl.glEnable if depth else gl.glDisable)(gl.GL_DEPTH_TEST)
            (gl.glEnable if blend else gl.glDisable)(gl.GL_BLEND)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, old['draw']); gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, old['read'])
        gl.glUseProgram(old['program']); gl.glBindVertexArray(old['vao']); gl.glViewport(*old['viewport'])
        gl.glActiveTexture(old['active'])
        gl.glDeleteTextures(textures); gl.glDeleteFramebuffers(1, [fbo]); gl.glDeleteVertexArrays(1, [vao]); gl.glDeleteProgram(program)


def run(args):
    import pygame as pg
    from OpenGL import GL as gl
    from mini3d.gl_renderer import GLRenderer
    VARIANTS['A_control'].update(width=args.width, sharpness=args.sharpness)
    for name in ('B_depth', 'B_power'):
        VARIANTS[name].update(strength=args.strength, width=args.width, sharpness=args.sharpness)
    # Validate GPU parameters before creating any output or GL resources.
    from mini3d.material_shaders import FRAGMENT_SHADER
    from material_maps import shader_source
    quality_shader(shader_source(FRAGMENT_SHADER, 'layered'), **VARIANTS['B_depth'])
    output, build = args.output.resolve(), args.build_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new empty output directory')
    if output == build or output in build.parents or build in output.parents:
        raise ValueError('Keep build and output separate')
    output.mkdir(parents=True, exist_ok=True)
    report = dict(stage='LAB-02B-Q1', passed=False, visual_acceptance='pending user review', commands=[],
                  variants=VARIANTS, fixtures={}, _output=output, arguments=vars(args).copy())
    report['arguments'] = {k: str(v) if isinstance(v, Path) else v for k, v in report['arguments'].items()}
    native = exporter = None
    try:
        report['git_head'] = command(['git', 'rev-parse', 'HEAD'], output/'git-head.log', report).strip()
        report['git_status'] = command(['git', 'status', '--short'], output/'git-status.log', report)
        cmake, compiler, ninja = [shutil.which(name) for name in ('cmake', 'g++', 'ninja')]
        if not all((cmake, compiler, ninja)):
            raise RuntimeError('CMake, MinGW g++ and Ninja required')
        command([cmake, '-S', HERE, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_CXX_COMPILER='+compiler, '-DCMAKE_MAKE_PROGRAM='+ninja], output/'configure.log', report)
        command([cmake, '--build', build, '--target', 'terrain_lab', '--parallel', '2'], output/'build.log', report)
        library = build/'bin/terrain_lab.dll'
        report['library_sha256'] = digest(library); report['source_sha256'] = source_hashes()
        report['source_sha256'].update({p.relative_to(ROOT).as_posix(): digest(p) for p in
                                      [HERE/'terrain_bridge.cpp', HERE/'CMakeLists.txt'] + list((HERE/'assets').rglob('*')) if p.is_file()})
        pg.display.init()
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION, 3); pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION, 3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK, pg.GL_CONTEXT_PROFILE_CORE)
        pg.display.set_mode((1081, 662), pg.OPENGL | pg.DOUBLEBUF | (0 if args.visible else pg.HIDDEN))
        report['environment'] = {name: gl.glGetString(value).decode() for name, value in
                                 (('renderer', gl.GL_RENDERER), ('version', gl.GL_VERSION), ('vendor', gl.GL_VENDOR))}
        exporter = GLRenderer(1081, 662)
        baseline_maps, quality_maps = MaterialMaps(), QualityMaps()
        for fixture in args.fixtures:
            heights = fixture_samples(65, 65, 16).astype(np.float64)/65535.*6.
            if fixture == 'steep':
                x = np.linspace(-18., 18., 65)[None, :]
                heights += 4.5 * (.5 + .5*np.tanh(x/.4))
            terrain = Heightfield(heights)
            frame_data = frames_bytes(terrain, args.samples)
            fixture_folder = output/fixture; fixture_folder.mkdir()
            np.save(fixture_folder/'terrain.npy', terrain.heights, allow_pickle=False)
            write_json(fixture_folder/'views.json', {view: dict(frame=index, position=list(camera_for(view, terrain).position),
                       view=np.asarray(camera_for(view, terrain).view_matrix).tolist()) for view, index in VIEWS.items()})
            rows = {}; report['fixtures'][fixture] = rows
            hashes = []
            for variant in args.variants:
                print('QUALITY '+fixture+' '+variant, flush=True)
                folder = fixture_folder/variant; folder.mkdir()
                maps = baseline_maps if variant == 'A' else quality_maps
                session = PaintSession()
                entities = export(terrain, session.weights, maps, variant, folder/'initial-bundle', exporter, frame_data)
                native = NativeTerrain(library, folder/'initial-bundle')
                control = paint_run.PaintWindow(terrain, session, native, entities, maps, 'layered')
                for _ in range(args.warmup):
                    native.render(); pg.display.flip()
                row = dict(initial_stats=native.stats()); rows[variant] = row
                row['timing_contract'] = timing_contract_check(native, folder)
                row['invalid_updates'] = paint_run.invalid_textures(control)
                row['transfer_state'] = paint_run.transfer_state_check(control)
                row['budget_rollback'] = paint_run.budget_event_check(terrain, native, entities, maps, 'layered')
                row['measurement_start_stats'] = native.stats()
                # Full checkpoint/readback work is outside every measured frame.
                checks, editing_gpu = {}, []
                def check(tag):
                    editing_gpu.extend(poll(native))
                    native.enable_gpu_timing(False)
                    checks[tag] = checkpoint(control, terrain, exporter, library, folder, tag, variant, frame_data)
                    native.enable_gpu_timing(True)
                checks['initial'] = checkpoint(control, terrain, exporter, library, folder, 'initial', variant, frame_data)
                native.enable_gpu_timing(True)
                original_render = native.render
                def editing_render(frame=168):
                    original_render(frame)
                    editing_gpu.extend(poll(native))
                native.render = editing_render
                try:
                    measured = paint_run.replay(control, folder, check)
                finally:
                    native.render = original_render
                editing_gpu.extend(poll(native)); native.enable_gpu_timing(False)
                row['editing_gpu'] = editing_gpu
                row['editing_terrain_color_gpu_ms'] = gpu_summary(editing_gpu, len(measured['frames']))
                row['editing'] = dict(frames=measured['frames'], timing_ms={key: summary([r[key] for r in measured['frames']])
                                    for key in ('frame_ms', 'cpu_and_upload_ms', 'render_finish_ms', 'swap_ms')})
                row['checkpoints'] = checks
                row['weight_sha256'] = measured['weight_sha256']; hashes.append(measured['weight_sha256'])
                row['history_bytes'] = measured['history_bytes']
                row['after_edit_stats'] = native.stats()
                np.save(folder/'weights.npy', session.weights, allow_pickle=False)
                write_json(folder/'input-replay.json', measured['events'])
                capture_views(control, folder)
                for mode, moving in (('static', False), ('navigation', True)):
                    row[mode] = [measure(control, args.samples, args.warmup, moving) for _ in range(args.repeats)]
                row['texture_allocation_bytes'] = sum(value.nbytes for value in control.arrays.values())
                row['weight_cpu_bytes'] = session.weights.nbytes
                row['pbr_cpu_prefilter_bytes'] = sum(level.nbytes for layers in maps._mip_maps.values()
                                                     for levels in layers for level in levels)
                row['height_cpu_prefilter_bytes'] = (sum(level.nbytes for levels in maps.height_levels for level in levels)
                                                     if isinstance(maps, QualityMaps) else 0)
                row['texture_layout'] = {name: dict(shape=list(a.shape), format='RGBA8', gl_levels=1, bytes=a.nbytes)
                                         for name, a in control.arrays.items()}
                row['upload_bytes_editing'] = row['after_edit_stats']['texture_uploaded_bytes']-row['measurement_start_stats']['texture_uploaded_bytes']
                row['upload_calls_editing'] = row['after_edit_stats']['texture_updates']-row['measurement_start_stats']['texture_updates']
                # Separate continuous motion recording, no readback in timing samples.
                images = []; recording = folder/'motion'; recording.mkdir()
                for index in range(args.samples):
                    native.render(NAV_START+index); pg.display.flip()
                    if index % 6 == 0:
                        path = recording/('%04d.ppm'%index); native.capture_color(path); images.append(path)
                save_gif(images, folder/'camera-motion.gif', 200)
                native.update_textures([(control.texture_ids['occlusion'], 0, 0, weight_rgba(PaintSession().weights))])
                recording_control = paint_run.PaintWindow(terrain, PaintSession(), native, entities, maps, 'layered')
                recorded = paint_run.replay(recording_control, folder, recording=True)
                assert recorded['weight_sha256'] == measured['weight_sha256']
                save_gif(recorded['animation_frames'], folder/'paint-replay.gif', 167)
                row['recording'] = dict(separate_from_timing=True, camera_frames=len(images),
                                        painting_frames=len(recorded['animation_frames']))
                # Balanced weight ramps isolate boundary behavior independently of weak paint strokes.
                diagnostic = diagnostic_weights(); np.save(folder/'diagnostic-weights.npy', diagnostic, allow_pickle=False)
                native.update_textures([(control.texture_ids['occlusion'], 0, 0, weight_rgba(diagnostic))])
                for view, index in VIEWS.items():
                    for _ in range(48):
                        native.render(index)
                    target = folder/('diagnostic-'+view+'.ppm'); native.capture_color(target)
                    png_from_ppm(target, target.with_suffix('.png'))
                if VARIANTS[variant] is not None:
                    row['gpu_blend_reference'] = gpu_blend_check((folder/'initial-bundle/shaders/material.frag').read_text(encoding='utf-8'), VARIANTS[variant])
                row['final_stats'] = native.stats()
                assert row['final_stats']['shader_compiles'] == row['initial_stats']['shader_compiles']
                assert row['final_stats']['updates'] == 0
                native.close(); native = None
                write_json(folder/'result.json', row)
            assert len(set(hashes)) == 1, 'Variants replayed different authoritative weights'
        report['passed'] = True
    except Exception as error:
        report['error'] = '{}: {}'.format(type(error).__name__, error)
        raise
    finally:
        cleanup_errors = []
        for cleanup in (native.close if native else None, exporter.close if exporter else None, pg.display.quit):
            if cleanup:
                try:
                    cleanup()
                except Exception as error:
                    cleanup_errors.append(str(error))
        if cleanup_errors:
            report['passed'] = False; report['cleanup_errors'] = cleanup_errors
        report.pop('_output'); write_json(output/'report.json', report)
        if cleanup_errors:
            raise RuntimeError('; '.join(cleanup_errors))
    print('PASS '+str(output/'report.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, default=ROOT/'captures/world-surroundings/build-lab02b-q')
    parser.add_argument('--fixtures', nargs='+', choices=('baseline', 'steep'), default=['baseline', 'steep'])
    parser.add_argument('--variants', nargs='+', choices=tuple(VARIANTS), default=list(VARIANTS))
    parser.add_argument('--samples', type=int, default=120)
    parser.add_argument('--warmup', type=int, default=24)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--strength', type=float, default=.75)
    parser.add_argument('--width', type=float, default=.35)
    parser.add_argument('--sharpness', type=float, default=4.)
    parser.add_argument('--visible', action='store_true')
    args = parser.parse_args()
    if args.samples < 24 or args.warmup < 1 or args.repeats < 1:
        parser.error('samples >= 24, warmup >= 1 and repeats >= 1 required')
    run(args)
