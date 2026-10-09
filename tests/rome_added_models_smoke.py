"""Issue #4 supplementary local assets and existing 2048 setting; no conversions."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot


def run(output):
    pygame.init();pygame.display.set_mode((640,480),pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer,target=GLRenderer(640,480),RenderTarget()
    renderer.render_mode='REALISTIC'
    api=Mini3DAPI(renderer)
    report={}
    try:
        api.load_scene(output/'stage-scene.json')
        view=json.loads((output/'stage-views.json').read_text())[0]
        api.create_shot_camera(**view)
        api.set_shadows(resolution=2048)
        api.capture(output/'stage-view0-2048.png')
        report['stage_2048']=api.get_shadows()
        for path,height,xy in [('model/09_other_roman_soldier/roman_soldier_-_t_pose_-_free_download.glb',1.8,[2,0]),('model/10_pantheon/agrippa_pantheon.glb',6,[0,7])]:
            entity=api.spawn(str(ROOT/path))
            bounds=api.get_entity(entity['entity_id'],include_bounds=True)['bounds']
            scale=height/(bounds['maximum'][2]-bounds['minimum'][2])
            api.set_transform(entity['entity_id'],scale=[scale]*3)
            api.place_on_ground(entity['entity_id'],x=xy[0],y=xy[1])
            report[path]=dict(scale=scale,target_height=height,entity_id=entity['entity_id'])
        api.create_shot_camera(position=[-10,-16,10],target=[0,3,2],focal_mm=35,near=.05,far=100)
        previous=None
        for enabled in (False,True):
            api.set_shadows(enabled=enabled,resolution=1024)
            scene=api._app.scene;scene.update()
            render_shot(scene,api._app.shot_camera,renderer,target)
            size=api._app.shot_camera.size
            depth=np.asarray(gl.glReadPixels(0,0,*size,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)).copy()
            if previous is not None:np.testing.assert_array_equal(previous,depth)
            previous=depth
            api.capture(output/('added-models-'+('on' if enabled else 'off')+'.png'))
        renderer.shadow_map.save_depth_png(output/'added-models-depth.png')
        api.save_scene(output/'added-models-scene.json')
        report['camera']=api.get_shot_camera();report['depth_equal']=True
        report['materials_note']='New T-pose soldier: normal PBR; Pantheon: original KHR_materials_unlit retained. Explicit built-in PBR floor.'
        assert gl.glGetError()==gl.GL_NO_ERROR
        (output/'added-models-results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print('PASS: supplied T-pose Roman + original Unlit Pantheon + explicit PBR floor, on/off depth equal; existing 2048 setting comparison')
    finally:
        renderer.close();target.close();pygame.quit()

if __name__=='__main__':run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'docs/rome-integration')
