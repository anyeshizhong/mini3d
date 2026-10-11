"""Prepare aligned Q1 scenes and photograph them with the real Mini3D Shot API."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import statistics
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.geometry import make_box,make_sphere
from mini3d.gl_renderer import GLRenderer
from mini3d.placement import geometry_bounds
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import ShotCamera, render_shot
import photographer_session as fixture


def prepare(output,assets,hdr):
    output.mkdir(parents=True,exist_ok=True)
    fixture.OUT=output
    floor=fixture.asset('stage',make_box(1,1,1),(.18,.18,.18),rough=.85)
    source=output/'assets/studio_small_02_2k.hdr'
    expected='8dee8bd1f47b6e723284a58bd0a2db12e3cd3bc70283e17707d06b6b142065e0'
    assert hashlib.sha256(hdr.read_bytes()).hexdigest()==expected
    if hdr.resolve()!=source.resolve():shutil.copyfile(str(hdr),str(source))
    cases=[]
    for name in ('Lantern','Avocado','spheres'):
        api=Mini3DAPI()
        api.set_lighting(mode='Scene',direction=[-3,-4,6],ambient=.12,diffuse=2.0)
        api.set_environment(enabled=True,intensity=.35)
        api.set_shadows(enabled=True,resolution=1024,bias=.0003,pcf=True)
        api.spawn(floor,name='Ground',position=[0,0,-.1],scale=[12,12,.2])
        if name!='spheres':
            path=assets/name/(name+'.glb')
            item=api.spawn(path,name=name)
            low,high=geometry_bounds(api._entity(item['entity_id']))
            scale=2/(high[2]-low[2])
            api.set_transform(item['entity_id'],scale=[scale]*3,
                position=[-(low[0]+high[0])/2*scale,-(low[1]+high[1])/2*scale,-low[2]*scale])
            pos,aim=[3.4,-5.2,2.9],[0,0,1]
        else:
            geo=make_sphere(.55,40,64)
            for z,metal in ((.6,0),(1.9,1)):
                for x,rough in zip((-2.1,-.7,.7,2.1),(.08,.3,.6,1)):
                    path=fixture.asset('sphere-m%d-r%.2f'%(metal,rough),geo,(.55,.25,.07),metal=metal,rough=rough)
                    api.spawn(path,name=path.stem,position=[x,0,z])
            pos,aim=[0,-9,4.2],[0,0,1.25]
        api.create_shot_camera(position=pos,target=aim,focal_mm=50,aspect='16:9',near=.03,far=100)
        api._app.scene.update()
        api.save_scene(output/(name+'-mini-scene.json'))
        saved=output/(name+'-mini-scene.json')
        document=json.loads(saved.read_text())
        for obj in document['objects']:
            path=Path(obj['asset'])
            obj['asset']=(str(Path('model/11_benchmark_round01')/name/path.name)
                          if path.suffix=='.glb' else str(Path('docs/renderer-v2/q2/assets')/path.name)).replace('\\','/')
        saved.write_text(json.dumps(document,indent=2)+'\n',encoding='utf8')
        objects=[]
        for root in api._app.scene.root_entities:
            low,high=geometry_bounds(root)
            path=Path(root.asset_path)
            objects.append(dict(name=root.name,asset=path.name,fixture=path.suffix=='.gltf',
                position=root.pos.tolist(),rotation=root.rot.tolist(),scale=root.scale.tolist(),
                world_bounds=[low.tolist(),high.tolist()],sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        cam=api._app.shot_camera
        cases.append(dict(name=name,objects=objects,camera=api.get_shot_camera(),
            projection=cam.projection_matrix(cam.aspect).tolist(),lighting=api.get_lighting(),
            environment=api.get_environment(),shadows=api.get_shadows()))
    (output/'cases.json').write_text(json.dumps(dict(baseline='1481814',hdr_sha256=expected,
                  resolution=[1920,1080],cases=cases),indent=2)+'\n',encoding='utf8')


def load(api,output,name,assets):
    document=json.loads((output/(name+'-mini-scene.json')).read_text())
    for obj in document['objects']:
        path=Path(obj['asset'])
        obj['asset']=str(assets/name/path.name if path.suffix=='.glb' else output/'assets'/path.name)
    with tempfile.TemporaryDirectory(dir=str(ROOT/'captures')) as folder:
        path=Path(folder)/'scene.json';path.write_text(json.dumps(document))
        api.load_scene(path)


class DoubleShot(ShotCamera):
    # Quality reference only: same camera/projection, four times the pixel count.
    ASPECTS={name:(2*w,2*h) for name,(w,h) in ShotCamera.ASPECTS.items()}


def render(output,assets):
    pygame.init();pygame.display.set_mode((64,64),pygame.OPENGL|pygame.HIDDEN)
    renderer=GLRenderer(64,64);renderer.render_mode='REALISTIC'
    targets={s:RenderTarget(s) for s in (1,4)};high=RenderTarget()
    report=dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),gl=gl.glGetString(gl.GL_VERSION).decode(),
                resolution=[1920,1080],samples_per_mode=8,complete_capture_samples=3,cases=[])
    query=int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
    def draw(api,camera,target):
        render_shot(api._app.scene,camera,renderer,target)
        w,h=camera.size
        return np.frombuffer(gl.glReadPixels(0,0,w,h,gl.GL_RGB,gl.GL_UNSIGNED_BYTE),np.uint8).reshape(h,w,3)[::-1].copy()
    def save(rgb,path):
        pygame.image.save(pygame.image.fromstring(rgb.astype(np.uint8).tobytes(),(rgb.shape[1],rgb.shape[0]),'RGB'),str(path))
    try:
        for case in json.loads((output/'cases.json').read_text())['cases']:
            name=case['name'];api=Mini3DAPI(renderer);load(api,output,name,assets)
            camera=api._app.shot_camera
            row=dict(name=name,modes={})
            for s in (1,4):
                api.set_antialiasing(s)
                api.capture(output/(name+'-mini-%sx.png'%s))
                draw(api,camera,targets[s]);gl.glFinish()
                row['modes'][str(s)]=dict(gpu_ms=[],cpu_gpu_ms=[],capture_ms=[])
            # Alternating warm targets avoid allocation bias in GPU pass timings.
            for _ in range(8):
                for s in (1,4):
                    camera.set_samples(s);target=targets[s];gl.glFinish();start=time.perf_counter()
                    gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
                    render_shot(api._app.scene,camera,renderer,target)
                    gl.glEndQuery(gl.GL_TIME_ELAPSED);gl.glFinish()
                    row['modes'][str(s)]['cpu_gpu_ms'].append((time.perf_counter()-start)*1000)
                    row['modes'][str(s)]['gpu_ms'].append(int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6)
            for _ in range(3):
                for s in (1,4):
                    api.set_antialiasing(s);gl.glFinish();start=time.perf_counter()
                    api.capture(output/(name+'-mini-%sx.png'%s))
                    row['modes'][str(s)]['capture_ms'].append((time.perf_counter()-start)*1000)
            row['draw_calls']=dict(renderer.render_stats)
            double=DoubleShot.from_dict(dict(camera.to_dict(),samples=1))
            rgb=draw(api,double,high).astype(np.float32)
            rgb=rgb.reshape(1080,2,1920,2,3).mean(axis=(1,3))
            save(np.rint(rgb),output/(name+'-mini-ssaa2.png'))
            # Diagnostic coverage only: real geometry, no floor, white Unlit.
            api._app.scene.root_entities[0].visible=False
            for entity in api._app.scene.get_flat_render_list():
                if hasattr(entity.model,'material'):
                    entity.model.material=dict(pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1]),
                        extensions=dict(KHR_materials_unlit={}),
                        doubleSided=entity.model.material.get('doubleSided',False))
            masks={}
            for s in (1,4):
                camera.set_samples(s);masks[s]=draw(api,camera,targets[s])[:,:,0].astype(float)
            supersampled=draw(api,double,high)[:,:,0].astype(float).reshape(1080,2,1920,2).mean(axis=(1,3))
            # Store diagnostic mask to make the metric independently inspectable.
            for label,array in [('1',masks[1]),('4',masks[4]),('ssaa2',supersampled)]:
                save(np.repeat(np.rint(array)[:,:,None],3,axis=2),output/(name+'-coverage-'+label+'.png'))
            edge=(supersampled>30)&(supersampled<255)
            row['coverage_edge_pixels']=int(edge.sum())
            row['coverage_edge_mae_1x']=float(np.abs(masks[1]-supersampled)[edge].mean())
            row['coverage_edge_mae_4x']=float(np.abs(masks[4]-supersampled)[edge].mean())
            for values in row['modes'].values():
                values['medians']={key:statistics.median(value) for key,value in values.items()}
            report['cases'].append(row)
            assert gl.glGetError()==gl.GL_NO_ERROR
            print(name,json.dumps(row),flush=True)
        (output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    finally:
        gl.glDeleteQueries(1,[query]);high.close()
        for target in targets.values():target.close()
        renderer.close();pygame.quit()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'docs/renderer-v2/q2')
    p.add_argument('--assets-root',type=Path)
    p.add_argument('--hdr',type=Path)
    p.add_argument('--render-only',action='store_true',help='Use the saved cases without preparing them again')
    args=p.parse_args()
    if args.assets_root and not args.render_only:
        if not args.hdr:p.error('--hdr is required when preparing scenes')
        prepare(args.output.resolve(),args.assets_root.resolve(),args.hdr.resolve())
    render(args.output.resolve(),(args.assets_root or ROOT/'model/11_benchmark_round01').resolve())
