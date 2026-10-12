import json,sys,time,statistics
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_scene_view
from tools.capture_sunset import desktop_context
from OpenGL import GL as gl
out=Path(sys.argv[1]);out.parent.mkdir(parents=True,exist_ok=True)
with desktop_context():
    r=GLRenderer(960,640);r.render_mode='REALISTIC';t=RenderTarget();api=Mini3DAPI(r)
    api.load_scene(Path(sys.argv[2]).resolve())
    app=api._app;app.scene.update();base=app.shot_camera.focus_distance
    report={'gpu':gl.glGetString(gl.GL_RENDERER).decode(),'samples_per_case':24,'warmup_frames':5,'excludes':'PNG, readback, swap/vsync; glFinish includes GPU completion','cases':{}}
    try:
        for width in (960,1920):
            for enabled in (False,True):
                times=[]
                for i in range(29):
                    started=time.perf_counter()
                    api.set_depth_of_field(enabled,base+.025*np.sin(i*.4),2.8)
                    render_scene_view(app.scene,app.shot_camera,r,t,(width,width*2//3),4)
                    gl.glFinish()
                    if i>=5:times.append((time.perf_counter()-started)*1000)
                report['cases'][str(width)+('-dof' if enabled else '-sharp')]={'median_ms':statistics.median(times),'p95_ms':float(np.percentile(times,95)),'samples_ms':times}
        assert gl.glGetError()==0
    finally:t.close();r.close()
out.write_text(json.dumps(report,indent=2));print(json.dumps({k:{n:v for n,v in value.items() if n!='samples_ms'} for k,value in report['cases'].items()}))
