"""Interactive (unbounded-loop) loading acceptance using the real Legionnaire."""
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def smoke(output, injected_delay=.5):
    import pygame
    from pygame._sdl2.video import Window
    from OpenGL import GL as gl
    from mini3d import asset_loader
    from mini3d.editor import Editor
    from mini3d.editor_ui import EditorUI
    from mini3d.editor_runtime import run
    from mini3d.native_renderer import NativeSceneRenderer

    output.mkdir(parents=True, exist_ok=False)
    ctypes.windll.kernel32.SetErrorMode(2)
    fault = (output / 'fault.log').open('w')
    faulthandler.enable(fault)
    os.environ['MINI3D_RENDER_BACKEND'] = 'native'
    state = dict(frame=0, phase='loading', cpu_frames=0, steps=[], flips=[], worker_threads=[])
    start = time.perf_counter()
    main_thread = threading.get_ident()
    prepare, draw = asset_loader.prepare_asset, EditorUI.draw
    events, flip = pygame.event.get, pygame.display.flip
    step = NativeSceneRenderer.prepare_step

    def cpu(*args, **kwargs):
        state['worker_threads'].append(threading.get_ident())
        # Deliberately slow CPU IO proves that UI progress does not depend on it.
        if injected_delay:
            time.sleep(injected_delay)
        return prepare(*args, **kwargs)

    def ui_draw(ui, *args):
        state['app'], state['ui'] = ui.app, ui
        return draw(ui, *args)

    def prepare_step(native, *args, **kwargs):
        assert threading.get_ident() == main_thread
        before = time.perf_counter()
        ready = step(native, *args, **kwargs)
        state['steps'].append(dict(seconds=time.perf_counter()-before, ready=ready,
                                   message=native.preparation_message))
        return ready

    def get_events():
        result = events()
        assert time.perf_counter()-start < 70, state
        app = state.get('app')
        if app is not None:
            if app.asset_loading.pending is not None:
                state['cpu_frames'] += 1
            native = getattr(app.api._renderer, 'native_renderer', None)
            stats = app.api._renderer.render_stats
            if (native is not None and native.preparation_message == 'Native scene bundle ready'
                    and not state.get('moved_during_prepare')):
                app.selection.pos[0] += .25
                state['moved_during_prepare'] = True
            if (state['phase'] == 'loading' and native is not None and native.frames >= 1
                    and state['ui'].startup_message is None):
                assert stats['backend'] == 'native-arrange', stats
                assert stats['color_triangles'] == 589879, stats
                assert native.transform_updates >= 1, 'Preparation-time transform was not sent to native'
                assert state['cpu_frames'] >= (10 if injected_delay else 1), state
                assert all(t != main_thread for t in state['worker_threads'])
                state['scene_seconds'] = time.perf_counter()-start
                app.api.screenshot(output / 'arrange.png')
                app.undo()
                assert not app.scene.root_entities
                app.redo()
                assert len(app.scene.root_entities) == 1
                app.create_camera_from_view()
                app.set_camera_view(True)
                app.workspace = 'Shot'
                state['phase'] = 'shot'
            elif state['phase'] == 'shot' and stats.get('backend') == 'native-photo':
                app.api.screenshot(output / 'shot.png')
                state['phase'] = 'done'
                result.append(pygame.event.Event(pygame.QUIT))
        return result

    def present():
        app = state['app']
        assert gl.glGetError() == gl.GL_NO_ERROR
        if state['frame'] == 0:
            app.api.screenshot(output / 'startup.png')
            state['first_ui_seconds'] = time.perf_counter()-start
            state['window'] = Window.from_display_module()  # Hold borrowed SDL wrapper.
        if state['frame'] == 5:
            state['window'].size = (1180, 760)
        flip()
        state['flips'].append(time.perf_counter()-start)
        state['frame'] += 1

    try:
        with patch.object(asset_loader, 'prepare_asset', cpu), \
             patch.object(EditorUI, 'draw', ui_draw), \
             patch.object(NativeSceneRenderer, 'prepare_step', prepare_step), \
             patch.object(pygame.event, 'get', get_events), patch.object(pygame.display, 'flip', present):
            run(Editor, ipc=False)
        assert state['phase'] == 'done', state['phase']
        report = dict(passed=True, injected_cpu_delay=injected_delay, first_ui_seconds=state['first_ui_seconds'],
                      scene_seconds=state['scene_seconds'], cpu_responsive_frames=state['cpu_frames'],
                      frame_count=state['frame'], steps=state['steps'],
                      longest_prepare_step=max(row['seconds'] for row in state['steps']),
                      longest_present_gap=max(b-a for a,b in zip(state['flips'],state['flips'][1:])),
                      checks=['worker CPU decode', 'UI events while loading', 'resize during loading',
                              'real native 589879-triangle scene', 'transform edit during preparation',
                              'single Add Undo/Redo', 'staged Shot switch'])
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps(report, indent=2))
    finally:
        faulthandler.disable()
        fault.close()


if __name__ == '__main__':
    smoke(Path(sys.argv[1]).resolve(), 0 if '--real-timing' in sys.argv[2:] else .5)
