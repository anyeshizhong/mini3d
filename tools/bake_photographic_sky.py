"""Rebuild bundled HDRI lighting once; no extra dependencies are required."""
import argparse
from pathlib import Path
import os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--source',default='sunset')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--samples',type=int,default=256)
    args=parser.parse_args()
    if args.headless:
        os.environ['PYOPENGL_PLATFORM']='egl'
        from mini3d.headless_gl import egl_context
        context=egl_context
    else:
        from tools.capture_sunset import desktop_context
        context=desktop_context
    from mini3d.photo_environment import load_sky,RESOURCES
    from mini3d.ibl_filter import filter_panorama
    import numpy as np
    output=args.output or RESOURCES/'sunset_ibl.npz'
    with context():arrays=filter_panorama(load_sky(args.source)[1],args.samples)
    np.savez_compressed(output,**arrays)
    print(output)

if __name__=='__main__':main()
