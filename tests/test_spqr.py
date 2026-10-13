"""A bounded street uses ordinary editable instances, history and scene v3."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import BATCH_METHODS, dispatch
from mini3d.assets import AssetCache
from mini3d.camera import Camera
from mini3d.placement import geometry_bounds, raycast_surface
from mini3d.roman_assets import ROMAN_ASSETS
from mini3d.scene import rotation_xyz


ASSETS = {'builtin:roman-' + name for name in
          ('road', 'sidewalk', 'shop', 'house', 'column', 'arch', 'amphora')}


def meshes(root):
    result = [] if root.model is None else [root.model]
    for child in root.children:
        result.extend(meshes(child))
    return result


class RomanStreetTests(unittest.TestCase):
    def setUp(self):
        self.api = self.new_api()
        self.app = self.api._app

    def new_api(self):
        api = Mini3DAPI()
        self.addCleanup(api._app.model_dialog.close)
        return api

    def test_builtin_catalog_geometry_and_shared_independent_instances(self):
        self.assertTrue(ASSETS <= {entry['path'] for entry in ROMAN_ASSETS})
        cache = AssetCache()
        unique_triangles = 0
        for path in sorted(ASSETS):
            with self.subTest(path=path):
                asset = cache.load(path)
                self.assertIs(cache.load(path), asset)
                first, second = asset.instantiate(), asset.instantiate()
                self.assertEqual(first.asset_path, path)
                self.assertIsNot(first, second)
                bounds = geometry_bounds(first)
                self.assertIsNotNone(bounds)
                self.assertTrue(np.isfinite(bounds).all())
                self.assertTrue(np.all(bounds[1] > bounds[0]))
                self.assertTrue(meshes(first))
                for a, b in zip(meshes(first), meshes(second)):
                    self.assertIs(a, b)
                    self.assertIs(a.material, b.material)
                    self.assertTrue(np.isfinite(a.vertices).all())
                    self.assertTrue(np.isfinite(a.vertex_normals).all())
                    self.assertGreater(len(a.indices), 0)
                    unique_triangles += len(a.indices)
                first.pos[:] = [2, 3, 4]
                first.rot[:] = [.1, .2, .3]
                first.scale[:] = [2, 2, 2]
                np.testing.assert_array_equal(second.pos, [0, 0, 0])
                np.testing.assert_array_equal(second.rot, [0, 0, 0])
                np.testing.assert_array_equal(second.scale, [1, 1, 1])
        # A geometry budget guards against accidentally bundling heavy scans.
        self.assertLess(unique_triangles, 20000)

    def test_default_street_count_groups_bounds_and_resource_reuse(self):
        result = self.api.create_roman_street()
        json.dumps(result, allow_nan=False)
        self.assertEqual((result['entity_count'], result['length'], result['width']), (49, 24, 6))
        self.assertEqual(len(set(result['member_ids'])), 49)
        self.assertEqual(set(result['groups']), {'roads', 'buildings', 'details'})
        self.assertEqual(len(self.api.list_groups()), 4)
        self.assertEqual(self.api.get_group(result['group_id'])['member_ids'], result['member_ids'])
        self.assertEqual(self.app.scene.selected_group_id, result['group_id'])
        partitions = [set(self.api.get_group(value)['member_ids']) for value in result['groups'].values()]
        self.assertEqual(set.union(*partitions), set(result['member_ids']))
        self.assertEqual(sum(map(len, partitions)), 49)
        roots = self.app.scene.root_entities
        self.assertTrue(all(entity.parent is None for entity in roots))
        counts = Counter(entity.asset_path for entity in roots)
        self.assertEqual(counts['builtin:roman-road'], 6)
        self.assertEqual(counts['builtin:roman-sidewalk'], 12)
        self.assertEqual(counts['builtin:roman-shop'] + counts['builtin:roman-house'], 12)
        self.assertEqual(counts['builtin:roman-column'], 12)
        self.assertEqual(counts['builtin:roman-amphora'], 6)
        self.assertEqual(counts['builtin:roman-arch'], 1)
        roads = [root for root in roots if root.asset_path == 'builtin:roman-road']
        road_bounds = [geometry_bounds(root) for root in roads]
        lo = np.min([bounds[0] for bounds in road_bounds], axis=0)
        hi = np.max([bounds[1] for bounds in road_bounds], axis=0)
        np.testing.assert_allclose((hi - lo)[:2], [6, 24], atol=1e-5)
        for path in counts:
            instances = [root for root in roots if root.asset_path == path]
            for other in instances[1:]:
                self.assertEqual([id(mesh) for mesh in meshes(instances[0])],
                                 [id(mesh) for mesh in meshes(other)])
                self.assertFalse(np.shares_memory(instances[0].pos, other.pos))
        self.assertLess(sum(len(mesh.indices) for root in roots for mesh in meshes(root)), 200000)

    def test_append_one_undo_redo_preserves_existing_scene_and_new_identities(self):
        existing = self.api.spawn('builtin:ground', position=[-20, 0, 0])
        self.api.select_entities([existing['entity_id']])
        before = self.api.get_scene_state()
        result = self.api.create_roman_street()
        after = self.api.get_scene_state()
        roots = list(self.app.scene.root_entities)
        self.assertEqual(after['history']['undo_count'], before['history']['undo_count'] + 1)
        self.api.undo()
        restored = self.api.get_scene_state()
        for key in before.keys() - {'history'}:
            self.assertEqual(restored[key], before[key], key)
        self.api.redo()
        self.assertEqual(self.api.get_scene_state(), after)
        self.assertEqual(self.app.scene.root_entities, roots)
        self.assertEqual(self.api.get_group(result['group_id'])['member_ids'], result['member_ids'])

    def test_origin_yaw_width_and_minimum_maximum_segments(self):
        base = self.api.create_roman_street(segments=2, road_width=4)
        rotated = self.new_api()
        result = rotated.create_roman_street(segments=2, road_width=4, origin=[11, -7, 3], facing=np.pi / 2)
        rotation = rotation_xyz([0, 0, np.pi / 2])
        self.assertEqual((result['entity_count'], result['length'], result['width']), (17, 8, 4))
        for first, second in zip(self.app.scene.root_entities, rotated._app.scene.root_entities):
            self.assertEqual(first.asset_path, second.asset_path)
            np.testing.assert_allclose(second.pos, [11, -7, 3] + rotation @ first.pos, atol=1e-12)
            np.testing.assert_allclose(rotation_xyz(second.rot), rotation @ rotation_xyz(first.rot), atol=1e-12)
            np.testing.assert_array_equal(first.scale, second.scale)
        largest = self.new_api().create_roman_street(segments=12, road_width=10)
        self.assertEqual((largest['entity_count'], largest['length'], largest['width']), (97, 48, 10))
        self.assertEqual(len(base['member_ids']), 17)

    def test_invalid_parameters_have_no_scene_history_or_camera_side_effects(self):
        self.api.spawn('builtin:ground')
        before = self.api.get_scene_state()
        view = self.api.get_view_state()
        bad = [{'segments': value} for value in (1, 13, 2.5, True, '6', None)]
        bad += [{'road_width': value} for value in (3.9, 10.1, True, '6', None, np.nan, np.inf)]
        bad += [{'facing': value} for value in (True, '0', None, np.nan, np.inf)]
        bad += [{'origin': value} for value in ([0, 0], [0, 0, 0, 0], [0, np.nan, 0], [0, 0, np.inf])]
        for params in bad:
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    self.api.create_roman_street(**params)
                self.assertEqual(self.api.get_scene_state(), before)
                self.assertEqual(self.api.get_view_state(), view)

    def test_partial_spawn_failure_rolls_back_and_preserves_redo_history(self):
        original = self.api.spawn('builtin:ground')
        self.api.duplicate(original['entity_id'])
        self.api.undo()
        before = self.api.get_scene_state()
        spawn = self.app.commands.spawn
        calls = []

        def fail_later(*args, **kwargs):
            calls.append(1)
            if len(calls) == 5:
                raise RuntimeError('Simulated street allocation failure')
            return spawn(*args, **kwargs)

        with patch.object(self.app.commands, 'spawn', fail_later):
            with self.assertRaisesRegex(RuntimeError, 'allocation failure'):
                self.api.create_roman_street()
        self.assertEqual(len(calls), 5)
        self.assertEqual(self.api.get_scene_state(), before)
        self.assertFalse(self.app.commands.active_transaction)
        self.api.redo()
        self.assertEqual(len(self.api.list_entities()), 2)

    def test_dispatch_exposes_operation_but_rejects_nested_batch_atomically(self):
        self.assertNotIn('create_roman_street', BATCH_METHODS)
        before = self.api.get_scene_state()
        result = dispatch(self.api, dict(command='transaction', args=dict(commands=[
            dict(command='spawn', args=dict(asset_path='builtin:ground')),
            dict(command='create_roman_street', args=dict(segments=2))])))
        self.assertFalse(result['ok'])
        self.assertEqual(self.api.get_scene_state(), before)
        with self.api.transaction():
            inside = self.api.get_scene_state()
            self.assertFalse(dispatch(self.api, dict(command='create_roman_street'))['ok'])
            self.assertEqual(self.api.get_scene_state(), inside)
        result = dispatch(self.api, dict(command='create_roman_street', args=dict(segments=2)))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['entity_count'], 17)

    def test_api_preserves_visible_camera_workspace_and_photography_settings(self):
        self.api.create_shot_camera(position=[7, -12, 3], target=[0, 0, 1], focal_mm=35,
                                    aspect='3:2', dof_enabled=True, f_number=4)
        self.api.set_photo_color(7200, 'Warm')
        self.api.set_antialiasing(4)
        self.api.set_view('Camera')
        before = deepcopy(self.api.get_view_state())
        self.api.create_roman_street()
        after = self.api.get_view_state()
        for key in before.keys() - {'selected_ids'}:
            self.assertEqual(after[key], before[key], key)

    def test_locked_road_geometry_is_real_placement_surface(self):
        self.api.create_roman_street(segments=2, origin=[0, 0, 2])
        road = next(root for root in self.app.scene.root_entities if root.asset_path == 'builtin:roman-road')
        self.api.lock(road.entity_id)
        camera = Camera(position=road.pos + [0, 0, 8], near=.01, far=100)
        camera.look_at(road.pos)
        hit = raycast_surface(self.app.scene, camera, (400, 300), (0, 0, 800, 600))
        self.assertIsNotNone(hit)
        self.assertIs(hit.entity, road)
        self.assertAlmostEqual(hit.position[2], 2, places=5)
        self.assertGreater(hit.normal[2], .9)
        urn = self.api.spawn('builtin:roman-amphora')
        self.app.commands.place_on_surface(urn['entity_id'], hit)
        self.assertAlmostEqual(geometry_bounds(self.api._entity(urn['entity_id']))[0][2], hit.position[2], places=5)
        with self.assertRaises(ValueError):
            self.api.delete(road.entity_id)

    def test_edit_duplicate_group_transform_delete_and_undo_use_normal_commands(self):
        result = self.api.create_roman_street(segments=2)
        building_ids = self.api.get_group(result['groups']['buildings'])['member_ids']
        before = [self.api.get_entity(entity_id) for entity_id in building_ids]
        self.api.transform_many(building_ids, translation=[2, -1, .5])
        for original, entity_id in zip(before, building_ids):
            np.testing.assert_allclose(self.api.get_entity(entity_id)['position'],
                                       np.asarray(original['position']) + [2, -1, .5])
        self.api.undo()
        self.assertEqual([self.api.get_entity(entity_id) for entity_id in building_ids], before)
        source = building_ids[0]
        duplicate = self.api.duplicate(source)
        self.api.set_transform(duplicate['entity_id'], rotation=[0, 0, .7], scale=[1.2, 1.2, 1.2])
        self.assertEqual(self.api.get_entity(source), before[0])
        self.api.delete(source)
        self.assertNotIn(source, self.api.get_group(result['group_id'])['member_ids'])
        self.assertNotIn(source, self.api.get_group(result['groups']['buildings'])['member_ids'])
        self.api.undo()
        self.assertIn(source, self.api.get_group(result['groups']['buildings'])['member_ids'])

    def test_save_load_fresh_cache_v3_preserves_ids_groups_geometry_and_shot(self):
        self.api.create_roman_street(segments=2, origin=[4, -5, .3], facing=.7)
        self.api.create_shot_camera(position=[15, -20, 8], target=[4, -5, 2], focal_mm=35,
                                    aspect='16:9', f_number=5.6, dof_enabled=True)
        self.api.set_photo_color(7100, 'Low saturation')
        self.api.set_antialiasing(4)
        before = self.api.get_scene_state(include_bounds=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'street.json'
            self.api.save_scene(path)
            document = json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(document['version'], 3)
            fresh = self.new_api()
            fresh.load_scene(path)
            after = fresh.get_scene_state(include_bounds=True)
            for key in before.keys() - {'history'}:
                self.assertEqual(after[key], before[key], key)
            self.assertEqual(after['history'], dict(undo_count=0, redo_count=0, active_transaction=False))
            # Different caches rebuild the procedural templates without files.
            self.assertIsNot(meshes(self.app.scene.root_entities[0])[0],
                             meshes(fresh._app.scene.root_entities[0])[0])
            for a, b in zip(self.app.scene.root_entities, fresh._app.scene.root_entities):
                np.testing.assert_allclose(geometry_bounds(a), geometry_bounds(b), atol=1e-6)


if __name__ == '__main__':
    unittest.main()
