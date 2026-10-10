"""A second practical shoot: still life, occlusion, light, and scale changes."""
import photographer_session as ph
import json
import time
from pathlib import Path
import numpy as np
import pygame
from OpenGL import GL
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer

ROOT=ph.ROOT
OUT=ROOT/'captures/second-session/still-life'

def pixels(path):
    return pygame.surfarray.array3d(pygame.image.load(path))

def build(renderer):
    ph.OUT=OUT
    ivory=ph.asset('ivory-block',ph.make_box(1,1,1),(.8,.74,.60),rough=.83)
    blue=ph.asset('blue-block',ph.make_box(1,1,1),(.025,.15,.44),rough=.45)
    red=ph.asset('red-cylinder',ph.make_cylinder(.7,1,64),(.52,.045,.024),rough=.42,upright=True)
    gold=ph.asset('copper-sphere',ph.make_sphere(.7,48,96),(.90,.40,.10),metal=.68,rough=.23)
    white=ph.asset('ivory-sphere',ph.make_sphere(.5,40,80),(.8,.74,.6),rough=.65)
    floor=ph.asset('navy-stage',ph.make_box(1,1,1),(.015,.035,.065),rough=.8)
    api=Mini3DAPI(renderer=renderer)
    def add(asset,name,pos,scale):
        return api.spawn(asset,name=name,position=pos,scale=scale)['entity_id']
    add(floor,'Stage',[0,0,-.1],[16,16,.2])
    with api.transaction('Arrange still life'):
        add(ivory,'Main plinth',[-.55,.4,.45],[2.8,2.3,.9])
        copper=add(gold,'Copper sphere',[-.80,.55,1.62],[1,1,1])
        api.place_at(copper,[-.80,.55,.9])
        add(red,'Vermilion cylinder',[1.3,1.1,1.45],[1,1,2.9])
        add(blue,'Blue cube',[1.3,-1.15,.63],[1.26,1.26,1.26])
        ivory_sphere=add(white,'Ivory sphere',[1.3,-1.15,1.78],[1,1,1])
        api.place_at(ivory_sphere,[1.3,-1.15,1.26])
        add(ivory,'Low bar',[-1.3,-1.5,.13],[2.4,.55,.26])
    api.create_group([e['entity_id'] for e in api.list_entities()[1:]],'Still life')
    api.set_shadows(enabled=True,resolution=4096,bias=.0003,pcf=True)
    return api

SHOTS=[
 dict(name='01_geometry',position=[7,-10,6.5],target=[0,0,1.1],focal_mm=50,aspect='3:2',light=[-3,-4,6],ambient=.35,diffuse=3.8),
 dict(name='02_low_sun',position=[7,-10,6.5],target=[0,0,1.1],focal_mm=50,aspect='3:2',light=[-5,-1,1.5],ambient=.2,diffuse=4.0),
 dict(name='03_copper',position=[.2,-7,3.1],target=[-.8,.55,1.6],focal_mm=85,aspect='1:1',light=[-2,-4,5],ambient=.3,diffuse=4.0),
 dict(name='04_silhouette',position=[5,-9,2.8],target=[0,0,1.35],focal_mm=50,aspect='16:9',light=[-1,4,3],ambient=.05,diffuse=3.8),
]

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    pygame.init();pygame.display.set_mode((800,600),pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer=GLRenderer(800,600);api=build(renderer)
    report=dict(gpu=GL.glGetString(GL.GL_RENDERER).decode(),shots=[],checks={})
    for shot in SHOTS:
        api.set_lighting(mode='Scene',direction=shot['light'],ambient=shot['ambient'],diffuse=shot['diffuse'])
        api.create_shot_camera(**{k:shot[k] for k in ('position','target','focal_mm','aspect')},near=.03,far=100)
        start=time.perf_counter();api.capture(OUT/(shot['name']+'.png'))
        report['shots'].append(dict(**shot,seconds=time.perf_counter()-start))
        api.save_scene(OUT/(shot['name']+'.json'))
        assert GL.glGetError()==0
        print(shot['name'],flush=True)
    api.load_scene(OUT/'01_geometry.json');api.capture(OUT/'01_reopened.png')
    original=pixels(OUT/'01_geometry.png')
    assert np.array_equal(original,pixels(OUT/'01_reopened.png'))
    report['checks']['reopen_identical']=True
    # A typical user deletes an obstruction, decides against it, and undoes.
    entity=next(e for e in api.list_entities() if e['name']=='Vermilion cylinder')
    api.delete(entity['entity_id']);api.capture(OUT/'without-cylinder.png')
    assert np.any(original!=pixels(OUT/'without-cylinder.png'))
    api.undo();api.capture(OUT/'after-undo.png')
    assert np.array_equal(original,pixels(OUT/'after-undo.png'))
    report['checks']['delete_and_undo_photo_identical']=True
    # Try a normal editing request: mirror a prop. Record unsupported operations.
    blue=next(e for e in api.list_entities() if e['name']=='Blue cube')
    try:
        api.set_transform(blue['entity_id'],scale=[-1.26,1.26,1.26])
    except ValueError as exc:
        report['checks']['mirror_request']=dict(supported=False,message=str(exc))
        assert api.get_entity(blue['entity_id'])==blue
    else:
        report['checks']['mirror_request']=dict(supported=True)
        api.undo()
    # Equivalent physical scene at cm scale and large world units.
    report['scale_comparisons']=[]
    for scale in (.01,100):
        api.load_scene(OUT/'01_geometry.json')
        api.transform_many([e['entity_id'] for e in api.list_entities()],scale=[scale]*3,pivot=[0,0,0])
        first=SHOTS[0]
        api.create_shot_camera(position=(np.array(first['position'])*scale).tolist(),
            target=(np.array(first['target'])*scale).tolist(),focal_mm=50,aspect='3:2',near=.03*scale,far=100*scale)
        file=OUT/('scale-'+str(scale)+'.png');api.capture(file);image=pixels(file)
        delta=np.abs(image.astype(int)-original.astype(int))
        report['scale_comparisons'].append(dict(scale=scale,changed_pixels=int(np.any(delta>0,axis=2).sum()),
            pixels_difference_over_8=int(np.any(delta>8,axis=2).sum()),mean_abs=float(delta.mean()),max_abs=int(delta.max())))
        assert GL.glGetError()==0
    (OUT/'session.json').write_text(json.dumps(report,indent=2))
    renderer.close();pygame.quit();print(json.dumps(report))

if __name__=='__main__':run()
