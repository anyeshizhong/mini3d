"""Real-GL ground coverage and warmed frame timings; artifacts stay in captures."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(output, backend, benchmark=False):
    os.environ['MINI3D_PHOTO_BACKEND'] = backend
    if backend == 'native':
        os.environ['MINI3D_REQUIRE_NATIVE_PHOTO'] = '1'
    from OpenGL import GL as gl
    from PIL import Image
    from tools.capture_sunset import desktop_context
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_scene_view
    output.mkdir(parents=True, exist_ok=True)
    report = dict(backend=backend, coverage=[], timings=[],
        source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=str(ROOT),text=True).strip(),
        source_diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','HEAD'],cwd=str(ROOT))).hexdigest(),
        native_dll_sha256=hashlib.sha256((ROOT/'native/spqr_photo.dll').read_bytes()).hexdigest() if backend=='native' else None)
    with desktop_context():
        report['gpu'] = gl.glGetString(gl.GL_RENDERER).decode()
        report['driver'] = gl.glGetString(gl.GL_VERSION).decode()
        renderer, target = GLRenderer(640, 360), RenderTarget()
        renderer.render_mode = 'REALISTIC'
        try:
            api = Mini3DAPI(renderer=renderer)
            # Native bundles need a material mesh even in the sky-only control.
            api.spawn('builtin:ground', position=[100000,100000,-100000])
            api.set_atmosphere(enabled=True, ground=True, ground_z=0., haze=0.)
            api.set_shadows(enabled=False)
            # Compare exact ground-only pixels to the same sky with ground off.
            for height in (1.7, 20., 100., 300.):
                for pitch in (15., 45., 90.):
                    angle = math.radians(pitch)
                    api.create_shot_camera(position=[0., 0., height],
                        target=[math.cos(angle), 0., height-math.sin(angle)],
                        focal_mm=35, aspect='16:9', near=.05, far=150)
                    cam = api._app.shot_camera

                    images = []
                    for ground in (False, True):
                        api.set_atmosphere(ground=ground)
                        render_scene_view(api._app.scene, cam, renderer, target, (640, 360))
                        raw = gl.glReadPixels(0, 0, 640, 360, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                        images.append(np.frombuffer(raw, np.uint8).reshape(360, 640, 3).copy())
                    # Independent double-precision rays determine where a plane should exist.
                    xx, yy = np.meshgrid((np.arange(640)+.5)/640*2-1,
                                         (np.arange(360)+.5)/360*2-1)
                    clip = np.stack((xx, yy, np.ones_like(xx), np.ones_like(xx)), axis=-1)
                    world = clip @ np.linalg.inv(cam.projection_matrix(640/360) @ cam.view_matrix).T
                    ray = world[..., :3]/world[..., 3:] - np.asarray(cam.position)
                    expected = ray[..., 2] < -1e-6
                    same = np.all(images[0] == images[1], axis=-1)
                    leaked = int((same & expected).sum())
                    raw_depth = gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)
                    depth = np.frombuffer(raw_depth, np.float32).reshape(360,640)
                    distance = -height / np.where(expected, ray[...,2], -1.)
                    hit = np.asarray(cam.position) + ray * distance[...,None]
                    actual = target.render_camera
                    projected = np.concatenate((hit, np.ones((360,640,1))), axis=-1) @ (
                        actual.projection_matrix(640/360) @ actual.view_matrix).T
                    expected_depth = projected[...,2]/projected[...,3]*.5+.5
                    near = expected & (expected_depth >= 0) & (expected_depth < .99999)
                    error = float(np.max(np.abs(depth[near]-expected_depth[near]))) if near.any() else 0.
                    name = 'h{}-pitch{}'.format(height, pitch)
                    Image.fromarray(images[1][::-1]).save(output/(name+'.png'))
                    report['coverage'].append(dict(height=height, pitch=pitch,
                        expected_ground_pixels=int(expected.sum()), sky_leak_pixels=leaked,
                        in_range_depth_max_error=error,
                        camera=api.get_shot_camera(), stats=dict(renderer.render_stats)))
                    print(name, 'sky_leak_pixels', leaked, flush=True)
            # Rays pointing away from the plane must retain the exact sky.
            api.set_shot_camera_pose(position=[0,0,20],target=[1,0,21])
            upward = []
            for ground in (False, True):
                api.set_atmosphere(ground=ground)
                render_scene_view(api._app.scene,api._app.shot_camera,renderer,target,(640,360))
                upward.append(bytes(gl.glReadPixels(0,0,640,360,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)))
            report['upward_sky_identical'] = upward[0] == upward[1]
            assert report['upward_sky_identical'], 'Ground changed upward sky rays'
            api.set_shot_camera_pose(position=[0,0,100],target=[0,0,0])
            render_scene_view(api._app.scene,api._app.shot_camera,renderer,target,(640,360))
            before_rgb = bytes(gl.glReadPixels(0,0,640,360,gl.GL_RGB,gl.GL_UNSIGNED_BYTE))
            before_depth = bytes(gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT))
            api.save_scene(output/'ground.scene.json')
            fresh = Mini3DAPI(renderer=renderer)
            fresh.load_scene(output/'ground.scene.json')
            render_scene_view(fresh._app.scene,fresh._app.shot_camera,renderer,target,(640,360))
            report['scene_v3_color_depth_identical'] = (
                before_rgb == bytes(gl.glReadPixels(0,0,640,360,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)) and
                before_depth == bytes(gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)))
            assert report['scene_v3_color_depth_identical'], 'Ground changed on scene reload'
            (output/'poses.json').write_text(json.dumps(
                [row['camera'] for row in report['coverage']],indent=2),encoding='utf8')
            if benchmark:
                api = Mini3DAPI(renderer=renderer)
                api.create_roman_street(segments=2)
                api.set_atmosphere(enabled=True, ground=True, haze=.005)
                api.set_shadows(enabled=True, resolution=2048)
                api.create_shot_camera(position=[9, -9, 4], target=[0, 0, 1],
                                       focal_mm=35, aspect='16:9', near=.05, far=150)
                cam = api._app.shot_camera

                # CPU submission excludes sync wait; complete frame includes GPU completion.
                for _ in range(20):
                    render_scene_view(api._app.scene, cam, renderer, target, (1280, 720))
                gl.glFinish()
                query = int(gl.glGenQueries(1)[0])
                complete, cpu, gpu = [], [], []
                try:
                    for i in range(60):
                        api.set_shot_camera_pose(position=[9+i*.002, -9, 4], target=[i*.002, 0, 1])
                        cam = api._app.shot_camera

                        start = time.perf_counter()
                        gl.glBeginQuery(gl.GL_TIME_ELAPSED, query)
                        render_scene_view(api._app.scene, cam, renderer, target, (1280, 720))
                        gl.glEndQuery(gl.GL_TIME_ELAPSED)
                        submitted = time.perf_counter()
                        gl.glFinish()
                        complete.append((time.perf_counter()-start)*1000)
                        cpu.append((submitted-start)*1000)
                        # PyOpenGL's uint64 converter is unreliable in the project Python env.
                        import ctypes
                        elapsed = ctypes.c_uint64()
                        from OpenGL.raw.GL.VERSION.GL_3_3 import glGetQueryObjectui64v
                        glGetQueryObjectui64v(query, gl.GL_QUERY_RESULT, ctypes.byref(elapsed))
                        gpu.append(elapsed.value/1e6)
                    report['timings'].append(dict(size=[1280,720], samples=60, warmup=20,
                        complete_ms=dict(zip(('p50','p95','p99'), np.percentile(complete,[50,95,99]))),
                        cpu_submit_ms=dict(zip(('p50','p95','p99'), np.percentile(cpu,[50,95,99]))),
                        gpu_ms=dict(zip(('p50','p95','p99'), np.percentile(gpu,[50,95,99]))),
                        raw_complete_ms=complete, raw_cpu_submit_ms=cpu, raw_gpu_ms=gpu,
                        stats=dict(renderer.render_stats)))
                finally:
                    gl.glDeleteQueries(1, [query])
                api.save_scene(output/'benchmark.scene.json')
            assert gl.glGetError() == gl.GL_NO_ERROR
        finally:
            target.close()
            renderer.close()
    (output/'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', choices=('python','native'), default='python')
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--allow-leaks', action='store_true', help='Record a known broken baseline')
    args = parser.parse_args()
    result = run(args.output, args.backend, args.benchmark)
    print(json.dumps([{k:v for k,v in row.items() if not k.startswith('raw_')}
                      for row in result['timings']], indent=2))
    if not args.allow_leaks:
        assert all(row['sky_leak_pixels']==0 for row in result['coverage']), 'Ground exposes sky'
        assert all(row['in_range_depth_max_error'] < 2e-5 for row in result['coverage']), 'Ground depth changed'
    if args.backend=='native':
        assert all(row['stats'].get('backend')=='native-photo' for row in result['coverage'])
