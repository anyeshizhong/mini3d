"""Open locally generated Mini3D photo-session scenes in Camera View.

Run from the project root, after the chosen session has generated its captures:
  python -B tools/open_photo_session.py --session photographer 02_sanctuary
  python -B tools/open_photo_session.py --session still-life 01_geometry
"""
import argparse
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mini3d import editor


SESSIONS = {
    'photographer': ('photographer-session', '02_sanctuary'),
    'still-life': ('second-session/still-life', '01_geometry'),
}


def resolve_scene(session, name=None):
    """Return only paths within the selected locally generated capture collection."""
    folder, default_name = SESSIONS[session]
    name = default_name if name is None else name
    if not name or name in ('.', '..') or Path(name).name != name or '\\' in name:
        raise ValueError('Scene must be a filename stem, not a path')
    if name.endswith('.json'):
        name = name[:-5]
        if not name:
            raise ValueError('Scene name is empty')
    return ROOT / 'captures' / folder / (name + '.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', choices=tuple(SESSIONS), default='photographer')
    parser.add_argument('scene', nargs='?', help='Saved scene name, without .json')
    parser.add_argument('--frames', type=int)
    parser.add_argument('--screenshot')
    parser.add_argument('--hidden', action='store_true')
    args = parser.parse_args(argv)
    if args.screenshot and not args.frames:
        parser.error('--screenshot requires --frames')
    if args.frames is not None and args.frames <= 0:
        parser.error('--frames must be positive')
    try:
        path = resolve_scene(args.session, args.scene)
    except ValueError as exc:
        parser.error(str(exc))
    if not path.is_file():
        parser.error('Saved scene is missing: {}. Generate the photo session first.'.format(path))

    class PhotoEditor(editor.Editor):
        def __init__(self, *pos, **kw):
            super().__init__(*pos, **kw)
            self.load_scene(path)
            self.scene_path = path
            self.set_camera_view(True)

    with patch.object(editor, 'Editor', PhotoEditor):
        editor.run(initial_asset=None, frames=args.frames,
                   screenshot=args.screenshot, hidden=args.hidden)


if __name__ == '__main__':
    main()
