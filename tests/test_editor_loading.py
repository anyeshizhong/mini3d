"""Editor-thread asset loading and placement handoff contracts."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from mini3d.asset_loader import AssetLoader, prepare_asset
from mini3d.assets import AssetCache
from mini3d.commands import PlacementCommands
from mini3d.editor import Editor
from mini3d.editor_loading import EditorAssetLoading
from mini3d.placement import SurfaceHit, geometry_bounds
from mini3d.scene import Scene
import mini3d.editor_loading as editor_loading_module


def _write_tiny_stl(directory):
    path = Path(directory) / 'tiny.stl'
    path.write_text(
        'solid tiny\n'
        ' facet normal 0 0 1\n'
        '  outer loop\n'
        '   vertex 0 0 0\n'
        '   vertex 1 0 0\n'
        '   vertex 0 1 0\n'
        '  endloop\n'
        ' endfacet\n'
        'endsolid tiny\n', encoding='ascii')
    return path


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.005)
    raise AssertionError('Timed out waiting for editor asset load')


class EditorAssetLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = _write_tiny_stl(self.temporary.name).resolve()
        self.app = Editor(800, 600)
        self.index = len(self.app.assets)
        self.app.assets.append({'name': 'Tiny', 'path': str(self.path)})
        self.center = (400, 300)
        self.loading = None
        self.loader = None
        self.release = None
        self.worker_done = None

    def tearDown(self):
        if self.release is not None:
            self.release.set()
        if self.worker_done is not None:
            self.worker_done.wait(2.0)
        if self.loading is not None:
            self.loading.close()
        self.app.model_dialog.close()
        self.temporary.cleanup()

    def attach_loading(self, prepare_fn=None):
        self.loader = AssetLoader(cache_factory=AssetCache, prepare_fn=prepare_fn)
        with mock.patch.object(editor_loading_module, 'AssetLoader', return_value=self.loader):
            self.loading = EditorAssetLoading(self.app)
        self.app.asset_loading = self.loading
        return self.loading

    def gated_prepare(self, started, release, done):
        def prepare(path, cache):
            started.set()
            try:
                if not release.wait(3.0):
                    raise RuntimeError('test worker was not released')
                return prepare_asset(path, cache)
            finally:
                done.set()
        return prepare

    def drain_success(self):
        result = None

        def poll_once():
            nonlocal result
            result = self.loading.poll()
            return self.loading.pending is None

        _wait_until(poll_once)
        return result

    def test_queue_is_worker_only_then_poll_commits_one_undoable_add_on_main_thread(self):
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.release, self.worker_done = release, done
        worker_threads = []

        def prepare(path, cache):
            worker_threads.append(threading.get_ident())
            return self.gated_prepare(started, release, done)(path, cache)

        self.attach_loading(prepare)
        main_thread = threading.get_ident()
        adopted_on = []
        adopted_assets = []
        original_adopt = self.app.cache.adopt

        def record_adopt(asset):
            adopted_on.append(threading.get_ident())
            adopted_assets.append(asset)
            return original_adopt(asset)

        self.app.cache.adopt = record_adopt
        request_id = self.loading.request('add_asset', self.index)
        self.assertIsNone(request_id)
        self.assertTrue(started.wait(1.0))
        self.assertEqual(self.loading.pending[1], 'add_asset')
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertEqual(self.app.commands.redo_count, 0)
        self.assertNotIn(str(self.path), self.app.cache._assets)
        self.assertIsNone(self.loading.poll())
        self.assertEqual(self.app.scene.root_entities, [])

        release.set()
        added = self.drain_success()
        self.assertIsNotNone(added)
        self.assertEqual(len(self.app.scene.root_entities), 1)
        self.assertIs(self.app.scene.root_entities[0], added)
        self.assertEqual(self.app.commands.undo_count, 1)
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], main_thread)
        self.assertEqual(adopted_on, [main_thread])
        self.assertEqual(len(adopted_assets), 1)
        self.assertIs(self.app.cache._assets[str(self.path)], adopted_assets[0])

        self.assertTrue(self.app.undo())
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertEqual(self.app.commands.redo_count, 1)
        self.assertTrue(self.app.redo())
        self.assertEqual(self.app.scene.root_entities, [added])
        self.assertEqual(self.app.commands.undo_count, 1)
        self.assertEqual(self.app.commands.redo_count, 0)

    def test_import_error_does_not_add_library_entry_scene_entity_or_cache_asset(self):
        started, done = threading.Event(), threading.Event()
        before_assets = list(self.app.assets)

        def fail_prepare(path, cache):
            started.set()
            try:
                raise ValueError('bad test asset')
            finally:
                done.set()

        self.attach_loading(fail_prepare)
        self.loading.request('import_asset', str(self.path))
        self.assertTrue(started.wait(1.0))

        def poll_failure():
            self.loading.poll()
            return self.loading.pending is None

        _wait_until(poll_failure)
        self.assertEqual(self.app.assets, before_assets)
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertNotIn(str(self.path), self.app.cache._assets)
        self.assertIn('Import failed: bad test asset', self.app.status)

    def test_cancel_suppresses_completed_request_without_submitting_scene_edit(self):
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.release, self.worker_done = release, done
        self.attach_loading(self.gated_prepare(started, release, done))
        self.loading.request('add_asset', self.index)
        self.assertTrue(started.wait(1.0))
        self.loading.cancel()
        release.set()
        self.assertTrue(done.wait(2.0))
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            self.assertIsNone(self.loading.poll())
            time.sleep(.005)
        self.assertIsNone(self.loading.pending)
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertNotIn(str(self.path), self.app.cache._assets)

    def test_replaced_scene_discards_old_request(self):
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.release, self.worker_done = release, done
        self.attach_loading(self.gated_prepare(started, release, done))
        original_scene = self.app.scene
        self.loading.request('add_asset', self.index)
        self.assertTrue(started.wait(1.0))

        replacement = Scene()
        self.app.scene = replacement
        self.app.commands = PlacementCommands(replacement, self.app.cache)
        self.app.viewer.scene = replacement
        release.set()
        self.assertTrue(done.wait(2.0))

        def poll_discarded():
            self.loading.poll()
            return self.loading.pending is None

        _wait_until(poll_discarded)
        self.assertEqual(original_scene.root_entities, [])
        self.assertEqual(replacement.root_entities, [])
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertNotIn(str(self.path), self.app.cache._assets)

    def test_public_scene_load_cancels_pending_asset_before_replacing_contents(self):
        scene_path = Path(self.temporary.name) / 'empty-scene.json'
        self.app.save_scene(scene_path)
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.release, self.worker_done = release, done
        self.attach_loading(self.gated_prepare(started, release, done))
        self.loading.request('add_asset', self.index)
        self.assertTrue(started.wait(1.0))

        self.app.load_scene(scene_path)
        self.assertIsNone(self.loading.pending)
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertEqual(self.app.commands.undo_count, 0)
        release.set()
        self.assertTrue(done.wait(2.0))
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            self.assertIsNone(self.loading.poll())
            time.sleep(.005)
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertNotIn(str(self.path), self.app.cache._assets)

    def test_undo_cancels_pending_asset_before_applying_history(self):
        existing = self.app.add_asset(self.index, position=(0, 0, 0))
        self.assertEqual(self.app.commands.undo_count, 1)
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.release, self.worker_done = release, done
        self.attach_loading(self.gated_prepare(started, release, done))
        self.loading.request('add_asset', self.index)
        self.assertTrue(started.wait(1.0))

        self.assertTrue(self.app.undo())
        self.assertIsNone(self.loading.pending)
        self.assertNotIn(existing, self.app.scene.root_entities)
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertEqual(self.app.commands.redo_count, 1)
        release.set()
        self.assertTrue(done.wait(2.0))
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            self.assertIsNone(self.loading.poll())
            time.sleep(.005)
        self.assertEqual(self.app.scene.root_entities, [])
        self.assertEqual(self.app.commands.redo_count, 1)

    def test_drop_uses_surface_hit_captured_when_request_was_queued(self):
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.release, self.worker_done = release, done
        self.attach_loading(self.gated_prepare(started, release, done))
        request_hit = SurfaceHit([12.0, -7.0, 3.5], [0.0, 0.0, 1.0])
        later_hit = SurfaceHit([-100.0, 80.0, -5.0], [0.0, 0.0, 1.0])
        with mock.patch.object(editor_loading_module, 'raycast_surface',
                               side_effect=[request_hit, later_hit]) as raycast:
            self.loading.request('drop_asset', self.index, self.center)
            self.assertTrue(started.wait(1.0))
            self.app.viewer.camera.position = [75.0, 12.0, 44.0]
            self.app.viewer.camera.look_at([0.0, 0.0, 0.0])
            release.set()
            dropped = self.drain_success()

        self.assertEqual(raycast.call_count, 1)
        self.assertIs(self.app.scene.root_entities[0], dropped)
        bounds = geometry_bounds(dropped)
        bottom_center = (bounds[0] + bounds[1]) * .5
        bottom_center[2] = bounds[0][2]
        np.testing.assert_allclose(bottom_center, request_hit.position, atol=1e-7)
        self.assertEqual(self.app.commands.undo_count, 1)


if __name__ == '__main__':
    unittest.main()
