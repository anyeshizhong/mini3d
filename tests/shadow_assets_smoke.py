"""Real library assets: GPU shadows, independent triangle rays and depth checks."""
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.camera import Camera
from mini3d.gltf_loader import load_gltf
from mini3d.gl_renderer import GLRenderer
from mini3d.picking import raycast_entities
from mini3d.placement import create_ground
from mini3d.render_target import RenderTarget
from mini3d.scene import Scene
from mini3d.shot_camera import ShotCamera,capture_png,render_shot
from mini3d.viewer import world_bounds
SIZE=(1000,750)
KEYS=('05_roman_soldier','03_side_table','02_water_bottle','04_fox','08_rome_river')


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'model/manifest.json').read_text(encoding='utf8'))
    assets={k:load_gltf(ROOT/'model'/k/manifest[k]['entry']) for k in KEYS}
    pygame.init()
    pygame.display.set_mode(SIZE,pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer,target=GLRenderer(*SIZE),RenderTarget()
    renderer.render_mode='REALISTIC'
    target.resize(*SIZE)
    scene=Scene()
    scene.lighting_mode='Scene'
    scene.show_grid=scene.show_axes=False
    scene.ambient,scene.diffuse=.18,2.5
    scene.light_dir=np.array([1.,-1.,1.6])
    camera=Camera((-4,6,4.6),near=.02,far=80)
    camera.look_at((0,0,.75))
    ground=create_ground(10)
    ground.model.material['pbrMetallicRoughness']['baseColorFactor']=[.6,.6,.6,1]
    scene.add(ground)
    roots=[]
    report=dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),size=SIZE,assets={},scenes={})

    def add(key,height=2.,xy=(0,0),z=0,rotation=0):
        root=assets[key].instantiate()
        root.rot[2]=rotation
        root.update_transform()
        lo,hi=world_bounds([root])
        scale=height/(hi[2]-lo[2])
        root.scale[:]=scale
        root.pos[:]=[xy[0]-(lo[0]+hi[0])*.5*scale,xy[1]-(lo[1]+hi[1])*.5*scale,z-lo[2]*scale]
        scene.add(root)
        roots.append(root)
        return root

    def draw(name=None,shadows=True):
        scene.shadows_enabled=shadows
        scene.update()
        target.bind()
        renderer.resize(*SIZE)
        gl.glDepthMask(True)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        renderer.render(scene,camera)
        raw=gl.glReadPixels(0,0,*SIZE,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        depth=np.asarray(gl.glReadPixels(0,0,*SIZE,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT),np.float32).reshape(SIZE[1],SIZE[0]).copy()
        if name:pygame.image.save(pygame.image.fromstring(raw,SIZE,'RGB',True),str(output/(name+'.png')))
        assert gl.glGetError()==gl.GL_NO_ERROR
        pygame.event.pump()
        return np.frombuffer(raw,np.uint8).reshape(SIZE[1],SIZE[0],3).copy(),depth

    def inspect(name,rays=True):
        off,depth_off=draw(name+'-off',False)
        on,depth_on=draw(name+'-on')
        np.testing.assert_array_equal(depth_off,depth_on)
        current=[r for r in roots if r.visible]
        for root in current:root.visible=False
        _,ground_depth=draw(shadows=False)
        for root in current:root.visible=True
        scene.update()
        receiver=(ground_depth<1)&(depth_off==ground_depth)
        delta=np.mean(off.astype(float)-on.astype(float),axis=2)
        dark=receiver&(delta>25)
        interior=dark.copy()
        for axis in (0,1):
            for shift in (-2,-1,1,2):interior &= np.roll(dark,shift,axis)
        assert dark.sum()>100,(name,int(dark.sum()))
        assert np.count_nonzero((delta < -1)&receiver)==0
        entry=dict(triangles=sum(len(e.model.indices) for e in scene.get_flat_render_list()),resolution=scene.shadow_resolution,
            ground_shadow_pixels=int(dark.sum()),model_shadow_changed_pixels=int(((~receiver)&(depth_off<1)&(delta>8)).sum()),
            geometry_depth_exact=True,receiver_pixels=int(receiver.sum()))
        if rays:
            pixels=np.argwhere(interior)
            chosen=pixels[np.linspace(0,len(pixels)-1,min(12,len(pixels))).astype(int)]
            inv=np.linalg.inv(camera.projection_matrix(SIZE[0]/SIZE[1])@camera.view_matrix)
            hits=[]
            for y,x in chosen:
                ndc=np.array([(x+.5)/SIZE[0]*2-1,(y+.5)/SIZE[1]*2-1,float(depth_off[y,x])*2-1,1])
                world=inv@ndc
                world=world[:3]/world[3]
                ray_camera=Camera(world+np.array([0,0,1e-5]),near=1e-5,far=100)
                ray_camera.look_at(world+scene.light_dir)
                hits.append(raycast_entities(current,ray_camera,(50,50),(0,0,100,100)) is not None)
            assert hits and sum(hits)/len(hits)>=.9,(name,hits)
            entry['cpu_shadow_rays']=dict(hits=sum(hits),samples=len(hits))
        draw()
        renderer.shadow_map.save_depth_png(output/(name+'-depth.png'))
        report['scenes'][name]=entry
        print(name,entry,flush=True)
        return off,on,depth_off,receiver

    def timings():
        result={}
        for enabled in (False,True):
            for _ in range(2):draw(shadows=enabled)
            query=int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
            gpu,cpu=[],[]
            for _ in range(7):
                target.bind()
                scene.shadows_enabled=enabled
                gl.glFinish()
                start=time.perf_counter()
                gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
                renderer.render(scene,camera)
                gl.glEndQuery(gl.GL_TIME_ELAPSED)
                gl.glFinish()
                cpu.append((time.perf_counter()-start)*1000)
                gpu.append(int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6)
            gl.glDeleteQueries(1,[query])
            result['on' if enabled else 'off']=dict(gpu_ms=statistics.median(gpu),synchronized_ms=statistics.median(cpu))
        return result

    try:
        for key in KEYS:
            for root in roots:root.visible=False
            root=add(key,height=2 if key!='08_rome_river' else 1.3)
            scene.update()
            visible=[e for e in scene.get_flat_render_list() if e is not ground]
            report['assets'][key]=dict(triangles=sum(len(e.model.indices) for e in visible),primitives=len(visible),scale=root.scale.tolist(),
                source=manifest[key].get('source'),license=manifest[key]['license'],materials=[dict(alpha=e.model.material.get('alphaMode','OPAQUE'),
                extensions=list(e.model.material.get('extensions',{})),textures=list(e.model.material.get('textures',{}))) for e in visible])
            name=key.split('_',1)[1]
            off,on,depth,receiver=inspect(name)
            if key=='08_rome_river':
                np.testing.assert_array_equal(off[(depth<1)&~receiver],on[(depth<1)&~receiver])
                report['scenes'][name]['unlit_opaque_pixels_unchanged']=True
            if key in ('05_roman_soldier','03_side_table'):
                report['scenes'][name]['timing']=timings()
                original=renderer.shadow_map.matrix.copy()
                camera.position=[-6,4,4.6]
                camera.look_at((0,0,.75))
                draw(name+'-camera-moved')
                np.testing.assert_array_equal(original,renderer.shadow_map.matrix)
                camera.position=[-4,6,4.6]
                camera.look_at((0,0,.75))
                scene.light_dir=np.array([-1.,-1.,1.6])
                inspect(name+'-sun-changed',rays=False)
                scene.light_dir=np.array([1.,-1.,1.6])
                scene.shadow_resolution=2048
                inspect(name+'-2048')
                scene.shadow_resolution=1024
        for root in roots:root.visible=False
        soldier=add('05_roman_soldier',2.5,(-1.1,0),rotation=.25)
        table=add('03_side_table',1.3,(.8,0))
        bottle=add('02_water_bottle',.48,(.8,0),z=1.3)
        fox=add('04_fox',.75,(0,1.6),rotation=.65)
        camera.position=[-5,7,4.7]
        camera.look_at((0,0,1))
        off,on,_,receiver=inspect('composed')
        scene.shadow_resolution=2048
        inspect('composed-2048')
        scene.shadow_resolution=1024
        report['scenes']['composed']['timing']=timings()
        with_bottle,depth_bottle=draw()
        bottle.visible=False
        without_bottle,depth_without=draw()
        unchanged=(depth_bottle==depth_without)&(depth_bottle<1)&~receiver
        restored=unchanged&(np.mean(without_bottle.astype(float)-with_bottle.astype(float),axis=2)>8)
        assert restored.sum()>5,int(restored.sum())
        report['scenes']['composed']['bottle_on_other_model_restored_pixels']=int(restored.sum())
        bottle.visible=True
        scene.update()
        scene.lighting_mode='Studio'
        scene.shadows_enabled=True
        shot=ShotCamera(camera)
        render_shot(scene,shot,renderer,target)
        raw=gl.glReadPixels(0,0,*shot.size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        capture_png(scene,shot,renderer,output/'composed-shot.png')
        assert raw==pygame.image.tostring(pygame.image.load(str(output/'composed-shot.png')),'RGB',True)
        scene.lighting_mode='Scene'
        target.resize(*SIZE)
        report['scenes']['composed']['shot_png_exact']=True
        for root in roots:root.visible=False
        for x in range(4):
            for y in range(2):add('05_roman_soldier',2.5,((x-1.5)*2.1,(y-.5)*2.2))
        ground.scale[:]=1.5
        camera.position=[-10,14,9]
        camera.look_at((0,0,1))
        inspect('eight-soldiers',rays=False)
        report['scenes']['eight-soldiers']['timing']=timings()
        meshes={id(e.model) for e in scene.get_flat_render_list()}
        report['scenes']['eight-soldiers']['unique_meshes_including_ground']=len(meshes)
        assert len(meshes)==7
        (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print('PASS: actual library assets, depth equality, triangle rays, material preservation, Shot, GPU timing',flush=True)
    finally:
        renderer.close()
        target.close()
        pygame.quit()

if __name__=='__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/shadow-assets')
