"""Real GPU angular sun-size regression and filtered procedural sky captures."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from PIL import Image
from OpenGL import GL
from tools.capture_sunset import desktop_context
from mini3d.api import Mini3DAPI
from mini3d.camera import Camera
from mini3d.sky_renderer import SkyRenderer
from mini3d.render_target import RenderTarget
from mini3d.lighting import scene_light_direction
from mini3d.gl_state import read_rgb


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output;out.mkdir(parents=True,exist_ok=False)
    with desktop_context():
        sky=SkyRenderer();target=RenderTarget();api=Mini3DAPI();api.sky_preset('day')
        scene=api._app.scene;camera=Camera([0,0,0],fov_y=20)
        camera.look_at(scene_light_direction(scene));counts={}
        try:
            target.resize(960,540);target.bind();GL.glViewport(0,0,960,540)
            for size in (.53,2.):
                api.set_atmosphere(sun_size=size)
                sky.render(scene,camera,960/540)
                pixels=np.frombuffer(read_rgb(0,0,960,540),np.uint8).reshape(540,960,3)
                counts[str(size)]=int((pixels.min(axis=2)>230).sum())
                Image.fromarray(pixels[::-1]).save(out/('sun-'+str(size)+'.png'))
            assert counts['0.53']>0 and counts['2.0']>counts['0.53']*6,counts
            assert GL.glGetError()==0
            report=dict(bright_disc_pixels=counts,gl_error=0,gpu=GL.glGetString(GL.GL_RENDERER).decode())
            (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(report)
        finally:target.close();sky.close()


if __name__=='__main__':main()
