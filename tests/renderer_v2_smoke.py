"""Real desktop OpenGL, paired V1/V2 PNG and timing evidence. No downloads.

python -B tests/renderer_v2_smoke.py --assets-root F:/python_project/mini3d
V1 is loaded from the pinned Git baseline, not approximated by a V2 switch.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from lighting_fixture import cube_geometry
from mini3d.camera import Camera
from mini3d.gltf_loader import load_gltf
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.scene import Entity, Mesh, Scene
from mini3d.shot_camera import ShotCamera, render_shot
import mini3d.shadow_map as shadow_module
import mini3d.gl_renderer as renderer_module

BASE = '6d725b4'


def summary(values):
    return dict(median_ms=float(np.median(values)), p95_ms=float(np.percentile(values, 95)), samples=len(values))


def run(output, assets_root):
    output.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(['git', 'show', BASE + ':mini3d/gl_renderer.py'], cwd=str(ROOT)).decode('utf8')
    old_module = types.ModuleType('mini3d.v1_renderer')
    old_module.__package__ = 'mini3d'
    exec(compile(source, 'V1@' + BASE, 'exec'), old_module.__dict__)
    pygame.init()
    pygame.display.set_mode((640, 480), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    old, new, target = old_module.GLRenderer(640, 480), GLRenderer(640, 480), RenderTarget()
    old.render_mode = new.render_mode = 'REALISTIC'
    cpu = os.environ.get('PROCESSOR_IDENTIFIER', platform.processor())
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
    report = dict(baseline=BASE, python=sys.version, os=platform.platform(),
                  cpu=cpu, gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                  driver_gl=gl.glGetString(gl.GL_VERSION).decode(),
                  warmup=3, samples=21, scenes=[], checks={}, skipped=[])
    v, n, indices = cube_geometry()
    material = {'pbrMetallicRoughness': {'baseColorFactor': [.65, .4, .2, 1], 'roughnessFactor': .8}}
    mesh = Mesh(v, indices, normals=n, material=material)

    def add(scene, position, scale=(1, 1, 1), source_mesh=mesh):
        entity = Entity(source_mesh)
        entity.pos[:], entity.scale[:] = position, scale
        scene.add(entity)
        return entity

    def scene_base():
        scene = Scene()
        scene.lighting_mode = 'Scene'
        scene.show_grid = scene.show_axes = False
        scene.light_dir = np.array([1., 0, 1.])
        scene.shadows_enabled = True
        scene.ambient, scene.diffuse = .15, 1.5
        return scene

    camera = ShotCamera(Camera([0, 0, 8], near=.05, far=20))
    camera.look_at([0, 0, 0])
    camera.set_lens(85)
    camera.set_aspect('1:1')
    scene = scene_base()
    add(scene, [0, 0, -.1], [200, 200, .2])
    caster = add(scene, [4, 0, 4])
    cases = [('offscreen-shadow', scene, camera)]

    mixed = scene_base()
    add(mixed, [0, 0, -.1], [32, 32, .2])
    parent = Entity()
    parent.pos[:] = [0, 0, 1]
    parent.scale[:] = [-1.4, .6, 1.2]
    parent.rot[:] = [.1, .3, .5]
    parent.add_child(Entity(mesh))
    mixed.add(parent)
    for alpha, x, y in ((.35, -.2, -.5), (.6, .2, .5)):
        transparent = Mesh(v, indices, normals=n, material={'alphaMode': 'BLEND', 'doubleSided': True,
                     'pbrMetallicRoughness': {'baseColorFactor': [.1, .6, .9, alpha]}})
        add(mixed, [x, y, 1.7], [.8, .8, .8], transparent)
    unlit = Mesh(v, indices, normals=n, material={'unlit': True,
                'extensions': {'KHR_materials_unlit': {}},
                'pbrMetallicRoughness': {'baseColorFactor': [.8, .1, .2, 1]}})
    add(mixed, [-2, 0, 1], source_mesh=unlit)
    add(mixed, [2, 0, 1], source_mesh=Mesh(v, indices, normals=n))
    for i in range(40):
        add(mixed, [30 + i, 0, 1])
    view = Camera([7, -10, 7], near=.05, far=150)
    view.look_at([0, 0, 1])
    cases.append(('mixed-hierarchy-transparency', mixed, view))
    helmet = assets_root / 'model/11_benchmark_round01/DamagedHelmet/DamagedHelmet.glb'
    if helmet.is_file():
        pbr = scene_base()
        pbr.add(load_gltf(helmet).instantiate())
        for i in range(40):
            add(pbr, [30 + i, 0, 0])
        view2 = Camera([0, -4, 2], near=.05, far=100)
        view2.look_at([0, 0, 0])
        cases.append(('DamagedHelmet-40-offscreen-boxes', pbr, ShotCamera(view2)))
    else:
        report['skipped'].append('DamagedHelmet: local GLB unavailable')
    report['skipped'].append('Victorian House + 40 CesiumMan: local assets unavailable; no substitute score')
    report['skipped'].append('Rome + 40: large stress rerun deferred for Milestone 1 quota; local originals preserved')

    def draw(renderer, scene, cam):
        if isinstance(cam, ShotCamera):
            render_shot(scene, cam, renderer, target)
        else:
            target.resize(640, 480)
            target.bind()
            renderer.resize(640, 480)
            gl.glDepthMask(True)
            gl.glDisable(gl.GL_SCISSOR_TEST)
            renderer.render(scene, cam)

    def pixels(renderer, scene, cam, name):
        scene.update()
        draw(renderer, scene, cam)
        raw = gl.glReadPixels(0, 0, renderer.w, renderer.h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        pygame.image.save(pygame.image.fromstring(raw, (renderer.w, renderer.h), 'RGB', True), str(output / (name + '.png')))
        assert gl.glGetError() == gl.GL_NO_ERROR
        return np.frombuffer(raw, np.uint8).copy()

    real_fit = shadow_module.light_matrix
    fit_times = []
    def fit(*args, **kwargs):
        start = time.perf_counter()
        result = real_fit(*args, **kwargs)
        fit_times.append((time.perf_counter() - start) * 1000)
        return result
    shadow_module.light_matrix = fit
    try:
        for label, scene, cam in cases:
            before = pixels(old, scene, cam, label + '-v1')
            after = pixels(new, scene, cam, label + '-v2')
            np.testing.assert_array_equal(before, after)
            stats = dict(new.render_stats)
            assert stats['entities_culled'] > 0, label
            # Resolve full V2 draw statistics with the same path and culling off.
            new.frustum_culling = False
            np.testing.assert_array_equal(before, pixels(new, scene, cam, label + '-unculled'))
            full_stats = dict(new.render_stats)
            new.frustum_culling = True
            assert full_stats['shadow_draw_calls'] == stats['shadow_draw_calls']
            timings = {key: dict(wall=[], update=[], fit=[], plan=[]) for key in ('v1', 'v2')}
            for iteration in range(24):
                for key, renderer in ((('v1', old), ('v2', new)) if iteration % 2 == 0 else (('v2', new), ('v1', old))):
                    gl.glFinish()
                    begin = time.perf_counter()
                    scene.update()
                    update = (time.perf_counter() - begin) * 1000
                    fit_times.clear()
                    begin = time.perf_counter()
                    draw(renderer, scene, cam)
                    gl.glFinish()
                    wall = (time.perf_counter() - begin) * 1000
                    if iteration >= 3:
                        timings[key]['wall'].append(wall)
                        timings[key]['update'].append(update)
                        timings[key]['fit'].append(sum(fit_times))
                        if key == 'v2':
                            timings[key]['plan'].append(new.render_stats['render_plan_cpu_ms'])
            gpu = {}
            # Separate queries for shadow and color; GL timer includes GPU command
            # timeline gaps, not CPU attribution. No nested queries or PNG encoding.
            for key, renderer in (('v1', old), ('v2', new)):
                queries = np.asarray(gl.glGenQueries(2)).reshape(-1)
                shadow_render, color_render = renderer.shadow_map.render, renderer._render_scene
                def timed(function, query):
                    def wrapper(*args, **kwargs):
                        gl.glBeginQuery(gl.GL_TIME_ELAPSED, int(query))
                        try:
                            return function(*args, **kwargs)
                        finally:
                            gl.glEndQuery(gl.GL_TIME_ELAPSED)
                    return wrapper
                renderer.shadow_map.render = timed(shadow_render, queries[0])
                renderer._render_scene = timed(color_render, queries[1])
                values = [[], []]
                try:
                    for _ in range(7):
                        draw(renderer, scene, cam)
                        gl.glFinish()
                        for j, query in enumerate(queries):
                            values[j].append(int(gl.glGetQueryObjectuiv(int(query), gl.GL_QUERY_RESULT)) / 1e6)
                finally:
                    renderer.shadow_map.render, renderer._render_scene = shadow_render, color_render
                    gl.glDeleteQueries(2, queries)
                gpu[key] = dict(shadow=summary(values[0]), color=summary(values[1]))
            record = dict(name=label, root_objects=len(scene.root_entities),
                          before=full_stats, after=stats, changed_pixels=0,
                          cpu_and_sync={key: {name: summary(values) for name, values in data.items() if values}
                                        for key, data in timings.items()}, gpu_command_timeline=gpu,
                          raw_ms=timings)
            report['scenes'].append(record)
            (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(label, full_stats['color_draw_calls'], '->', stats['color_draw_calls'],
                  'wall median', summary(timings['v1']['wall']), '->', summary(timings['v2']['wall']), flush=True)
        # Preserve the editor's existing material modes and legacy expanded
        # outline behavior, and count actual GL submissions independently.
        mode_checks = []
        real_draw = gl.glDrawElements
        for legacy_mode, material_mode in (('REALISTIC', 'Wireframe'), ('REALISTIC', 'Unlit'),
                                          ('OUTLINE', 'Lit'), ('TOON', 'Lit')):
            old.render_mode = new.render_mode = legacy_mode
            mixed.render_mode = material_mode
            submissions = []
            def counted(mode, count, kind, pointer):
                submissions.append(int(count) // 3)
                return real_draw(mode, count, kind, pointer)
            before = pixels(old, mixed, cases[1][2], 'mode-' + legacy_mode + '-' + material_mode + '-v1')
            with patch.object(gl, 'glDrawElements', counted), patch.object(renderer_module, 'glDrawElements', counted):
                after = pixels(new, mixed, cases[1][2], 'mode-' + legacy_mode + '-' + material_mode + '-v2')
            np.testing.assert_array_equal(before, after)
            assert new.render_stats['draw_calls'] == len(submissions)
            assert new.render_stats['submitted_triangles'] == sum(submissions)
            mode_checks.append(dict(legacy=legacy_mode, material=material_mode,
                                    stats=dict(new.render_stats), changed_pixels=0))
        report['checks']['editor_modes_and_actual_gl_counts'] = mode_checks
        old.render_mode = new.render_mode = 'REALISTIC'
        shadow_on = pixels(new, cases[0][1], camera, 'offscreen-shadow-on')
        assert caster not in [item.entity for item in new.last_render_plan.imported]
        assert caster in new.last_render_plan.shadow_candidates
        cases[0][1].shadows_enabled = False
        shadow_off = pixels(new, cases[0][1], camera, 'offscreen-shadow-off')
        changed = int(np.count_nonzero(np.any(shadow_on.reshape(-1, 3) != shadow_off.reshape(-1, 3), axis=1)))
        assert changed > 100, changed
        report['checks'].update(pixel_identical_to_pinned_v1=True, offscreen_caster_shadow_pixels=changed,
                                gl_error=int(gl.glGetError()))
        assert report['checks']['gl_error'] == 0
        (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    finally:
        shadow_module.light_matrix = real_fit
        target.close()
        old.close()
        new.close()
        pygame.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'captures/renderer-v2')
    parser.add_argument('--assets-root', type=Path, default=ROOT)
    args = parser.parse_args()
    run(args.output, args.assets_root)
