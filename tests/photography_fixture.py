"""Shared original geometry glTF fixture; never starts a session or GL context.

OUT is set by each sequential CLI caller, preserving the historical asset API
and byte serialization. Environment defaults preserve Linux offscreen support.
"""
import os
if os.name != 'nt' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
if os.environ.get('SDL_VIDEODRIVER') == 'offscreen':
    os.environ.setdefault('PYOPENGL_PLATFORM','egl')
import base64,json,sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from mini3d.geometry import make_box, make_cylinder, make_sphere
from mini3d.scene import Mesh
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
