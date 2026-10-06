"""Run Tk's native file picker outside the SDL/OpenGL event loop.

The worker owns every Tk object on its main thread. Only a JSON result crosses
the process boundary; scene changes and GPU work stay on the editor thread.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


class ModelFileDialog:
    def __init__(self, directory):
        self.directory = Path(directory)
        self._process = None
        self._temporary = None

    @property
    def pending(self):
        return self._process is not None

    def open(self):
        if self.pending:
            return False
        self._temporary = tempfile.TemporaryDirectory(prefix="mini3d-picker-")
        self._result = Path(self._temporary.name) / "result.json"
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-B", str(Path(__file__).resolve()),
                 str(self._result), str(self.directory)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self._cleanup()
            raise
        return True

    def poll(self):
        """Return a completed result once, or None without blocking a frame."""
        if not self.pending or self._process.poll() is None:
            return None
        try:
            result = json.loads(self._result.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or not isinstance(result.get("path"), str):
                raise ValueError("Invalid file picker result")
            if result["path"]:
                self.directory = Path(result["path"]).parent
            return result
        except (OSError, ValueError) as exc:
            return {"path": "", "error": "File picker closed without a valid result: {}".format(exc)}
        finally:
            self._cleanup()

    def close(self):
        """Cancel only this editor's picker, including an unclosed native dialog."""
        if self.pending and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._cleanup()

    def _cleanup(self):
        self._process = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def choose_model(directory):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        return filedialog.askopenfilename(
            parent=root, title="Mini3D - Import model",
            initialdir=str(directory),
            filetypes=[("Supported models", "*.glb *.gltf *.stl *.STL"),
                       ("Binary glTF", "*.glb"), ("glTF", "*.gltf"),
                       ("STL", "*.stl *.STL")],
        ) or ""
    finally:
        root.destroy()


def main(result_path, directory):
    try:
        result = {"path": choose_model(directory)}
    except Exception as exc:
        result = {"path": "", "error": str(exc)}
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
