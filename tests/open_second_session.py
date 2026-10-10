"""Open the still-life photographs as editable Mini3D scenes."""
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mini3d import editor

name=sys.argv[1] if len(sys.argv)>1 else '01_geometry'
path=ROOT/'captures/second-session/still-life'/(name+'.json')

class PhotoEditor(editor.Editor):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.load_scene(path)
        self.scene_path=path
        self.set_camera_view(True)

if __name__=='__main__':
    with patch.object(editor,'Editor',PhotoEditor):
        editor.run(initial_asset=None)
