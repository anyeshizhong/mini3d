"""Own a test editor: routed face click, resized frames, IPC color, settle and PNG.

python -B tests/photo_workflow_ui_smoke.py OUTPUT SCENE
Synthetic mouse events run the actual input router; this is not a human acceptance claim.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace
from time import perf_counter
import sys
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pygame
import imgui
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.editor_ui import EditorUI
from mini3d.editor_runtime import run
from mini3d.ipc_client import EditorClient
from mini3d.gl_state import read_rgb


def pixels(path):return pygame.surfarray.array3d(pygame.image.load(str(path))).transpose(1,0,2)


def smoke(output,scene):
    output.mkdir(parents=True,exist_ok=True)
    state={'frame':0,'checks':{},'times':[],'sizes':[]};original_flip=pygame.display.flip
    registry=output/'registry'
    with ThreadPoolExecutor(1) as pool:
        class App(Editor):
            def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);state['app']=self
        class UI(EditorUI):
            def __init__(self,app):super().__init__(app);state['ui']=self
            def draw(self,width,height,texture_id):
                state['display_texture']=texture_id
                return super().draw(width,height,texture_id)
        def point():
            x,y,w,h=state['app'].viewport_rect;return [x+w*.32,y+h*.34]
        def routed_click():
            app=state['app'];ui=state['ui']
            # Use the editor's same UI capture contract, after it reports the image rectangle.
            previous=ui.modal_open,ui.mouse_captured,ui.asset_dragging,ui.viewport_hovered
            ui.modal_open=False;ui.mouse_captured=False;ui.asset_dragging=False;ui.viewport_hovered=True
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=point()),ui)
            app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP,button=1,pos=point()),ui)
            ui.modal_open,ui.mouse_captured,ui.asset_dragging,ui.viewport_hovered=previous
        def flip():
            frame=state['frame'];app=state['app'];ui=state['ui']
            gl.glFinish()
            if frame==0 and ui.startup_message:
                # The first visible frame deliberately precedes native creation.
                assert 'target' not in state
                app.api.screenshot(output/'startup-editor.png')
                state['checks']['startup_before_native_scene']=True
                original_flip();state['frame']+=1
                return
            assert state['display_texture']==state['target'].texture
            if 56 <= frame <= 80:
                state['times'].append((perf_counter()-state['changed_at'])*1000)
                state['sizes'].append([state['target'].width,state['target'].height])
            if frame==2:
                files=list(registry.glob('*.json'));assert len(files)==1
                state['client']=EditorClient(json.loads(files[0].read_text()))
                assert app.camera_view and ui.workspace=='Shot'
                state['gpu']=gl.glGetString(gl.GL_RENDERER).decode()
            elif frame==4:
                pose=app.shot_camera.view_matrix.copy();routed_click()
                assert app.shot_camera.focus_point is not None
                np.testing.assert_array_equal(pose,app.shot_camera.view_matrix)
                state['first_focus']=app.shot_camera.focus_distance
            elif frame==16:
                routed_click()
                assert abs(app.shot_camera.focus_distance-state['first_focus'])<.002
                before=app.shot_camera.to_dict();x,y,w,h=app.viewport_rect
                assert not app.api.focus_screen([x-1,y+h*.5])['focused']
                assert not app.api.focus_screen([x+w*.98,y+h*.02])['focused']
                assert app.shot_camera.to_dict()==before
                app.api.screenshot(output/'clicked-face-editor.png')
                state['checks']['real_routed_face_click_repeat_sky_and_black_borders']=True
                from pygame._sdl2.video import Window
                # SDL event.window borrows a raw pointer to this wrapper;
                # keep the Python object alive until SDL shutdown.
                state['window']=Window.from_display_module()
                state['window'].size=(1000,760)
                app.set_shot_aspect('1:1')
            elif frame==32:
                routed_click()
                x,y,w,h=app.viewport_rect;assert abs(w/h-1)<.01
                app.api.screenshot(output/'resized-square-editor.png')
                state['checks']['resized_square_focus_and_marker']=True
                app.set_shot_aspect('3:2')
                # Independent client process-style HTTP request, pumped on the UI thread.
                state['future']=pool.submit(state['client'].call,'set_photo_color',white_balance_kelvin=7400,preset='Warm')
            elif frame==47:
                assert state['future'].done();result=state['future'].result();assert result['ok'],result
                assert app.shot_camera.white_balance_kelvin==7400 and app.shot_camera.color_preset=='Warm'
                state['checks']['ipc_color_and_shared_ui_state']=True
                state['base_focus']=app.shot_camera.focus_distance
            if 49 <= frame <= 79:
                app.api.set_depth_of_field(focus_distance=state['base_focus']+.02*np.sin(frame*.4))
                state['changed_at']=perf_counter()
            elif frame==101:
                assert (state['target'].width,state['target'].height)==app.shot_camera.size
                state['checks']['interactive_960_then_idle_full_size']=True
                app.api.focus_screen(point())
                app.api.save_scene(output/'final.scene.json')
                app.api.capture(output/'final.png')
            elif frame==119:
                shot=app.shot_camera;target=state['target']
                gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,target.framebuffer)
                preview=np.frombuffer(read_rgb(0,0,*shot.size),np.uint8).reshape(shot.size[1],shot.size[0],3)[::-1]
                np.testing.assert_array_equal(preview,pixels(output/'final.png'))
                app.api.screenshot(output/'final-editor.png')
                app.api.load_scene(output/'final.scene.json');app.api.capture(output/'reloaded.png')
                np.testing.assert_array_equal(pixels(output/'final.png'),pixels(output/'reloaded.png'))
                state['checks']['idle_preview_png_reload_exact']=True
            assert gl.glGetError()==0
            original_flip();state['frame']+=1
        from mini3d.shot_camera import render_scene_view as original_render
        def render(*args,**kwargs):
            state['target']=args[3]
            return original_render(*args,**kwargs)
        with patch('mini3d.editor_ui.EditorUI',UI),patch.object(pygame.display,'flip',flip),patch('mini3d.editor_runtime.render_scene_view',render):
            run(App,initial_asset=None,frames=122,ipc_directory=registry,scene_path=scene)
    report=dict(passed=True,gpu=state['gpu'],checks=state['checks'],
        interaction=dict(samples=len(state['times']),median_ms=float(np.median(state['times'])),
            p95_ms=float(np.percentile(state['times'],95)),samples_ms=state['times'],render_sizes=state['sizes'],
            measurement='parameter change to completed real editor frame; excludes PNG, screenshots and readback'))
    assert all(size==[960,640] for size in state['sizes'])
    (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':smoke(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
