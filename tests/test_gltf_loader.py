"""Importer regression tests: layout, coordinates, sharing and real assets."""
import base64
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from mini3d.gltf_loader import AssetCache, GltfError, _Document, _node_matrix, load_gltf


PROJECT = Path(__file__).resolve().parents[1]


def walk(root):
    yield root
    for child in root.children:
        yield from walk(child)


def meshes(root):
    return [entity.model for entity in walk(root) if entity.model is not None]


def bounds(root):
    points = []

    def visit(entity, parent):
        matrix = parent @ entity.extra_local
        if entity.model is not None:
            points.append((matrix @ entity.model.vertices.T).T[:, :3])
        for child in entity.children:
            visit(child, matrix)

    visit(root, np.eye(4))
    vertices = np.concatenate(points)
    return np.array([vertices.min(axis=0), vertices.max(axis=0)])


class SyntheticImporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def document(self, raw, **fields):
        data = {'asset': {'version': '2.0'}, 'buffers': [
            {'byteLength': len(raw), 'uri': 'data:application/octet-stream;base64,' +
             base64.b64encode(raw).decode('ascii')}]}
        data.update(fields)
        path = self.directory / 'sample.gltf'
        path.write_text(json.dumps(data), encoding='utf8')
        return _Document(path)

    def test_interleaved_offset_and_normalized_components(self):
        raw = bytes([99, 99, 0, 127, 255, 9, 9, 9, 255, 0, 127, 9, 9, 9])
        doc = self.document(raw, bufferViews=[{'buffer': 0, 'byteOffset': 2, 'byteLength': 12, 'byteStride': 6}],
                            accessors=[{'bufferView': 0, 'componentType': 5121, 'count': 2,
                                        'type': 'VEC3', 'normalized': True}])
        np.testing.assert_allclose(doc.accessor(0), [[0, 127/255, 1], [1, 0, 127/255]])

    def test_sparse_without_base_view(self):
        raw = bytes([1]) + np.array([3, 4, 5], dtype='<f4').tobytes()
        doc = self.document(raw, bufferViews=[{'buffer': 0, 'byteLength': 1},
                                              {'buffer': 0, 'byteOffset': 1, 'byteLength': 12}],
                            accessors=[{'componentType': 5126, 'count': 3, 'type': 'VEC3',
                                        'sparse': {'count': 1, 'indices': {'bufferView': 0, 'componentType': 5121},
                                                   'values': {'bufferView': 1}}}])
        np.testing.assert_array_equal(doc.accessor(0), [[0, 0, 0], [3, 4, 5], [0, 0, 0]])

    def test_matrix_byte_column_padding(self):
        doc = self.document(bytes([1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0]),
                            bufferViews=[{'buffer': 0, 'byteLength': 12}],
                            accessors=[{'bufferView': 0, 'componentType': 5121, 'count': 1, 'type': 'MAT3'}])
        np.testing.assert_array_equal(doc.accessor(0), [list(range(1, 10))])

    def test_trs_order_and_column_major_matrix(self):
        node = {'translation': [1, 2, 3], 'rotation': [0, 0, np.sqrt(.5), np.sqrt(.5)], 'scale': [2, 3, 4]}
        actual = _node_matrix(node)
        np.testing.assert_allclose(actual @ [1, 0, 0, 1], [1, 4, 3, 1], atol=1e-10)
        np.testing.assert_array_equal(_node_matrix({'matrix': actual.T.ravel().tolist()}), actual)

    def test_accessor_bounds_fail_clearly(self):
        doc = self.document(bytes(8), bufferViews=[{'buffer': 0, 'byteLength': 8}],
                            accessors=[{'bufferView': 0, 'componentType': 5126, 'count': 1, 'type': 'VEC3'}])
        with self.assertRaisesRegex(GltfError, 'bounds'):
            doc.accessor(0)

    def test_required_compression_rejected(self):
        with self.assertRaisesRegex(GltfError, 'KHR_draco_mesh_compression'):
            self.document(b'', extensionsRequired=['KHR_draco_mesh_compression'])

    def test_nonzero_uv_channel_rejected(self):
        doc = self.document(b'')
        with self.assertRaisesRegex(GltfError, 'TEXCOORD_0'):
            doc.texture({'index': 0, 'texCoord': 1})

    def test_hierarchy_and_shared_mesh(self):
        raw = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='<f4').tobytes()
        doc = self.document(raw, bufferViews=[{'buffer': 0, 'byteLength': len(raw)}],
                            accessors=[{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'}],
                            meshes=[{'primitives': [{'attributes': {'POSITION': 0}}]}],
                            nodes=[{'name': 'Parent', 'translation': [10, 20, 30], 'children': [1, 2]},
                                   {'mesh': 0, 'scale': [2, 2, 2]}, {'mesh': 0, 'translation': [5, 0, 0]}],
                            scenes=[{'nodes': [0]}])
        asset = load_gltf(doc.path)
        self.assertEqual(asset.root.children[0].name, 'Parent')
        self.assertIs(*meshes(asset.root))
        np.testing.assert_allclose(bounds(asset.root), [[10, -30, 20], [16, -30, 22]])
        first, second = asset.instantiate(), asset.instantiate()
        self.assertIsNot(first, second)
        self.assertIs(meshes(first)[0], meshes(second)[0])
        first.pos[0] = 42
        self.assertEqual(second.pos[0], 0)

    def test_default_skin_pose_and_inverse_bind(self):
        positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='<f4')
        joints = np.zeros((3, 4), dtype='u1')
        weights = np.tile(np.array([1, 0, 0, 0], dtype='<f4'), (3, 1))
        inverse_bind = np.eye(4, dtype='<f4')
        inverse_bind[1, 3] = -1
        chunks = [positions.tobytes(), joints.tobytes(), weights.tobytes(), inverse_bind.T.tobytes()]
        views, offset = [], 0
        for chunk in chunks:
            views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(chunk)})
            offset += len(chunk)
        doc = self.document(b''.join(chunks), bufferViews=views,
                            accessors=[{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'},
                                       {'bufferView': 1, 'componentType': 5121, 'count': 3, 'type': 'VEC4'},
                                       {'bufferView': 2, 'componentType': 5126, 'count': 3, 'type': 'VEC4'},
                                       {'bufferView': 3, 'componentType': 5126, 'count': 1, 'type': 'MAT4'}],
                            meshes=[{'primitives': [{'attributes': {'POSITION': 0, 'JOINTS_0': 1, 'WEIGHTS_0': 2}}]}],
                            nodes=[{'mesh': 0, 'skin': 0, 'translation': [2, 0, 0]}, {'translation': [0, 3, 0]}],
                            skins=[{'joints': [1], 'inverseBindMatrices': 3}], scenes=[{'nodes': [0, 1]}])
        asset = load_gltf(doc.path)
        np.testing.assert_allclose(bounds(asset.root), [[0, 0, 2], [1, 0, 3]])
        np.testing.assert_allclose(meshes(asset.root)[0].vertex_normals, [[0, 0, 1]]*3)


class RealAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = AssetCache()

    def test_five_downloaded_assets(self):
        paths = [PROJECT / 'model' / relative for relative in (
            '01_box/Box.glb', '02_water_bottle/WaterBottle.glb',
            '03_side_table/side_table.glb', '04_fox/Fox.glb',
            '05_roman_soldier/roman_legionnaire.glb')]
        expected_counts = {'Box.glb': (24, 12), 'WaterBottle.glb': (2549, 4510),
                           'side_table.glb': (5186, 6408), 'Fox.glb': (1728, 576),
                           'roman_legionnaire.glb': (338972, 589879)}
        for path in paths:
            with self.subTest(asset=path.name):
                if not path.is_file():
                    self.skipTest('Optional local asset not installed: ' + path.name)
                asset = self.cache.load(path)
                self.assertIs(asset, self.cache.load(path))
                models = meshes(asset.root)
                self.assertGreater(len(models), 0)
                triangle_count = sum(len(model.indices) for model in models)
                self.assertEqual((sum(len(model.vertices) for model in models), triangle_count),
                                 expected_counts[path.name])
                box = bounds(asset.root)
                self.assertTrue(np.isfinite(box).all())
                self.assertTrue(np.all(box[1] > box[0]))
                for model in models:
                    self.assertTrue(np.isfinite(model.vertices).all())
                    self.assertTrue(np.isfinite(model.vertex_normals).all())
                    self.assertEqual(len(model.vertices), len(model.vertex_normals))
                    for texture in model.material['textures'].values():
                        self.assertGreater(len(texture['image']), 100)
                if path.name == 'Box.glb':
                    self.assertEqual(triangle_count, 12)
                elif path.name == 'Fox.glb':
                    self.assertEqual(asset.skin_count, 1)
                    self.assertEqual(len(asset.animation_names), 3)
                elif path.name == 'roman_legionnaire.glb':
                    self.assertGreater(triangle_count, 500000)
                instance = asset.instantiate()
                self.assertIs(meshes(instance)[0], models[0])

    def test_side_table_external_gltf_equals_glb(self):
        folder = PROJECT / 'model' / '03_side_table'
        if not (folder / 'side_table.glb').is_file():
            self.skipTest('Optional side-table assets not installed')
        glb = self.cache.load(folder / 'side_table.glb')
        gltf = self.cache.load(folder / 'side_table_tall_01_2k.gltf')
        np.testing.assert_allclose(bounds(glb.root), bounds(gltf.root))
        for one, two in zip(meshes(glb.root), meshes(gltf.root)):
            np.testing.assert_array_equal(one.vertices, two.vertices)
            np.testing.assert_array_equal(one.indices, two.indices)
            self.assertEqual(one.material['textures'], two.material['textures'])


if __name__ == '__main__':
    unittest.main()
