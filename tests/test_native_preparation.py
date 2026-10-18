"""Interactive staged preparation lifecycle without a live GL context."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mini3d.native_renderer import NativeSceneRenderer, NativeRenderError


class NativePreparationTests(unittest.TestCase):
    def setUp(self):
        self.native = NativeSceneRenderer(Mock())
        self.native.library = Mock()
        self.native._load = Mock()
        self.native._keys = Mock(return_value=('resource', 'parameters'))
        self.context = patch('mini3d.native_renderer.preserved_native_state', nullcontext)
        self.policy = patch('mini3d.native_renderer.backend_policy', return_value=('auto', False))
        self.context.start()
        self.policy.start()
        self.addCleanup(self.context.stop)
        self.addCleanup(self.policy.stop)
        self.scene = Mock(render_mode='Lit')

    def step(self):
        return self.native.prepare_step(self.scene, Mock(), (800, 600))

    def test_one_job_per_step_then_ready(self):
        jobs = []
        def prepare(*args):
            jobs.append('shader')
            yield 'shader'
            jobs.append('mesh')
            yield 'mesh'
            self.native.resource_key = 'resource'
        self.native._prepare_resources = prepare
        self.assertFalse(self.step())
        self.assertEqual(jobs, ['shader'])
        self.assertFalse(self.step())
        self.assertEqual(jobs, ['shader', 'mesh'])
        self.assertTrue(self.step())
        self.assertTrue(self.step())
        self.assertIsNone(self.native._preparation)

    def test_warm_jobs_share_the_ui_frame_budget(self):
        jobs = []
        def prepare(*args):
            for index in range(3):
                jobs.append(index)
                yield str(index)
            self.native.resource_key = 'resource'
        self.native._prepare_resources = prepare
        self.assertTrue(self.native.prepare_step(self.scene, Mock(), (800, 600), budget_seconds=.01))
        self.assertEqual(jobs, [0, 1, 2])

    def test_resource_change_closes_partial_job_and_restarts(self):
        events = []
        def prepare(*args):
            resource = args[-1]
            try:
                events.append(('begin', resource))
                yield 'working'
            finally:
                events.append(('close', resource))
        self.native._prepare_resources = prepare
        self.assertFalse(self.step())
        self.native._keys.return_value = ('replacement', 'parameters')
        self.assertFalse(self.step())
        self.assertEqual(events, [('begin', 'resource'), ('close', 'resource'), ('begin', 'replacement')])
        self.native.close()
        self.assertEqual(events[-1], ('close', 'replacement'))
        self.assertIsNone(self.native._preparation)

    def test_failure_is_cached_without_retrying_each_ui_frame(self):
        prepared = Mock(side_effect=ValueError('unsupported material'))
        self.native._prepare_resources = prepared
        self.assertTrue(self.step())
        self.assertTrue(self.step())
        self.assertEqual(prepared.call_count, 1)
        self.assertEqual(self.native.last_reason, 'unsupported material')

    def test_required_native_reports_failure(self):
        self.native._prepare_resources = Mock(side_effect=ValueError('native failed'))
        with patch('mini3d.native_renderer.backend_policy', return_value=('native', True)):
            with self.assertRaisesRegex(NativeRenderError, 'native failed'):
                self.step()

    def test_missing_optional_symbol_keeps_legacy_sync_path(self):
        for exports in ({}, {'spqr_photo_begin_shared': Mock()}, {'spqr_photo_prepare_step': Mock()}):
            with self.subTest(exports=tuple(exports)):
                self.native.library = SimpleNamespace(**exports)
                self.native._prepare_resources = Mock()
                self.assertTrue(self.step())
                self.native._prepare_resources.assert_not_called()


if __name__ == '__main__':
    unittest.main()
