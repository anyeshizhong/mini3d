"""Original, self-contained glTF PBR cube for directional-light acceptance."""
import base64
import json
import numpy as np


def cube_geometry():
    positions, normals, indices = [], [], []
    for axis in range(3):
        for sign in (-1, 1):
            n = np.eye(3)[axis] * sign
            u = np.eye(3)[(axis + 1) % 3]
            v = np.cross(n, u)
            start = len(positions)
            positions.extend((n + a*u + b*v)*.7 for a, b in
                             ((-1, -1), (1, -1), (1, 1), (-1, 1)))
            normals.extend([n]*4)
            indices.extend([start, start+1, start+2, start, start+2, start+3])
    return (np.asarray(positions, '<f4'), np.asarray(normals, '<f4'),
            np.asarray(indices, '<u2'))


def write_pbr_cube(path):
    positions, normals, indices = cube_geometry()
    arrays = (positions, normals, indices)
    binary = b''.join(a.tobytes() for a in arrays)
    views, offset = [], 0
    for a in arrays:
        views.append(dict(buffer=0, byteOffset=offset, byteLength=a.nbytes))
        offset += a.nbytes
    document = dict(
        asset=dict(version='2.0', generator='Mini3D original lighting fixture'),
        scene=0, scenes=[dict(nodes=[0])], nodes=[dict(mesh=0)],
        meshes=[dict(primitives=[dict(attributes=dict(POSITION=0, NORMAL=1),
                                     indices=2, material=0)])],
        materials=[dict(name='Rough nonmetal PBR', pbrMetallicRoughness=dict(
            baseColorFactor=[.55, .3, .12, 1], metallicFactor=0, roughnessFactor=1))],
        buffers=[dict(byteLength=len(binary), uri='data:application/octet-stream;base64,'+
                      base64.b64encode(binary).decode('ascii'))],
        bufferViews=views,
        accessors=[dict(bufferView=0, componentType=5126, count=len(positions), type='VEC3',
                        min=positions.min(axis=0).tolist(), max=positions.max(axis=0).tolist()),
                   dict(bufferView=1, componentType=5126, count=len(normals), type='VEC3'),
                   dict(bufferView=2, componentType=5123, count=len(indices), type='SCALAR')])
    path.write_text(json.dumps(document, indent=2), encoding='utf8')
