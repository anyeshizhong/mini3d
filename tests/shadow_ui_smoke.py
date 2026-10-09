"""Real Editor checkbox -> live scene shadow preview (SDL/ImGui, GPU)."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import imgui
import numpy as np
import pygame
from OpenGL import GL as gl
import editor_app
from mini3d import editor
from mini3d.editor_ui import EditorUI
from mini3d.render_target import RenderTarget


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    state = dict(frame=0,items={},pictures={})
    real_get,real_flip = pygame.event.get,pygame.display.flip
    real_checkbox = imgui.checkbox

    class App(editor.Editor):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.assets = [dict(name='Shadow PBR cube',path=str(ROOT/'docs/shadows/pbr-cube.gltf'))]
            self.show_grid = False
            self.set_lighting(mode='Scene',direction=[1,-1,2],diffuse=2,ambient=.12)
            ground = self.add_asset(0)
            ground.pos[:],ground.scale[:] = [0,0,-.14],[5,5,.2]
            cube = self.add_asset(0)
            cube.pos[:] = [0,0,.7]
            self.scene.selected_ids = []
            self.scene.primary_selection_id = None
            self.scene.update()
            self.frame_all()
            self.viewer.controller.yaw = 2.15
            self.viewer.controller.pitch = .9
            self.viewer.controller.update()
            state['app'] = self

    class UI(EditorUI):
        def __init__(self,*args):
            super().__init__(*args)
            self._show_lighting = True

    class Target(RenderTarget):
        def __init__(self):
            super().__init__()
            state.setdefault('target',self)

    def checkbox(label,*args,**kwargs):
        result = real_checkbox(label,*args,**kwargs)
        if label == 'Scene shadows':
            low,high = imgui.get_item_rect_min(),imgui.get_item_rect_max()
            state['point'] = (int(low.x+8),int((low.y+high.y)/2))
        return result

    def events():
        real_get()
        frame = state['frame']
        if frame in (4,10):
            point = state['point']
            return [pygame.event.Event(pygame.MOUSEMOTION,pos=point,rel=(0,0),buttons=(0,0,0)),
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=point,button=1)]
        if frame in (5,11):
            return [pygame.event.Event(pygame.MOUSEBUTTONUP,pos=state['point'],button=1)]
        return []

    def inspect():
        frame = state['frame']
        if frame in (3,8,14):
            expected = frame == 8
            assert state['app'].scene.shadows_enabled == expected
            target = state['target']
            old = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,target.framebuffer)
            size = state['app'].viewport_rect[2:]
            raw = gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            state['pictures'][frame] = np.frombuffer(raw,np.uint8).copy()
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,old)
            screen = pygame.display.get_window_size()
            pixels = gl.glReadPixels(0,0,*screen,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            pygame.image.save(pygame.image.fromstring(pixels,screen,'RGB',True),str(output/('editor-'+str(frame)+'.png')))
        assert gl.glGetError() == gl.GL_NO_ERROR
        real_flip()
        state['frame'] += 1

    with patch.object(editor,'Editor',App),patch('mini3d.editor_ui.EditorUI',UI), \
            patch('mini3d.render_target.RenderTarget',Target),patch.object(imgui,'checkbox',checkbox), \
            patch.object(pygame.event,'get',events),patch.object(pygame.display,'flip',inspect):
        editor_app.main(['--empty','--hidden','--frames','16'])
    pictures = state['pictures']
    assert np.count_nonzero(pictures[3] != pictures[8]) > 100
    np.testing.assert_array_equal(pictures[3],pictures[14])
    print('PASS: real Editor Scene shadows checkbox on/off, immediate GPU change, exact restoration')


if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/shadow-ui')
