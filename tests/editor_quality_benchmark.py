"""Real 40-soldier GPU timings; same geometry and quality before/after.

Run: python -B tests/editor_quality_benchmark.py OUTPUT
This owns a temporary GL context, never attaches to a user's editor.
"""
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    pygame.init()
    pygame.display.set_mode((846, 662), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    app, renderer, target = Editor(846, 662), GLRenderer(846, 662), RenderTarget()
    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(), timings={})
    try:
        soldier = app.commands.spawn(ROOT / 'model/05_roman_soldier/roman_legionnaire.glb', scale=[.1]*3)
        for index in range(40):
            actor = soldier if index == 0 else app.commands.duplicate(soldier)
            actor.pos[:] = [(index % 8)*1.8, (index // 8)*1.8, .174]
        app.commands.spawn('builtin:ground', position=[6, 4, 0], scale=[4, 3, 1])
        app.frame_all()
        app.scene.lighting_mode = 'Scene'
        app.scene.light_dir = np.array([-1., -.35, .3])
        app.scene.shadow_resolution = 2048
        app.scene.show_grid = app.scene.show_axes = False
        target.resize(846, 662)

        def draw():
            app.scene.update()
            app.viewer.update_clipping()
            target.bind()
            gl.glDepthMask(True)
            renderer.render(app.scene, app.viewer.camera)
            gl.glFinish()  # Include actual GPU completion, not submission time.
            pygame.event.pump()

        for name, shadows, orbit in [('no-shadow', False, False),
                                     ('static-shadow', True, False),
                                     ('orbit-shadow', True, True)]:
            app.scene.shadows_enabled = shadows
            for _ in range(2):
                draw()
            samples = []
            for index in range(8):
                started = perf_counter()
                if orbit:
                    app.viewer.controller.orbit(2, 0)
                draw()
                samples.append((perf_counter()-started)*1000)
            report['timings'][name] = dict(median_ms=statistics.median(samples),
                                           samples_ms=samples, stats=dict(renderer.render_stats))
        assert gl.glGetError() == gl.GL_NO_ERROR
        (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps(report, indent=2))
    finally:
        target.close()
        renderer.close()
        pygame.quit()


if __name__ == '__main__':
    run(Path(sys.argv[1]))
