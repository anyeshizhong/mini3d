"""Keep the last usable Arrange image visible while adding real GLB assets.

Run on the desktop OpenGL environment with the native DLL already built:
    python -B tests/editor_repeated_assets_smoke.py OUTPUT

This deliberately uses the unbounded, visible editor loop and its normal CPU
asset worker. The first asset is the full 589879-triangle Legionnaire; two more
instances and the manifest WaterBottle force three consecutive native rebuilds.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _target_pixels(target):
    """Read the viewport attachment without changing the active GL read FBO."""
    from OpenGL import GL as gl
    from mini3d.gl_state import preserved_pixel_pack

    previous = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    previous_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))
    try:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        with preserved_pixel_pack(reset=True):
            pixels = gl.glReadPixels(0, 0, target.width, target.height,
                                     gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        return bytes(pixels), (target.width, target.height)
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, previous)
        gl.glReadBuffer(previous_buffer)


def _save_target(pixels, size, path):
    import pygame

    surface = pygame.image.fromstring(pixels, size, 'RGB', True)
    pygame.image.save(surface, str(path))


def _shader_diagnostics(stats):
    """Return a future native shader/program counter when the DLL exposes one."""
    return {key: value for key, value in stats.items()
            if 'shader' in key.lower() or 'program' in key.lower()}


def smoke(output):
    import pygame
    from OpenGL import GL as gl
    from mini3d.editor import Editor
    from mini3d.editor_runtime import run as run_editor
    from mini3d.editor_ui import EditorUI
    from mini3d.native_renderer import NativeSceneRenderer
    from mini3d.render_target import RenderTarget

    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, rounds=[], screenshots=[], checks=[])
    state = dict(app=None, ui=None, targets=[], round=None, completed=0,
                 pending_prepare_frame=None, stale_ui_expected=False,
                 click_pending=False, click_injected=False, click_expected=None,
                 frame=0, start=time.perf_counter())

    saved_env = {key: os.environ.get(key) for key in (
        'MINI3D_RENDER_BACKEND', 'MINI3D_ARRANGE_BACKEND',
        'MINI3D_PHOTO_BACKEND', 'MINI3D_REQUIRE_NATIVE_RENDER',
        'MINI3D_REQUIRE_NATIVE_PHOTO')}
    os.environ['MINI3D_RENDER_BACKEND'] = 'native'
    os.environ['MINI3D_REQUIRE_NATIVE_RENDER'] = '1'
    os.environ.pop('MINI3D_ARRANGE_BACKEND', None)
    os.environ.pop('MINI3D_PHOTO_BACKEND', None)
    os.environ.pop('MINI3D_REQUIRE_NATIVE_PHOTO', None)

    original_draw = EditorUI.draw
    original_prepare = NativeSceneRenderer.prepare_step
    original_events = pygame.event.get
    original_flip = pygame.display.flip
    original_target_init = RenderTarget.__init__

    def find_asset(app, filename):
        for index, record in enumerate(app.assets):
            if Path(record['path']).name.lower() == filename.lower():
                return index
        raise AssertionError('Required manifest asset is missing: ' + filename)

    def expected_triangles(round_index):
        # Initial Legionnaire + zero/one/two repeated Legionnaires; the final
        # round adds the genuine 4510-triangle WaterBottle GLB.
        legionnaires = 1 + min(round_index + 1, 2)
        return legionnaires * 589879 + (4510 if round_index == 2 else 0)

    def target_snapshot():
        if not state['targets']:
            raise AssertionError('The editor viewport RenderTarget was not captured')
        target = state['targets'][0]
        return _target_pixels(target)

    def program_compile_count(native):
        query = getattr(native.library, 'spqr_photo_program_compile_count', None)
        assert query is not None, 'Rebuild DLL: shader compile-count API is missing'
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        query.restype = ctypes.c_int
        result = ctypes.c_uint32()
        if not query(native.handle, ctypes.byref(result)):
            message = native.library.spqr_photo_last_error()
            raise AssertionError('program compile-count query failed: {}'.format(
                message.decode('utf8', 'replace') if message else 'unknown native error'))
        return int(result.value)

    def queue_round(app, index):
        legionnaire = find_asset(app, 'roman_legionnaire.glb')
        bottle = find_asset(app, 'WaterBottle.glb')
        asset_index = legionnaire if index < 2 else bottle
        pixels, size = target_snapshot()
        _save_target(pixels, size, output / ('before-{}.png'.format(index + 1)))
        report['screenshots'].append('before-{}.png'.format(index + 1))
        native = app.api._renderer.native_renderer
        state['round'] = dict(index=index, asset=Path(app.assets[asset_index]['path']).name,
            asset_index=asset_index, request_time=time.perf_counter(),
            committed_time=None, prepare_start=None, complete_time=None,
            base_builds=native.bundle_builds, base_frames=native.frames,
            baseline=pixels, baseline_size=size, prep_frames=0, steps=[],
            during_saved=False, click_tested=False)
        if index < 2:
            position = app.scene.root_entities[0].pos.copy()
        else:
            position = app.viewer.controller.target.copy()
        # Explicit placement avoids add_asset's default focus/dolly. The
        # viewport baseline therefore uses the same camera for every rebuild.
        app.asset_loading.request('add_asset', asset_index, position=position)

    def draw(ui, *args):
        result = original_draw(ui, *args)
        app = ui.app
        state['app'], state['ui'] = app, ui
        current = state['round']

        if state['stale_ui_expected']:
            assert ui.resource_message, 'Stale viewport had no resource-preparation status'
            assert not ui.startup_message, 'Resource rebuild replaced the stable startup message'
            assert ui.viewport_stale is True, 'UI did not mark the retained viewport stale'
            assert not ui.viewport_hovered, 'Stale viewport still accepts hover/input'
            assert ui.mouse_captured and ui.keyboard_captured, \
                'Stale viewport did not capture mouse and keyboard input'
            state['stale_ui_expected'] = False
            report['checks'].append('stale viewport shows status-bar progress and captures input')

        if state['click_injected'] and state['click_expected'] is None:
            # Asset loading may have committed earlier in this same loop, so
            # snapshot selection after poll/adoption but before event dispatch.
            state['click_expected'] = tuple(app.scene.selected_ids)

        native = getattr(app.api._renderer, 'native_renderer', None)
        if current is None and state['completed'] == 0 and native is not None:
            stats = app.api._renderer.render_stats
            if native.frames >= 1 and stats.get('backend') == 'native-arrange':
                roots = len(app.scene.root_entities)
                triangles = sum(len(entity.model.indices)
                                for entity in app.scene.get_flat_render_list())
                assert roots == 1, ('initial scene must contain one real asset root', roots)
                assert triangles == 589879, ('initial model is not the manifest Legionnaire', triangles)
                assert stats.get('color_triangles') == 589879, stats
                assert native.bundle_builds >= 1, native.bundle_builds
                initial_compile_count = program_compile_count(native)
                assert initial_compile_count == 3, initial_compile_count
                report['initial'] = dict(roots=roots, triangles=triangles,
                    bundle_builds=native.bundle_builds, program_compile_count=initial_compile_count,
                    stats=dict(stats))
                report['checks'].append('full 589879-triangle Legionnaire rendered natively')
                queue_round(app, 0)
                current = state['round']

        if current is not None:
            expected_roots = current['index'] + 2
            if len(app.scene.root_entities) == expected_roots and current['committed_time'] is None:
                current['committed_time'] = time.perf_counter()
            stats = app.api._renderer.render_stats
            if (current['committed_time'] is not None and
                    current['complete_time'] is None and
                    native.bundle_builds == current['base_builds'] + 1 and
                    native.frames > current['base_frames'] and
                    stats.get('backend') == 'native-arrange'):
                expected = expected_triangles(current['index'])
                triangles = sum(len(entity.model.indices)
                                for entity in app.scene.get_flat_render_list())
                assert expected_roots == len(app.scene.root_entities), (
                    current['index'], len(app.scene.root_entities), expected_roots)
                assert triangles == expected, (current['index'], triangles, expected)
                assert stats.get('color_triangles') == expected, stats
                compile_count = program_compile_count(native)
                assert compile_count == 0, ('A subsequent bundle recompiled native shader programs',
                                             current['index'], compile_count)
                current['complete_time'] = time.perf_counter()
                after_pixels, after_size = target_snapshot()
                _save_target(after_pixels, after_size,
                             output / ('after-{}.png'.format(current['index'] + 1)))
                report['screenshots'].append('after-{}.png'.format(current['index'] + 1))
                current['result'] = dict(asset=current['asset'], roots=expected_roots,
                    triangles=triangles, bundle_builds=native.bundle_builds,
                    frames=native.frames, program_compile_count=compile_count,
                    stats=dict(stats),
                    shader_diagnostics=_shader_diagnostics(stats),
                    total_wait_seconds=current['complete_time'] - current['request_time'],
                    cpu_load_seconds=None if current['committed_time'] is None else
                        current['committed_time'] - current['request_time'],
                    native_prepare_seconds=None if current['prepare_start'] is None else
                        current['complete_time'] - current['prepare_start'],
                    longest_prepare_step=max((row['seconds'] for row in current['steps']), default=0.),
                    prepare_steps=len(current['steps']), preserved_frames=current['prep_frames'])
                assert current['prep_frames'] > 0, 'Native rebuild did not yield interactive preparation frames'
                report['rounds'].append(current['result'])
                state['completed'] += 1
                state['round'] = None
                if state['completed'] < 3:
                    queue_round(app, state['completed'])
        return result

    def prepare_step(native, *args, **kwargs):
        started = time.perf_counter()
        ready = original_prepare(native, *args, **kwargs)
        elapsed = time.perf_counter() - started
        current = state['round']
        if current is not None and current['committed_time'] is not None:
            current['steps'].append(dict(seconds=elapsed, ready=ready,
                message=native.preparation_message))
            if not ready:
                if current['prepare_start'] is None:
                    current['prepare_start'] = started
                current['prep_frames'] += 1
                state['pending_prepare_frame'] = current['index']
                state['stale_ui_expected'] = True
                if not current['click_tested']:
                    current['click_tested'] = True
                    state['click_pending'] = True
        return ready

    def events():
        rows = original_events()
        if time.perf_counter() - state['start'] > 240:
            raise AssertionError('Repeated asset smoke exceeded four minutes: ' +
                                 json.dumps({key: value for key, value in state.items()
                                             if key not in ('app', 'ui', 'targets')}, default=str))
        if state['click_pending'] and state['app'] is not None:
            x, y, width, height = state['app'].viewport_rect
            point = (x + width // 2, y + height // 2)
            rows.extend((pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point, mod=0),
                         pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=point)))
            state['click_pending'] = False
            state['click_injected'] = True
        if state['completed'] == 3:
            rows.append(pygame.event.Event(pygame.QUIT))
        return rows

    def flip():
        current = state['round']
        if current is not None and state['pending_prepare_frame'] == current['index']:
            pixels, size = target_snapshot()
            assert size == current['baseline_size'], (size, current['baseline_size'])
            # During a native rebuild the old viewport attachment must remain
            # byte-for-byte visible. The old implementation cleared it to the
            # editor's flat startup color on every preparation frame.
            assert pixels == current['baseline'], (
                'Viewport texture changed while preparing {} (usually to clear-color black)'
                .format(current['asset']))
            if not current['during_saved']:
                _save_target(pixels, size, output / ('during-{}.png'.format(current['index'] + 1)))
                report['screenshots'].append('during-{}.png'.format(current['index'] + 1))
                current['during_saved'] = True
            state['pending_prepare_frame'] = None
            report['checks'].append('old viewport retained during native rebuild {}'.format(current['index'] + 1))

        if state['click_expected'] is not None:
            app = state['app']
            assert tuple(app.scene.selected_ids) == state['click_expected'], \
                'A click on the stale viewport changed selection'
            assert not app.commands.active_transaction, 'Stale click began an edit transaction'
            state['click_expected'] = None
            state['click_injected'] = False
            report['checks'].append('stale viewport click did not pick or start a gizmo')

        if gl.glGetError() != gl.GL_NO_ERROR:
            raise AssertionError('OpenGL error during repeated asset rebuild')
        original_flip()
        state['frame'] += 1

    def target_init(target, *args, **kwargs):
        original_target_init(target, *args, **kwargs)
        state['targets'].append(target)

    try:
        with patch.object(EditorUI, 'draw', draw), \
             patch.object(NativeSceneRenderer, 'prepare_step', prepare_step), \
             patch.object(pygame.event, 'get', events), \
             patch.object(pygame.display, 'flip', flip), \
             patch.object(RenderTarget, '__init__', target_init):
            run_editor(Editor, initial_asset='auto', frames=None, hidden=False, ipc=False)
        assert state['completed'] == 3, state['completed']
        assert [row['triangles'] for row in report['rounds']] == [
            2 * 589879, 3 * 589879, 3 * 589879 + 4510]
        assert all(row['bundle_builds'] == report['initial']['bundle_builds'] + index + 1
                   for index, row in enumerate(report['rounds']))
        report['passed'] = True
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        report_path = output / 'report.json'
        report_path.write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    smoke(parser.parse_args().output)
