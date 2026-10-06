"""File-picker lifecycle and asynchronous import behavior."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mini3d.editor import Editor, PROJECT
from mini3d.model_dialog import ModelFileDialog, choose_model, main


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.dialog = ModelFileDialog(PROJECT / "model")

    def tearDown(self):
        self.dialog.close()

    def test_long_running_picker_does_not_wait_or_open_twice(self):
        worker = Mock()
        worker.poll.return_value = None
        with patch("mini3d.model_dialog.subprocess.Popen", return_value=worker) as launch:
            self.assertTrue(self.dialog.open())
            self.assertFalse(self.dialog.open())
            for _ in range(100):
                self.assertIsNone(self.dialog.poll())
            worker.wait.assert_not_called()
            launch.assert_called_once()
            temporary = self.dialog._result.parent
            self.dialog.close()
            worker.terminate.assert_called_once()
            worker.wait.assert_called_once()
            self.assertFalse(temporary.exists())
            self.assertFalse(self.dialog.pending)

    def test_result_is_delivered_once_and_remembers_directory(self):
        worker = Mock()
        worker.poll.return_value = 0
        filename = str(PROJECT / "model/01_box/Box.glb")
        with patch("mini3d.model_dialog.subprocess.Popen", return_value=worker):
            self.dialog.open()
            self.dialog._result.write_text(json.dumps({"path": filename}), encoding="utf8")
            self.assertEqual(self.dialog.poll(), {"path": filename})
            self.assertIsNone(self.dialog.poll())
            self.assertEqual(self.dialog.directory, Path(filename).parent)
            worker.terminate.assert_not_called()

    def test_crash_can_be_reported_and_picker_reopened(self):
        worker = Mock()
        worker.poll.return_value = 1
        with patch("mini3d.model_dialog.subprocess.Popen", return_value=worker):
            self.dialog.open()
            self.assertTrue(self.dialog.poll()["error"])
            self.assertFalse(self.dialog.pending)
            self.assertTrue(self.dialog.open())

    def test_launch_failure_cleans_temporary_state(self):
        with patch("mini3d.model_dialog.subprocess.Popen", side_effect=OSError("launch failed")):
            with self.assertRaises(OSError):
                self.dialog.open()
        self.assertIsNone(self.dialog._temporary)
        self.assertFalse(self.dialog.pending)

    def test_tk_root_destroyed_on_success_cancel_or_error(self):
        for outcome in ("模型.glb", "", RuntimeError("dialog failed")):
            with self.subTest(outcome=outcome), patch("tkinter.Tk") as factory, \
                    patch("tkinter.filedialog.askopenfilename") as picker:
                if isinstance(outcome, Exception):
                    picker.side_effect = outcome
                    with self.assertRaises(RuntimeError):
                        choose_model(PROJECT)
                else:
                    picker.return_value = outcome
                    self.assertEqual(choose_model(PROJECT), outcome)
                factory.return_value.withdraw.assert_called_once()
                factory.return_value.destroy.assert_called_once()
                self.assertIs(picker.call_args.kwargs["parent"], factory.return_value)

    def test_worker_reports_tk_failure_without_crashing_editor(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = Path(temporary) / "result.json"
            with patch("mini3d.model_dialog.choose_model", side_effect=RuntimeError("Tk unavailable")):
                main(result, PROJECT)
            self.assertEqual(json.loads(result.read_text(encoding="utf8")),
                             {"path": "", "error": "Tk unavailable"})


class AsyncImportTests(unittest.TestCase):
    def setUp(self):
        self.app = Editor()

    def test_completed_path_imports_on_editor_thread(self):
        path = str(PROJECT / "model/06_stl_cube/cube.STL")
        with patch.object(self.app.model_dialog, "poll", return_value={"path": path}):
            entity = self.app.poll_model_dialog()
        self.assertIs(self.app.selection, entity)
        self.assertEqual(len(self.app.scene.root_entities), 1)

    def test_wait_cancel_and_failure_preserve_existing_scene(self):
        entity = self.app.add_asset(0)
        for result in (None, {"path": ""}, {"path": "", "error": "Tk unavailable"},
                       {"path": str(PROJECT / "missing.glb")}):
            with self.subTest(result=result), patch.object(self.app.model_dialog, "poll", return_value=result):
                self.assertIsNone(self.app.poll_model_dialog())
                self.assertEqual(self.app.scene.root_entities, [entity])
                self.assertIs(self.app.selection, entity)


if __name__ == "__main__":
    unittest.main()
