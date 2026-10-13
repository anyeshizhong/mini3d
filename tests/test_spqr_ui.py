"""Exercise the real ImGui street dialog without requiring a GL renderer."""
import unittest
from unittest.mock import patch
import imgui
from mini3d.editor import Editor
from mini3d.editor_ui import EditorUI


class StreetDialogTests(unittest.TestCase):
    def test_dialog_creates_street_and_rejects_invalid_input(self):
        context = imgui.create_context()
        app = Editor()
        try:
            io = imgui.get_io()
            io.display_size = (1280, 800)
            io.delta_time = 1 / 60
            io.fonts.get_tex_data_as_rgba32()
            ui = EditorUI(app)
            real_button = imgui.button
            def click_create(label, *args, **kwargs):
                actual = real_button(label, *args, **kwargs)
                return True if label == 'Create street' else actual
            ui._open_street = True
            ui.street_segments = 1
            with patch.object(imgui, 'button', click_create):
                for _ in range(2):
                    imgui.new_frame()
                    ui.draw(1280, 800, 0)
                    imgui.render()
            self.assertTrue(ui.street_error)
            self.assertEqual(len(app.scene.root_entities), 0)
            ui.street_segments = 6
            with patch.object(imgui, 'button', click_create):
                imgui.new_frame()
                ui.draw(1280, 800, 0)
                imgui.render()
            self.assertEqual(len(app.scene.root_entities), 49)
            self.assertEqual(app.commands.undo_count, 1)
            self.assertEqual(app.workspace, 'Arrange')
            self.assertFalse(app.camera_view)
            app.undo()
            self.assertEqual(len(app.scene.root_entities), 0)
        finally:
            app.model_dialog.close()
            imgui.destroy_context(context)
