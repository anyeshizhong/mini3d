"""Real editor UI cancellation and quit while a CPU worker remains blocked."""
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def smoke(output):
    import imgui
    import pygame
    from mini3d import asset_loader
    from mini3d.assets import Asset
    from mini3d.scene import Entity
    from mini3d.editor import Editor
    from mini3d.editor_ui import EditorUI
    from mini3d.editor_runtime import run

    output.mkdir(parents=True, exist_ok=False)
    os.environ['MINI3D_RENDER_BACKEND'] = 'python'
    entered, release = threading.Event(), threading.Event()
    state = dict(frame=0, phase='loading', mouse=(0, 0))
    real_get, real_flip, real_draw, real_button = pygame.event.get, pygame.display.flip, EditorUI.draw, imgui.button
    started = time.perf_counter()

    def blocked(path, cache):
        entered.set()
        assert release.wait(20), 'Test worker release timed out'
        return Asset(path, Entity(name='late template'))

    def draw(ui, *args):
        state['app'] = ui.app
        return real_draw(ui, *args)

    def button(label, *args, **kwargs):
        result = real_button(label, *args, **kwargs)
        if label == 'Cancel model loading':
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            state['cancel_point'] = ((lo.x+hi.x)/2, (lo.y+hi.y)/2)
        return result

    def events():
        actual = real_get()
        assert time.perf_counter()-started < 15
        frame, app = state['frame'], state.get('app')
        if frame == 4:
            assert entered.is_set()
            point = tuple(map(int, state['cancel_point']))
            state['mouse'] = point
            return actual + [pygame.event.Event(pygame.MOUSEMOTION, pos=point, rel=(0, 0), buttons=(0, 0, 0)),
                             pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=point, button=1)]
        if frame == 5:
            return actual + [pygame.event.Event(pygame.MOUSEBUTTONUP, pos=state['mouse'], button=1)]
        if frame == 7:
            assert app.asset_loading.pending is None, 'Cancel model loading did not cancel'
            assert not app.scene.root_entities
            state['phase'] = 'cancelled'
            app.asset_loading.request('add_asset', 0)
        if frame == 10:
            assert app.asset_loading.pending is not None
            assert not app.scene.root_entities
            state['quit_started'] = time.perf_counter()
            return actual + [pygame.event.Event(pygame.QUIT)]
        return actual

    def flip():
        real_flip()
        state['frame'] += 1

    try:
        with patch.object(asset_loader, 'prepare_asset', blocked), patch.object(EditorUI, 'draw', draw), \
             patch.object(imgui, 'button', button), patch.object(pygame.event, 'get', events), \
             patch.object(pygame.display, 'flip', flip):
            run(Editor, ipc=False)
        quit_seconds = time.perf_counter()-state['quit_started']
        loading = state['app'].asset_loading
        assert loading.closed and loading.pending is None
        assert quit_seconds < .5, quit_seconds
        assert loading.loader._thread.is_alive(), 'Worker should still be waiting; quit must not join it'
        release.set()
        loading.loader._thread.join(2)
        assert not loading.loader._thread.is_alive()
        assert loading.loader.poll() is None
        assert not state['app'].scene.root_entities
        report = dict(passed=True, quit_seconds=quit_seconds, ui_frames=state['frame'],
                      checks=['Cancel model loading button via SDL click', 'cancelled result never commits',
                              'quit does not join blocked worker', 'late result suppressed after shutdown'])
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps(report, indent=2))
    finally:
        release.set()


if __name__ == '__main__':
    smoke(Path(sys.argv[1]).resolve())
