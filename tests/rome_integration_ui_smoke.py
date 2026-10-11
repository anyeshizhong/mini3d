"""Actual Editor/Camera View screenshots for Issue #4's saved Roman scene."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
import editor_app
from mini3d import editor
from mini3d.camera import Camera
from mini3d.shot_camera import ShotCamera


def run(output):
    state=dict(frame=0)
    views=json.loads((output/'views.json').read_text(encoding='utf8'))
    real_get,real_flip=pygame.event.get,pygame.display.flip

    class App(editor.Editor):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.load_scene(output/'rome-scene.json')
            self.commands.set_selection([])
            self.sync_selection()
            self.show_grid=False
            state['app']=self

    def events():
        real_get()
        app=state['app']
        case=state['frame']//4
        if state['frame']%4==0:
            index=(case%4)//2
            enabled=bool(case%2)
            view=views[index]
            app.set_shadows(enabled=enabled)
            delta=np.array(view['position'])-view['target']
            control=app.viewer.controller
            control.target=np.array(view['target'])
            control.distance=float(np.linalg.norm(delta))
            control.yaw=float(np.arctan2(delta[1],delta[0]))
            control.pitch=float(np.arcsin(delta[2]/control.distance))
            control.update()
            camera=Camera(view['position'],near=view['near'],far=view['far'])
            camera.look_at(view['target'])
            shot=ShotCamera(camera)
            shot.set_aspect(view['aspect']);shot.set_lens(view['focal_mm'])
            app.shot_camera=shot
            app.viewer.camera.fov_y=shot.fov_y
            app.set_camera_view(case>=4)
            state['name']='%s-view%d-%s'%('camera-ui' if case>=4 else 'editor',index,'on' if enabled else 'off')
            app.status='Issue #4: Rome ORIGINAL Unlit; 40 PBR soldiers; Scene shadows '+('ON' if enabled else 'OFF')
        return []

    def inspect():
        if state['frame']%4==3:
            size=pygame.display.get_window_size()
            raw=gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            pygame.image.save(pygame.image.fromstring(raw,size,'RGB',True),str(output/(state['name']+'.png')))
            assert gl.glGetError()==gl.GL_NO_ERROR
        real_flip();state['frame']+=1

    with patch.object(editor,'Editor',App),patch.object(pygame.event,'get',events),patch.object(pygame.display,'flip',inspect):
        editor_app.main(['--empty','--hidden','--frames','32'])
    assert state['frame']==32
    print('PASS: actual Editor and Camera View, two viewpoints x shadows off/on, original Unlit Rome')


if __name__=='__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'docs/rome-integration')
