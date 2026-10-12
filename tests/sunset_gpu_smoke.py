"""Real GPU acceptance: lit face, long shadow, aligned sun and lossless reload.

Linux: python tests/sunset_gpu_smoke.py (surfaceless EGL / Mesa is sufficient).
This deliberately exercises the application renderer, not an image generator.
"""
import os
os.environ['PYOPENGL_PLATFORM']='egl'
from pathlib import Path
import sys
import tempfile
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from OpenGL import GL as gl
from mini3d.headless_gl import egl_context
from mini3d.api import Mini3DAPI
from mini3d.camera import Camera
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_scene_view
from mini3d.gl_state import read_rgb
from mini3d.lighting import scene_light_direction
from tools.capture_sunset import build_scene

SIZE=(720,480)


def frame(api,renderer,camera=None):
    target=RenderTarget()
    try:
        api._app.scene.update()
        render_scene_view(api._app.scene,camera or api._app.shot_camera,renderer,target,SIZE,4)
        return np.frombuffer(read_rgb(0,0,*SIZE),np.uint8).reshape(SIZE[1],SIZE[0],3)[::-1].copy()
    finally:target.close()


def project(camera,point):
    p=camera.projection_matrix(1.5)@camera.view_matrix@np.r_[point,1.]
    p=p[:2]/p[3]
    return int((p[0]+1)*.5*SIZE[0]),int((1-p[1])*.5*SIZE[1])


def main():
    results={}
    with egl_context():
        renderer=GLRenderer(*SIZE);renderer.render_mode='REALISTIC'
        try:
            api=Mini3DAPI(renderer=renderer);build_scene(api)
            roots=list(api._app.scene.root_entities)
            reference=frame(api,renderer)
            assert api._app.scene.root_entities==roots,'Ground leaked into editing/persistence'
            api.set_shadows(enabled=False);no_shadow=frame(api,renderer)
            delta=np.mean(no_shadow.astype(float)-reference.astype(float),axis=2)
            # Ignore geometry; count the dark footprint outside the body box.
            mask=delta>5;mask[:200]=False;mask[:,:350]=False
            ys,xs=np.where(mask)
            assert len(xs)>1500,'No substantial ground shadow'
            assert xs.max()-xs.min()>160,'Shadow is not visibly long'
            results['shadow_pixels']=len(xs);results['shadow_span_pixels']=int(xs.max()-xs.min())
            api.set_shadows(enabled=True)
            api.set_atmosphere(sun_size=0);hard=frame(api,renderer)
            api.set_atmosphere(sun_size=.53);soft=frame(api,renderer)
            changed=np.max(np.abs(hard.astype(int)-soft.astype(int)),axis=2)>2
            assert np.count_nonzero(changed[200:,350:])>100,'Solar size does not soften the long shadow'
            results['soft_shadow_changed_ground_pixels']=int(np.count_nonzero(changed[200:,350:]))
            x,y=project(api._app.shot_camera,(0,-.08,1.75))
            def face_ratio(image):
                region=image[y-5:y+5,x-5:x+5].astype(float).mean(axis=(0,1))
                return float(region[0]/max(region[2],1))
            api.set_atmosphere(sun_temperature=2500);warm=frame(api,renderer)
            api.set_atmosphere(sun_temperature=8000);cool=frame(api,renderer)
            assert face_ratio(warm)>face_ratio(cool)*1.15,'Temperature does not warm the face'
            results['face_red_blue_warm']=face_ratio(warm);results['face_red_blue_cool']=face_ratio(cool)
            api.set_atmosphere(sun_temperature=3500)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'scene.json';api.save_scene(path)
                fresh=Mini3DAPI(renderer=renderer);fresh.load_scene(path)
                reloaded=frame(fresh,renderer)
                error=np.abs(reloaded.astype(int)-reference.astype(int))
                assert error.max()<=1,'Saved scene changes the photo'
                results['reload_max_channel_error']=int(error.max())
            # A sky-only camera aimed at the exact lighting vector sees the disc
            # at its optical centre. No geometry/ground can fake this assertion.
            sky=Mini3DAPI(renderer=renderer);sky.sunset_preset();sky.set_atmosphere(ground=False,azimuth=-90,elevation=9)
            sun_camera=Camera((0,0,2),fov_y=27)
            sun_camera.look_at(sun_camera.position+scene_light_direction(sky._app.scene))
            sky_image=frame(sky,renderer,sun_camera)
            centre=sky_image[240,360].astype(float).mean()
            nearby=sky_image[240,380].astype(float).mean()
            assert centre-nearby>35,'Sun disc disagrees with world light direction'
            results['sun_disc_contrast']=float(centre-nearby)
            # The real HDR dome's recorded bright sun must follow the lamp,
            # even when both azimuth and elevation change.
            sky.set_atmosphere(sky_texture='sunset',tone_mapping='filmic')
            for azimuth,elevation in ((-90,9),(35,25)):
                sky.set_atmosphere(azimuth=azimuth,elevation=elevation)
                sun_camera.look_at(sun_camera.position+scene_light_direction(sky._app.scene))
                hdr=frame(sky,renderer,sun_camera)
                brightness=hdr.astype(float).mean(axis=2)
                assert brightness[240,360]>=np.percentile(brightness,98)-2,'HDR sun direction disagrees with shadows'
            results['hdr_sun_centre_brightness']=float(brightness[240,360])
            from mini3d.photo_environment import RESOURCES
            sky.set_atmosphere(sky_texture=str(RESOURCES/'sunset.hdr'))
            custom=frame(sky,renderer,sun_camera)
            assert np.array_equal(custom,hdr),'Custom HDR path differs from bundled backdrop'
            # First-time custom filtering must preserve cube, sampler, viewport,
            # framebuffer and pack state; ordinary camera motion only reuses it.
            from mini3d.ibl_filter import filter_panorama
            from mini3d.photo_environment import load_sky
            from mini3d.gl_state import save_state
            expected=save_state()
            before_view=np.array(gl.glGetIntegerv(gl.GL_VIEWPORT))
            before_fbo=int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
            before_pack=int(gl.glGetIntegerv(gl.GL_PACK_ALIGNMENT))
            gl.glActiveTexture(expected['ACTIVE_TEXTURE'])
            arrays=filter_panorama(load_sky('sunset')[1],samples=16)
            actual=save_state()
            for name in ('textures','cubemaps','samplers','ACTIVE_TEXTURE','CURRENT_PROGRAM'):
                assert actual[name]==expected[name],name+' leaks from HDR filtering'
            assert np.array_equal(gl.glGetIntegerv(gl.GL_VIEWPORT),before_view)
            assert int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))==before_fbo
            assert int(gl.glGetIntegerv(gl.GL_PACK_ALIGNMENT))==before_pack
            assert arrays['diffuse'].shape==(6,32,32,3)
            results['hdr_filter_gl_state_preserved']=True
            assert gl.glGetError()==gl.GL_NO_ERROR,'OpenGL error after capture/reload'
            results['renderer']=gl.glGetString(gl.GL_RENDERER).decode()
            print(json.dumps(results,indent=2))
        finally:renderer.close()

if __name__=='__main__':main()
