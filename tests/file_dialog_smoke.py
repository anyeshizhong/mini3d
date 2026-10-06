"""Real Tk picker + hidden OpenGL editor: pending, cancel, reopen, quit.

The native file picker briefly appears. No user interaction is required; the
test closes only the picker process it starts. Requires desktop Tk/OpenGL.
"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pygame
from OpenGL import GL as gl
from mini3d import editor


def run_smoke():
    state = {"frame": 0, "workers": []}
    real_get, real_flip = pygame.event.get, pygame.display.flip

    class CaptureEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state["app"] = self

    def events():
        real_get()
        frame, app = state["frame"], state["app"]
        if frame in (2, 70):
            app.browse_model()
            state["workers"].append(app.model_dialog._process)
        if frame == 45:
            assert app.model_dialog.pending
            assert app.model_dialog._process.poll() is None, app.status
            original = app.model_dialog._process
            app.browse_model()
            assert app.model_dialog._process is original
            from pygame._sdl2.video import Window
            Window.from_display_module().size = (1200, 800)
        if frame == 60:
            app.cancel_model_dialog()
            assert not app.model_dialog.pending
            assert state["workers"][0].poll() is not None
        if frame == 115:
            assert app.model_dialog.pending
            assert app.model_dialog._process.poll() is None, app.status
            return [pygame.event.Event(pygame.QUIT)]
        return []

    def inspect():
        assert gl.glGetError() == gl.GL_NO_ERROR
        if state["frame"] == 50:
            assert pygame.display.get_window_size() == (1200, 800)
            assert state["app"].viewer.width == state["app"].viewport_rect[2]
        real_flip()
        state["frame"] += 1

    with patch.object(editor, "Editor", CaptureEditor), \
            patch.object(pygame.event, "get", events), \
            patch.object(pygame.display, "flip", inspect):
        editor.run(initial_asset=0, frames=120, hidden=True)
    assert state["frame"] == 115
    assert all(worker.poll() is not None for worker in state["workers"])
    assert not state["app"].model_dialog.pending
    print("PASS: editor renders/resizes while native Tk picker stays open; cancel, reopen and editor quit clean up workers")


if __name__ == "__main__":
    run_smoke()
