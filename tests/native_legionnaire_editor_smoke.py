"""Reproduce real Legionnaire import/selection/drag in the complete native editor.

Uses the installed 589879-triangle GLB and injected SDL gestures, not a proxy
model. Writes timings, screenshots and native resource counters for inspection.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import time
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(output):
    import pygame
    from OpenGL import GL as gl
    from mini3d.editor import Editor
    from mini3d.editor_runtime import run as run_editor
    from mini3d.editor_ui import EditorUI
    from mini3d import scene_renderer, native_photo_bundle
    from mini3d.native_renderer import preserved_native_state
    from mini3d.scene import Scene

    output.mkdir(parents=True, exist_ok=True)
    os.environ['MINI3D_RENDER_BACKEND'] = 'native'
    os.environ.pop('MINI3D_PHOTO_BACKEND', None)
    os.environ.pop('MINI3D_ARRANGE_BACKEND', None)
    report = dict(passed=False, frames=[], renders=[])
    state = dict(frame=-1, app=None, drag_start=None, last_flip=None, initial_builds=None)
    real_draw, real_events, real_flip = EditorUI.draw, pygame.event.get, pygame.display.flip
    real_render = scene_renderer.render_scene

    def render(*args, **kwargs):
        start = time.perf_counter()
        real_render(*args, **kwargs)
        gl.glFinish()
        renderer = args[2]
        report['renders'].append(dict(frame=state['frame'], seconds=time.perf_counter()-start,
                                     stats=dict(renderer.render_stats)))
        assert renderer.render_stats['backend'].startswith('native-'), renderer.render_stats
        assert gl.glGetError() == gl.GL_NO_ERROR

    def draw(ui, *args):
        state['frame'] += 1
        frame, app = state['frame'], ui.app
        state['app'] = app
        if frame == 0:
            assert Path(app.selection.asset_path).name == 'roman_legionnaire.glb'
            report['triangles'] = sum(len(e.model.indices) for e in app.scene.get_flat_render_list())
            assert report['triangles'] == 589879
        elif frame == 1:
            app.select(None)
        elif frame == 2:
            app.select(app.scene.root_entities[0])
        elif frame == 17:
            report['after_drag'] = app.selection.pos.tolist()
            assert not app.commands.active_transaction
            app.undo()
            report['after_undo'] = app.selection.pos.tolist()
            assert report['after_undo'] != report['after_drag']
        elif frame == 18:
            app.redo()
            assert app.selection.pos.tolist() == report['after_drag']
        elif frame == 19:
            app.api.save_scene(output / 'legionnaire.scene.json')
            app.api.screenshot(output / 'arrange.png')
        elif frame == 20:
            app.api.load_scene(output / 'legionnaire.scene.json')
            app.select(app.scene.root_entities[0])
        elif frame == 22:
            app.api.set_environment(enabled=True)
            app.api.create_shot_camera()
            app.api.set_view('Camera')
        elif frame == 24:
            app.api.set_workspace('Arrange')
            app.api.set_view('Editor')
        elif frame == 26:
            app.api.screenshot(output / 'after-reload-and-shot.png')
            native = app.api._renderer.native_renderer
            report['final_stats'] = dict(app.api._renderer.render_stats)
            handles = [record[1] for record in app.api._renderer.material_renderer._textures.values()]
            environment = app.api._renderer.material_renderer.environment
            assert environment is not None
            handles.extend(environment.handles)
            live_bundle = Path(native.directory.name)
            with preserved_native_state():
                assert not native.library.spqr_photo_create(str(live_bundle), 64, 64, 1), \
                    'offline API accepted process-local texture references'
                bad = output / 'invalid-borrowed-texture'
                bad.mkdir(exist_ok=True)
                shutil.copytree(live_bundle / 'shaders', bad / 'shaders', dirs_exist_ok=True)
                payload = bytearray((live_bundle / 'scene.bin').read_bytes())
                assert struct.unpack_from('<I', payload, 12)[0] >= 2
                struct.pack_into('<I', payload, 28, 0x7fffffff)  # Second handle is invalid.
                (bad / 'scene.bin').write_bytes(payload)
                assert not native.library.spqr_photo_create_shared(str(bad), 64, 64, 1)
                assert all(gl.glIsTexture(handle) for handle in handles), \
                    'failed native constructor deleted borrowed caller textures'
                # The original offline v1 entry remains usable for exported bundles.
                offline = output / 'offline-v1'
                # Only this explicit offline export is permitted to read pixels.
                with patch.object(helpers, 'capture_texture', original_capture):
                    native_photo_bundle.export_live_bundle(Scene(), app.viewer.camera,
                        app.api._renderer, offline, native.root)
                legacy = native.library.spqr_photo_create(str(offline), 64, 64, 1)
                assert legacy, native.library.spqr_photo_last_error()
                assert native.library.spqr_photo_destroy(legacy)
            report['resource_lifecycle'] = dict(v2_rejected_by_offline_api=True,
                constructor_failure_preserves_borrowed_textures=True, offline_v1_create_destroy=True,
                borrowed_environment_cube_maps=True)
            native.close()
            native.close()
            assert all(gl.glIsTexture(handle) for handle in handles), 'native deleted borrowed textures'
            # A renderer recreated after close must still render the same resources.
            app.show_grid = not app.show_grid
        result = real_draw(ui, *args)
        if 4 <= frame <= 16:
            ui.viewport_hovered, ui.mouse_captured, ui.asset_dragging = True, False, False
        return result

    def events():
        result = real_events()
        frame = state['frame'] + 1
        app = state['app']
        if app is None:
            return result
        if frame == 4:
            _origin, center, _length = app.gizmo.geometry(app.viewport_rect)
            start = tuple(map(int, center))
            state['drag_start'] = start
            result.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start, mod=0))
        elif 5 <= frame <= 15:
            start = state['drag_start']
            point = (start[0] + (frame-4)*4, start[1] - (frame-4)*2)
            result.append(pygame.event.Event(pygame.MOUSEMOTION, pos=point, rel=(4, -2), buttons=(1, 0, 0)))
        elif frame == 16:
            start = state['drag_start']
            result.append(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(start[0]+44, start[1]-22)))
        return result

    def flip():
        now = time.perf_counter()
        app = state['app']
        stats = app.api._renderer.render_stats
        frame = state['frame']
        native = app.api._renderer.native_renderer
        if state['initial_builds'] is None:
            state['initial_builds'] = native.bundle_builds
        if frame < 20:
            assert native.bundle_builds == state['initial_builds'], 'imported resources were rebuilt on selection/drag'
        report['frames'].append(dict(frame=frame,
            seconds=None if state['last_flip'] is None else now-state['last_flip'],
            backend=stats['backend'], bundle_builds=native.bundle_builds,
            transform_updates=native.transform_updates,
            viewport_redrawn=stats.get('viewport_redrawn')))
        state['last_flip'] = now
        real_flip()

    helpers = native_photo_bundle._export_helpers()
    original_capture = helpers.capture_texture
    try:
        with patch.object(EditorUI, 'draw', draw), patch.object(pygame.event, 'get', events), \
                patch.object(pygame.display, 'flip', flip), \
                patch.object(scene_renderer, 'render_scene', render), \
                patch.object(helpers, 'capture_texture', side_effect=AssertionError('live path read back a texture')):
            run_editor(Editor, initial_asset='auto', frames=28, hidden=True, ipc=False)
        drag_times = [row['seconds'] for row in report['frames'] if 5 <= row['frame'] <= 16]
        assert len(drag_times) == 12
        assert max(drag_times) < 1., drag_times
        assert report['frames'][-1]['transform_updates'] >= 11
        report['drag_frame_ms'] = dict(p50=float(np.percentile(drag_times, 50)*1000),
                                      p95=float(np.percentile(drag_times, 95)*1000),
                                      max=max(drag_times)*1000)
        report['passed'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    run(parser.parse_args().output)
