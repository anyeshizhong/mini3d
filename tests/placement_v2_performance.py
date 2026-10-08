"""Measure real Editor/OpenGL Roman 1/40/100 cases; no optimization or downloads.

Run: F:/gymenv/python.exe -B tests/placement_v2_performance.py [result.json]
Wall frame samples include Editor UI, selection outline and synchronized GPU
completion. Render samples include synchronized scene rendering only. The same
OpenGL context/cache stays alive across all counts to detect repeated uploads.
"""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pygame
from OpenGL import GL as gl

from mini3d import editor
from mini3d.gl_renderer import GLRenderer
from mini3d.picking import pick_entity, project_point
from mini3d.placement import SurfaceHit, geometry_bounds


def measure(output):
    roman_path = ROOT / "model/05_roman_soldier/roman_legionnaire.glb"
    if not roman_path.is_file():
        raise FileNotFoundError("Existing Roman asset is required: " + str(roman_path))
    state = dict(frame=0, case=None, samples=[], results=[], render_ms=0,
                 uploads=dict(buffers=0, textures=0), measuring_render=False)
    original_get, original_flip = pygame.event.get, pygame.display.flip
    original_render = GLRenderer.render
    original_buffer, original_texture = gl.glBufferData, gl.glTexImage2D

    class TestEditor(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            state['graphics'] = dict(vendor=gl.glGetString(gl.GL_VENDOR).decode(),
                                     renderer=gl.glGetString(gl.GL_RENDERER).decode(),
                                     version=gl.glGetString(gl.GL_VERSION).decode())
            self.assets = []  # Asset thumbnails are unrelated to instance caches.
            root = self.commands.spawn(str(roman_path))
            low, high = geometry_bounds(root)
            self.commands.set_transform(root, scale=np.full(3, 1.8 / (high[2] - low[2])))
            self.commands.place_on_surface(root, SurfaceHit([0, 0, 0], [0, 0, 1]))
            self.select(root)
            self.commands.clear_history()
            self.show_grid = False
            state["app"], state["source"] = self, root

    def upload_buffer(*args, **kwargs):
        if state["measuring_render"]:
            state["uploads"]["buffers"] += 1
        return original_buffer(*args, **kwargs)

    def upload_texture(*args, **kwargs):
        if state["measuring_render"]:
            state["uploads"]["textures"] += 1
        return original_texture(*args, **kwargs)

    def render(renderer, *args, **kwargs):
        state["renderer"] = renderer
        started = time.perf_counter()
        state["measuring_render"] = True
        try:
            result = original_render(renderer, *args, **kwargs)
            gl.glFinish()
        finally:
            state["measuring_render"] = False
        state["render_ms"] = (time.perf_counter() - started) * 1000
        return result

    def milliseconds(operation):
        started = time.perf_counter()
        result = operation()
        return (time.perf_counter() - started) * 1000, result

    def prepare(count):
        app, source = state["app"], state["source"]
        if state["case"] not in (None, 1):
            assert app.commands.undo()
            assert app.scene.root_entities == [source]
        app.select(source)
        if count > 1:
            rows, columns = (5, 8) if count == 40 else (10, 10)
            elapsed, group = milliseconds(lambda: app.commands.create_rectangular_formation(
                source.entity_id, rows, columns, 1.2, 1.4))
        else:
            elapsed, group = 0, None
        app.frame_all()
        app.viewer.controller.pitch = .65
        app.viewer.controller.update()
        app.tool = "move"
        state.update(case=count, samples=[], creation_ms=elapsed,
                     uploads_before=dict(state["uploads"]))
        print("Measuring Roman instances:", count, flush=True)
        assert len(app.scene.root_entities) == count
        return group

    def interaction_metrics():
        app, source = state["app"], state["source"]
        low, high = geometry_bounds(source)
        timings, hits = [], 0
        for fraction in (.25, .4, .5, .6, .75):
            world = (low + high) / 2
            world[2] = low[2] + fraction * (high[2] - low[2])
            point = project_point(app.viewer.camera, world, app.viewport_rect)
            assert point is not None
            elapsed, hit = milliseconds(lambda: pick_entity(
                app.scene, app.viewer.camera, point, app.viewport_rect))
            timings.append(elapsed)
            hits += hit[0] is not None
        assert hits, "No real Roman geometry picked"
        before = [entity.pos.copy() for entity in app.scene.root_entities]
        geometry = app.gizmo.geometry(app.viewport_rect)
        assert geometry is not None
        _, center, _ = geometry
        assert app.gizmo.begin(center, app.viewport_rect), "Gizmo did not capture selection centre"
        update_ms, _ = milliseconds(lambda: app.gizmo.update(center + [12, -4]))
        app.gizmo.finish()
        after = [entity.pos.copy() for entity in app.scene.root_entities]
        assert all(np.linalg.norm(a - b) > 1e-5 for a, b in zip(after, before))
        assert app.commands.undo()
        for entity, position in zip(app.scene.root_entities, before):
            np.testing.assert_allclose(entity.pos, position)
        return dict(picking_median_ms=float(np.median(timings)),
                    picking_max_ms=max(timings), picking_hits=hits,
                    gizmo_update_ms=update_ms, gizmo_undo_restored=True)

    def workflow():
        for count in (1, 40, 100):
            prepare(count)
            for _ in range(3):
                yield []  # Warm shaders/caches/UI before timing samples.
            state["sampling"] = True
            for _ in range(8):
                yield []
            state["sampling"] = False
            metrics = interaction_metrics()
            renderer = state["renderer"].material_renderer
            frame_times = [sample[0] for sample in state["samples"]]
            render_times = [sample[1] for sample in state["samples"]]
            metrics.update(instances=count, formation_ms=state["creation_ms"],
                frame_median_ms=float(np.median(frame_times)), frame_max_ms=max(frame_times),
                render_median_ms=float(np.median(render_times)),
                mesh_cache=len(renderer._meshes), texture_cache=len(renderer._textures),
                new_buffer_uploads=state["uploads"]["buffers"] - state["uploads_before"]["buffers"],
                new_texture_uploads=state["uploads"]["textures"] - state["uploads_before"]["textures"],
                samples=len(frame_times))
            if state["results"]:
                baseline = state["results"][0]
                assert metrics["mesh_cache"] == baseline["mesh_cache"]
                assert metrics["texture_cache"] == baseline["texture_cache"]
                assert metrics["new_buffer_uploads"] == metrics["new_texture_uploads"] == 0
            state["results"].append(metrics)
            print(json.dumps(metrics), flush=True)
        state["complete"] = True
        yield [pygame.event.Event(pygame.QUIT)]

    driver = workflow()

    def events():
        original_get()
        result = next(driver)
        state["frame_started"] = time.perf_counter()
        return result

    def flip():
        gl.glFinish()
        assert gl.glGetError() == gl.GL_NO_ERROR
        if state.get("sampling"):
            state["samples"].append(((time.perf_counter() - state["frame_started"]) * 1000,
                                     state["render_ms"]))
        original_flip()
        state["frame"] += 1

    from contextlib import ExitStack
    with ExitStack() as stack:
        for owner, name, replacement in ((editor, "Editor", TestEditor),
                (GLRenderer, "render", render), (pygame.event, "get", events),
                (pygame.display, "flip", flip), (gl, "glBufferData", upload_buffer),
                (gl, "glTexImage2D", upload_texture)):
            stack.enter_context(patch.object(owner, name, replacement))
        editor.run(initial_asset=None, frames=100)
    assert state.get("complete"), "Performance workflow was interrupted"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(graphics=state['graphics'], results=state["results"],
        notes="Same GL context; 3 warm-up + 8 measured frames; timings exclude swap/vsync and clock cap; "
              "frame includes UI + selection outline + GPU finish; exact triangle picking; "
              "Gizmo update uses selection-centre drag and undo verification."), indent=2), encoding="utf8")
    print("PASS: performance observations written to", output)


if __name__ == "__main__":
    destination = (Path(sys.argv[1]) if len(sys.argv) > 1
                   else ROOT / "captures/placement-v2-validation/performance.json")
    measure(destination)
