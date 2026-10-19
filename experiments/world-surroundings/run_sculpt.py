"""LAB-02A replay, GPU validation and optional standalone mouse sculpt window."""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import threading
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from run_baseline import command, digest, source_hashes, write_json
from run_heightmap import fixture_samples, terrain_scene, check_surface
import baseline_scene as baseline
from heightfield import Heightfield
from sculpt import SculptSession
from sculpt_native import NativeTerrain
from native.export_scene import mesh_payload, BinaryWriter


def height_hash(terrain):
    return hashlib.sha256(terrain.heights.tobytes()).hexdigest()


def export_state(terrain, initial, folder, exporter):
    """Only startup and offline reference construction use this exporter."""
    from mini3d.native_photo_bundle import export_live_bundle
    scene = terrain_scene(terrain, 32)
    # Existing models keep their initial transforms when terrain changes.
    for marker in scene.root_entities[1:4]:
        marker.pos[2] = initial.query_surface(*map(float, marker.pos[:2]))['height']
    scene.update()
    camera = baseline.camera_for_view('oblique')
    bundle = export_live_bundle(scene, camera, exporter, folder, ROOT / 'spqr-native', shared_textures=False)
    writer = BinaryWriter()
    writer.raw(b'SPQRF001')
    writer.u32(144 * 3)
    for view in baseline.VIEW_NAMES:
        writer.raw(baseline._frame_bytes(baseline.camera_for_view(view), 1081, 662)[12:])
    (folder / 'frames.bin').write_bytes(writer.data)
    terrain_entities = [scene.root_entities[0]] + scene.root_entities[4:]
    entity_indices = [next(i for i, obj in enumerate(bundle['entity_bindings']) if obj is entity)
                      for entity in terrain_entities]
    return entity_indices


class SculptWindow:
    def __init__(self, session, native, entity_indices):
        self.session, self.native = session, native
        self.mesh_ids = [native.mesh_id(i) for i in entity_indices]
        self.material = baseline.create_baseline_scene().root_entities[0].model.material
        self.camera = baseline.camera_for_view('oblique')
        self.mode, self.radius, self.strength = 'raise', 2.8, 2.5
        self.stroke_radius = self.radius
        self.pointer, self.last_point = (540, 331), None
        self.drawing = False
        self.revision = -1
        self.payloads = []
        self.sync(initial=True)

    def sync(self, initial=False):
        if self.revision == self.session.revision:
            return dict(chunks=0, bytes=0, cpu_ms=0., upload_ms=0.)
        started = time.perf_counter()
        chunks = self.session.terrain.iter_mesh_chunks(self.material, 32)
        payloads = [mesh_payload(chunk['mesh'])[0] for chunk in chunks]
        changed = [(mid, vertices) for index, (mid, vertices) in enumerate(zip(self.mesh_ids, payloads))
                   if not initial and not np.array_equal(vertices, self.payloads[index])]
        self.pick_mesh = self.session.terrain.to_mesh(self.material)
        self.pick_revision = self.session.revision
        cpu_end = time.perf_counter()
        self.native.update(changed)
        ended = time.perf_counter()
        self.payloads, self.chunks, self.revision = payloads, chunks, self.session.revision
        return dict(chunks=len(changed), bytes=sum(vertices.nbytes for _, vertices in changed),
                    cpu_ms=(cpu_end-started)*1000, upload_ms=(ended-cpu_end)*1000)

    def pick(self, position):
        from mini3d.picking import screen_ray, _triangle_hit
        if self.pick_revision != self.session.revision:
            self.pick_mesh = self.session.terrain.to_mesh(self.material)
            self.pick_revision = self.session.revision
        origin, direction = screen_ray(self.camera, position, (0, 0, 1081, 662))
        hit = _triangle_hit(self.pick_mesh, origin, direction, self.camera.near, self.camera.far)
        return None if hit is None else origin + hit[0] * direction

    def screen_point(self, x, y):
        from mini3d.picking import project_point
        height = self.session.terrain.query_surface(float(x), float(y))['height']
        point = project_point(self.camera, (x, y, height), (0, 0, 1081, 662))
        if point is None:
            raise RuntimeError('Replay point is behind the camera')
        return tuple(int(round(value)) for value in point)

    def events(self, events):
        import pygame as pg
        for event in events:
            if event.type == pg.QUIT:
                return False
            if event.type == pg.KEYDOWN:
                modes = {pg.K_1:'raise', pg.K_2:'lower', pg.K_3:'smooth', pg.K_4:'flatten'}
                if event.key in modes:
                    if self.session.active:
                        self.session.cancel_stroke()
                    self.drawing, self.last_point = False, None
                    self.mode = modes[event.key]
                    self.strength = 5. if self.mode in ('smooth', 'flatten') else 2.5
                elif event.key == pg.K_ESCAPE:
                    if self.session.active:
                        self.session.cancel_stroke()
                    self.drawing, self.last_point = False, None
                elif event.key in (pg.K_z, pg.K_y) and not self.session.active:
                    (self.session.undo if event.key == pg.K_z else self.session.redo)()
            elif event.type == pg.MOUSEWHEEL:
                self.radius = min(12., max(.25, self.radius * (1.15 ** event.y)))
            elif event.type == pg.MOUSEMOTION:
                self.pointer = event.pos
            elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                self.pointer = event.pos
                if not self.session.active and self.pick(event.pos) is not None:
                    self.session.begin_stroke(self.mode, self.radius, self.strength)
                    self.stroke_radius = self.radius
                    self.drawing, self.last_point = True, None
            elif event.type == pg.MOUSEBUTTONUP and event.button == 1:
                if self.session.active:
                    self.session.end_stroke()
                self.drawing, self.last_point = False, None
        return True

    def tick(self, dt):
        if self.drawing and self.session.active:
            point = self.pick(self.pointer)
            if point is not None:
                current = np.asarray(point[:2])
                start = current if self.last_point is None else self.last_point
                count = max(1, int(math.ceil(np.linalg.norm(current - start) / (self.stroke_radius * .2))))
                for step in range(1, count + 1):
                    sample = start + (current - start) * (step / count)
                    self.session.dab(float(sample[0]), float(sample[1]), amount=dt/count)
                self.last_point = current
            else:
                self.last_point = None
        return self.sync()


def invalid_batch_checks(control):
    native = control.native
    mesh_id = control.mesh_ids[0]
    original = native.read(mesh_id)
    before = native.stats()
    invalid = []
    changed = original.copy(); changed[:, 2] += .1
    bad_xy = original.copy(); bad_xy[0, 0] += 1.
    nan = original.copy(); nan[0, 2] = np.nan
    zero_normal = original.copy(); zero_normal[0, 3:6] = 0.
    batches = [('later-invalid-index', [(mesh_id, changed), (999999, original)]),
               ('duplicate', [(mesh_id, changed), (mesh_id, changed)]),
               ('wrong-count', [(mesh_id, original[:-1])]),
               ('immutable-xy', [(mesh_id, bad_xy)]), ('nan', [(mesh_id, nan)]),
               ('zero-normal', [(mesh_id, zero_normal)])]
    for label, rows in batches:
        assert native.update(rows, check=False) == 0, label
        message = native.error()
        assert np.array_equal(native.read(mesh_id), original), label
        assert native.stats()['updates'] == before['updates']
        invalid.append(dict(case=label, error=message))
    result = []
    def worker():
        result.append((native.dll.lab_render(native.handle, 168), native.error()))
    thread = threading.Thread(target=worker)
    thread.start(); thread.join()
    assert result[0][0] == 0
    # Temporarily detach, without destroying or replacing the caller's context.
    wgl = C.WinDLL('opengl32')
    wgl.wglGetCurrentContext.restype = C.c_void_p
    wgl.wglGetCurrentDC.restype = C.c_void_p
    wgl.wglMakeCurrent.argtypes = [C.c_void_p, C.c_void_p]
    context, dc = wgl.wglGetCurrentContext(), wgl.wglGetCurrentDC()
    assert wgl.wglMakeCurrent(None, None)
    try:
        assert native.dll.lab_destroy(native.handle) == 0
        context_error = native.error()
    finally:
        assert wgl.wglMakeCurrent(dc, context)
    return dict(invalid_batches=invalid, wrong_thread=result[0][1], wrong_context=context_error)


def png_from_ppm(source, destination):
    from PIL import Image
    with Image.open(source) as image:
        image.save(destination)


def compare_checkpoint(control, initial, exporter, library, output, tag, *, reference=True):
    folder = output / 'checkpoints' / tag
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / 'dynamic'
    control.native.capture(stem)
    png_from_ppm(stem.with_suffix('.ppm'), folder / 'preview.png')
    for mesh_id, payload in zip(control.mesh_ids, control.payloads):
        assert np.array_equal(control.native.read(mesh_id), payload), 'GPU buffer differs from CPU mesh'
    surface = check_surface(control.session.terrain, control.material, 32)
    row = dict(height_sha256=height_hash(control.session.terrain), surface=surface,
               gpu_vertices_exact=True, preview=(folder/'preview.png').relative_to(output).as_posix())
    if reference:
        bundle = folder / 'fresh-bundle'
        export_state(control.session.terrain, initial, bundle, exporter)
        fresh = NativeTerrain(library, bundle)
        try:
            fresh.capture(folder / 'fresh')
        finally:
            fresh.close()
        for suffix in ('.rgba', '.depth.f32'):
            assert stem.with_suffix(suffix).read_bytes() == (folder/'fresh').with_suffix(suffix).read_bytes(), \
                'Dynamic renderer differs from full reference: ' + tag + suffix
        row['fresh_color_and_shadow_exact'] = True
    return row


def replay(control, output, checkpoint=None, recording=False):
    import pygame as pg
    timings, events_log, frames = [], [], []
    frame_number = 0
    def frame(events):
        nonlocal frame_number
        for event in events:
            pg.event.post(event)
        started = time.perf_counter()
        assert control.events(pg.event.get())
        input_end = time.perf_counter()
        update = control.tick(1/30.)
        update_end = time.perf_counter()
        control.native.render()
        render_end = time.perf_counter()
        pg.display.flip()
        ended = time.perf_counter()
        timings.append(dict(frame=frame_number, frame_ms=(ended-started)*1000,
            input_ms=(input_end-started)*1000, cpu_and_upload_ms=(update_end-input_end)*1000,
            render_finish_ms=(render_end-update_end)*1000, swap_ms=(ended-render_end)*1000, **update))
        events_log.append([dict(type=event.type, **event.dict) for event in events])
        if recording and frame_number % 5 == 0:
            path = output / 'animation-frames' / ('frame-%04d.ppm' % frame_number)
            control.native.capture_color(path)
            frames.append(path)
        frame_number += 1
    def key(number):
        return pg.event.Event(pg.KEYDOWN, key=number, mod=0)
    def stroke(number, start, end, count):
        for index in range(count):
            point = np.asarray(start) + (np.asarray(end)-start)*index/max(1, count-1)
            screen = control.screen_point(*point)
            events = [pg.event.Event(pg.MOUSEMOTION, pos=screen, rel=(0,0), buttons=(1,0,0))]
            if index == 0:
                events = [key(pg.K_ESCAPE), key(number),
                          pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=screen)]
            frame(events)
        frame([pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=control.pointer)])
    for mode, start, end, count in ((pg.K_1, (-5.,-2.), (3.,2.), 32),
                                    (pg.K_2, (6.,-2.), (7.,3.), 24),
                                    (pg.K_3, (-4.,-1.), (1.,1.), 24),
                                    (pg.K_4, (-7.,3.), (-7.,3.), 32)):
        stroke(mode, start, end, count)
        if checkpoint:
            checkpoint(control.mode)
    edited = height_hash(control.session.terrain)
    # Preview then Esc: no fifth history record, exact state restoration.
    screen = control.screen_point(5., -5.)
    frame([key(pg.K_1), pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=screen)])
    for _ in range(10):
        frame([])
    assert height_hash(control.session.terrain) != edited
    frame([key(pg.K_ESCAPE)])
    assert height_hash(control.session.terrain) == edited
    assert control.session.undo_count == 4
    if checkpoint:
        checkpoint('cancel')
    frame([key(pg.K_z)])
    assert height_hash(control.session.terrain) != edited
    if checkpoint:
        checkpoint('undo')
    frame([key(pg.K_y)])
    assert height_hash(control.session.terrain) == edited
    if checkpoint:
        checkpoint('redo')
    return dict(frames=timings, input_events=events_log, height_sha256=edited,
                history_bytes=control.session.history_bytes, animation_frames=frames)


def summarize(values):
    return {name:float(np.percentile(values, q)) for name,q in (('p50',50),('p95',95),('p99',99))}


def interactive_loop(control, frame_limit=0):
    import pygame as pg
    clock=pg.time.Clock()
    frames=0
    pg.display.set_caption('SPQR Sculpt Lab | 1/2/3/4 modes, LMB draw, wheel next radius, Esc cancel, Z/Y undo/redo')
    while control.events(pg.event.get()):
        dt=clock.tick(60)/1000.
        control.tick(dt)
        control.native.render(); pg.display.flip()
        pg.display.set_caption('SPQR Sculpt Lab | {} radius {:.2f} | 1/2/3/4, LMB, wheel, Esc, Z/Y'.format(
            control.mode,control.radius))
        frames+=1
        if frame_limit and frames>=frame_limit:
            break
    return frames


def run(args):
    import pygame as pg
    from PIL import Image
    from mini3d.gl_renderer import GLRenderer
    output, build = args.output.resolve(), args.build_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new empty output directory')
    if output == build or output in build.parents or build in output.parents:
        raise ValueError('Keep build and results separate')
    output.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, stage='LAB-02A', commands=[], _output=output)
    native = exporter = None
    try:
        report['git_head'] = command(['git','rev-parse','HEAD'],output/'git-head.log',report).strip()
        report['git_status_before'] = command(['git','status','--short'],output/'git-status.log',report)
        cmake, compiler, ninja = [shutil.which(tool) for tool in ('cmake','g++','ninja')]
        if not all((cmake,compiler,ninja)):
            raise RuntimeError('CMake, MinGW g++ and Ninja are required')
        command([cmake,'-S',HERE,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_CXX_COMPILER='+compiler,'-DCMAKE_MAKE_PROGRAM='+ninja],output/'configure.log',report)
        command([cmake,'--build',build,'--target','terrain_lab','--parallel','2'],output/'build.log',report)
        library = build/'bin/terrain_lab.dll'
        report['library_sha256'] = digest(library)
        report['source_sha256'] = source_hashes()
        for name in ('terrain_bridge.cpp','CMakeLists.txt'):
            report['source_sha256'][(HERE/name).relative_to(ROOT).as_posix()] = digest(HERE/name)
        initial = Heightfield(fixture_samples(65,65,16).astype('float64')/65535.*6.)
        pg.display.init()
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK,pg.GL_CONTEXT_PROFILE_CORE)
        pg.display.set_mode((1081,662),pg.OPENGL|pg.DOUBLEBUF|(0 if args.interactive else pg.HIDDEN))
        exporter = GLRenderer(1081,662)
        entity_indices = export_state(initial,initial,output/'initial-bundle',exporter)
        native = NativeTerrain(library,output/'initial-bundle')
        control = SculptWindow(SculptSession(initial),native,entity_indices)
        native.render(); pg.display.flip()
        report['initial_stats'] = native.stats()
        if args.interactive:
            report['mode']='interactive'
            report['automated_checks']=False
            report['interactive_frames']=interactive_loop(control,args.live_frames)
            report['final_stats']=native.stats()
            report['passed']=True
            print('Interactive session closed; no automated replay was requested',flush=True)
            return
        report['mode']='automated-replay'
        report['automated_checks']=True
        report['invalid_input_checks'] = invalid_batch_checks(control)
        checkpoints = {}
        def checkpoint(tag):
            print('CHECK '+tag,flush=True)
            checkpoints[tag] = compare_checkpoint(control,initial,exporter,library,output,tag,
                                                   reference=tag not in ('cancel','redo'))
        checkpoint('initial')
        measured = replay(control,output,checkpoint=checkpoint)
        report['checkpoints'] = checkpoints
        for tag in ('cancel','redo'):
            for suffix in ('.rgba','.depth.f32'):
                assert (output/'checkpoints'/tag/('dynamic'+suffix)).read_bytes() == \
                       (output/'checkpoints/flatten'/('dynamic'+suffix)).read_bytes()
        write_json(output/'input-replay.json',measured['input_events'])
        report['measured_frames'] = measured['frames']
        report['timing_ms'] = {name:summarize([row[name] for row in measured['frames']]) for name in
                              ('frame_ms','cpu_and_upload_ms','render_finish_ms','swap_ms')}
        report['history_bytes'] = measured['history_bytes']
        report['measured_stats'] = native.stats()
        assert report['measured_stats']['shader_compiles'] == report['initial_stats']['shader_compiles']
        # Separate replay with readback/encoding; not mixed into timing results.
        recorded_control = SculptWindow(SculptSession(initial),native,entity_indices)
        # Restore the initial payload into the persistent renderer for replay.
        native.update(list(zip(recorded_control.mesh_ids,recorded_control.payloads)))
        recorded = replay(recorded_control,output,recording=True)
        assert recorded['height_sha256'] == measured['height_sha256']
        images=[]
        for path in recorded['animation_frames']:
            with Image.open(path) as image:
                image=image.copy(); image.thumbnail((648,397)); images.append(image)
        images[0].save(output/'sculpt-replay.gif',save_all=True,append_images=images[1:],duration=167,loop=0)
        for image in images:
            image.close()
        report['recording'] = dict(separate_replay=True, frames=len(images),
                                   file='sculpt-replay.gif', height_sha256=recorded['height_sha256'])
        report['final_stats'] = native.stats()
        assert report['final_stats']['shader_compiles'] == report['initial_stats']['shader_compiles']
        report['passed']=True
    except Exception as error:
        report['error']='{}: {}'.format(type(error).__name__,error)
        raise
    finally:
        cleanup_errors = []
        for label, cleanup in (('native', native.close if native else None),
                               ('exporter', exporter.close if exporter else None),
                               ('display', pg.display.quit)):
            if cleanup is not None:
                try:
                    cleanup()
                except Exception as error:
                    cleanup_errors.append('{}: {}'.format(label, error))
        if cleanup_errors:
            report['passed'] = False
            report['cleanup_errors'] = cleanup_errors
        report.pop('_output')
        write_json(output/'report.json',report)
        if cleanup_errors:
            raise RuntimeError('; '.join(cleanup_errors))
    print('PASS: '+str(output/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--build-dir',type=Path,default=ROOT/'captures/world-surroundings/build-lab02a')
    parser.add_argument('--interactive',action='store_true')
    parser.add_argument('--live-frames',type=int,default=0,help='Interactive smoke limit; 0 runs until window closes')
    run(parser.parse_args())
