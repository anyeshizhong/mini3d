"""Repeatable original-geometry and local PBR photography, with real GPU timing.

All generated assets/PNGs stay under captures. Never downloads or uploads GLBs.
python -B tests/render_quality_v1.py baseline [--output captures/render-quality-v1/baseline]
"""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import statistics
import struct
import sys
import time

import photographer_session as fixture
ROOT = fixture.ROOT
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.placement import geometry_bounds
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot


def glb_inventory(path):
    raw = path.read_bytes()
    length = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20+length])
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(), asset=doc.get('asset'),
                extensions_required=doc.get('extensionsRequired', []),
                extensions_used=doc.get('extensionsUsed', []),
                materials=doc.get('materials', []), textures=len(doc.get('textures', [])))


def run(label, output):
    output.mkdir(parents=True, exist_ok=True)
    fixture.OUT = ROOT / 'captures/render-quality-v1'
    box = fixture.asset('quality-box', fixture.make_box(1,1,1), (.7,.3,.08), rough=.7)
    floor = fixture.asset('quality-floor', fixture.make_box(1,1,1), (.4,.4,.4), rough=.85)
    sphere = fixture.asset('quality-metal', fixture.make_sphere(.7,40,64), (.9,.4,.1), metal=1, rough=.2)
    cylinder = fixture.asset('quality-cylinder', fixture.make_cylinder(.4,1,48), (.08,.25,.55), rough=.6, upright=True)
    unlit = fixture.asset('quality-unlit', fixture.make_box(1,1,1), (.1,.8,.2))
    doc = json.loads(unlit.read_text())
    doc['materials'][0]['extensions'] = {'KHR_materials_unlit': {}}
    unlit.write_text(json.dumps(doc), encoding='utf8')
    pygame.init()
    pygame.display.set_mode((800,600), pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer, target = GLRenderer(800,600), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    report = dict(label=label, gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                  gl=gl.glGetString(gl.GL_VERSION).decode(), runs=[], assets=[], checks={})

    def setup():
        api = Mini3DAPI(renderer)
        api.set_lighting(mode='Scene', direction=[-3,-2,3], ambient=.3, diffuse=3)
        api.set_shadows(enabled=True, resolution=1024, bias=.0003, pcf=True)
        return api

    def draw(api):
        api._app.scene.update()
        render_shot(api._app.scene, api._app.shot_camera, renderer, target)
        size = api._app.shot_camera.size
        rgb = np.frombuffer(gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE), np.uint8).reshape(size[1],size[0],3).copy()
        depth = np.asarray(gl.glReadPixels(0,0,*size,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT),np.float32).reshape(size[1],size[0]).copy()
        assert gl.glGetError() == gl.GL_NO_ERROR
        return rgb, depth

    def measure(api):
        # Time the shadow pass separately; include CPU fitting in the wall metric.
        scene = api._app.scene
        entities = scene.get_flat_render_list()
        extra = dict(camera=api._app.shot_camera) if 'camera' in inspect.signature(renderer.shadow_map.render).parameters else {}
        query = int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
        gpu, wall = [], []
        for _ in range(7):
            gl.glFinish()
            started = time.perf_counter()
            gl.glBeginQuery(gl.GL_TIME_ELAPSED, query)
            renderer.shadow_map.render(entities,scene,renderer,**extra)
            gl.glEndQuery(gl.GL_TIME_ELAPSED)
            gl.glFinish()
            wall.append((time.perf_counter()-started)*1000)
            gpu.append(int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6)
        gl.glDeleteQueries(1,[query])
        return dict(shadow_gpu_ms=statistics.median(gpu[2:]),
                    shadow_cpu_gpu_ms=statistics.median(wall[2:]))

    def take(api, name, category, timed=True):
        api.capture(output/(name+'.png'))
        rgb, depth = draw(api)
        encoded = pygame.image.tostring(pygame.image.load(str(output/(name+'.png'))),'RGB',True)
        assert encoded == rgb.tobytes(), 'Shot PNG must match render_shot'
        api.save_scene(output/(name+'.json'))
        record = dict(name=name, category=category, camera=api.get_shot_camera(),
                      lighting=api.get_lighting(), shadows=api.get_shadows(),
                      entities=api.list_entities(), gl_error=int(gl.glGetError()),
                      camera_depth_sha256=hashlib.sha256(depth.tobytes()).hexdigest(),
                      png_sha256=hashlib.sha256((output/(name+'.png')).read_bytes()).hexdigest())
        if api.get_shadows()['enabled']:
            matrix = renderer.shadow_map.matrix
            ranges = 2 / np.linalg.norm(matrix[:3,:3],axis=1)
            record.update(light_space_extent=ranges.tolist(),
                          world_units_per_texel=(ranges[:2]/api.get_shadows()['resolution']).tolist(),
                          normalized_bias_world_depth=float(api.get_shadows()['bias']*ranges[2]))
            if timed:
                record.update(measure(api))
        report['runs'].append(record)
        (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(name, record.get('world_units_per_texel'), record.get('shadow_gpu_ms'), flush=True)
        return rgb, depth

    def probe(api, rgb, world):
        cam = api._app.shot_camera
        p = cam.projection_matrix(cam.aspect) @ cam.view_matrix @ np.append(world,1)
        xy = ((p[:2]/p[3]+1)*np.asarray(cam.size)/2).astype(int)
        assert 2 <= xy[0] < cam.size[0]-2 and 2 <= xy[1] < cam.size[1]-2
        return np.median(rgb[xy[1]-1:xy[1]+2,xy[0]-1:xy[0]+2],axis=(0,1))

    try:
        api = setup()
        ground = api.spawn(floor, name='Ground', position=[0,0,-.1], scale=[10,10,.2])['entity_id']
        api.spawn(box, name='Subject', position=[0,0,1], scale=[1,1,2])
        api.create_shot_camera(position=[7,9,13], target=[.6,.5,0], focal_mm=50,aspect='4:3',near=.05,far=400)
        for span in (10,32,200):
            api.set_transform(ground,scale=[span,span,.2])
            for resolution in (1024,4096):
                api.set_shadows(resolution=resolution)
                take(api, 'ground-%d-%d'%(span,resolution),'controlled-ground')
        api.set_shadows(enabled=False)
        off,d0 = take(api,'ground-200-off','controlled-ground',False)
        api.set_shadows(enabled=True,resolution=1024)
        on,d1 = draw(api)
        np.testing.assert_array_equal(d0,d1)
        report['checks']['ground_off_on_camera_depth_identical'] = True
        # Geometry/multiple views, changed directional light, metal and Unlit.
        api = setup()
        api.spawn(floor, name='Ground',position=[0,0,-.1],scale=[32,32,.2])
        api.spawn(box,name='Box',position=[-1.5,0,.8],scale=[1,1,1.6])
        api.spawn(sphere,name='Metal sphere',position=[0,0,.7])
        api.spawn(cylinder,name='Cylinder',position=[1.5,.2,1.2],scale=[1,1,2.4])
        api.spawn(unlit,name='Unlit marker',position=[-2,2,.5])
        views = [('geometry-front',[7,-10,6.5],[0,0,1],[-3,-4,6],50),
                 ('geometry-reverse',[-7,10,5],[0,0,1],[3,4,3],50),
                 ('geometry-close',[.2,-4,1.8],[0,0,.7],[-3,-4,6],85),
                 ('geometry-far',[14,-20,13],[0,0,1],[-3,-4,6],50)]
        for name,pos,aim,light,lens in views:
            api.create_shot_camera(position=pos,target=aim,focal_mm=lens,aspect='16:9',near=.03,far=200)
            api.set_lighting(direction=light)
            take(api,name,'geometry')
        api.create_shot_camera(position=views[0][1],target=[0,0,1],focal_mm=50,aspect='16:9',near=.03,far=200)
        api.set_lighting(direction=views[0][3])
        api.set_shadows(enabled=False)
        off,d0=take(api,'geometry-off','geometry',False)
        api.set_shadows(enabled=True)
        on,d1=draw(api)
        np.testing.assert_array_equal(d0,d1)
        np.testing.assert_array_equal(probe(api,off,[-2,2,1]),probe(api,on,[-2,2,1]))
        report['checks']['geometry_off_on_depth_and_unlit_preserved']=True
        # Offscreen casters, including a long low-sun ray entering the image.
        for name, light, caster in [('offscreen',[1,0,1],[4,0,4]),
                                    ('offscreen-low-sun',[1,0,.2],[20,0,4])]:
            api=setup()
            api.spawn(floor,name='Ground',position=[0,0,-.1],scale=[200,200,.2])
            item=api.spawn(box,name='Offscreen caster',position=caster)
            api.set_lighting(direction=light)
            api.create_shot_camera(position=[0,0,8],target=[0,0,0],focal_mm=85,aspect='1:1',near=.01,far=100)
            on,d1=take(api,name,'offscreen-caster')
            api.set_shadows(enabled=False)
            off,d0=take(api,name+'-off','offscreen-caster',False)
            np.testing.assert_array_equal(d0,d1)
            shadow_drop=float(np.mean(probe(api,off,[0,0,0])-probe(api,on,[0,0,0])))
            report['checks'][name]=dict(origin_shadow_drop=shadow_drop, caster_position=item['position'],depth_identical=True)
            # Low sun reduces N dot L and therefore the maximum direct-light drop.
            assert shadow_drop>5, (name,shadow_drop)
        # Three already downloaded PBR assets; no external model changes.
        for name in ('DamagedHelmet','Lantern','Avocado'):
            path=ROOT/'model/11_benchmark_round01'/name/(name+'.glb')
            inventory=glb_inventory(path)
            api=setup()
            api.spawn(floor,name='Ground',position=[0,0,-.1],scale=[200,200,.2])
            item=api.spawn(path,name=name)
            entity=api._entity(item['entity_id'])
            low,high=geometry_bounds(entity)
            scale=2/(high[2]-low[2])
            api.set_transform(item['entity_id'],scale=[scale]*3,
                              position=[-(low[0]+high[0])/2*scale,-(low[1]+high[1])/2*scale,-low[2]*scale])
            def walk(root):
                yield root
                for child in root.children:
                    yield from walk(child)
            inventory['loaded_textures']=[sorted(e.model.material.get('textures',{})) for e in walk(entity)
                                           if e.model is not None and e.model.material is not None]
            report['assets'].append(inventory)
            for suffix,pos,light in [('front',[4,-6,3.5],[-3,-4,6]),('reverse',[-4,6,3.5],[3,4,3])]:
                api.create_shot_camera(position=pos,target=[0,0,1],focal_mm=50,aspect='16:9',near=.03,far=200)
                api.set_lighting(direction=light)
                take(api,name+'-'+suffix,'pbr-model')
            api.save_scene(output/(name+'-reload.json'))
            expected=api.get_shot_camera()
            reference,_=draw(api)
            fresh=Mini3DAPI(renderer)
            fresh.load_scene(output/(name+'-reload.json'))
            assert fresh.get_shot_camera()==expected
            reloaded,_=draw(fresh)
            np.testing.assert_array_equal(reference,reloaded)
            report['checks'][name+'_reload_identical']=True
        report['checks']['all_gl_errors_zero']=gl.glGetError()==gl.GL_NO_ERROR
        (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    finally:
        target.close()
        renderer.close()
        pygame.quit()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('label')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    run(args.label,args.output or ROOT/'captures/render-quality-v1'/args.label)
