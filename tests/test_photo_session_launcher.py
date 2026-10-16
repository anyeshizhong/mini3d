"""CPU-only checks for the single manual photo-session launcher."""
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import open_photo_session as launcher


class PhotoSessionLauncherTests(unittest.TestCase):
    def test_both_session_defaults_and_names(self):
        self.assertEqual(
            launcher.resolve_scene('photographer').relative_to(launcher.ROOT).as_posix(),
            'captures/photographer-session/02_sanctuary.json')
        self.assertEqual(
            launcher.resolve_scene('still-life').relative_to(launcher.ROOT).as_posix(),
            'captures/second-session/still-life/01_geometry.json')
        self.assertEqual(
            launcher.resolve_scene('still-life', '04_silhouette.json').name,
            '04_silhouette.json')

    def test_rejects_directory_traversal(self):
        for name in ('', '.', '..', '../other', '..\\other', 'folder/name', '/tmp/elsewhere'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    launcher.resolve_scene('photographer', name)

    def test_missing_capture_exits_before_opening_editor(self):
        with patch.object(Path, 'is_file', return_value=False), \
                patch.object(launcher.editor, 'run') as run:
            with self.assertRaises(SystemExit) as exit_case:
                launcher.main(['--session', 'still-life', 'does-not-exist'])
            self.assertEqual(exit_case.exception.code, 2)
            run.assert_not_called()

    def test_camera_view_patch_is_active_for_existing_capture(self):
        original = launcher.editor.Editor
        def capture(**kwargs):
            self.assertIsNot(launcher.editor.Editor, original)
            self.assertEqual(kwargs['frames'], 1)
            self.assertTrue(kwargs['hidden'])
        with patch.object(Path, 'is_file', return_value=True), \
                patch.object(launcher.editor, 'run', side_effect=capture) as run:
            launcher.main(['--session', 'photographer', '--frames', '1', '--hidden'])
            run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
