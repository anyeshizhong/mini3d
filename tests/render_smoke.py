"""Run all real demo loops in hidden OpenGL windows, with navigation events.

Usage: python -B tests/render_smoke.py [screenshot-directory]
Requires a working desktop OpenGL driver; not part of the headless unit suite.
"""
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import numpy as np
import pygame
from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, GL_NO_ERROR, glGetError, glReadPixels

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_demo(filename, output=None):
    # Importing must not open a window or start the old top-level demo loop.
    module = runpy.run_path(str(ROOT / filename), run_name="smoke_import")
    assert not pygame.display.get_init(), "Import unexpectedly opened a window"
    set_mode = pygame.display.set_mode
    event_get = pygame.event.get
    flip = pygame.display.flip
    state = {"frame": 0, "captures": 0}

    def hidden_mode(size, flags=0, *args, **kwargs):
        return set_mode(size, flags | pygame.HIDDEN, *args, **kwargs)

    def events():
        event_get()  # Pump real window events; inject a deterministic sequence.
        frame = state["frame"]
        make = pygame.event.Event
        sequence = {
            1: [make(pygame.MOUSEBUTTONDOWN, button=1),
                make(pygame.MOUSEMOTION, rel=(40, -20), buttons=(1, 0, 0), mod=0)],
            2: [make(pygame.MOUSEMOTION, rel=(20, 10), buttons=(1, 0, 0), mod=pygame.KMOD_SHIFT),
                make(pygame.MOUSEBUTTONUP, button=1)],
            3: [make(pygame.MOUSEWHEEL, y=2)],
            4: [make(pygame.KEYDOWN, key=pygame.K_f, mod=0)],
            5: [make(pygame.KEYDOWN, key=pygame.K_7, mod=0)],
            6: [make(pygame.KEYDOWN, key=pygame.K_HOME, mod=0)],
            7: [make(pygame.VIDEORESIZE, w=640, h=800)],
            8: [make(pygame.KEYDOWN, key=pygame.K_r, mod=0)],
            9: [make(pygame.QUIT)],
        }
        return sequence.get(frame, [])

    def inspect_frame():
        error = glGetError()
        assert error == GL_NO_ERROR, "OpenGL error {} in {}".format(error, filename)
        if state["frame"] in (0, 5):
            size = pygame.display.get_surface().get_size()
            pixels = glReadPixels(0, 0, *size, GL_RGB, GL_UNSIGNED_BYTE)
            rgb = np.frombuffer(pixels, dtype=np.uint8).reshape(-1, 3).astype(int)
            # Require colored model pixels, not merely background/grid lines.
            colorful = (rgb.max(axis=1) - rgb.min(axis=1)) > 40
            assert np.count_nonzero(colorful) > 1000, "Missing model in " + filename
            if output is not None:
                image = pygame.image.fromstring(pixels, size, "RGB", True)
                pygame.image.save(image, str(output / (Path(filename).stem + "-" + str(state["frame"]) + ".png")))
            state["captures"] += 1
        flip()
        state["frame"] += 1

    try:
        with patch.object(pygame.display, "set_mode", hidden_mode), \
                patch.object(pygame.event, "get", events), \
                patch.object(pygame.display, "flip", inspect_frame):
            module["main"]()
        assert state["captures"] == 2
        print("PASS:", filename, "startup, orbit, pan, zoom, focus, top, frame-all, resize, reset")
    finally:
        pygame.quit()


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
    for filename in ("1.py", "1 copy.py", "2.py"):
        if filename == '2.py' and not (ROOT / 'model/07_urdf_car/car/urdf/car.urdf').is_file():
            print('SKIP: 2.py requires optional local 07 URDF assets')
            continue
        run_demo(filename, output)
