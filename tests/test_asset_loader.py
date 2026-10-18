"""CPU background asset loader contracts; no display or GL context required."""
import base64
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
import zlib
from unittest import mock

from mini3d.asset_loader import AssetLoader, prepare_asset
from mini3d.assets import AssetCache
import mini3d.asset_loader as asset_loader_module


def _png_rgba_1x1(red=255, green=0, blue=0, alpha=255):
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload +
                struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))

    header = struct.pack('>2I5B', 1, 1, 8, 6, 0, 0, 0)
    scanline = bytes((0, red, green, blue, alpha))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
            chunk(b'IDAT', zlib.compress(scanline)) + chunk(b'IEND', b''))


class AssetFixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def close(self):
        self.temporary.cleanup()

    def write_stl(self):
        path = self.directory / 'tiny.stl'
        path.write_text(
            'solid tiny\n'
            ' facet normal 0 0 1\n'
            '  outer loop\n'
            '   vertex 0 0 0\n'
            '   vertex 1 0 0\n'
            '   vertex 0 1 0\n'
            '  endloop\n'
            ' endfacet\n'
            'endsolid tiny\n', encoding='ascii')
        return path

    def write_textured_gltf(self):
        path = self.directory / 'tiny.gltf'
        positions = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
        texcoords = struct.pack('<6f', 0, 0, 1, 0, 0, 1)
        indices = struct.pack('<3H', 0, 1, 2)
        binary = positions + texcoords + indices
        png = _png_rgba_1x1()
        document = {
            'asset': {'version': '2.0'},
            'buffers': [{'byteLength': len(binary), 'uri': 'data:application/octet-stream;base64,' +
                         base64.b64encode(binary).decode('ascii')}],
            'bufferViews': [
                {'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions)},
                {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(texcoords)},
                {'buffer': 0, 'byteOffset': len(positions) + len(texcoords), 'byteLength': len(indices)},
            ],
            'accessors': [
                {'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'},
                {'bufferView': 1, 'componentType': 5126, 'count': 3, 'type': 'VEC2'},
                {'bufferView': 2, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'},
            ],
            'images': [{'uri': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')}],
            'textures': [{'source': 0}, {'source': 0}],
            'materials': [
                {'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}},
                {'pbrMetallicRoughness': {'baseColorTexture': {'index': 1}}},
            ],
            'meshes': [
                {'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                 'indices': 2, 'material': 0}]},
                {'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                 'indices': 2, 'material': 1}]},
            ],
            'nodes': [{'mesh': 0}, {'mesh': 1}],
            'scenes': [{'nodes': [0, 1]}],
            'scene': 0,
        }
        path.write_text(json.dumps(document), encoding='utf8')
        return path


def _wait_for_result(loader, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = loader.poll()
        if result is not None:
            return result
        time.sleep(.005)
    raise AssertionError('Timed out waiting for asset loader result')


def _textures(asset):
    result = []
    pending = [asset.root]
    while pending:
        entity = pending.pop()
        pending.extend(entity.children)
        if entity.model is not None:
            result.extend(entity.model.material['textures'].values())
    return result


class AssetPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = AssetFixture()

    def tearDown(self):
        self.fixture.close()

    def test_real_gltf_decodes_shared_image_once_and_keeps_encoded_bytes(self):
        import pygame

        path = self.fixture.write_textured_gltf()
        with mock.patch.object(pygame.image, 'load', wraps=pygame.image.load) as load_image:
            asset = prepare_asset(path, AssetCache())

        self.assertEqual(load_image.call_count, 1)
        textures = _textures(asset)
        self.assertEqual(len(textures), 2)
        self.assertIs(textures[0]['image'], textures[1]['image'])
        self.assertEqual(textures[0]['_decoded_image'], (1, 1, bytes((255, 0, 0, 255))))
        self.assertIs(textures[0]['_decoded_image'], textures[1]['_decoded_image'])
        self.assertIs(textures[0]['_decoded_source'], textures[0]['image'])
        self.assertIs(textures[1]['_decoded_source'], textures[1]['image'])
        self.assertTrue(textures[0]['image'].startswith(b'\x89PNG'))

    def test_replacing_texture_image_redecodes_and_repeat_prepare_is_read_only(self):
        import pygame

        path = self.fixture.write_textured_gltf()
        cache = AssetCache()
        asset = prepare_asset(path, cache)
        texture = _textures(asset)[0]

        class TrackingDict(dict):
            def __init__(self, source):
                dict.__init__(self, source)
                self.writes = 0

            def __setitem__(self, key, value):
                self.writes += 1
                dict.__setitem__(self, key, value)

        tracked = TrackingDict(texture)
        texture_slots = asset.root.children[0].children[0].model.material['textures']
        texture_slots['baseColor'] = tracked
        original_image = tracked['image']
        original_decoded = tracked['_decoded_image']
        with mock.patch.object(asset_loader_module, '_decode_image', wraps=asset_loader_module._decode_image) as decode:
            self.assertIs(prepare_asset(path, cache), asset)
            self.assertEqual(decode.call_count, 0)
        self.assertEqual(tracked.writes, 0)
        self.assertIs(tracked['_decoded_source'], original_image)
        self.assertIs(tracked['_decoded_image'], original_decoded)

        replacement = _png_rgba_1x1(0, 255, 0, 255)
        tracked['image'] = replacement
        tracked.writes = 0
        with mock.patch.object(pygame.image, 'load', wraps=pygame.image.load) as load_image:
            prepare_asset(path, cache)
        self.assertEqual(load_image.call_count, 1)
        self.assertEqual(tracked.writes, 2)
        self.assertIs(tracked['_decoded_source'], replacement)
        self.assertIs(tracked['image'], replacement)
        self.assertEqual(tracked['_decoded_image'], (1, 1, bytes((0, 255, 0, 255))))

    def test_stl_is_loaded_by_asset_cache(self):
        asset = prepare_asset(self.fixture.write_stl())
        self.assertEqual(asset.name, 'tiny')
        self.assertIsNotNone(asset.root.model)
        self.assertEqual(len(asset.root.model.indices), 1)


class AssetLoaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = AssetFixture()

    def tearDown(self):
        self.fixture.close()

    def test_load_and_parse_run_on_private_worker_cache(self):
        main_thread = threading.get_ident()
        observations = []

        class RecordingCache:
            def __init__(self):
                self.owner = threading.get_ident()
                self.cache = AssetCache()
                observations.append(('cache', self.owner))

            def load(self, path):
                observations.append(('load', threading.get_ident()))
                return self.cache.load(path)

        loader = AssetLoader(cache_factory=RecordingCache)
        try:
            request_id = loader.submit(self.fixture.write_stl())
            result = _wait_for_result(loader)
            self.assertEqual(result[0], request_id)
            self.assertIsNone(result[2])
            self.assertEqual([kind for kind, _ in observations], ['cache', 'load'])
            self.assertTrue(all(thread_id != main_thread for _, thread_id in observations))
            self.assertEqual(observations[0][1], observations[1][1])
        finally:
            loader.close()

    def test_texture_decode_runs_on_worker_thread(self):
        import pygame

        main_thread = threading.get_ident()
        decode_threads = []
        original_load = pygame.image.load

        def recording_load(source):
            decode_threads.append(threading.get_ident())
            return original_load(source)

        loader = AssetLoader()
        try:
            with mock.patch.object(pygame.image, 'load', side_effect=recording_load):
                request_id = loader.submit(self.fixture.write_textured_gltf())
                returned_id, asset, error = _wait_for_result(loader)
            self.assertEqual(returned_id, request_id)
            self.assertIsNone(error)
            self.assertIsNotNone(asset)
            self.assertEqual(len(decode_threads), 1)
            self.assertNotEqual(decode_threads[0], main_thread)
            material = asset.root.children[0].children[0].model.material
            self.assertEqual(material['textures']['baseColor']['_decoded_image'][0:2], (1, 1))
        finally:
            loader.close()

    def test_errors_are_returned_as_result_for_caller(self):
        loader = AssetLoader()
        try:
            request_id = loader.submit('unsupported.extension')
            returned_id, asset, error = _wait_for_result(loader)
            self.assertEqual(returned_id, request_id)
            self.assertIsNone(asset)
            self.assertIsInstance(error, ValueError)
            self.assertIn('Unsupported model format', str(error))
        finally:
            loader.close()

    def test_cancel_suppresses_in_flight_late_result(self):
        started = threading.Event()
        release = threading.Event()

        def blocked_prepare(path, cache):
            started.set()
            release.wait(2.0)
            return path

        loader = AssetLoader(cache_factory=object, prepare_fn=blocked_prepare)
        try:
            request_id = loader.submit('ready')
            self.assertTrue(started.wait(1.0))
            self.assertTrue(loader.cancel(request_id))
            release.set()
            self.assertFalse(loader.cancel(request_id))
            deadline = time.monotonic() + .5
            while time.monotonic() < deadline:
                self.assertIsNone(loader.poll())
                time.sleep(.005)
        finally:
            release.set()
            loader.close()

    def test_close_does_not_wait_for_active_cpu_work_or_deliver_its_result(self):
        started = threading.Event()
        release = threading.Event()

        def blocked_prepare(path, cache):
            started.set()
            release.wait(2.0)
            return path

        loader = AssetLoader(cache_factory=object, prepare_fn=blocked_prepare)
        request_id = loader.submit('ready')
        self.assertTrue(started.wait(1.0))
        before = time.monotonic()
        loader.close()
        elapsed = time.monotonic() - before
        try:
            self.assertLess(elapsed, .1)
            self.assertIsNone(loader.poll())
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                loader.submit('another')
        finally:
            release.set()
        deadline = time.monotonic() + .5
        while time.monotonic() < deadline:
            self.assertIsNone(loader.poll())
            time.sleep(.005)
        self.assertFalse(loader.cancel(request_id))


if __name__ == '__main__':
    unittest.main()
