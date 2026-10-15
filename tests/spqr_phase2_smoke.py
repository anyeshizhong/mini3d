"""Celestial/optimization acceptance on real desktop GL, including shadow reference."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from OpenGL import GL
from tools.capture_sunset import desktop_context
from tools.build_roman_street import build_scene
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output;out.mkdir(parents=True,exist_ok=False)
    with desktop_context():
        renderer=GLRenderer(1920,1080)
        try:
            api=Mini3DAPI(renderer);build_scene(api)
            def capture(name):
                path=out/(name+'.png');api.capture(path)
                return np.array(Image.open(path))
            optimized=capture('day')
            renderer.shadow_map._cache_key=None
            # Disable both color and light-frustum rejection as a conservative reference.
            with patch('mini3d.render_plan.batch_world_bounds',side_effect=lambda nodes:[None]*len(nodes)):
                reference=capture('unculled-reference')
            delta=np.abs(optimized.astype(int)-reference.astype(int))
            assert delta.max()==0, ('Culling changes output',delta.max())
            for preset in ('stars','moonlit'):
                api.sky_preset(preset)
                api.set_editor_camera(position=[1,-10,2],target=[0,14,5])
                api.create_shot_camera(position=[1,-10,2],target=[0,14,5],focal_mm=24)
                original=capture(preset)
                api.save_scene(out/(preset+'.scene.json'))
                fresh=Mini3DAPI(renderer);fresh.load_scene(out/(preset+'.scene.json'))
                fresh.capture(out/(preset+'-reloaded.png'))
                d=np.abs(original.astype(int)-np.array(Image.open(out/(preset+'-reloaded.png'))).astype(int))
                assert d.max()<=32 and np.any(d,axis=2).mean()<=.0001,(preset,d.max())
            # Actual polar and below-horizon rendering, not just parameter checks.
            for elevation in (-90,0,90):
                api.sky_preset('day');api.set_atmosphere(elevation=elevation)
                capture('sun-elevation-'+str(elevation))
            api.sky_preset('moonlit');api.set_atmosphere(azimuth=90,elevation=25)
            api.create_shot_camera(position=[1,-10,2],target=[0,14,9],focal_mm=24)
            capture('moon-disc')
            # Rotate moon to illuminate the opposite street side.
            api.set_atmosphere(azimuth=-90);capture('moon-reversed')
            assert GL.glGetError()==0
            report=dict(gl_error=0,culling_max_channel_difference=int(delta.max()),
                        renderer=GL.glGetString(GL.GL_RENDERER).decode())
            (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
            print(report)
        finally:renderer.close()


if __name__=='__main__':main()
