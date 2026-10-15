"""Measure complete moving editor frames, including ImGui and presentation."""
import argparse
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import numpy as np
import pygame

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from tools.build_roman_street import build_scene
from spqr_performance_benchmark import pose
from OpenGL import GL


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    base=args.baseline_project.resolve()/'mini3d'
    spec=importlib.util.spec_from_file_location('editor_before',base/'__init__.py',submodule_search_locations=[str(base)])
    package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
    report=dict(window=[1440,900],quality='Arrange Editor View, 1x AA, 2048 shadows, identical panel layout',cases={})
    for route in ('walk','orbit'):
        runs={'before':[],'after':[]}
        for repeat in range(3):
            for label in (('before','after') if repeat%2==0 else ('after','before')):
                prefix='editor_before' if label=='before' else 'mini3d'
                module=lambda name:importlib.import_module(prefix+'.'+name)
                editor=module('editor');ui_module=module('editor_ui');runtime=module('editor_runtime')
                original_ui=ui_module.EditorUI;original_get=pygame.event.get;original_flip=pygame.display.flip
                samples=[];intervals=[];state=dict(frame=0,started=0,previous=None,redraws=0,rect=None)
                class MovingUI(original_ui):
                    def __init__(self,app):
                        super().__init__(app);build_scene(app.api);app.set_camera_view(False)
                        self.workspace='Arrange';self.assets_visible=False
                    def draw(self,width,height,texture):
                        frame=state['frame'];p,q=pose(route,frame/5 if frame<6 else (frame-6)/23)
                        self.app.viewer.camera.position=p;self.app.viewer.camera.look_at(q)
                        result=super().draw(width,height,texture);state['rect']=result
                        state['app']=self.app
                        return result
                def get_events(*a,**kw):
                    now=time.perf_counter()
                    if state['previous'] is not None and state['frame']>=7:
                        intervals.append((now-state['previous'])*1000)
                    state['previous']=now;state['started']=now
                    return original_get(*a,**kw)
                def flip():
                    original_flip();end=time.perf_counter()
                    if state['frame']>=6:
                        samples.append((end-state['started'])*1000)
                        assert state['app'].api._renderer.render_stats['viewport_redrawn']
                        state['redraws']+=1
                    state['frame']+=1
                    if state['frame']==30:
                        assert GL.glGetError()==0
                        if repeat==2:state['app'].api.screenshot(args.output/(route+'-'+label+'.png'))
                # Share the same model catalog/data without sharing baseline code.
                with patch.object(editor,'PROJECT',ROOT),patch.object(ui_module,'EditorUI',MovingUI),\
                     patch.object(pygame.event,'get',get_events),patch.object(pygame.display,'flip',flip):
                    runtime.run(editor.Editor,initial_asset=None,frames=30,hidden=True,ipc=False)
                runs[label].append(dict(mean_frame_ms=float(np.mean(samples)),p95_frame_ms=float(np.percentile(samples,95)),
                    mean_interval_ms=float(np.mean(intervals)),frame_ms=samples,interval_ms=intervals,viewport=list(state['rect']),redrawn_frames=state['redraws']))
                print(route,repeat,label,round(np.mean(samples),2),'ms',flush=True)
        summary={label:dict(median_mean_ms=float(np.median([r['mean_frame_ms'] for r in values])),
                           median_interval_ms=float(np.median([r['mean_interval_ms'] for r in values])),
                           p95_ms=float(np.percentile([t for r in values for t in r['frame_ms']],95))) for label,values in runs.items()}
        report['cases'][route]=dict(runs=runs,summary=summary)
        (args.output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')


if __name__=='__main__':main()
