"""glTF 2.0 assets, preserved scene graphs and shared immutable mesh resources.

Coordinates are converted once, on the asset root: glTF +Y up becomes +Z up.
Skins are baked at the file's default node pose; animation playback is not implied.
"""
import base64
import copy
import json
from pathlib import Path
import struct
from urllib.parse import unquote

import numpy as np

from .scene import Entity, Mesh


class GltfError(ValueError):
    """An invalid or unsupported glTF feature."""


_DTYPES = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2',
           5125: '<u4', 5126: '<f4'}
_SHAPES = {'SCALAR': (1, 1), 'VEC2': (1, 2), 'VEC3': (1, 3),
           'VEC4': (1, 4), 'MAT2': (2, 2), 'MAT3': (3, 3), 'MAT4': (4, 4)}


def _node_matrix(node):
    if 'matrix' in node:
        return np.asarray(node['matrix'], dtype=np.float64).reshape(4, 4).T
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])
    length = np.linalg.norm([x, y, z, w])
    if length == 0:
        raise GltfError('Node has a zero quaternion')
    x, y, z, w = np.array([x, y, z, w]) / length
    rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation @ np.diag(node.get('scale', [1, 1, 1]))
    matrix[:3, 3] = node.get('translation', [0, 0, 0])
    return matrix


def _normals(positions, indices):
    normals = np.zeros_like(positions, dtype=np.float32)
    faces = positions[indices]
    face_normals = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
    for corner in range(3):
        np.add.at(normals, indices[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.maximum(lengths, 1e-20)


class _Document:
    def __init__(self, path):
        self.path = Path(path).resolve()
        raw = self.path.read_bytes()
        binary = None
        if raw[:4] == b'glTF':
            if len(raw) < 20:
                raise GltfError('Truncated GLB header')
            _, version, length = struct.unpack_from('<4sII', raw)
            if version != 2 or length != len(raw):
                raise GltfError('Expected a complete GLB version 2 file')
            offset, document = 12, None
            while offset < len(raw):
                if offset + 8 > len(raw):
                    raise GltfError('Truncated GLB chunk header')
                size, kind = struct.unpack_from('<II', raw, offset)
                offset += 8
                if offset + size > len(raw):
                    raise GltfError('Truncated GLB chunk')
                chunk = raw[offset:offset+size]
                offset += size
                if kind == 0x4E4F534A:
                    document = json.loads(chunk)
                elif kind == 0x004E4942:
                    binary = chunk
            if document is None:
                raise GltfError('GLB has no JSON chunk')
            self.data = document
        else:
            self.data = json.loads(raw.decode('utf-8-sig'))
        if self.data.get('asset', {}).get('version') != '2.0':
            raise GltfError('Only glTF 2.0 is supported')
        supported = {'KHR_materials_unlit', 'KHR_materials_specular'}
        unsupported = set(self.data.get('extensionsRequired', [])) - supported
        if unsupported:
            raise GltfError('Unsupported required extensions: ' + ', '.join(sorted(unsupported)))
        self.buffers = []
        for buffer in self.data.get('buffers', []):
            content = self.uri(buffer['uri']) if 'uri' in buffer else binary
            if content is None or len(content) < buffer['byteLength']:
                raise GltfError('Missing or truncated buffer')
            self.buffers.append(content)
        self.accessors, self.images, self.materials = {}, {}, {}

    def uri(self, uri):
        if uri.startswith('data:'):
            header, payload = uri.split(',', 1)
            if ';base64' not in header:
                raise GltfError('Only base64 data URIs are supported')
            return base64.b64decode(payload, validate=True)
        if '://' in uri:
            raise GltfError('Remote resource URIs are not supported: ' + uri)
        return (self.path.parent / unquote(uri)).read_bytes()

    def view(self, index):
        view = self.data['bufferViews'][index]
        if 'EXT_meshopt_compression' in view.get('extensions', {}):
            raise GltfError('EXT_meshopt_compression is not supported')
        buffer = self.buffers[view['buffer']]
        start = view.get('byteOffset', 0)
        end = start + view['byteLength']
        if start < 0 or end > len(buffer):
            raise GltfError('Buffer view exceeds buffer bounds')
        return memoryview(buffer)[start:end]

    def _read_array(self, view_index, offset, count, dtype, shape, use_stride=True):
        columns, rows = shape
        # glTF matrix columns of byte/short components start on 4-byte boundaries.
        column_bytes = rows * dtype.itemsize
        column_stride = ((column_bytes + 3) // 4) * 4 if columns > 1 else column_bytes
        element_bytes = columns * column_stride
        view = self.data['bufferViews'][view_index]
        stride = view.get('byteStride', element_bytes) if use_stride else element_bytes
        data = self.view(view_index)
        if count < 0 or offset < 0 or stride < element_bytes:
            raise GltfError('Invalid accessor layout')
        required = offset + (count-1)*stride + element_bytes if count else offset
        if required > len(data):
            raise GltfError('Accessor exceeds buffer view bounds')
        array = np.ndarray((count, columns, rows), dtype=dtype, buffer=data,
                           offset=offset, strides=(stride, column_stride, dtype.itemsize))
        return array.reshape(count, columns*rows).copy()

    def accessor(self, index):
        if index in self.accessors:
            return self.accessors[index]
        item = self.data['accessors'][index]
        try:
            dtype = np.dtype(_DTYPES[item['componentType']])
            shape = _SHAPES[item['type']]
        except KeyError as exc:
            raise GltfError('Unsupported accessor type') from exc
        count = item['count']
        if 'bufferView' in item:
            array = self._read_array(item['bufferView'], item.get('byteOffset', 0), count, dtype, shape)
        else:
            array = np.zeros((count, shape[0]*shape[1]), dtype=dtype)
        if 'sparse' in item:
            sparse = item['sparse']
            indices = sparse['indices']
            if indices['componentType'] not in (5121, 5123, 5125):
                raise GltfError('Invalid sparse index type')
            selected = self._read_array(indices['bufferView'], indices.get('byteOffset', 0),
                                        sparse['count'], np.dtype(_DTYPES[indices['componentType']]),
                                        (1, 1), False).ravel()
            if len(selected) and (np.any(selected >= count) or np.any(selected[1:] <= selected[:-1])):
                raise GltfError('Sparse indices must be ordered and within the accessor')
            values = sparse['values']
            array[selected] = self._read_array(values['bufferView'], values.get('byteOffset', 0),
                                                sparse['count'], dtype, shape, False)
        if item.get('normalized', False):
            if dtype.kind not in 'iu':
                raise GltfError('Only integer accessors may be normalized')
            array = array.astype(np.float32) / np.iinfo(dtype).max
            if dtype.kind == 'i':
                array = np.maximum(array, -1.0)
        self.accessors[index] = array
        return array

    def image(self, index):
        if index not in self.images:
            image = self.data['images'][index]
            self.images[index] = self.uri(image['uri']) if 'uri' in image else bytes(self.view(image['bufferView']))
        return self.images[index]

    def texture(self, info):
        if info.get('texCoord', 0) != 0:
            raise GltfError('Only TEXCOORD_0 textures are currently supported')
        if 'KHR_texture_transform' in info.get('extensions', {}):
            raise GltfError('KHR_texture_transform is not supported')
        texture = self.data['textures'][info['index']]
        if 'source' not in texture:
            raise GltfError('Texture has no supported image source')
        return {'image': self.image(texture['source']),
                'sampler': self.data.get('samplers', [])[texture['sampler']] if 'sampler' in texture else {},
                'texCoord': 0}

    def material(self, index):
        if index not in self.materials:
            material = copy.deepcopy(self.data['materials'][index]) if index is not None else {}
            pbr = material.get('pbrMetallicRoughness', {})
            slots = {'baseColor': pbr.get('baseColorTexture'),
                     'metallicRoughness': pbr.get('metallicRoughnessTexture'),
                     'normal': material.get('normalTexture'),
                     'occlusion': material.get('occlusionTexture'),
                     'emissive': material.get('emissiveTexture')}
            specular = material.get('extensions', {}).get('KHR_materials_specular', {})
            slots['specular'] = specular.get('specularTexture')
            material['textures'] = {name: self.texture(info) for name, info in slots.items() if info is not None}
            self.materials[index] = material
        return self.materials[index]


class Asset:
    """Loaded template whose instances share mesh and material resources."""
    def __init__(self, path, root, animation_names=None, skin_count=0):
        self.path = str(Path(path).resolve())
        self.name = Path(path).stem
        self.root = root
        self.animation_names = animation_names or []
        self.skin_count = skin_count

    def instantiate(self):
        instance = self.root.clone()
        instance.asset_path = self.path
        return instance


class AssetCache:
    def __init__(self):
        self._assets = {}

    def load(self, path):
        key = str(Path(path).resolve())
        if key not in self._assets:
            suffix = Path(key).suffix.lower()
            if suffix == '.stl':
                from .stl_loader import load_stl
                self._assets[key] = load_stl(key)
            elif suffix in ('.gltf', '.glb'):
                self._assets[key] = load_gltf(key)
            else:
                raise ValueError('Unsupported model format: {}. Choose GLB, glTF or STL.'.format(suffix))
        return self._assets[key]


def load_gltf(path):
    """Load a GLB/glTF at native scale, with static default-pose skinning."""
    doc = _Document(path)
    data = doc.data
    nodes = data.get('nodes', [])
    local = [_node_matrix(node) for node in nodes]
    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get('children', []):
            if child in parents or child < 0 or child >= len(nodes):
                raise GltfError('Invalid node hierarchy')
            parents[child] = index
    world = {}

    def world_matrix(index, active=None):
        if index in world:
            return world[index]
        active = set() if active is None else active
        if index in active:
            raise GltfError('Cyclic node hierarchy')
        active.add(index)
        world[index] = world_matrix(parents[index], active) @ local[index] if index in parents else local[index]
        active.remove(index)
        return world[index]

    for index in range(len(nodes)):
        world_matrix(index)
    mesh_cache = {}

    def primitive_mesh(mesh_index, primitive_index, node_index):
        node = nodes[node_index]
        skin_index = node.get('skin')
        key = (mesh_index, primitive_index, node_index if skin_index is not None else None)
        if key in mesh_cache:
            return mesh_cache[key]
        primitive = data['meshes'][mesh_index]['primitives'][primitive_index]
        if primitive.get('mode', 4) != 4:
            raise GltfError('Only TRIANGLES primitives are supported')
        if 'KHR_draco_mesh_compression' in primitive.get('extensions', {}):
            raise GltfError('KHR_draco_mesh_compression is not supported')
        if primitive.get('targets'):
            raise GltfError('Morph targets are not yet supported')
        attrs = primitive['attributes']
        positions = doc.accessor(attrs['POSITION']).astype(np.float32)
        normals = doc.accessor(attrs['NORMAL']).astype(np.float32) if 'NORMAL' in attrs else None
        uv = doc.accessor(attrs['TEXCOORD_0']).astype(np.float32) if 'TEXCOORD_0' in attrs else None
        if positions.ndim != 2 or positions.shape[1] != 3 or not np.isfinite(positions).all():
            raise GltfError('POSITION must contain finite VEC3 values')
        if normals is not None and (normals.shape != positions.shape or not np.isfinite(normals).all()):
            raise GltfError('NORMAL must contain one finite VEC3 per vertex')
        if uv is not None and (uv.shape != (len(positions), 2) or not np.isfinite(uv).all()):
            raise GltfError('TEXCOORD_0 must contain one finite VEC2 per vertex')
        if 'indices' in primitive:
            index_accessor = data['accessors'][primitive['indices']]
            if index_accessor['componentType'] not in (5121, 5123, 5125) or index_accessor['type'] != 'SCALAR':
                raise GltfError('Triangle indices must be unsigned integer scalars')
        indices = doc.accessor(primitive['indices']).ravel() if 'indices' in primitive else np.arange(len(positions))
        if len(indices) % 3 or (len(indices) and (np.min(indices) < 0 or np.max(indices) >= len(positions))):
            raise GltfError('Invalid triangle indices')
        indices = indices.astype(np.uint32).reshape(-1, 3)
        if skin_index is not None:
            skin = data['skins'][skin_index]
            joints = skin['joints']
            inverse_bind = (doc.accessor(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
                            if 'inverseBindMatrices' in skin else np.tile(np.eye(4), (len(joints), 1, 1)))
            if len(inverse_bind) != len(joints):
                raise GltfError('Skin inverse bind count differs from joint count')
            palette = np.linalg.inv(world[node_index]) @ np.array([world[joint] for joint in joints]) @ inverse_bind
            joint_ids = doc.accessor(attrs['JOINTS_0']).astype(np.int64)
            weights = doc.accessor(attrs['WEIGHTS_0']).astype(np.float64)
            if joint_ids.shape != (len(positions), 4) or weights.shape != joint_ids.shape:
                raise GltfError('Skin requires four joint indices and weights per vertex')
            if not np.isfinite(weights).all() or np.any(weights < 0):
                raise GltfError('Skin weights must be finite and nonnegative')
            if 'JOINTS_1' in attrs or 'WEIGHTS_1' in attrs:
                raise GltfError('More than four skin weights are not supported')
            if np.any(joint_ids < 0) or np.any(joint_ids >= len(joints)):
                raise GltfError('Skin joint index outside palette')
            totals = weights.sum(axis=1, keepdims=True)
            if np.any(totals <= 0):
                raise GltfError('Skin vertices must have positive total weights')
            weights /= totals
            matrices = np.einsum('nk,nkij->nij', weights, palette[joint_ids])
            homogeneous = np.column_stack((positions, np.ones(len(positions))))
            positions = np.einsum('nij,nj->ni', matrices, homogeneous)[:, :3].astype(np.float32)
            if normals is not None:
                normals = np.einsum('nji,nj->ni', np.linalg.inv(matrices[:, :3, :3]), normals)
                normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-20)
        if normals is None:
            normals = _normals(positions, indices)
        material = doc.material(primitive.get('material'))
        if material['textures'] and uv is None:
            raise GltfError('Textured mesh is missing TEXCOORD_0')
        mesh = Mesh(positions, indices, normals=normals, texcoords=uv, material=material)
        mesh_cache[key] = mesh
        return mesh

    def build_node(index):
        node = nodes[index]
        entity = Entity(name=node.get('name', 'Node {}'.format(index)), matrix=local[index])
        if 'mesh' in node:
            mesh_index = node['mesh']
            for primitive_index, _ in enumerate(data['meshes'][mesh_index]['primitives']):
                mesh = primitive_mesh(mesh_index, primitive_index, index)
                entity.add_child(Entity(model=mesh, name='Primitive {}'.format(primitive_index)))
        for child in node.get('children', []):
            entity.add_child(build_node(child))
        return entity

    conversion = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float)
    root = Entity(name=Path(path).stem, matrix=conversion)
    scenes = data.get('scenes', [])
    roots = scenes[data.get('scene', 0)].get('nodes', []) if scenes else [i for i in range(len(nodes)) if i not in parents]
    for index in roots:
        root.add_child(build_node(index))
    root.update_transform()
    return Asset(path, root, [animation.get('name', 'Animation {}'.format(i))
                             for i, animation in enumerate(data.get('animations', []))], len(data.get('skins', [])))
