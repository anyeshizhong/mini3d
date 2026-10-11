"""Reproduce the phase-one photograph with the normal Mini3D capture pipeline.

python tools/capture_sunset.py --headless --output captures/proud_roman_soldier.png
Use --asset model/05_roman_soldier/roman_legionnaire.glb for your own scan;
otherwise this uses our original built-in study figurine, not the museum scan.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from contextlib import contextmanager

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def build_scene(api, asset='builtin:roman-soldier'):
    import numpy as np
    from mini3d.placement import geometry_bounds
    entity=api.spawn(asset,name='Proud Roman Soldier',placement_type='character',keep_upright=True)
    root=api._app.scene.find_by_id(entity['entity_id'])
    if asset != 'builtin:roman-soldier':
        lo,hi=geometry_bounds(root);height=hi[2]-lo[2]
        if height<=0:raise ValueError('Soldier needs a positive Z-up height')
        api.set_transform(entity['entity_id'],scale=[2.4/height]*3)
    api.place_on_ground(entity['entity_id'])
    api.sunset_preset()
    api.set_atmosphere(azimuth=-90,elevation=9,haze=.009)
    api.create_shot_camera(position=(3.3,-5.8,2.05),target=(.45,.45,1.25),
                           focal_mm=50,aspect='3:2',near=.025,far=65)
    api.set_shadows(resolution=4096,bias=.000025)
    api.set_antialiasing(4)
    api._app.scene.update()
    return entity


@contextmanager
def desktop_context():
    import pygame
    pygame.display.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION,3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION,3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.set_mode((16,16),pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    try:yield
    finally:pygame.display.quit()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--asset',default='builtin:roman-soldier')
    parser.add_argument('--output',type=Path,default=Path('captures/proud_roman_soldier.png'))
    parser.add_argument('--scene',type=Path,default=Path('scenes/proud_roman_soldier.json'))
    args=parser.parse_args()
    if args.headless:
        os.environ['PYOPENGL_PLATFORM']='egl'
        from mini3d.headless_gl import egl_context
        context=egl_context
    else:context=desktop_context
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from OpenGL import GL
    with context():
        renderer=GLRenderer(1920,1280);renderer.render_mode='REALISTIC'
        try:
            api=Mini3DAPI(renderer=renderer)
            build_scene(api,args.asset)
            api.save_scene(args.scene)
            result=api.capture(args.output)
            result['renderer']=GL.glGetString(GL.GL_RENDERER).decode()
            result['atmosphere']=api.get_atmosphere()
            result['lighting']=api.get_lighting()
            result['asset']=args.asset
            args.output.with_suffix('.json').write_text(json.dumps(result,indent=2),encoding='utf8')
            print(json.dumps(result,indent=2))
        finally:renderer.close()

if __name__=='__main__':main()
