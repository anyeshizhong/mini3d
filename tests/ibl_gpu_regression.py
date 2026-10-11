"""IBL enabled: alpha/Unlit, first-upload GL state, offscreen shadows and lifetime."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from lighting_fixture import cube_geometry
from mini3d.camera import Camera
from mini3d.environment import EnvironmentMap
from mini3d.gl_renderer import GLRenderer
from mini3d.material_renderer import MaterialRenderer
from mini3d.render_target import RenderTarget
from mini3d.scene import Scene, Mesh, Entity
from mini3d.shot_camera import ShotCamera, render_shot


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION,3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION,3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.set_mode((64,64),pygame.OPENGL | pygame.HIDDEN)
    target, material, renderer = RenderTarget(), MaterialRenderer(), GLRenderer(512,512)
    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),checks={})
    try:
        # First upload with hostile unpack alignment and row offsets.
        parameters = (gl.GL_UNPACK_ALIGNMENT,gl.GL_UNPACK_ROW_LENGTH,gl.GL_UNPACK_SKIP_ROWS,gl.GL_UNPACK_SKIP_PIXELS)
        for p,v in zip(parameters,(8,17,3,2)): gl.glPixelStorei(p,v)
        state = material._save_state(); material._restore_state(state)
        gl.glFinish(); start=time.perf_counter()
        env=EnvironmentMap(); gl.glFinish()
        report['first_upload_sync_ms']=(time.perf_counter()-start)*1000
        assert [int(gl.glGetIntegerv(p)) for p in parameters] == [8,17,3,2]
        material.environment=env
        material._restore_state(state)
        report['texture_formats']=[]
        for unit,target_type,handle in ((8,gl.GL_TEXTURE_CUBE_MAP,env.handles[0]),
                                        (9,gl.GL_TEXTURE_CUBE_MAP,env.handles[1]),
                                        (10,gl.GL_TEXTURE_2D,env.handles[2])):
            gl.glActiveTexture(gl.GL_TEXTURE0+unit);gl.glBindTexture(target_type,handle)
            face=gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X if unit<10 else target_type
            bits=[int(gl.glGetTexLevelParameteriv(face,0,p)) for p in
                  (gl.GL_TEXTURE_RED_SIZE,gl.GL_TEXTURE_GREEN_SIZE,gl.GL_TEXTURE_BLUE_SIZE)]
            assert bits == ([16,16,16] if unit<10 else [16,16,0])
            report['texture_formats'].append(dict(unit=unit,channel_bits=bits))
        material._restore_state(state)
        for p,v in zip(parameters,(4,0,0,0)): gl.glPixelStorei(p,v)
        report['checks']['first_upload_restores_unpack']=True

        v,n,i=cube_geometry()
        mesh=Mesh(v,i,normals=n,material=dict(pbrMetallicRoughness=dict(
            baseColorFactor=[.55,.25,.07,.5],metallicFactor=1,roughnessFactor=.3),alphaMode='BLEND'))
        entity=Entity(mesh); entity.update_transform()
        camera=Camera([3,-6,4]);camera.look_at([0,0,0])
        scene=Scene();scene.lighting_mode='Scene';scene.diffuse=scene.ambient=0
        target.resize(512,512)

        def draw(enabled):
            scene.environment_enabled=enabled;target.bind()
            gl.glDepthMask(True);gl.glColorMask(True,True,True,True)
            gl.glDisable(gl.GL_SCISSOR_TEST);gl.glClearColor(0,0,0,0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            material.render([entity],camera,scene,512,512)
            return np.frombuffer(gl.glReadPixels(0,0,512,512,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE),np.uint8).reshape(512,512,4).copy()

        for mode,alpha in (('BLEND',.5),('MASK',.2),('MASK',.8),('OPAQUE',1)):
            mesh.material['alphaMode']=mode;mesh.material['pbrMetallicRoughness']['baseColorFactor'][3]=alpha
            a,b=draw(False),draw(True)
            np.testing.assert_array_equal(a[...,3],b[...,3])
            if mode=='MASK' and alpha<.5: assert not b.any()
            else: assert np.count_nonzero(a[...,:3]!=b[...,:3])>100
        mesh.material['extensions']={'KHR_materials_unlit':{}}
        np.testing.assert_array_equal(draw(False),draw(True))
        report['checks']['blend_mask_opaque_alpha_and_unlit']=True
        scene.environment_enabled=True
        draw(True);env_handles=list(env.handles);material.close();material.close()
        assert all(not gl.glIsTexture(h) for h in env_handles)
        report['checks']['close_deletes_all_ibl_textures']=True

        # Shot fit must retain the invisible caster while IBL fills the receiver.
        scene=Scene();scene.lighting_mode='Scene';scene.show_grid=scene.show_axes=False
        scene.environment_enabled=True;scene.shadows_enabled=True
        scene.light_dir=np.array([1.,0,1.]);scene.diffuse=1.5;scene.ambient=.12
        mesh=Mesh(v,i,normals=n,material=dict(pbrMetallicRoughness=dict(
            baseColorFactor=[.55,.55,.55,1],metallicFactor=0,roughnessFactor=.8)))
        ground=Entity(mesh);ground.pos[:]=[0,0,-.1];ground.scale[:]=[200,200,.2];scene.add(ground)
        caster=Entity(mesh);caster.pos[:]=[4,0,4];scene.add(caster);scene.update()
        shot=ShotCamera(Camera([0,0,8],near=.03,far=100));shot.look_at([0,0,0]);shot.set_lens(85);shot.set_aspect('16:9')
        def shadow_draw(enabled):
            scene.shadows_enabled=enabled;render_shot(scene,shot,renderer,target)
            rgb=np.frombuffer(gl.glReadPixels(0,0,*shot.size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE),np.uint8).reshape(1080,1920,3).copy()
            depth=np.asarray(gl.glReadPixels(0,0,*shot.size,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)).copy()
            return rgb,depth
        off,d0=shadow_draw(False);on,d1=shadow_draw(True)
        assert caster not in [item.entity for item in renderer.last_render_plan.imported]
        assert caster in renderer.last_render_plan.shadow_candidates
        np.testing.assert_array_equal(d0,d1)
        drop=float(off[539:542,959:962].mean()-on[539:542,959:962].mean())
        assert drop>5,drop
        report['checks']['ibl_offscreen_shadow_drop']=drop
        report['checks']['gl_error_zero']=gl.glGetError()==gl.GL_NO_ERROR
        assert report['checks']['gl_error_zero']
        (output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        material.close();renderer.close();target.close();pygame.quit()


if __name__=='__main__': run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/q1-regressions/ibl')
