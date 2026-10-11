"""Unified entry: compose the editor runtime in mini3d.editor.run.

Editor owns input arbitration. Viewer supplies camera/framing only; its legacy
input bindings are disabled. GLRenderer delegates asset draws to MaterialRenderer.
"""
import argparse

from mini3d.editor import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mini3D Editor 0.1")
    parser.add_argument("--asset", type=int,
                        help="Initial model number in the list of installed assets (starting at 1)")
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--scene", help="Open a saved scene, including its photo camera")
    parser.add_argument("--hidden", action="store_true", help="Hidden window for rendering checks")
    parser.add_argument("--no-ipc", action="store_true", help="Disable the local live-editor API endpoint")
    parser.add_argument("--frames", type=int, help="Exit after this many frames")
    parser.add_argument("--screenshot", help="Save the last frame as an image (requires --frames)")
    options = parser.parse_args(argv)
    if options.scene and (options.empty or options.asset is not None):
        parser.error("--scene cannot be combined with --empty or --asset")
    if options.screenshot and not options.frames:
        parser.error("--screenshot requires --frames")
    if options.frames is not None and options.frames < 1:
        parser.error("--frames must be positive")
    if options.asset is not None and options.asset < 1:
        parser.error("--asset must be positive")
    initial = "auto" if options.asset is None else options.asset - 1
    run(None if options.empty else initial, options.frames, options.screenshot, options.hidden,
        ipc=not options.no_ipc, scene_path=options.scene)


if __name__ == "__main__":
    main()
