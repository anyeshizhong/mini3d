"""Ground occlusion, focus, DoF depth preservation and sky on a real GL context."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(output, backend):
    os.environ['MINI3D_PHOTO_BACKEND'] = backend
    os.environ['MINI3D_REQUIRE_NATIVE_PHOTO'] = '1' if backend=='native' else '0'
    from OpenGL import GL as gl
    from tools.capture_sunset import desktop_context
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.render_target import RenderTarget
    from mini3d.photo_focus import read_focus_point
    from mini3d.shot_camera import render_scene_view
    output.mkdir(parents=True,exist_ok=True)
    report = dict(backend=backend, checks={})
    with desktop_context():
        renderer, target = GLRenderer(640,360), RenderTarget()
        try:
            api = Mini3DAPI(renderer=renderer)
            api.set_atmosphere(enabled=True,ground=True,ground_z=-.14,haze=0)
            api.set_shadows(enabled=True,resolution=2048)
            api.spawn('builtin:ground',position=[0,0,1],scale=[.2,.2,1])
            # Parallel planes give sample-invariant depth under 4x MSAA; an
            # oblique plane's resolved sample need not be the pixel-center ray.
            api.create_shot_camera(position=[0,0,4],target=[0,0,1],
                                   focal_mm=35,aspect='16:9',near=.05,far=150)
            api.set_antialiasing(4)
            def render():
                render_scene_view(api._app.scene,api._app.shot_camera,renderer,target,(640,360),4)
                if backend=='native':
                    assert renderer.render_stats['backend']=='native-photo'
                assert gl.glGetError()==gl.GL_NO_ERROR
            def point(pixel):
                return read_focus_point(target,api._app.shot_camera,pixel,(0,0,640,360))
            render()
            foreground, ground = point([320,180]), point([80,300])
            assert foreground is not None and abs(foreground[2]-1)<1e-3, foreground
            assert ground is not None and abs(ground[2]+.14)<1e-3, ground
            report['checks']['foreground_above_ground'] = foreground.tolist()
            report['checks']['ground_focus_point'] = ground.tolist()
            before = bytes(gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT))
            api.focus_at(ground.tolist())
            api.set_depth_of_field(enabled=True,f_number=1.4)
            render()
            after = bytes(gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT))
            assert before==after, 'DoF changed ground/foreground depth'
            report['checks']['dof_preserves_depth'] = True
            api.set_depth_of_field(enabled=False)
            api.set_shot_camera_pose(position=[0,0,300],target=[0,0,0])
            render()
            depth=np.asarray(gl.glReadPixels(0,0,640,360,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT))
            assert np.all(depth<1), 'Empty shadow receiver stopped aerial ground rendering'
            report['checks']['aerial_with_shadows'] = True
            api.set_shot_camera_pose(position=[0,-5,4],target=[0,-5,5])
            render()
            assert point([320,180]) is None, 'Upward sky incorrectly receives ground depth'
            report['checks']['upward_focus_is_sky'] = True
            api.set_shot_camera_pose(position=[0,0,-2],target=[0,0,-.14])
            render()
            underside=point([320,180])
            assert underside is not None and abs(underside[2]+.14)<1e-3, underside
            report['checks']['underside_plane'] = underside.tolist()
            report['gpu']=gl.glGetString(gl.GL_RENDERER).decode()
            report['native_dll_sha256']=hashlib.sha256((ROOT/'native/spqr_photo.dll').read_bytes()).hexdigest() if backend=='native' else None
        finally:
            target.close()
            renderer.close()
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=('python','native'),default='native')
    args=parser.parse_args()
    run(args.output,args.backend)
