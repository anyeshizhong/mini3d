"""Launch the Mini3D editor using F:/gymenv/python.exe editor.py."""
import argparse

from mini3d.editor import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mini3D Editor 0.1")
    parser.add_argument("--asset", type=int,
                        help="Initial model number in the list of installed assets (starting at 1)")
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--hidden", action="store_true", help="Hidden window for rendering checks")
    parser.add_argument("--frames", type=int, help="Exit after this many frames")
    parser.add_argument("--screenshot", help="Save the last frame as an image (requires --frames)")
    options = parser.parse_args()
    if options.screenshot and not options.frames:
        parser.error("--screenshot requires --frames")
    initial = "auto" if options.asset is None else options.asset - 1
    run(None if options.empty else initial, options.frames, options.screenshot, options.hidden)
