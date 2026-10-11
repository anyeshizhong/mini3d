"""40 real soldiers in Editor Runtime: idle reuse, move/undo and lighting redraw.

Run: python -B tests/editor_retained_view_smoke.py OUTPUT [BASELINE_PACKAGE_ROOT]
This owns one temporary editor and does not touch the user's scene.
"""
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASELINE = len(sys.argv) > 2
sys.path.insert(0, str(Path(sys.argv[2]) if BASELINE else ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
import mini3d.editor as editor_module
editor_module.PROJECT = ROOT
from mini3d.editor import Editor
from mini3d.editor_runtime import run
from mini3d.gl_renderer import GLRenderer


def smoke(output):
    output.mkdir(parents=True, exist_ok=False)
    state = dict(frame=0, times=[], draws=0, images={}, results={})
    flip_original = pygame.display.flip

    class App(Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state['app'] = self
            soldier = self.commands.spawn(ROOT/'model/05_roman_soldier/roman_legionnaire.glb', scale=[.1]*3)
            state['soldier'] = soldier
            for index in range(40):
                actor = soldier if index == 0 else self.commands.duplicate(soldier)
                actor.pos[:] = [(index%8)*1.8, (index//8)*1.8, .174]
            self.commands.spawn('builtin:ground',position=[6,4,0],scale=[4,3,1])
            self.frame_all()
            self.set_lighting(mode='Scene')
            self.set_shadows(enabled=True,resolution=2048)

    class Renderer(GLRenderer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state['renderer'] = self
        def render(self, *args, **kwargs):
            state['draws'] += 1
            return super().render(*args, **kwargs)

    def snapshot(name):
        rect = state['app'].viewport_rect
        # Read the scene target that the renderer just rendered/cached, using
        # the editor screenshot's viewport crop (includes ImGui overlays).
        if BASELINE:
            return
        state['app'].api.screenshot(output/(name+'.png'))
        image = pygame.surfarray.array3d(pygame.image.load(str(output/(name+'.png'))))
        x,y,w,h = rect
        state['images'][name] = image[x:x+w,y:y+h].copy()

    def flip():
        gl.glFinish()
        frame = state['frame']
        now = perf_counter()
        if 3 <= frame <= 12:
            state['times'].append((now-state['last'])*1000)
        state['last'] = now
        if frame == 12:
            state['results']['idle_draws'] = state['draws']
            if not BASELINE:
                assert state['draws'] <= 3, state['draws']  # Initial UI layout may resize once.
            snapshot('before')
            if BASELINE:
                state['app'].commands.set_transform(state['soldier'],position=[2,0,.174])
            else:
                state['app'].api.set_transform(state['soldier'].entity_id,position=[2,0,.174])
            state['before_move_draws'] = state['draws']
        elif frame == 14:
            assert state['draws'] > state['before_move_draws']
            snapshot('moved')
            state['app'].commands.undo()
            state['before_undo_draws'] = state['draws']
        elif frame == 16:
            assert state['draws'] > state['before_undo_draws']
            snapshot('undone')
            if not BASELINE:
                a,b,c = [state['images'][name] for name in ('before','moved','undone')]
                assert np.count_nonzero(a != b) > 1000
                np.testing.assert_array_equal(a,c)
            state['app'].scene.light_dir[0] *= -1
            state['before_light_draws'] = state['draws']
        elif frame == 18:
            assert state['draws'] > state['before_light_draws']
            assert gl.glGetError() == gl.GL_NO_ERROR
            state['results'].update(passed=True, idle_median_ms=statistics.median(state['times']),
                idle_samples_ms=state['times'], gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                checks=['40 soldiers', 'live viewport redraw on move/undo/light',
                        'undo restores viewport pixels'] if not BASELINE else ['baseline timings'])
        state['frame'] += 1
        flip_original()

    with patch('mini3d.gl_renderer.GLRenderer',Renderer), patch('pygame.display.flip',flip):
        kwargs = {} if BASELINE else dict(ipc=False)
        run(App,initial_asset=None,frames=20,hidden=True,**kwargs)
    (output/'report.json').write_text(json.dumps(state['results'],indent=2),encoding='utf8')
    print(json.dumps(state['results'],indent=2))


if __name__ == '__main__':
    smoke(Path(sys.argv[1]))
