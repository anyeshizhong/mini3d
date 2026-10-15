"""Compare pinned Phase 1.1 modules and current code in one GL session."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import types
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from OpenGL import GL
from tools.capture_sunset import desktop_context
from tools.build_roman_street import build_scene
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.shadow_map import ShadowMap
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_scene_view


def baseline_module(file, name, ref):
    source=subprocess.check_output(['git','show',ref+':mini3d/'+file],text=True)
    module=types.ModuleType('mini3d.'+name);sys.modules[module.__name__]=module
    exec(compile(source,file,'exec'),module.__dict__)
    return module


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-ref',default='7f0c5d8')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    old_plan=baseline_module('render_plan.py','_baseline_plan',args.baseline_ref)
    old_shadow=baseline_module('shadow_map.py','_baseline_shadow',args.baseline_ref)
    with desktop_context():
        renderer=GLRenderer(960,540);target=RenderTarget()
        try:
            api=Mini3DAPI(renderer);build_scene(api)
            api.create_shot_camera(position=[.5,15,1.7],target=[0,27,2.8],focal_mm=24)
            runs={'before':[],'after':[]};stats={}
            for repeat in range(3):
                for label in ('before','after'):
                    import contextlib
                    with contextlib.ExitStack() as stack:
                        if label=='before':
                            stack.enter_context(patch('mini3d.gl_renderer.build_render_plan',old_plan.build_render_plan))
                            stack.enter_context(patch.object(ShadowMap,'render',old_shadow.ShadowMap.render))
                        times=[]
                        for frame in range(24):
                            api._app.shot_camera.position=[.5+frame*.015,15,1.7]
                            start=time.perf_counter()
                            render_scene_view(api._app.scene,api._app.shot_camera,renderer,target,(960,540),1)
                            GL.glFinish()
                            if frame>=4:times.append((time.perf_counter()-start)*1000)
                        runs[label].append(float(np.mean(times)))
                        stats[label]=dict(renderer.render_stats)
            medians={label:float(np.median(values)) for label,values in runs.items()}
            report=dict(runs_ms=runs,median_ms=medians,
                improvement_percent=100*(1-medians['after']/medians['before']),stats=stats,
                resolution=[960,540],samples=1,shadow_resolution=2048,measured_frames_per_run=20,
                renderer=GL.glGetString(GL.GL_RENDERER).decode(),vram='not measured')
            args.output.write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report,indent=2))
        finally:target.close();renderer.close()


if __name__=='__main__':main()
