"""Real-GL performance regression: full old/new images, depth and resource reuse."""
import argparse
import importlib
import importlib.util
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from PIL import Image
from OpenGL import GL
from tools.capture_sunset import desktop_context
from tools.build_roman_street import build_scene
from mini3d.geometry import make_box


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--photo-samples',type=int,choices=(1,4),default=1)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    base=args.baseline_project.resolve()/'mini3d'
    spec=importlib.util.spec_from_file_location('spqr_reference',base/'__init__.py',submodule_search_locations=[str(base)])
    package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
    report=dict(cases={},baseline=str(args.baseline_project.resolve()),photo_samples=args.photo_samples)
    with desktop_context():
        states={}
        try:
            for label,prefix in (('before','spqr_reference'),('after','mini3d')):
                module=lambda name:importlib.import_module(prefix+'.'+name)
                renderer=module('gl_renderer').GLRenderer(1920,1080)
                renderer.render_mode='REALISTIC'
                api=module('api').Mini3DAPI(renderer);build_scene(api)
                api.create_shot_camera(position=[1,-10,2],target=[0,20,3],focal_mm=24,near=.05,far=200)
                states[label]=(api,renderer,module('scene'))
            def compare(name,setup):
                images={};depths={};stats={}
                for label,(api,renderer,module) in states.items():
                    setup(api,renderer,module)
                    api.set_antialiasing(args.photo_samples)
                    renderer.shadow_map._cache_key=None
                    path=args.output/(name+'-'+label+'.png');api.capture(path)
                    images[label]=np.asarray(Image.open(path)).astype(int)
                    depths[label]=renderer.shadow_map.save_depth_png(args.output/(name+'-depth-'+label+'.png'))
                    stats[label]=dict(renderer.render_stats)
                diff=abs(images['before']-images['after']);dd=abs(depths['before']-depths['after'])
                report['cases'][name]=dict(max_channel_difference=int(diff.max()),changed_pixels=int(np.any(diff,axis=2).sum()),
                    max_depth_difference=float(dd.max()),changed_depth_texels=int((dd>0).sum()),stats=stats)
                assert diff.max()==0 and dd.max()==0, (name,report['cases'][name])
                assert stats['before']['submitted_triangles']==stats['after']['submitted_triangles'],name
                assert GL.glGetError()==0,name
                print(name,'exact match',flush=True)
            def pose(p,q):
                return lambda api,r,m:api.create_shot_camera(position=p,target=q,focal_mm=24,near=.05,far=200)
            for name,p,q in (('walk',[1,-10,1.7],[0,20,3]),('arch',[0,24,2],[0,38,3]),
                              ('roof-left',[-13,2,10],[0,8,3]),('roof-right',[13,2,10],[0,8,3]),
                              ('roof-underside',[4,-3,.4],[7,0,5]),('overhead',[26,-36,28],[0,8,0])):
                compare(name,pose(p,q))
            for preset in ('stars','moonlit'):
                def setup(api,r,m):
                    api.sky_preset(preset)
                    api.create_shot_camera(position=[1,-10,2],target=[0,20,6],focal_mm=24)
                compare(preset,setup)
            for elevation in (-90,0,90,3):
                def setup(api,r,m):
                    api.sky_preset('day');api.set_atmosphere(elevation=elevation,ground=True)
                compare('sun-'+str(elevation),setup)
            def mixed(api,r,module):
                api.sky_preset('day');api.set_atmosphere(ground=False)
                scene=api._app.scene
                scene.root_entities.clear();scene.groups.clear();scene.selected_ids=[]
                v,i=make_box(1,1,1)
                opaque=dict(pbrMetallicRoughness=dict(baseColorFactor=[.7,.3,.1,1],metallicFactor=.2,roughnessFactor=.4))
                mesh=module.Mesh(v,i,material=opaque)
                parent=module.Entity();parent.pos[:]=[0,0,.5];parent.rot[:]=[.1,.2,.4]
                for n,scale in enumerate(([-1,2,.7],[-1,1,1],[1,1,1],[1,.4,2],[0,1,1])):
                    e=module.Entity(mesh);e.pos[:]=[(n-2)*1.5,0,1];e.scale[:]=scale
                    parent.add_child(e)
                scene.add(parent)
                stream=io.BytesIO()
                image=Image.new('RGBA',(2,2));image.putdata([(255,255,255,255),(255,255,255,0)]*2);image.save(stream,format='PNG')
                for mode,x in (('MASK',-2),('BLEND',0),('BLEND',.5)):
                    mat=dict(alphaMode=mode,alphaCutoff=.5,doubleSided=True,
                        pbrMetallicRoughness=dict(baseColorFactor=[.1,.5,.9,.5 if mode=='BLEND' else 1]),
                        textures={'baseColor':dict(image=stream.getvalue())})
                    obj=module.Entity(module.Mesh(v,i,material=mat));obj.pos[:]=[x,-1,1.3];scene.add(obj)
                legacy=module.Entity(module.Mesh(v,i));legacy.pos[:]=[2,1,1];scene.add(legacy)
                api.create_shot_camera(position=[7,-10,6],target=[0,0,1],focal_mm=35)
            compare('mixed-mirrors-mask-blend-legacy',mixed)
            def edit(api,r,m):
                root=api._app.scene.root_entities[0];root.pos[0]+=1;root.children[0].scale[1]=.65
                root.children[0].model.bounds[1][0]+=.1
            compare('direct-array-edit',edit)
            # The single-object/selection VAOs must keep divisor zero after batching.
            api,r,m=states['after'];api._app.scene.update()
            from mini3d.render_target import RenderTarget
            from mini3d.shot_camera import render_scene_view
            from mini3d.gl_state import save_state
            target=RenderTarget()
            try:
                def pixels(enabled):
                    r.gpu_instancing=enabled;r.shadow_map._cache_key=None
                    render_scene_view(api._app.scene,api._app.shot_camera,r,target,(640,360),1)
                    r.material_renderer.render_selection(api._app.scene.get_flat_render_list()[:3],api._app.shot_camera,640,360)
                    return np.frombuffer(GL.glReadPixels(0,0,640,360,GL.GL_RGB,GL.GL_UNSIGNED_BYTE),np.uint8).copy()
                np.testing.assert_array_equal(pixels(False),pixels(True))
                report['selection_exact']=True
                resources=len(r.material_renderer._instances)
                for frame in range(40):
                    api._app.shot_camera.position[0]+=.003
                    pixels(True)
                assert len(r.material_renderer._instances)==resources
                # Material/selection passes restore caller state, including VAO,
                # instance buffer, front face and independent texture samplers.
                before=save_state()
                r.material_renderer.render(api._app.scene.get_flat_render_list()[:-1],api._app.shot_camera,api._app.scene,640,360)
                after=save_state()
                for key in before:
                    np.testing.assert_equal(before[key],after[key],err_msg=key)
                report['state_restored']=True
                handles=[row[:2] for row in r.material_renderer._instances.values()]
                r.material_renderer.release()
                assert all(not GL.glIsVertexArray(vao) and not GL.glIsBuffer(vbo) for vao,vbo in handles)
                # Editing again after release must lazily rebuild all needed data.
                pixels(True)
                report['resource_reuse_frames']=40
                report['resource_release_and_rebuild']=True
            finally:target.close()
            report.update(gpu=GL.glGetString(GL.GL_RENDERER).decode(),gl_error=int(GL.glGetError()))
            assert report['gl_error']==0
            (args.output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        finally:
            for api,renderer,module in states.values():renderer.close();renderer.close()


if __name__=='__main__':main()
