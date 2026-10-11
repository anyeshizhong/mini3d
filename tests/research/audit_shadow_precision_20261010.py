"""Controlled render: only ground span and shadow resolution vary."""
import os
if os.name != 'nt' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
if os.environ.get('SDL_VIDEODRIVER') == 'offscreen':
    os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/"tests"))
import numpy as np
import pygame
from OpenGL import GL
import photography_fixture as source
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.geometry import make_box

OUT = source.ROOT / 'captures/second-session/shadow-study'

def run():
    OUT.mkdir(parents=True, exist_ok=True)
    source.OUT = OUT
    pygame.init()
    pygame.display.set_mode((800, 600), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer = GLRenderer(800, 600)
    api = Mini3DAPI(renderer)
    floor = source.asset('ground', make_box(1, 1, 1), (.4, .4, .4))
    block = source.asset('subject', make_box(1, 1, 1), (.7, .3, .08))
    ground = api.spawn(floor, name='Ground', position=[0, 0, -.1], scale=[10, 10, .2])['entity_id']
    api.spawn(block, name='Subject', position=[0, 0, 1], scale=[1, 1, 2])
    api.set_lighting(mode='Scene', direction=[-3, -2, 3], ambient=.3, diffuse=3)
    api.create_shot_camera(position=[7, 9, 13], target=[.6, .5, 0], focal_mm=50,
                           aspect='4:3', near=.05, far=400)
    report = {'gpu': GL.glGetString(GL.GL_RENDERER).decode(), 'camera': api.get_shot_camera(),
              'light': [-3, -2, 3], 'bias': .0003, 'pcf': True, 'runs': []}
    for span in (10, 32, 200):
        api.set_transform(ground, scale=[span, span, .2])
        for resolution in (1024, 4096):
            api.set_shadows(enabled=True, resolution=resolution, bias=.0003, pcf=True)
            path = OUT / f'ground_{span}_shadow_{resolution}.png'
            api.capture(path)
            matrix = renderer.shadow_map.matrix
            ranges = 2 / np.linalg.norm(matrix[:3, :3], axis=1)
            run = {'ground_span': span, 'resolution': resolution,
                   'light_space_extent': ranges.tolist(),
                   'world_units_per_shadow_texel': (ranges[:2] / resolution).tolist(),
                   'normalized_bias_world_depth': float(.0003 * ranges[2]),
                   'gl_error': int(GL.glGetError()), 'image': path.name}
            report['runs'].append(run)
            print(json.dumps(run), flush=True)
    api.save_scene(OUT / 'controlled_scene.json')
    (OUT / 'measurements.json').write_text(json.dumps(report, indent=2))
    renderer.close()
    pygame.quit()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; preserve original evidence')
    OUT = parser.parse_args().output.resolve()
    if OUT.exists():
        parser.error('Output exists; choose a fresh directory')
    run()
