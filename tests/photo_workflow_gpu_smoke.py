"""Resolved-depth focus and pre-tone linear color on a real desktop GL context."""
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.camera import Camera
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_scene_view
from mini3d.photo_focus import read_focus_point
from mini3d.photo_color import adjust_linear
from mini3d.gl_state import read_rgb
from tools.capture_sunset import desktop_context
sys.path.insert(0,str(Path(__file__).resolve().parent))
from depth_of_field_gpu_smoke import write_fixture


def pixels(path):return pygame.surfarray.array3d(pygame.image.load(str(path))).transpose(1,0,2)


def run(output,scene):
    output.mkdir(parents=True,exist_ok=True)
    fixture=write_fixture(output);data=json.loads(fixture.read_text())
    data['materials']=[{'doubleSided':True,'emissiveFactor':[2,.5,.15],
        'extensions':{'KHR_materials_specular':{'specularFactor':0}},
        'pbrMetallicRoughness':{'baseColorFactor':[0,0,0,1],'metallicFactor':0,'roughnessFactor':1}}]
    data.pop('extensionsUsed',None);fixture.write_text(json.dumps(data))
    checks={}
    with desktop_context():
        renderer=GLRenderer(640,480);renderer.render_mode='REALISTIC';target=RenderTarget()
        api=Mini3DAPI(renderer);app=api._app
        try:
            api.spawn(fixture,position=[0,0,-2])
            api.create_shot_camera(position=[0,0,0],target=[0,0,-2],focal_mm=50,near=.01,far=100)
            app.set_camera_view(True)
            api.set_lighting(diffuse=0,ambient=0);api.set_shadows(enabled=False)
            api.set_atmosphere(enabled=True,ground=False,haze=0,exposure_ev=0,tone_mapping='reinhard')
            api.set_antialiasing(4)
            for aspect in app.shot_camera.ASPECTS:
                api.set_aspect(aspect)
                shot=app.shot_camera;size=(640,int(round(640/shot.aspect)))
                render_scene_view(app.scene,shot,renderer,target,size,4)
                for outer in ((30,80,811,491),(113,37,371,253)):
                    app.viewport_rect=shot.fit_rect(outer);x,y,w,h=app.viewport_rect
                    app.photo_focus_reader=lambda p,rect:read_focus_point(target,shot,p,rect)
                    # Deliberately different caller read FBO/pack state.
                    gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,0)
                    gl.glPixelStorei(gl.GL_PACK_ALIGNMENT,8)
                    before=(int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)),int(gl.glGetIntegerv(gl.GL_PACK_ALIGNMENT)))
                    assert api.focus_screen([x+w*.5,y+h*.5])['focused']
                    np.testing.assert_allclose(shot.focus_distance,2,atol=1e-4)
                    first=shot.to_dict()
                    assert api.focus_screen([x+w*.5,y+h*.5])['focused']
                    assert shot.to_dict()==first
                    assert not api.focus_screen([x-1,y+h*.5])['focused']
                    assert shot.to_dict()==first
                    # Tiny emissive plane covers the center; corner is sky/depth=1.
                    assert not api.focus_screen([x+1,y+1])['focused']
                    assert shot.to_dict()==first
                    after=(int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING)),int(gl.glGetIntegerv(gl.GL_PACK_ALIGNMENT)))
                    assert before==after
            checks['resolved_depth_all_aspects_scaled_rect_repeat_sky_black_borders_and_pack_state']=True
            api.set_aspect('3:2');shot=app.shot_camera
            api.set_photo_color(8000,'Warm')
            render_scene_view(app.scene,shot,renderer,target,(640,427),4)
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,target.framebuffer)
            pixel=np.frombuffer(read_rgb(320,213,1,1),np.uint8)
            linear=adjust_linear([2,.5,.15],8000,'Warm');mapped=linear/(1+linear)
            expected=np.where(mapped<=.0031308,mapped*12.92,1.055*mapped**(1/2.4)-.055)*255
            np.testing.assert_allclose(pixel,expected,atol=1.1)
            checks['linear_white_balance_before_tone_mapping_matches_cpu']=True
            checks['emissive_sample_rgb']=pixel.tolist()
            api.load_scene(scene);app.set_camera_view(True)
            shot=app.shot_camera
            original_lights=api.get_lighting();original_atmosphere=api.get_atmosphere()
            api.capture(output/'original.png')
            api.set_photo_color(7800,'Warm');api.capture(output/'warm.png')
            api.set_photo_color(6500,'Low saturation');api.capture(output/'low-saturation.png')
            assert api.get_lighting()==original_lights and api.get_atmosphere()==original_atmosphere
            api.reset_photo_color();api.capture(output/'reset.png')
            np.testing.assert_array_equal(pixels(output/'original.png'),pixels(output/'reset.png'))
            checks['reset_restores_exact_legacy_photo_and_scene_lights_unchanged']=True
            for name in ('warm','low-saturation'):
                assert np.count_nonzero(pixels(output/(name+'.png'))!=pixels(output/'original.png'))>10000
            api.set_photo_color(7200,'Original');api.set_depth_of_field(enabled=True,f_number=2.8)
            # Read the face from a displayed full-resolution frame and reuse focus_at.
            render_scene_view(app.scene,shot,renderer,target,shot.size,shot.samples)
            app.viewport_rect=shot.fit_rect((25,45,1000,700))
            app.photo_focus_reader=lambda p,rect:read_focus_point(target,shot,p,rect)
            x,y,w,h=app.viewport_rect
            assert api.focus_screen([x+w*.32,y+h*.34])['focused']
            api.capture(output/'clicked-face.png');api.save_scene(output/'clicked-face.scene.json')
            render_scene_view(app.scene,shot,renderer,target,shot.size,shot.samples)
            preview=np.frombuffer(read_rgb(0,0,*shot.size),np.uint8).reshape(shot.size[1],shot.size[0],3)[::-1]
            np.testing.assert_array_equal(preview,pixels(output/'clicked-face.png'))
            api.load_scene(output/'clicked-face.scene.json');api.capture(output/'reloaded.png')
            np.testing.assert_array_equal(pixels(output/'clicked-face.png'),pixels(output/'reloaded.png'))
            checks['real_face_click_color_aperture_preview_png_reload_exact']=True
            checks['focus_distance_m']=api.get_shot_camera()['focus_distance']
            assert gl.glGetError()==0
            report={'gpu':gl.glGetString(gl.GL_RENDERER).decode(),'checks':checks,'passed':True}
        finally:target.close();renderer.close()
    (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':run(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
