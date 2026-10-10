"""Separate CPU fit scaling from synchronized real Rome+40 Shot rendering.

cpu-proxy: original simple geometry, counts/hierarchy only, NOT real asset timing.
real: requires the two original GLBs; never silently replaces missing models.
No production edits, assets and output stay local.
"""
import os
if os.name != 'nt' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('SDL_VIDEODRIVER','offscreen')
if os.environ.get('SDL_VIDEODRIVER')=='offscreen':
    os.environ.setdefault('PYOPENGL_PLATFORM','egl')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from mini3d.scene import Entity,Mesh,Scene
from mini3d.camera import Camera
from mini3d.geometry import make_box
from mini3d.shot_camera import ShotCamera,render_shot
from mini3d.shadow_fit import receiver_matrix
from mini3d import shadow_fit,shadow_map
from mini3d.shadow_map import light_matrix


def stats(values):
    return dict(samples=len(values),median_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)),
                min_ms=float(min(values)),max_ms=float(max(values)))


def measure(function,samples=51,warm=5):
    for _ in range(warm): function()
    values=[]
    for _ in range(samples):
        start=time.perf_counter();function();values.append((time.perf_counter()-start)*1000)
    return stats(values)


def nodes(scene):
    def walk(e):
        yield e
        for child in e.children: yield from walk(child)
    return [e for root in scene.root_entities for e in walk(root)]


def counts(scene):
    render=scene.get_flat_render_list()
    return dict(roots=len(scene.root_entities),hierarchy_nodes=len(nodes(scene)),render_entities=len(render),
                submitted_triangles=sum(len(e.model.indices) for e in render),
                shared_meshes=len({id(e.model) for e in render}))


def intersection_counts(entities,light,cam,resolution):
    original=shadow_fit._intersection
    result=dict(contained=0,rejected=0,partial=0,total=0)
    def wrapped(bounds,world,planes,corners):
        local=planes@world;local/=np.linalg.norm(local[:,:3],axis=1)[:,None]
        box=shadow_fit._corners(bounds);tol=max(float(np.max(np.abs(box)))*1e-9,1e-12)
        d=box@local[:,:3].T+local[:,3]
        kind='contained' if (d>=-tol).all() else 'rejected' if (d.max(axis=0)<-tol).any() else 'partial'
        result[kind]+=1;result['total']+=1
        return original(bounds,world,planes,corners)
    with patch.object(shadow_fit,'_intersection',side_effect=wrapped):
        fitted=receiver_matrix(entities,light,cam,resolution)
    result['fallback']=fitted is None
    return result


def paired_fit(entities,light,cam,samples):
    # Alternate ordering to reduce systematic warm-up/thermal bias.
    whole,camera,delta=[],[],[]
    for _ in range(5): light_matrix(entities,light);light_matrix(entities,light,cam,1024)
    for i in range(samples):
        times={}
        for kind in (('whole','camera') if i%2==0 else ('camera','whole')):
            start=time.perf_counter()
            matrix=light_matrix(entities,light,cam if kind=='camera' else None,1024)
            assert matrix is not None and np.isfinite(matrix).all()
            times[kind]=(time.perf_counter()-start)*1000
        whole.append(times['whole']);camera.append(times['camera']);delta.append(times['camera']-times['whole'])
    return dict(whole_scene=stats(whole),camera_fit=stats(camera),paired_extra=stats(delta))


def proxy_scene(count,background=0,depth=1):
    scene=Scene();mesh=Mesh(*make_box(1,1,1))
    floor=Entity(mesh,'Ground');floor.pos[:]=[0,0,-.1];floor.scale[:]=[200,200,.2];scene.add(floor)
    parts=[([0,0,.85],[.45,.3,.75]),([0,0,1.4],[.3,.3,.3]),
           ([-.3,0,.9],[.18,.2,.65]),([.3,0,.9],[.18,.2,.65]),
           ([-.14,0,.28],[.2,.24,.55]),([.14,0,.28],[.2,.24,.55])]
    for i in range(count):
        root=Entity(name=f'Proxy-{i}');root.pos[:]=[i%8*1.2,i//8*1.4,0];scene.add(root)
        branch=root
        for j in range(depth-1):
            child=Entity(name=f'Hierarchy-{j}');branch.add_child(child);branch=child
        for position,scale in parts:
            leaf=Entity(mesh,'Proxy part');leaf.pos[:]=position;leaf.scale[:]=scale;branch.add_child(leaf)
    for i in range(background):
        e=Entity(mesh,'Synthetic background');e.pos[:]=[(i%8-4)*4,(i//8-4)*4,2]
        e.scale[:]=[2,2,4];e.rot[2]=(i%5)*.17;scene.add(e)
    scene.update();return scene


def shot(position,target,lens=50):
    cam=Camera(position,near=.05,far=400);cam.look_at(target)
    cam=ShotCamera(cam);cam.set_lens(lens);cam.set_aspect('16:9');return cam


def environment():
    cpu='unknown'
    if Path('/proc/cpuinfo').exists():
        cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),cpu)
    return dict(python=platform.python_version(),platform=platform.platform(),cpu=cpu,logical_cpus=os.cpu_count(),
                openblas_threads=os.environ.get('OPENBLAS_NUM_THREADS','default'),
                commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())


def cpu_proxy(output,samples):
    report=dict(environment=environment(),mode='SYNTHETIC CPU ONLY: not Rome/legionnaire geometry or real GPU performance',runs=[])
    light=np.array([-3,-2,3.]);light/=np.linalg.norm(light)
    cases=[('simple-2',0,0,1,False),('one-6parts',1,0,1,False),('40-6parts',40,0,1,False),
           ('100-6parts',100,0,1,False),('40-deep',40,0,4,False),
           ('40-background64',40,64,4,False),('40-close-frustum',40,64,4,True)]
    for name,count,background,depth,close in cases:
        scene=proxy_scene(count,background,depth)
        if name=='simple-2':
            e=Entity(scene.root_entities[0].model,'Box');e.pos[:]=[0,0,1];e.scale[:]=[1,1,2];scene.add(e);scene.update()
        cam=shot([10,-14,10],[4.2,3.0,0]) if not close else shot([3,-3,2],[4,2,1],85)
        entities=scene.get_flat_render_list()
        record=dict(name=name,counts=counts(scene),camera=cam.to_dict(),intersection_work=intersection_counts(entities,light,cam,1024),
                    fitting=paired_fit(entities,light,cam,samples),scene_update=measure(scene.update,samples),
                    flatten=measure(scene.get_flat_render_list,samples))
        report['runs'].append(record);output.write_text(json.dumps(report,indent=2))
        print(name,record['counts'],record['fitting'],flush=True)
    return report


def real(output,rome,soldier,gpu_samples,cpu_samples,resolutions,fixture_smoke=False):
    missing=[str(p) for p in (rome,soldier) if not p.is_file()]
    if missing:
        result=dict(status='BLOCKED_MISSING_REAL_ASSETS',missing=missing,environment=environment(),
                    note='No substitute model is used. Provide the original local GLBs and rerun real mode.')
        output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return 2
    import pygame
    from OpenGL import GL as gl
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.lighting import scene_light_direction
    from mini3d.placement import geometry_bounds
    from mini3d.render_target import RenderTarget
    pygame.init();pygame.display.set_mode((800,600),pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer,target=GLRenderer(800,600),RenderTarget();renderer.render_mode='REALISTIC'
    report=dict(status='RUNNING_FIXTURE_SMOKE' if fixture_smoke else 'RUNNING_REAL_ASSETS',environment=environment(),renderer=gl.glGetString(gl.GL_RENDERER).decode(),
                gl=gl.glGetString(gl.GL_VERSION).decode(),assets=[],runs=[],
                layout='Rome longest XY span normalized to 40; soldiers height 1.7, 5x8 includes source. Default layout is reproducible, not earlier user scene.')
    for p in (rome,soldier): report['assets'].append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    try:
        api=Mini3DAPI(renderer);background=api.spawn(rome,name='Rome')['entity_id']
        lo,hi=geometry_bounds(api._entity(background));factor=40/max((hi-lo)[:2])
        api.set_transform(background,scale=[factor]*3,position=[-(lo[0]+hi[0])/2*factor,-(lo[1]+hi[1])/2*factor,-lo[2]*factor]);api.lock(background)
        figure=api.spawn(soldier,name='Legionnaire')['entity_id'];lo,hi=geometry_bounds(api._entity(figure));factor=1.7/(hi[2]-lo[2])
        api.set_transform(figure,scale=[factor]*3,position=[-4.2-(lo[0]+hi[0])/2*factor,-2.8-(lo[1]+hi[1])/2*factor,-lo[2]*factor])
        api.create_rectangular_formation(figure,5,8,1.2,1.4)
        scene=api._app.scene;scene.update();entities=scene.get_flat_render_list()
        api.set_lighting(mode='Scene',direction=[-3,-2,3],ambient=.3,diffuse=3)
        report['counts']=counts(scene)
        print('FIXTURE COUNTS' if fixture_smoke else 'REAL COUNTS',report['counts'],flush=True)
        for view,position,target_point,lens in [('overview',[25,-32,25],[0,0,3],35),('legion-close',[9,-12,7],[0,0,1],50)]:
            api.create_shot_camera(position=position,target=target_point,focal_mm=lens,aspect='16:9',near=.05,far=400)
            cam=api._app.shot_camera;light=scene_light_direction(scene)
            fitting=paired_fit(entities,light,cam,cpu_samples)
            for resolution in resolutions:
                api.set_shadows(enabled=True,resolution=resolution,bias=.0003,pcf=True)
                # Preload real geometry/textures and allocate the same framebuffer.
                render_shot(scene,cam,renderer,target);gl.glFinish()
                record=dict(view=view,resolution=resolution,camera=cam.to_dict(),fitting=fitting,
                            intersection_work=intersection_counts(entities,light,cam,resolution),passes={})
                for mode in ('off','whole-scene','camera-fit'):
                    scene.shadows_enabled=mode!='off'
                    def draw():
                        gl.glFinish()
                        if mode=='whole-scene':
                            original=shadow_map.light_matrix
                            with patch.object(shadow_map,'light_matrix',side_effect=lambda es,d,c=None,r=1024:original(es,d,None,r)):
                                render_shot(scene,cam,renderer,target)
                        else: render_shot(scene,cam,renderer,target)
                        gl.glFinish()
                    record['passes'][mode]=measure(draw,gpu_samples,3)
                    assert gl.glGetError()==gl.GL_NO_ERROR
                    if mode=='camera-fit': api.capture(output.parent/f'{view}-{resolution}.png')
                scene.shadows_enabled=True
                report['runs'].append(record);output.write_text(json.dumps(report,indent=2));print('FIXTURE RESULT' if fixture_smoke else 'REAL RESULT',view,resolution,record['passes'],flush=True)
        report['status']='COMPLETED_FIXTURE_SMOKE_NOT_ROME' if fixture_smoke else 'COMPLETED_REAL_ASSETS';report['all_gl_errors_zero']=gl.glGetError()==gl.GL_NO_ERROR
        output.write_text(json.dumps(report,indent=2))
    finally: target.close();renderer.close();pygame.quit()
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('cpu-proxy','real','fixture-smoke'))
    parser.add_argument('--output',type=Path);parser.add_argument('--cpu-samples',type=int,default=51)
    parser.add_argument('--gpu-samples',type=int,default=9);parser.add_argument('--resolutions',type=int,nargs='+',default=[1024,4096])
    parser.add_argument('--rome',type=Path,default=ROOT/'model/08_rome_river/rome_river_side.glb')
    parser.add_argument('--soldier',type=Path,default=ROOT/'model/05_roman_soldier/roman_legionnaire.glb')
    args=parser.parse_args();output=args.output or ROOT/f'captures/shadow-performance-20261010/{args.mode}.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    if args.mode=='cpu-proxy': cpu_proxy(output,args.cpu_samples)
    elif args.mode=='fixture-smoke':
        import photographer_session as fixture
        fixture.OUT=output.parent/'harness-fixtures'
        ground=fixture.asset('ground',make_box(1,1,1),(.4,.4,.4))
        figure=fixture.asset('figure-box',make_box(.4,.3,1.7),(.7,.3,.08))
        sys.exit(real(output,ground,figure,args.gpu_samples,args.cpu_samples,args.resolutions,fixture_smoke=True))
    else: sys.exit(real(output,args.rome,args.soldier,args.gpu_samples,args.cpu_samples,args.resolutions))
