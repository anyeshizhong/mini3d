"""Paired f36a0ff/current CPU timings and real-asset GL correctness evidence.

python -B tests/renderer_v2_cpu_cache_benchmark.py --assets-root F:/python_project/mini3d
--profile-only records the original hotspot before production edits. No download.
"""
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import platform
import pstats
import subprocess
import struct
import sys
import time
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from mini3d.gltf_loader import load_gltf
from mini3d.placement import geometry_bounds, create_ground
from mini3d.render_plan import build_render_plan
from mini3d.scene import Scene
from mini3d import shadow_fit
from shadow_fit_performance_20261010 import counts, shot

BASE = 'f36a0ffae693841e03d8fad21fca058062bf9545'


def cpu_model():
    result = os.environ.get('PROCESSOR_IDENTIFIER', platform.processor())
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                result = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
    return result


def asset_record(path):
    with path.open('rb') as stream:
        header = stream.read(20)
        asset = json.loads(stream.read(struct.unpack_from('<I', header, 12)[0]))['asset']
    return dict(path=str(path), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), asset=asset)


def reference():
    module = types.ModuleType('mini3d.shadow_fit_reference')
    source = subprocess.check_output(['git', 'show', BASE + ':mini3d/shadow_fit.py'], cwd=str(ROOT)).decode('utf8')
    exec(compile(source, 'shadow_fit@f36a0ff', 'exec'), module.__dict__)
    return module


def real_scene(assets_root):
    paths = [assets_root / 'model/08_rome_river/rome_river_side.glb',
             assets_root / 'model/05_roman_soldier/roman_legionnaire.glb']
    if not all(p.is_file() for p in paths):
        raise FileNotFoundError('Original Rome and Roman Legionnaire GLBs required: ' + str(paths))
    scene = Scene()
    scene.lighting_mode = 'Scene'
    scene.shadows_enabled = True
    scene.light_dir = np.array([-3., -2., 3.])
    scene.show_axes = scene.show_grid = False
    rome, soldier = [load_gltf(p).instantiate() for p in paths]
    lo, hi = geometry_bounds(rome)
    factor = 40 / max((hi - lo)[:2])
    rome.scale[:] = factor
    rome.pos[:] = [-(lo[0] + hi[0]) * factor / 2, -(lo[1] + hi[1]) * factor / 2, -lo[2] * factor]
    scene.add(rome)
    lo, hi = geometry_bounds(soldier)
    factor = 1.7 / (hi[2] - lo[2])
    soldier.scale[:] = factor
    origin = np.array([-(lo[0] + hi[0]) * factor / 2, -(lo[1] + hi[1]) * factor / 2, -lo[2] * factor])
    for i in range(40):
        entity = soldier.clone()
        entity.pos[:] = origin + [i % 8 * 1.2 - 4.2, i // 8 * 1.4 - 2.8, 0]
        entity.asset_path = str(paths[1])
        scene.add(entity)
    rome.asset_path = str(paths[0])
    ground = create_ground(10)  # Serializable explicit PBR receiver; Rome stays Unlit.
    ground.scale[:] = [10, 10, 1]
    ground.asset_path = 'builtin:ground'
    scene.add(ground)
    scene.update()
    return scene, paths


def summary(values):
    return dict(median_ms=float(np.median(values)), p95_ms=float(np.percentile(values, 95)), samples=len(values))


def profile(function, repetitions=5):
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(repetitions):
        function()
    profiler.disable()
    result = []
    for (filename, line, name), (primitive, calls, self_time, cumulative, _) in pstats.Stats(profiler).stats.items():
        result.append(dict(function=name, file=Path(filename).name, line=line, calls=calls,
                           self_ms=self_time * 1000, cumulative_ms=cumulative * 1000))
    return sorted(result, key=lambda row: row['cumulative_ms'], reverse=True)[:30]


def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    old = reference()
    scene, paths = real_scene(args.assets_root)
    camera = shot([9, -12, 7], [0, 0, 1], 50)
    entities = scene.get_flat_render_list()
    report = dict(baseline=BASE, python=sys.version, platform=platform.platform(),
                  cpu=cpu_model(),
                  counts=counts(scene), camera=camera.to_dict(), light=scene.light_dir.tolist(),
                  assets=[asset_record(p) for p in paths])
    report['profile'] = profile(lambda: old.receiver_matrix(entities, scene.light_dir, camera, 1024))
    (args.output / 'profile-before.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print('REAL ASSET COUNTS', report['counts'], flush=True)
    print('PROFILE', json.dumps(report['profile'][:14], indent=2), flush=True)
    if args.profile_only:
        return
    values = {name: [] for name in ('fit_before', 'fit_after', 'plan_before', 'plan_after', 'update_before', 'update_after')}
    for i in range(args.samples + 3):
        matrices = []
        functions = [('fit_before', old.receiver_matrix), ('fit_after', shadow_fit.receiver_matrix)]
        if i % 2:
            functions.reverse()
        for name, function in functions:
            suffix = name.split('_')[1]
            for kind, operation in (('update', scene.update),
                                    ('plan', lambda: build_render_plan(scene, camera, 1920, 1080))):
                start = time.perf_counter()
                operation()
                if i >= 3:
                    values[kind + '_' + suffix].append((time.perf_counter() - start) * 1000)
            started = time.perf_counter()
            matrix = function(entities, scene.light_dir, camera, 1024)
            elapsed = (time.perf_counter() - started) * 1000
            assert matrix is not None
            matrices.append(matrix)
            if i >= 3:
                values[name].append(elapsed)
        np.testing.assert_array_equal(matrices[0], matrices[1])
    report['static_cpu'] = {name: summary(data) for name, data in values.items()}
    report['raw_cpu_ms'] = values
    report['profile_after'] = profile(lambda: shadow_fit.receiver_matrix(entities, scene.light_dir, camera, 1024))
    report['matrix_identical'] = True
    report['mutation_checks'] = mutations(scene, camera, old)
    (args.output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print('CPU', report['static_cpu'], flush=True)
    if args.gpu:
        gpu_checks(scene, camera, old, report, args.output)


def mutations(scene, camera, old):
    """Compare full fit after in-place edits, hierarchy and mesh/bounds changes."""
    entities = scene.get_flat_render_list()
    child = next(e for e in entities if e.parent is not None)
    root = scene.root_entities[1]
    original_parent, child_index = child.parent, child.parent.children.index(child)
    states = []
    def check(name):
        scene.update()
        current = scene.get_flat_render_list()
        before = old.receiver_matrix(current, scene.light_dir, camera, 1024)
        after = shadow_fit.receiver_matrix(current, scene.light_dir, camera, 1024)
        np.testing.assert_array_equal(before, after)
        states.append(name)
    saved = [(e, e.pos.copy(), e.rot.copy(), e.scale.copy(), e.extra_local.copy()) for e in (root, child)]
    mesh, bounds = child.model, tuple(b.copy() for b in child.model.bounds)
    camera_state, light = camera.to_dict(), scene.light_dir.copy()
    try:
        root.pos[:] += [.3, -.2, .1]
        check('parent position changed in place')
        root.rot[:] += [.2, .1, -.3]
        check('parent rotation changed in place')
        root.scale[:] *= [1.2, .8, 1.1]
        check('parent nonuniform scale changed in place')
        child.pos[:] += [.1, .05, -.03]
        child.extra_local[0, 3] += .07
        check('child transform and imported matrix changed in place')
        child.model = entities[-1].model
        check('model replaced')
        child.model = mesh
        mesh.bounds[0][:] -= [.1, .2, .05]
        check('bounds mutated in place')
        camera.position += [1, -.5, .2]
        camera.look_at([.5, 0, 1])
        camera.set_lens(85)
        camera.set_aspect('4:3')
        camera.near, camera.far = .1, 180
        check('camera pose lens aspect near far changed')
        scene.light_dir[:] = [1., 0, .2]
        check('light direction changed in place')
        root.visible = False
        check('visibility changed')
        root.visible = True
        parent = child.parent
        other = root if parent is not root else scene.root_entities[2]
        other.add_child(child)
        check('child reparented')
        parent.add_child(child)
    finally:
        if child.parent is not original_parent:
            original_parent.add_child(child)
        original_parent.children.remove(child)
        original_parent.children.insert(child_index, child)
        for e, pos, rot, scale, extra in saved:
            e.pos[:], e.rot[:], e.scale[:], e.extra_local[:] = pos, rot, scale, extra
        child.model = mesh
        mesh.bounds[0][:], mesh.bounds[1][:] = bounds
        scene.light_dir[:] = light
        restored = type(camera).from_dict(camera_state)
        camera.__dict__.update(restored.__dict__)
        scene.update()
    check('restored state')
    return states


def gpu_checks(scene, camera, old, report, output):
    import pygame
    from OpenGL import GL as gl
    from mini3d.api import Mini3DAPI
    from mini3d.commands import PlacementCommands
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_shot
    pygame.init()
    pygame.display.set_mode((640, 480), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer, target = GLRenderer(640, 480), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()
    report['driver'] = gl.glGetString(gl.GL_VERSION).decode()
    checks = []
    def draw(name, original=False):
        with patch.object(shadow_fit, 'receiver_matrix', old.receiver_matrix if original else optimized):
            scene.update()
            render_shot(scene, camera, renderer, target)
            raw = gl.glReadPixels(0, 0, *camera.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            pygame.image.save(pygame.image.fromstring(raw, camera.size, 'RGB', True), str(output / (name + '.png')))
            assert gl.glGetError() == 0
            return np.frombuffer(raw, np.uint8).copy(), dict(renderer.render_stats), renderer.shadow_map.matrix.copy()
    optimized = shadow_fit.receiver_matrix
    try:
        for label in ('original', 'changed-model-camera-light'):
            if label != 'original':
                scene.root_entities[1].pos[:] += [.3, -.15, .1]
                scene.root_entities[1].rot[2] += .15
                camera.position += [.2, -.1, .15]
                camera.look_at([0, 0, 1])
                scene.light_dir[:] = [-2., -1., 4.]
            before, before_stats, before_matrix = draw(label + '-before', True)
            after, after_stats, after_matrix = draw(label + '-after')
            np.testing.assert_array_equal(before, after)
            np.testing.assert_array_equal(before_matrix, after_matrix)
            for field in ('entities_before', 'entities_after', 'color_draw_calls', 'shadow_draw_calls', 'submitted_triangles'):
                assert before_stats[field] == after_stats[field]
            checks.append(dict(name=label, changed_pixels=0, before=before_stats, after=after_stats))
        # Use the public save/load API on these original assets and compare PNG.
        api = Mini3DAPI(renderer)
        api._app.scene = scene
        api._app.viewer.scene = scene
        api._commands = api._app.commands = PlacementCommands(scene, api._app.cache)
        api._app.shot_camera = camera
        api.save_scene(output / 'real.scene.json')
        saved, _, _ = draw('saved')
        api.load_scene(output / 'real.scene.json')
        camera = api._app.shot_camera
        reloaded, _, _ = draw('reloaded')
        np.testing.assert_array_equal(saved, reloaded)
        checks.append(dict(name='API scene save/load', changed_pixels=0))
        report['gpu_checks'] = checks
        (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print('REAL GPU CHECKS PASSED', flush=True)
    finally:
        target.close()
        renderer.close()
        pygame.quit()


def offscreen_check(args):
    """A real Legionnaire outside the color frustum still casts visible shadow."""
    import pygame
    from OpenGL import GL as gl
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_shot
    old, optimized = reference(), shadow_fit.receiver_matrix
    scene = Scene()
    scene.lighting_mode, scene.shadows_enabled = 'Scene', True
    scene.light_dir = np.array([1., 0, 1.])
    scene.add(create_ground(200))
    caster = load_gltf(args.assets_root / 'model/05_roman_soldier/roman_legionnaire.glb').instantiate()
    lo, hi = geometry_bounds(caster)
    caster.scale[:] = 1.7 / (hi[2] - lo[2])
    lo, hi = geometry_bounds(caster)
    caster.pos[:] = [4 - (lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, 4 - lo[2]]
    scene.add(caster)
    camera = shot([0, 0, 8], [0, 0, 0], 85)
    camera.set_aspect('1:1')
    pygame.init()
    pygame.display.set_mode((640, 480), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer, target = GLRenderer(640, 480), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    pictures, statistics = [], []
    try:
        for name, function, enabled in (('offscreen-before', old.receiver_matrix, True),
                                        ('offscreen-after', optimized, True),
                                        ('offscreen-disabled', optimized, False)):
            scene.shadows_enabled = enabled
            with patch.object(shadow_fit, 'receiver_matrix', function):
                scene.update()
                render_shot(scene, camera, renderer, target)
                raw = gl.glReadPixels(0, 0, *camera.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                pygame.image.save(pygame.image.fromstring(raw, camera.size, 'RGB', True), str(args.output / (name + '.png')))
                pictures.append(np.frombuffer(raw, np.uint8).reshape(-1, 3).copy())
                statistics.append(dict(renderer.render_stats))
                assert gl.glGetError() == 0
        np.testing.assert_array_equal(pictures[0], pictures[1])
        assert statistics[1]['entities_after'] == 1  # Only the ground is color-visible.
        assert statistics[1]['shadow_draw_calls'] == statistics[1]['entities_before']
        changed = int(np.count_nonzero(np.any(pictures[1] != pictures[2], axis=1)))
        assert changed > 100
        report = json.loads((args.output / 'results.json').read_text(encoding='utf8'))
        report['offscreen_shadow'] = dict(model='Original Roman Legionnaire', changed_pixels_vs_baseline=0,
                                         shadow_pixels=changed, before=statistics[0], after=statistics[1], gl_error=0)
        (args.output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print('REAL OFFSCREEN SHADOW PASSED', changed, flush=True)
    finally:
        target.close()
        renderer.close()
        pygame.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT / 'captures/renderer-v2-cpu-cache')
    parser.add_argument('--profile-only', action='store_true')
    parser.add_argument('--samples', type=int, default=21)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--offscreen-only', action='store_true')
    args = parser.parse_args()
    if args.offscreen_only:
        offscreen_check(args)
    else:
        run(args)
