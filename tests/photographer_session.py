"""An original Mini3D photography session. Run from any directory; no downloaded models."""
import os
if os.name != 'nt' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
if os.environ.get('SDL_VIDEODRIVER') == 'offscreen':
    os.environ.setdefault('PYOPENGL_PLATFORM','egl')
import sys, json, base64, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL
from mini3d.geometry import make_box, make_cylinder, make_sphere
from mini3d.scene import Mesh
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer

OUT=ROOT/'captures/photographer-session'

def asset(name, geometry, color, metal=0, rough=.7, upright=False):
    v,i=geometry
    if upright:
        v=v[:,[0,2,1]].copy(); v[:,1]*=-1
    m=Mesh(v,i)
    # Export engine Z-up to glTF Y-up; the loader reverses this basis.
    p=np.asarray(v[:,[0,2,1]],dtype='<f4').copy(); p[:,2]*=-1
    n=np.asarray(m.vertex_normals[:,[0,2,1]],dtype='<f4').copy(); n[:,2]*=-1
    idx=np.asarray(i,dtype='<u4').ravel()
    arrays=(p,n,idx); buf=b''.join(a.tobytes() for a in arrays)
    views=[]; offset=0
    for a in arrays:
        views.append(dict(buffer=0,byteOffset=offset,byteLength=a.nbytes)); offset+=a.nbytes
    doc=dict(asset=dict(version='2.0',generator='Mini3D geometry photography session'),scene=0,
      scenes=[dict(nodes=[0])],nodes=[dict(mesh=0)],
      meshes=[dict(primitives=[dict(attributes=dict(POSITION=0,NORMAL=1),indices=2,material=0)])],
      materials=[dict(name=name,pbrMetallicRoughness=dict(baseColorFactor=[*color,1],metallicFactor=metal,roughnessFactor=rough))],
      buffers=[dict(byteLength=len(buf),uri='data:application/octet-stream;base64,'+base64.b64encode(buf).decode())],bufferViews=views,
      accessors=[dict(bufferView=0,componentType=5126,count=len(p),type='VEC3',min=p.min(0).tolist(),max=p.max(0).tolist()),
                 dict(bufferView=1,componentType=5126,count=len(n),type='VEC3'),
                 dict(bufferView=2,componentType=5125,count=len(idx),type='SCALAR')])
    path=OUT/'assets'/(name+'.gltf');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc));return path

def build(api):
    stone=asset('ivory-box',make_box(1,1,1),(.73,.65,.49))
    column=asset('ivory-cylinder',make_cylinder(.38,1,48),(.73,.65,.49),upright=True)
    dark=asset('slate-box',make_box(1,1,1),(.075,.12,.16))
    red=asset('terracotta-box',make_box(1,1,1),(.42,.105,.055))
    gold=asset('gold-sphere',make_sphere(.9,40,64),(.83,.49,.12),metal=.62,rough=.27)
    def add(path,name,p,s):return api.spawn(path,name=name,position=p,scale=s)['entity_id']
    ground=add(dark,'Slate stage',[0,0,-.22],[32,32,.4]);api.lock(ground)
    add(stone,'Lower step',[0,0,.10],[8.4,11,.2])
    add(stone,'Upper step',[0,0,.30],[7.6,10.2,.2])
    members=[]
    with api.transaction('Build colonnade'):
        for x in (-2.8,2.8):
            for j,y in enumerate((-3.8,-1.9,0,1.9,3.8)):
                members.append(add(stone,'Column foot',[x,y,.53],[.95,.95,.26]))
                members.append(add(column,'Column shaft',[x,y,2.36],[1,1,3.4]))
                members.append(add(stone,'Column capital',[x,y,4.2],[1,1,.28]))
            members.append(add(stone,'Lintel',[x,0,4.48],[1.04,8.8,.28]))
    api.create_group(members,'Colonnade')
    add(red,'Altar',[0,2,1.0],[1.8,1.8,1.2])
    add(stone,'Altar cornice',[0,2,1.65],[2.0,2.0,.15])
    add(gold,'Golden sun',[0,2,2.64],[1,1,1])
    api.set_shadows(enabled=True,resolution=4096,bias=.0003,pcf=True)
    return api

SHOTS=[
 dict(name='01_colonnade',position=[9,-18,13],target=[0,0,1.8],focal_mm=35,aspect='16:9',light=[-3,-4,5],ambient=.38,diffuse=3.4),
 dict(name='02_sanctuary',position=[0,-15,3.0],target=[0,1,2.4],focal_mm=35,aspect='3:2',light=[-.8,-3,5],ambient=.35,diffuse=3.5),
 dict(name='03_golden_sun',position=[.8,-8,3.7],target=[0,2,2.35],focal_mm=85,aspect='1:1',light=[-1,-3,5],ambient=.35,diffuse=3.5),
 dict(name='04_long_shadows',position=[10,-13,17],target=[0,0,0],focal_mm=35,aspect='4:3',light=[-4,-2,2],ambient=.3,diffuse=3.5),
]

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    pygame.init();pygame.display.set_mode((800,600),pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer=GLRenderer(800,600)
    report=dict(commit='7cb7719',gpu=GL.glGetString(GL.GL_RENDERER).decode(),opengl=GL.glGetString(GL.GL_VERSION).decode(),shots=[])
    api=build(Mini3DAPI(renderer=renderer))
    for shot in SHOTS:
        name=shot['name'];api.set_lighting(mode='Scene',direction=shot['light'],ambient=shot['ambient'],diffuse=shot['diffuse'])
        api.create_shot_camera(**{k:shot[k] for k in ('position','target','focal_mm','aspect')},near=.05,far=200)
        t=time.perf_counter();api.capture(OUT/(name+'.png')); elapsed=time.perf_counter()-t
        api.save_scene(OUT/(name+'.json'))
        error=int(GL.glGetError());assert error==0,error
        report['shots'].append(dict(**shot,capture_seconds=elapsed,gl_error=error))
        print(name,round(elapsed,3),flush=True)
    # Restore an earlier photographic setup without rebuilding its camera.
    api.load_scene(OUT/'01_colonnade.json');api.capture(OUT/'01_reopened.png')
    a=pygame.surfarray.array3d(pygame.image.load(OUT/'01_colonnade.png'))
    b=pygame.surfarray.array3d(pygame.image.load(OUT/'01_reopened.png'))
    report['reopen_changed_pixels']=int(np.any(a!=b,axis=2).sum())
    assert report['reopen_changed_pixels']==0
    report['entities']=len(api.list_entities());report['groups']=api.list_groups()
    (OUT/'session.json').write_text(json.dumps(report,indent=2))
    renderer.close();pygame.quit();print(json.dumps(report))

if __name__=='__main__':run()
