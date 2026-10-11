"""Headless tests for the task-workspace state transitions.

These do not stand in for manual OpenGL/ImGui usability acceptance.
"""
import unittest
from types import SimpleNamespace

from mini3d.editor_ui import EditorUI


class EditorWorkspaceTests(unittest.TestCase):
    def setUp(self):
        # No ImGui context or GPU is needed to test presentation state.
        self.ui = EditorUI.__new__(EditorUI)
        self.ui.workspace = "Arrange"
        self.ui.assets_visible = True
        self.ui.app = SimpleNamespace(camera_view=False)
        self.calls = []
        self.ui._call = lambda name, *args: self.calls.append((name, *args))

    def test_switching_to_lighting_preserves_editor_and_hides_library(self):
        self.ui._choose_workspace("Lighting")
        self.assertEqual("Lighting", self.ui.workspace)
        self.assertFalse(self.ui.assets_visible)
        self.assertEqual([("finish_edit",)], self.calls)

    def test_switching_to_shot_does_not_implicitly_create_camera(self):
        self.ui._choose_workspace("Shot")
        self.assertEqual("Shot", self.ui.workspace)
        self.assertFalse(self.ui.assets_visible)
        self.assertEqual([("finish_edit",)], self.calls)

    def test_switching_to_arrange_exits_camera_preview(self):
        self.ui.workspace = "Shot"
        self.ui.app.camera_view = True
        self.ui.assets_visible = False
        self.ui._choose_workspace("Arrange")
        self.assertEqual("Arrange", self.ui.workspace)
        self.assertTrue(self.ui.assets_visible)
        self.assertEqual([("finish_edit",), ("set_camera_view", False)], self.calls)

    def test_selecting_same_workspace_does_not_reset_camera_or_state(self):
        self.ui._choose_workspace("Arrange")
        self.assertEqual([], self.calls)
        self.assertTrue(self.ui.assets_visible)

    def test_switching_from_shot_to_lighting_exits_camera_preview(self):
        self.ui.workspace = "Shot"
        self.ui.app.camera_view = True
        self.ui._choose_workspace("Lighting")
        self.assertEqual([("finish_edit",), ("set_camera_view", False)], self.calls)


if __name__ == "__main__":
    unittest.main()
