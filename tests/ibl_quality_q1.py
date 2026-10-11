"""Real Mini3D A/B PNGs and GL regressions. Uses local licensed glTF assets.

--engine-root can select the untouched dfcca0d worktree to prove A is original V2.
Never imports a reference renderer or substitutes generated imagery for Mini3D.
"""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--assets-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--engine-root', type=Path, default=ROOT)
parser.add_argument('--baseline', action='store_true')
parser.add_argument('--original', type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.engine_root))
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.geometry import make_box, make_sphere
from mini3d.gl_renderer import GLRenderer
from mini3d.placement import geometry_bounds
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot
import photographer_session as fixture
sys.path.remove(str(args.engine_root))
sys.path.insert(0, str(args.engine_root))  # Fixture helper inserts its own ROOT.


def run():
    args.output.mkdir(parents=True, exist_ok=True)
    fixture.OUT = ROOT/'captures/q1-fixtures'
    ground = fixture.asset('stage', make_box(1,1,1), (.18,.18,.18), rough=.85)
    sphere_geometry = make_sphere(.55,40,64)
    pygame.init(); pygame.display.set_mode((64,64), pygame.OPENGL | pygame.HIDDEN)
    renderer, target = GLRenderer(64,64), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    report = dict(baseline=args.baseline, gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                  gl_version=gl.glGetString(gl.GL_VERSION).decode(),
                  texture_units=int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_IMAGE_UNITS)),
                  resolution=[1920,1080], exposure=1.0, environment_intensity=.35,
                  cases=[], checks={})
    report['baseline_commit']='dfcca0de6465d70e4cdcc8881a7f4c4d8084ace3'
    report['sphere_materials']=dict(base_color_linear=[.55,.25,.07],top_row_metallic=1,
                                    bottom_row_metallic=0,roughness_left_to_right=[.08,.3,.6,1.0])

    def setup():
        api = Mini3DAPI(renderer)
        api.set_lighting(mode='Scene', direction=[-3,-4,6], ambient=.12, diffuse=2.0)
        api.set_shadows(enabled=True, resolution=1024, bias=.0003, pcf=True)
        api.spawn(ground, name='Ground', position=[0,0,-.1], scale=[12,12,.2])
        return api

    def draw(api):
        api._app.scene.update()
        render_shot(api._app.scene, api._app.shot_camera, renderer, target)
        rgb = np.frombuffer(gl.glReadPixels(0,0,1920,1080,gl.GL_RGB,gl.GL_UNSIGNED_BYTE),np.uint8).reshape(1080,1920,3).copy()
        depth = np.asarray(gl.glReadPixels(0,0,1920,1080,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)).reshape(1080,1920).copy()
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return rgb,depth

    def take(api, name):
        rgb, depth = draw(api)
        path = args.output/(name+'.png')
        # glReadPixels is bottom-first; public capture exports top-first.
        api.capture(path)
        saved = pygame.image.tostring(pygame.image.load(str(path)),'RGB',True)
        assert saved == rgb.tobytes(), 'Public capture must match Shot render'
        query = int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
        wall, gpu = [], []
        for _ in range(7):
            gl.glFinish(); start = time.perf_counter()
            gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
            render_shot(api._app.scene,api._app.shot_camera,renderer,target)
            gl.glEndQuery(gl.GL_TIME_ELAPSED); gl.glFinish()
            wall.append((time.perf_counter()-start)*1000)
            gpu.append(int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6)
        gl.glDeleteQueries(1,[query])
        case = dict(name=name,camera=api.get_shot_camera(),lighting=api.get_lighting(),shadows=api.get_shadows(),
                    environment=api.get_environment() if hasattr(api,'get_environment') else dict(enabled=False,intensity=.35),
                    gpu_ms=statistics.median(gpu[2:]),cpu_gpu_ms=statistics.median(wall[2:]),
                    png_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),draw_calls=dict(renderer.render_stats))
        report['cases'].append(case)
        print(name, round(case['gpu_ms'],2), round(case['cpu_gpu_ms'],2), flush=True)
        return rgb,depth

    def paired_timing(api):
        query=int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
        samples={False:dict(gpu=[],wall=[]),True:dict(gpu=[],wall=[])}
        try:
            for iteration in range(15):
                for enabled in ((False,True) if iteration%2==0 else (True,False)):
                    api.set_environment(enabled=enabled)
                    gl.glFinish();start=time.perf_counter()
                    gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
                    render_shot(api._app.scene,api._app.shot_camera,renderer,target)
                    gl.glEndQuery(gl.GL_TIME_ELAPSED);gl.glFinish()
                    wall=(time.perf_counter()-start)*1000
                    gpu=int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6
                    if iteration>=3:
                        samples[enabled]['gpu'].append(gpu);samples[enabled]['wall'].append(wall)
            return {('B' if k else 'A'):dict(gpu_median_ms=statistics.median(v['gpu']),
                     gpu_p95_ms=float(np.percentile(v['gpu'],95)),cpu_gpu_median_ms=statistics.median(v['wall']),
                     cpu_gpu_p95_ms=float(np.percentile(v['wall'],95)),samples=len(v['gpu'])) for k,v in samples.items()}
        finally: gl.glDeleteQueries(1,[query])

    def pair(api,name):
        a,da = take(api,name+'-A')
        if args.baseline: return
        if args.original:
            old = pygame.image.tostring(pygame.image.load(str(args.original/(name+'-A.png'))),'RGB',True)
            assert old == a.tobytes(), 'Disabled IBL must match untouched dfcca0d: '+name
        api.set_environment(enabled=True, intensity=.35)
        b,db = take(api,name+'-B')
        np.testing.assert_array_equal(da,db)
        changed = np.any(a != b,axis=2)
        assert np.count_nonzero(changed) > 1000
        report['checks'][name] = dict(disabled_matches_original=bool(args.original),depth_identical=True,
                                      changed_pixels=int(changed.sum()),max_channel=int(b.max()),
                                      saturated_pixels=int(np.any(b>=254,axis=2).sum()))
        report.setdefault('paired_timing',{})[name]=paired_timing(api)
        api.set_environment(enabled=True)
        scene_path=ROOT/'captures/q1-fixtures'/(name+'-scene.json')
        api.save_scene(scene_path)
        fresh = Mini3DAPI(renderer); fresh.load_scene(scene_path)
        c,dc = draw(fresh); np.testing.assert_array_equal(b,c); np.testing.assert_array_equal(db,dc)
        report['checks'][name]['save_load_pixels_identical']=True
        api.set_environment(enabled=False); c,_=draw(api); np.testing.assert_array_equal(a,c)
        if name == 'spheres': extra_checks(api,b,db)

    def extra_checks(api, reference, depth):
        api.set_environment(enabled=True)
        env = renderer.material_renderer.environment
        handles = list(env.handles)
        # Resource sharing and changed camera/light/model must take effect.
        for _ in range(3): draw(api)
        assert handles == renderer.material_renderer.environment.handles
        report['texture_bytes'] = env.texture_bytes
        api.set_lighting(direction=[3,4,2]); c,_=draw(api); assert np.any(c != reference)
        api.set_lighting(direction=[-3,-4,6])
        old = api.get_shot_camera()
        api.create_shot_camera(position=[-5,-9,6],target=[0,0,1.0],focal_mm=50,aspect='16:9')
        c,_=draw(api); assert np.any(c != reference)
        api._app.shot_camera = api._app.shot_camera.from_dict(old)
        entity = api._app.scene.root_entities[1]
        entity.pos[:] += [0,.2,.1]; c,_=draw(api); assert np.any(c != reference)
        entity.pos[:] -= [0,.2,.1]
        # Unlit ignores every lighting contribution, including IBL.
        meshes = [e.model for e in api._app.scene.get_flat_render_list() if e.model.material is not None]
        backup = [json.loads(json.dumps(m.material,default=str)) for m in meshes]  # Fixtures have no image bytes.
        for m in meshes: m.material.setdefault('extensions',{})['KHR_materials_unlit'] = {}
        u,_=draw(api); api.set_environment(enabled=False); v,_=draw(api); np.testing.assert_array_equal(u,v)
        for m,material in zip(meshes,backup): m.material = material
        # Caller-owned 2D/cube bindings, active unit, seamless and unpack state survive.
        dummy = [int(x) for x in gl.glGenTextures(3)]
        for unit,h in zip((8,9),dummy[:2]):
            gl.glActiveTexture(gl.GL_TEXTURE0+unit); gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP,h)
        gl.glActiveTexture(gl.GL_TEXTURE0+10); gl.glBindTexture(gl.GL_TEXTURE_2D,dummy[2])
        gl.glActiveTexture(gl.GL_TEXTURE0+4); gl.glDisable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)
        api.set_environment(enabled=True)
        before = renderer.material_renderer._save_state(); renderer.material_renderer._restore_state(before)
        renderer.material_renderer.render(api._app.scene.get_flat_render_list(),api._app.shot_camera,
                                          api._app.scene,1920,1080)
        after = renderer.material_renderer._save_state(); renderer.material_renderer._restore_state(after)
        for k in ('textures','cubemaps','ACTIVE_TEXTURE','enabled'): assert before[k] == after[k],k
        gl.glDeleteTextures(dummy)
        report['checks']['unlit_state_and_resource_reuse'] = True
        renderer.material_renderer.release()
        assert all(not gl.glIsTexture(h) for h in handles)
        draw(api)
        assert renderer.material_renderer.environment is not None
        report['checks']['release_recreate'] = True

    try:
        for name in ('DamagedHelmet','Lantern','Avocado'):
            path = args.assets_root/name/(name+'.glb')
            if not path.is_file(): raise FileNotFoundError('Real model required: '+str(path))
            api = setup(); item = api.spawn(path,name=name)
            low,high = geometry_bounds(api._entity(item['entity_id']))
            scale = 2/(high[2]-low[2])
            api.set_transform(item['entity_id'],scale=[scale]*3,
                              position=[-(low[0]+high[0])/2*scale,-(low[1]+high[1])/2*scale,-low[2]*scale])
            api.create_shot_camera(position=[3.4,-5.2,2.9],target=[0,0,1],focal_mm=50,aspect='16:9',near=.03,far=100)
            pair(api,name)
            report['cases'][-1]['asset_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        api = setup()
        for z,metal in ((.6,0),(1.9,1)):
            for x,rough in zip((-2.1,-.7,.7,2.1),(.08,.3,.6,1.0)):
                sphere = fixture.asset('sphere-m%d-r%.2f'%(metal,rough),sphere_geometry,
                                       (.55,.25,.07),metal=metal,rough=rough)
                api.spawn(sphere,position=[x,0,z])
        api.create_shot_camera(position=[0,-9,4.2],target=[0,0,1.25],focal_mm=50,aspect='16:9',near=.03,far=100)
        pair(api,'spheres')
        shader_path=Path(inspect.getfile(renderer.material_renderer.__class__))
        report['material_shader_source']=str(shader_path.relative_to(args.engine_root))
        report['material_shader_source_sha256']=hashlib.sha256(shader_path.read_bytes()).hexdigest()
        report['checks']['gl_error_zero'] = gl.glGetError() == gl.GL_NO_ERROR
        (args.output/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    finally:
        target.close(); renderer.close(); renderer.close(); pygame.quit()


if __name__ == '__main__': run()
