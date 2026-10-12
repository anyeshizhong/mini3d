"""Headless tests for the task-workspace state transitions.

These do not stand in for manual OpenGL/ImGui usability acceptance.
"""
import unittest
from mini3d.editor import Editor

from mini3d.editor_ui import EditorUI


class EditorWorkspaceTests(unittest.TestCase):
    def setUp(self):
        # No ImGui context or GPU is needed to test presentation state.
        self.ui = EditorUI.__new__(EditorUI)
        self.ui.app = Editor()
        self.addCleanup(self.ui.app.model_dialog.close)
        self.calls = []
        def call(name, *args):
            self.calls.append((name, *args))
            return getattr(self.ui.app, name)(*args)
        self.ui._call = call

    def test_switching_to_lighting_preserves_editor_and_hides_library(self):
        self.ui._choose_workspace("Lighting")
        self.assertEqual("Lighting", self.ui.workspace)
        self.assertFalse(self.ui.assets_visible)
        self.assertEqual([('set_workspace', 'Lighting')], self.calls)

    def test_switching_to_shot_does_not_implicitly_create_camera(self):
        self.ui._choose_workspace("Shot")
        self.assertEqual("Shot", self.ui.workspace)
        self.assertFalse(self.ui.assets_visible)
        self.assertEqual([('set_workspace', 'Shot')], self.calls)

    def test_switching_to_arrange_exits_camera_preview(self):
        self.ui.workspace = "Shot"
        self.ui.app.camera_view = True
        self.ui.assets_visible = False
        self.ui._choose_workspace("Arrange")
        self.assertEqual("Arrange", self.ui.workspace)
        self.assertTrue(self.ui.assets_visible)
        self.assertEqual([('set_workspace', 'Arrange')], self.calls)

    def test_selecting_same_workspace_does_not_reset_camera_or_state(self):
        self.ui._choose_workspace("Arrange")
        self.assertEqual([], self.calls)
        self.assertTrue(self.ui.assets_visible)

    def test_switching_from_shot_to_lighting_exits_camera_preview(self):
        self.ui.workspace = "Shot"
        self.ui.app.camera_view = True
        self.ui._choose_workspace("Lighting")
        self.assertEqual([('set_workspace', 'Lighting')], self.calls)


if __name__ == "__main__":
    unittest.main()
