"""Open an explicit saved photography Scene in the existing Mini3D Editor."""
import argparse
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mini3d import editor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', type=Path, help='Saved Scene JSON; relative to the working directory')
    parser.add_argument('--frames', type=int)
    parser.add_argument('--screenshot')
    parser.add_argument('--hidden', action='store_true')
    args = parser.parse_args()
    path = args.scene.resolve()
    if not path.is_file():
        parser.error('Scene does not exist')
    if args.screenshot and Path(args.screenshot).exists():
        parser.error('Screenshot exists; choose a fresh output path')

    class PhotoEditor(editor.Editor):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.load_scene(path)
            self.scene_path = path
            self.set_camera_view(True)

    with patch.object(editor, 'Editor', PhotoEditor):
        editor.run(initial_asset=None, frames=args.frames,
                   screenshot=args.screenshot, hidden=args.hidden)


if __name__ == '__main__':
    main()
