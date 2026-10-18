"""Roman Street, original lens/AA, saved scenes and warmed end-to-end GPU timings.

--baseline-ref restores source modules in memory and uses the backed-up DLL;
the working tree and installed DLL are never changed by the comparison.
"""
import argparse
import ctypes
import importlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

_DLL_HANDLES = []
if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
    for directory in (Path(sys.prefix), Path(sys.prefix)/'Library/bin', Path(sys.prefix)/'DLLs'):
        if directory.is_dir():
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def restore_baseline(ref, dll):
    for name in ('shadow_fit', 'shadow_map', 'material_shaders', 'material_renderer',
                 'render_plan', 'roman_assets', 'native_photo_bundle'):
        module = importlib.import_module('mini3d.'+name)
        source = subprocess.check_output(['git','show',ref+':mini3d/'+name+'.py'],cwd=str(ROOT))
        exec(compile(source, str(ROOT/'mini3d'/(name+'.py')), 'exec'), module.__dict__)
    original = ctypes.CDLL
    def load(path, *args, **kwargs):
        if Path(str(path)).name.lower() == 'spqr_photo.dll':
            path = str(dll.resolve())
        return original(path, *args, **kwargs)
    ctypes.CDLL = load


def run(args):
    os.environ['MINI3D_PHOTO_BACKEND'] = args.backend
    if args.backend == 'native':
        os.environ['MINI3D_REQUIRE_NATIVE_PHOTO'] = '1'
    args.output.mkdir(parents=True, exist_ok=True)
    if args.baseline_ref:
        restore_baseline(args.baseline_ref, args.baseline_dll)
        scene = args.output/'baseline.scene.json'
        scene.write_bytes(subprocess.check_output(['git','show',
            args.baseline_ref+':examples/roman_street/street.json'],cwd=str(ROOT)))
    else:
        scene = ROOT/'examples/roman_street/street.json'
    from OpenGL import GL as gl
    from OpenGL.raw.GL.VERSION.GL_3_3 import glGetQueryObjectui64v
    from PIL import Image
    from tools.capture_sunset import desktop_context
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.shot_camera import render_scene_view
    report = dict(backend=args.backend, baseline_ref=args.baseline_ref,
                  scene='examples/roman_street/street.json', size=[1081,662],
                  warmup=24, measured_frames=120, captures=[], paths=[])
    report['source_head'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=str(ROOT),text=True).strip()
    report['source_diff_sha256'] = hashlib.sha256(subprocess.check_output(['git','diff','HEAD'],cwd=str(ROOT))).hexdigest()
    library = args.baseline_dll if args.baseline_ref else ROOT/'native/spqr_photo.dll'
    report['native_dll_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest() if args.backend=='native' else None
    with desktop_context():
        gl.glPixelStorei(gl.GL_PACK_ALIGNMENT,1)
        report.update(gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                      driver=gl.glGetString(gl.GL_VERSION).decode())
        print('GPU:', report['gpu'], report['driver'], flush=True)
        renderer, target = GLRenderer(1081,662), RenderTarget()
        renderer.render_mode = 'REALISTIC'
        try:
            api = Mini3DAPI(renderer=renderer)
            api.load_scene(scene)
            initial = api.get_shot_camera()
            report.update(camera=initial, atmosphere=api.get_atmosphere(),
                          lighting=api.get_lighting(), shadows=api.get_shadows())
            p0 = np.asarray(initial['position'])
            rotation = np.asarray(initial['rotation'])
            forward = -rotation[:,2]
            query = int(gl.glGenQueries(1)[0])
            try:
                for label, delta in [('lateral',np.array([.2,0.,0.])),('dolly',forward*3.)]:
                    records, complete, cpu, gpu = [], [], [], []
                    for i in range(144):
                        u = max(0,i-24)/119
                        pose = dict(position=(p0+delta*u).tolist(),rotation=rotation.tolist())
                        api.set_shot_camera_pose(**pose)
                        cam = api._app.shot_camera
                        start = time.perf_counter()
                        gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
                        render_scene_view(api._app.scene,cam,renderer,target,(1081,662),samples=cam.samples)
                        gl.glEndQuery(gl.GL_TIME_ELAPSED)
                        submitted = time.perf_counter()
                        gl.glFinish()
                        end = time.perf_counter()
                        elapsed = ctypes.c_uint64()
                        glGetQueryObjectui64v(query,gl.GL_QUERY_RESULT,ctypes.byref(elapsed))
                        stats = dict(renderer.render_stats)
                        if args.backend == 'native':
                            assert stats.get('backend')=='native-photo',stats
                        if i>=24:
                            records.append(pose)
                            complete.append((end-start)*1000)
                            cpu.append((submitted-start)*1000)
                            gpu.append(elapsed.value/1e6)
                        if i in (24,84,143):
                            raw = gl.glReadPixels(0,0,1081,662,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
                            path = args.output/(label+'-'+str(i)+'.png')
                            Image.frombytes('RGB',(1081,662),raw).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(path)
                        assert gl.glGetError()==gl.GL_NO_ERROR
                    row = dict(label=label, poses=records, stats=stats)
                    for key,values in [('frame_ms',complete),('cpu_submit_ms',cpu),('gpu_ms',gpu)]:
                        row[key] = dict(zip(('p50','p95','p99'),np.percentile(values,[50,95,99])))
                        row['raw_'+key] = values
                    report['paths'].append(row)
                    print(label, row['frame_ms'], 'GPU',row['gpu_ms'],flush=True)
                # High camera: the continuation must cover every downward sky ray.
                for height in (20,100,300):
                    api.set_shot_camera_pose(position=[0,0,height],target=[0,0,0])
                    cam = api._app.shot_camera
                    try:
                        render_scene_view(api._app.scene,cam,renderer,target,(640,360),samples=cam.samples)
                    except ValueError as exc:
                        if not args.baseline_ref:
                            raise
                        report['captures'].append(dict(height=height,error=str(exc)))
                        continue
                    raw = gl.glReadPixels(0,0,640,360,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
                    Image.frombytes('RGB',(640,360),raw).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(
                        args.output/('overhead-'+str(height)+'.png'))
                    raw = gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)
                    depth = np.frombuffer(raw,np.float32)
                    report['captures'].append(dict(height=height,sky_pixels=int((depth==1.).sum()),
                                                   camera=api.get_shot_camera()))
                api.save_scene(args.output/'verified.scene.json')
            finally:
                gl.glDeleteQueries(1,[query])
        finally:
            target.close()
            renderer.close()
    (args.output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    if not args.baseline_ref:
        assert all(row['sky_pixels']==0 for row in report['captures']), 'Street overhead exposes sky'
    return report


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=('native','python'),default='native')
    parser.add_argument('--baseline-ref')
    parser.add_argument('--baseline-dll',type=Path,
        default=ROOT/'captures/visual-integrity-20261017/spqr_photo.before.dll')
    run(parser.parse_args())
