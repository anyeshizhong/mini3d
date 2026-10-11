"""Issue #4: real Rome placement/rendering/photography/JSON API acceptance.

Requires local third-party GLBs; writes only scenes, reports and GPU PNGs.
No material conversion or production-code changes.
"""
import json
import math
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch_json
from mini3d.camera import Camera
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.picking import raycast_entities
from mini3d.shot_camera import render_shot
from mini3d.viewer import world_bounds

SIZE=(1000,700)
ROMAN=ROOT/'model/05_roman_soldier/roman_legionnaire.glb'
ROME=ROOT/'model/08_rome_river/rome_river_side.glb'


def run(output,probe_path):
    output.mkdir(parents=True,exist_ok=True)
    probe=json.loads(Path(probe_path).read_text(encoding='utf8'))
    points=np.asarray(probe['points'],float)
    center=points.mean(axis=0)
    pygame.init()
    pygame.display.set_mode(SIZE,pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer,target=GLRenderer(*SIZE),RenderTarget()
    renderer.render_mode='REALISTIC'
    api=Mini3DAPI(renderer)
    calls=[]
    report=dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),baseline='52ee1ee',checks={},views={},timing={},placement=probe)

    def call(command,**args):
        result=json.loads(dispatch_json(api,json.dumps(dict(command=command,args=args))))
        assert result['ok'],result
        calls.append(dict(command=command,args=args))
        return result['result']

    def render(name=None):
        scene=api._app.scene
        scene.update()
        render_shot(scene,api._app.shot_camera,renderer,target)
        size=api._app.shot_camera.size
        raw=gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        depth=np.asarray(gl.glReadPixels(0,0,*size,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT),np.float32).reshape(size[1],size[0]).copy()
        if name:
            call('capture',path=str(output/(name+'.png')))
            assert raw==pygame.image.tostring(pygame.image.load(str(output/(name+'.png'))),'RGB',True)
        assert gl.glGetError()==gl.GL_NO_ERROR
        return np.frombuffer(raw,np.uint8).reshape(size[1],size[0],3).copy(),depth

    def timing(label):
        measurements={}
        for enabled in (False,True):
            call('set_shadows',enabled=enabled)
            render()
            query=int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
            gpu,cpu=[],[]
            for _ in range(5):
                gl.glFinish()
                start=time.perf_counter()
                gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
                render_shot(api._app.scene,api._app.shot_camera,renderer,target)
                gl.glEndQuery(gl.GL_TIME_ELAPSED)
                gl.glFinish()
                cpu.append((time.perf_counter()-start)*1000)
                gpu.append(int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6)
            gl.glDeleteQueries(1,[query])
            measurements['on' if enabled else 'off']=dict(gpu_ms=statistics.median(gpu),cpu_gpu_ms=statistics.median(cpu))
        report['timing'][label]=measurements

    def assert_editor_clips(label):
        app=api._app
        app.scene.update()
        app.viewer.update_clipping()
        view=app.viewer.camera
        low,high=app.viewer._clip_depth_range()
        assert view.far>high and view.near>0
        report['checks'][label]=dict(near=view.near,far=view.far,scene_box_depth=[low,high])

    try:
        city=call('spawn',asset_path=str(ROME),name='Rome River Side (original Unlit)',scale=[100]*3)
        city_id=city['entity_id']
        call('place_on_ground',entity_id=city_id,x=0,y=0)
        call('lock',entity_id=city_id)
        api._app.scene.update()
        for point in points:
            ray=Camera([point[0],point[1],60],near=.01,far=100)
            ray.look_at([point[0],point[1],0])
            hit=raycast_entities([api._entity(city_id)],ray,(.5,.5),(0,0,1,1))
            assert hit is not None
            np.testing.assert_allclose(hit[1],point,atol=1e-6)
        report['checks']['all_40_points_rechecked_on_real_rome_triangles']=True
        report['placement_quality']='NOT APPROVED: grid overlaps fountain/market obstacles; point anchoring is not footprint collision avoidance. Requires manual layout review, not automatic material/architecture edits.'
        roman=call('spawn',asset_path=str(ROMAN),name='Roman original scan',scale=[.07]*3,placement_type='character',keep_upright=True)
        source=roman['entity_id']
        call('place_at',entity_id=source,position=points[0].tolist())
        call('set_lighting',mode='Scene',direction=[1,-1,1.6],diffuse=2.5,ambient=.22)
        call('set_shadows',enabled=True,resolution=1024,bias=.0005,pcf=True)
        views=[dict(position=(center+[-14,-20,35]).tolist(),target=(center+[0,0,.8]).tolist(),focal_mm=35,aspect='16:9',near=.05,far=300),
               dict(position=(center+[16,-15,8]).tolist(),target=(center+[0,0,.8]).tolist(),focal_mm=35,aspect='16:9',near=.05,far=300)]
        call('create_shot_camera',**views[0])
        render('rome-one')
        # Exercise actual duplicate, group, transformations and atomic history.
        with api.transaction('three soldiers'):
            one=api.duplicate(source)
            two=api.duplicate(source)
            api.place_at(one['entity_id'],points[1].tolist())
            api.place_at(two['entity_id'],points[2].tolist())
            small=api.create_group([source,one['entity_id'],two['entity_id']],'Three soldiers')
            api.transform_many(small['member_ids'],rotation=[0,0,.08])
        render('rome-three')
        call('undo')
        assert len(api.list_entities())==2
        call('redo')
        assert len(api.list_entities())==4
        call('undo')
        group=call('create_rectangular_formation',source_id=source,rows=5,columns=8,spacing_x=1.5,spacing_y=1.8)
        ids=group['member_ids']
        assert len(ids)==40 and len(set(ids))==40
        with api.transaction('conform formation to real Roman surfaces'):
            for entity_id,point in zip(ids,points):api.place_at(entity_id,point.tolist())
        scene=api._app.scene
        scene.update()
        for entity_id,point in zip(ids,points):
            item=api.get_entity(entity_id,include_bounds=True)
            np.testing.assert_allclose(item['bounds']['minimum'][2],point[2],atol=1e-6)
            np.testing.assert_allclose(item['rotation'][:2],[0,0])
        entities=scene.get_flat_render_list()
        report['structure']=dict(roots=len(scene.root_entities),instances=40,draw_primitives=len(entities),
            triangles=sum(len(e.model.indices) for e in entities),unique_meshes=len({id(e.model) for e in entities}),
            roman_height=.07*25.96310174,rome_scale=100,roman_scale=.07)
        assert report['structure']['unique_meshes']==23
        app=api._app
        app.select(api._entity(source));app.focus_selected();assert_editor_clips('focus_soldier')
        app.frame_all();assert_editor_clips('frame_all')
        app.viewer.controller.orbit(80,20);app.viewer.controller.pan(12,8,700);app.viewer.controller.zoom(-1)
        assert_editor_clips('orbit_pan_zoom')
        # Visible high detail models keep identical camera depth on/off.
        for index,view in enumerate(views):
            call('create_shot_camera',**view)
            call('set_shadows',enabled=False)
            off,d0=render('rome-view%d-off'%index)
            call('set_shadows',enabled=True)
            on,d1=render('rome-view%d-on'%index)
            np.testing.assert_array_equal(d0,d1)
            # Isolate the actual Unlit city surfaces without converting materials.
            for entity_id in ids:api._entity(entity_id).visible=False
            city_rgb,city_depth=render()
            for entity_id in ids:api._entity(entity_id).visible=True
            city_mask=(city_depth<1)&(city_depth==d0)
            np.testing.assert_array_equal(off[city_mask],on[city_mask])
            delta=np.mean(off.astype(float)-on.astype(float),axis=2)
            soldier_mask=(d0<1)&~city_mask
            assert soldier_mask.sum()>500
            entry=dict(camera=api.get_shot_camera(),unlit_city_pixels_unchanged=int(city_mask.sum()),
                       soldier_pixels=int(soldier_mask.sum()),shadow_changed_pixels=int((soldier_mask&(delta>3)).sum()),
                       camera_depth_equal=True,camera_view_png_equal=True)
            report['views']['rome-'+str(index)]=entry
            render()
            renderer.shadow_map.save_depth_png(output/('rome-view%d-depth.png'%index))
            if index==0:timing('rome-40-1920x1080')
        call('set_shadows',enabled=True)
        before=api.get_scene_state()
        call('save_scene',path=str(output/'rome-scene.json'))
        fresh=Mini3DAPI(renderer)
        fresh.load_scene(output/'rome-scene.json')
        assert fresh.list_entities()==before['entities'] and fresh.list_groups()==before['groups']
        assert fresh.get_lighting()==before['lighting'] and fresh.get_shadows()==before['shadows']
        report['checks']['v3_entities_groups_lighting_shadows_roundtrip']=True
        report['checks']['shot_camera_not_in_scene_v3']=fresh.get_shot_camera() is None
        # Existing v3 saves Editor camera; record/recreate Shot explicitly through API.
        api=fresh
        call('create_shot_camera',**views[1])
        restored,_=render('rome-reloaded')
        previous=pygame.image.tostring(pygame.image.load(str(output/'rome-view1-on.png')),'RGB',True)
        np.testing.assert_array_equal(restored,np.frombuffer(previous,np.uint8).reshape(restored.shape))
        report['checks']['recreated_shot_after_reload_exact']=True
        (output/'views.json').write_text(json.dumps(views,indent=2),encoding='utf8')
        # Explicit separate PBR stage: no invisible query plane becomes geometry.
        stage=Mini3DAPI(renderer)
        api=stage
        floor=call('spawn',asset_path='builtin:ground',name='EXPLICIT PBR stage',scale=[2]*3)
        actor=call('spawn',asset_path=str(ROMAN),name='Roman on PBR stage',scale=[.07]*3)
        call('place_on_ground',entity_id=actor['entity_id'],x=0,y=0)
        call('set_lighting',mode='Scene',direction=[1,-1,1.6],diffuse=2.5,ambient=.22)
        call('set_shadows',enabled=True,resolution=1024,bias=.0005,pcf=True)
        stage_views=[dict(position=[-4,6,4],target=[0,0,.8],focal_mm=50,aspect='16:9',near=.02,far=100),
                     dict(position=[-6,3,3],target=[0,0,.8],focal_mm=50,aspect='16:9',near=.02,far=100)]
        for index,view in enumerate(stage_views):
            call('create_shot_camera',**view)
            call('set_shadows',enabled=False)
            off,d0=render('stage-view%d-off'%index)
            call('set_shadows',enabled=True)
            on,d1=render('stage-view%d-on'%index)
            np.testing.assert_array_equal(d0,d1)
            api._entity(actor['entity_id']).visible=False
            _,floor_depth=render()
            api._entity(actor['entity_id']).visible=True
            mask=(floor_depth<1)&(floor_depth==d0)
            dark=mask&(np.mean(off.astype(float)-on.astype(float),axis=2)>10)
            assert dark.sum()>100
            report['views']['stage-'+str(index)]=dict(pbr_ground_shadow_pixels=int(dark.sum()),camera_view_png_equal=True,camera_depth_equal=True,camera=api.get_shot_camera())
            render()
            renderer.shadow_map.save_depth_png(output/('stage-view%d-depth.png'%index))
        call('save_scene',path=str(output/'stage-scene.json'))
        (output/'stage-views.json').write_text(json.dumps(stage_views,indent=2),encoding='utf8')
        (output/'json-api-commands.json').write_text(json.dumps(calls,indent=2),encoding='utf8')
        (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report,indent=2),flush=True)
    finally:
        renderer.close();target.close();pygame.quit()


if __name__=='__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/rome-integration',
        ROOT/'docs/rome-integration/placement-probe.json')
