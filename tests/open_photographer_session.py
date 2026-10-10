"""Open one of the saved photographic setups in the existing Mini3D Editor."""
import argparse
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mini3d import editor

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('scene',nargs='?',default='02_sanctuary')
    parser.add_argument('--frames',type=int)
    parser.add_argument('--screenshot')
    parser.add_argument('--hidden',action='store_true')
    args=parser.parse_args()
    path=ROOT/'captures/photographer-session'/(args.scene+'.json')
    class PhotoEditor(editor.Editor):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw)
            self.load_scene(path)
            self.scene_path=path
            self.set_camera_view(True)
    with patch.object(editor,'Editor',PhotoEditor):
        editor.run(initial_asset=None,frames=args.frames,screenshot=args.screenshot,hidden=args.hidden)

if __name__=='__main__':main()
