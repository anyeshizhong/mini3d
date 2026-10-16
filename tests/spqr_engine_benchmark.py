"""Alternate complete project snapshots at fixed quality; no profiler in timings."""
import argparse
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.capture_sunset import desktop_context
from tools.build_roman_street import build_scene
from tools.build_pompeii import build_scene as build_district
from OpenGL import GL


def pose(name,t):
    if name=='walk':return [1,-10+16*t,1.7],[0,20,3]
    if name=='arch':return [0,6+18*t,2],[0,38,3]
    if name=='orbit':
        angle=-2.8+t*2.2
        return [25*np.cos(angle),8+25*np.sin(angle),10],[0,8,2]
    angle=-2.5+t*1.5
    return [30*np.cos(angle),8+30*np.sin(angle),28],[0,8,0]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=20)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--sizes',type=int,nargs='+',choices=(85,435),default=[85,435])
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    base=args.baseline_project.resolve()/'mini3d'
    spec=importlib.util.spec_from_file_location('spqr_before',base/'__init__.py',submodule_search_locations=[str(base)])
    package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
    report=dict(baseline=str(args.baseline_project.resolve()),size=[960,540],samples=1,shadow_resolution=2048,
                includes=['scene update','navigation clipping','scene render','resolve','glFinish'],
                excludes=['ImGui','input','presentation','PNG encoding'],repeats=args.repeats,warmup=6,frames=args.samples,cases={})
    states={}
    with desktop_context():
        try:
            for label,prefix in (('before','spqr_before'),('after','mini3d')):
                renderer=importlib.import_module(prefix+'.gl_renderer').GLRenderer(960,540)
                renderer.render_mode='REALISTIC'
                states[label]=dict(renderer=renderer,prefix=prefix,
                    target=importlib.import_module(prefix+'.render_target').RenderTarget(),
                    render=importlib.import_module(prefix+'.shot_camera').render_scene_view)
            for roots in args.sizes:
                for state in states.values():
                    r=state['renderer'];r.shadow_map.close()
                    if hasattr(r,'material_renderer'):r.material_renderer.release()
                    api=importlib.import_module(state['prefix']+'.api').Mini3DAPI(r)
                    (build_scene if roots==85 else build_district)(api)
                    api.create_shot_camera(position=[1,-10,2],target=[0,20,3],focal_mm=24,near=.05,far=250)
                    assert len(api.list_entities())==roots
                    state['api']=api
                routes=('walk','arch','orbit','overhead')
                for route in routes:
                    case={label:[] for label in states}
                    for repeat in range(args.repeats):
                        for label in (('before','after') if repeat%2==0 else ('after','before')):
                            state=states[label];api=state['api'];r=state['renderer'];times=[];draws=[];gpu=[];triangles=[];shadow_draws=[];color_draws=[]
                            query=int(np.asarray(GL.glGenQueries(1)).reshape(-1)[0])
                            try:
                                for frame in range(6+args.samples):
                                    p,q=pose(route,max(0,frame-6)/(args.samples-1))
                                    shot=api._app.shot_camera;shot.position=p;shot.look_at(q)
                                    started=time.perf_counter()
                                    api._app.scene.update();api._app.viewer.update_clipping()
                                    GL.glBeginQuery(GL.GL_TIME_ELAPSED,query)
                                    state['render'](api._app.scene,shot,r,state['target'],(960,540),1)
                                    GL.glEndQuery(GL.GL_TIME_ELAPSED);GL.glFinish()
                                    elapsed=(time.perf_counter()-started)*1000
                                    device_ns=int(GL.glGetQueryObjectuiv(query,GL.GL_QUERY_RESULT))
                                    if frame>=6:
                                        times.append(elapsed);gpu.append(device_ns/1e6)
                                        draws.append(r.render_stats['draw_calls']);triangles.append(r.render_stats['submitted_triangles'])
                                        shadow_draws.append(r.render_stats['shadow_draw_calls']);color_draws.append(r.render_stats['color_draw_calls'])
                            finally:GL.glDeleteQueries(1,[query])
                            case[label].append(dict(mean_ms=float(np.mean(times)),p95_ms=float(np.percentile(times,95)),frame_ms=times,
                                gpu_timeline_ms=float(np.mean(gpu)),draws=float(np.mean(draws)),triangles=float(np.mean(triangles)),
                                color_draws=float(np.mean(color_draws)),shadow_draws=float(np.mean(shadow_draws))))
                    summary={label:dict(median_mean_ms=float(np.median([r['mean_ms'] for r in runs])),
                             pooled_p95_ms=float(np.percentile([t for r in runs for t in r['frame_ms']],95)),
                             mean_draws=float(np.mean([r['draws'] for r in runs])),
                             gpu_timeline_ms=float(np.median([r['gpu_timeline_ms'] for r in runs]))) for label,runs in case.items()}
                    reduction=1-summary['after']['median_mean_ms']/summary['before']['median_mean_ms']
                    for before,after in zip(case['before'],case['after']):assert before['triangles']==after['triangles']
                    report['cases'][str(roots)+'-'+route]=dict(runs=case,summary=summary,frame_time_reduction=reduction)
                    print(roots,route,summary,'reduction',round(reduction*100,1),flush=True)
                    report.update(gpu=GL.glGetString(GL.GL_RENDERER).decode(),gl_error=int(GL.glGetError()))
                    assert report['gl_error']==0
                    args.output.write_text(json.dumps(report,indent=2),encoding='utf8')
        finally:
            for state in states.values():state['target'].close();state['renderer'].close()


if __name__=='__main__':main()
