"""Frame snapshots preserve public mutable scene inputs and command history."""
from itertools import product
import copy
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.commands import PlacementCommands
from mini3d.scene import Entity, Mesh, Scene
from mini3d.scene_snapshot import SceneSnapshot, scene_frame, snapshot


def box(material=None):
    return Entity(Mesh(list(product((-1, 1), repeat=3)), [[0, 1, 2]],
                       material=material))


class SceneSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.entity = self.scene.add(box({
            'baseColorFactor': [1., .7, .5, 1.],
            'textures': {'baseColor': {'image': b'original', 'sampler': {'wrapS': 10497}}},
        }))

    def frame(self):
        with scene_frame(self.scene):
            return snapshot(self.scene)

    def test_nested_consumers_update_and_validate_once(self):
        original_refresh = SceneSnapshot.refresh
        with patch.object(self.scene, 'update', wraps=self.scene.update) as update, \
             patch.object(SceneSnapshot, 'refresh', autospec=True,
                          side_effect=original_refresh) as refresh:
            with scene_frame(self.scene):
                first = snapshot(self.scene)
                with scene_frame(self.scene):
                    self.assertIs(snapshot(self.scene), first)
                self.assertIs(snapshot(self.scene), first)
                self.assertEqual(update.call_count, 1)
                self.assertEqual(refresh.call_count, 1)
            with scene_frame(self.scene):
                self.assertIs(snapshot(self.scene), first)
            self.assertEqual(update.call_count, 2)
            self.assertEqual(refresh.call_count, 2)

    def test_noop_frame_preserves_revision_and_record_identity(self):
        first = self.frame()
        record = first.records[id(self.entity)]
        revisions = (first.revision, first.geometry_revision, first.material_revision)
        second = self.frame()
        self.assertIs(second.records[id(self.entity)], record)
        self.assertEqual((second.revision, second.geometry_revision,
                          second.material_revision), revisions)
        self.assertTrue({'key', 'geometry', 'matrix', 'normal', 'mirrored'} <= set(record))

    def test_render_only_overlay_reuses_city_records_and_tracks_floor_and_base_edits(self):
        floor = box({'extras': {'photographicGround': True}})
        overlay = copy.copy(self.scene)
        overlay.root_entities = self.scene.root_entities + [floor]
        overlay._render_base_scene = self.scene
        overlay._render_extra_entities = [floor]
        floor.update_transform()
        with scene_frame(self.scene):
            city = snapshot(self.scene)
            city_record = city.records[id(self.entity)]
            composed = snapshot(overlay)
            self.assertIs(composed.records[id(self.entity)], city_record)
            old_floor = composed.records[id(floor)]
            old_revision = composed.revision
            floor.pos[0] = 15
            floor.update_transform()
            composed = snapshot(overlay)
            self.assertIs(composed.records[id(self.entity)], city_record)
            self.assertIsNot(composed.records[id(floor)], old_floor)
            self.assertGreater(composed.revision, old_revision)
        self.entity.pos[2] = 9
        with scene_frame(self.scene):
            composed = snapshot(overlay)
            np.testing.assert_array_equal(composed.records[id(self.entity)]['matrix'][:3, 3], [0, 0, 9])
            self.assertIsNot(composed.records[id(self.entity)], city_record)

    def test_direct_numpy_transform_edit_updates_bounds_without_explicit_update(self):
        before = self.frame()
        revision = before.geometry_revision
        record = before.records[id(self.entity)]
        self.entity.pos[:] = [3, 4, 5]
        self.entity.scale[:] = [-2, 3, 4]
        after = self.frame()
        current = after.records[id(self.entity)]
        self.assertGreater(after.geometry_revision, revision)
        self.assertIsNot(current, record)
        np.testing.assert_array_equal(current['matrix'][:3, 3], [3, 4, 5])
        np.testing.assert_allclose(after.bounds[0], [[1, 1, 1], [5, 7, 9]])
        np.testing.assert_allclose(current['normal'], np.diag([-.5, 1 / 3, .25]), atol=1e-7)
        self.assertTrue(current['mirrored'])

    def test_unchanged_entity_record_survives_another_entity_edit(self):
        other = self.scene.add(box())
        first = self.frame()
        retained = first.records[id(self.entity)]
        changed = first.records[id(other)]
        other.pos[0] = 12
        second = self.frame()
        self.assertIs(second.records[id(self.entity)], retained)
        self.assertIsNot(second.records[id(other)], changed)

    def test_parent_transform_and_reparent_update_child_world_geometry(self):
        self.scene.root_entities.remove(self.entity)
        parent = self.scene.add(Entity(name='parent'))
        parent.add_child(self.entity)
        parent.pos[:] = [10, 0, 0]
        self.entity.pos[:] = [2, 0, 0]
        self.frame()
        parent.pos[:] = [20, 0, 0]
        np.testing.assert_array_equal(self.frame().bounds[0], [[21, -1, -1], [23, 1, 1]])
        other = self.scene.add(Entity(name='other parent'))
        other.pos[:] = [-5, 0, 0]
        other.add_child(self.entity)
        np.testing.assert_array_equal(self.frame().bounds[0], [[-4, -1, -1], [-2, 1, 1]])

    def test_root_membership_visibility_and_hidden_parent_are_detected(self):
        first = self.frame()
        revision = first.geometry_revision
        other = self.scene.add(box())
        current = self.frame()
        self.assertEqual(current.entities, [self.entity, other])
        self.assertGreater(current.geometry_revision, revision)
        self.entity.visible = False
        self.assertEqual(self.frame().entities, [other])
        self.entity.visible = True
        self.scene.root_entities.remove(other)
        self.assertEqual(self.frame().entities, [self.entity])
        self.scene.root_entities.remove(self.entity)
        parent = self.scene.add(Entity())
        parent.add_child(self.entity)
        parent.visible = False
        self.assertEqual(self.frame().entities, [])
        parent.visible = True
        self.assertEqual(self.frame().entities, [self.entity])

    def test_mesh_replacement_and_shared_bounds_mutation_refresh_all_instances(self):
        other = self.scene.add(Entity(self.entity.model))
        initial = self.frame()
        initial_record = initial.records[id(self.entity)]
        other_record = initial.records[id(other)]
        self.entity.model.bounds[1][0] = 5
        current = self.frame()
        for entity in (self.entity, other):
            np.testing.assert_array_equal(current.records[id(entity)]['geometry'][3],
                                          [[-1, -1, -1], [5, 1, 1]])
        self.assertIsNot(current.records[id(self.entity)], initial_record)
        self.assertIsNot(current.records[id(other)], other_record)
        self.entity.model = box().model
        current = self.frame()
        np.testing.assert_array_equal(current.bounds[0], [[-1, -1, -1], [1, 1, 1]])
        np.testing.assert_array_equal(current.bounds[1], [[-1, -1, -1], [5, 1, 1]])

    def test_nested_material_edit_advances_material_not_geometry_revision(self):
        current = self.frame()
        geometry_revision = current.geometry_revision
        for mutate in (
                lambda: self.entity.model.material['baseColorFactor'].__setitem__(0, .25),
                lambda: self.entity.model.material['textures']['baseColor']['sampler'].__setitem__('wrapS', 33071),
                lambda: self.entity.model.material['textures']['baseColor'].__setitem__('image', b'replacement'),
                lambda: self.entity.model.material.__setitem__('alphaMode', 'BLEND')):
            with self.subTest(mutation=mutate):
                revision, material_revision = current.revision, current.material_revision
                mutate()
                current = self.frame()
                self.assertGreater(current.revision, revision)
                self.assertGreater(current.material_revision, material_revision)
                self.assertEqual(current.geometry_revision, geometry_revision)

    def test_numpy_material_value_in_place_edit_is_detected(self):
        self.entity.model.material['baseColorFactor'] = np.ones(4, np.float32)
        first = self.frame()
        material_revision = first.material_revision
        self.entity.model.material['baseColorFactor'][2] = .125
        self.assertGreater(self.frame().material_revision, material_revision)

    def test_standalone_snapshot_validates_world_data_without_updating_scene(self):
        self.scene.update()
        first = snapshot(self.scene)
        prior = first.records[id(self.entity)]
        self.entity.world_matrix[0, 3] = 17
        with patch.object(self.scene, 'update', wraps=self.scene.update) as update:
            current = snapshot(self.scene)
            update.assert_not_called()
        self.assertIsNot(current.records[id(self.entity)], prior)
        np.testing.assert_array_equal(current.bounds[0], [[16, -1, -1], [18, 1, 1]])

    def test_standalone_snapshot_after_frame_does_not_reuse_frozen_frame_data(self):
        first = self.frame()
        revision = first.geometry_revision
        self.entity.pos[1] = 8
        self.scene.update()
        current = snapshot(self.scene)
        self.assertGreater(current.geometry_revision, revision)
        np.testing.assert_array_equal(current.bounds[0], [[-1, 7, -1], [1, 9, 1]])

    def test_exception_exit_releases_frame_and_next_frame_reads_changes(self):
        with self.assertRaisesRegex(RuntimeError, 'consumer failed'):
            with scene_frame(self.scene):
                snapshot(self.scene)
                with scene_frame(self.scene):
                    raise RuntimeError('consumer failed')
        self.entity.pos[2] = 9
        with patch.object(self.scene, 'update', wraps=self.scene.update) as update:
            current = self.frame()
            update.assert_called_once_with()
        np.testing.assert_array_equal(current.bounds[0], [[-1, -1, 8], [1, 1, 10]])

    def test_failed_frame_synchronization_does_not_poison_later_frames(self):
        with patch.object(self.scene, 'update', side_effect=RuntimeError('sync failed')):
            with self.assertRaisesRegex(RuntimeError, 'sync failed'):
                with scene_frame(self.scene):
                    self.fail('frame body must not run when synchronization fails')
        self.entity.pos[0] = 6
        np.testing.assert_array_equal(self.frame().bounds[0], [[5, -1, -1], [7, 1, 1]])

    def test_commands_undo_redo_restore_transforms_and_deleted_instances(self):
        commands = PlacementCommands(self.scene, None)
        self.frame()
        commands.set_transform(self.entity, position=[4, 0, 0])
        np.testing.assert_array_equal(self.frame().bounds[0], [[3, -1, -1], [5, 1, 1]])
        self.assertTrue(commands.undo())
        np.testing.assert_array_equal(self.frame().bounds[0], [[-1, -1, -1], [1, 1, 1]])
        self.assertTrue(commands.redo())
        np.testing.assert_array_equal(self.frame().bounds[0], [[3, -1, -1], [5, 1, 1]])
        commands.delete(self.entity)
        self.assertEqual(self.frame().entities, [])
        self.assertTrue(commands.undo())
        self.assertEqual(self.frame().entities, [self.entity])
        np.testing.assert_array_equal(self.frame().bounds[0], [[3, -1, -1], [5, 1, 1]])


if __name__ == '__main__':
    unittest.main()
