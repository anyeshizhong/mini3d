"""Selection, group and multi-transform contracts without an Editor or GL context."""
from types import SimpleNamespace
import unittest

import numpy as np

from mini3d.commands import PlacementCommands
from mini3d.scene import Entity, Mesh, Scene, SceneGroup, rotation_xyz


class PlacementV2CommandsTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.mesh = Mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])
        self.template = Entity(name="Same name")
        self.template.add_child(Entity(self.mesh, "Imported child"))
        cache = SimpleNamespace(load=lambda path: SimpleNamespace(instantiate=self.template.clone))
        self.commands = PlacementCommands(self.scene, cache)
        self.a = self.commands.spawn("fixture.glb", position=[-1, 0, 0])
        self.b = self.commands.spawn("fixture.glb", position=[1, 0, 0])
        self.c = self.commands.spawn("fixture.glb", position=[0, 4, 0])
        self.commands.clear_history()

    @property
    def pair(self):
        return [self.a.entity_id, self.b.entity_id]

    def test_selection_uses_ids_not_names_and_does_not_write_history(self):
        self.commands.set_selection(self.pair, primary_id=self.a.entity_id)
        self.assertEqual(self.commands.selected_entities, [self.a, self.b])
        self.assertIs(self.commands.primary_selection, self.a)
        self.assertEqual(self.commands.undo_count, 0)
        self.commands.set_metadata(self.a, name="Renamed")
        self.assertEqual(self.scene.selected_ids, self.pair)
        self.commands.set_selection([self.b.entity_id, self.b.entity_id])
        self.assertEqual(self.scene.selected_ids, [self.b.entity_id])
        self.commands.set_selection([])
        self.assertIsNone(self.scene.primary_selection)

    def test_invalid_selection_is_atomic(self):
        self.commands.set_selection(self.pair)
        for args in ((["Missing"],), (self.a.entity_id,)):
            with self.assertRaises(ValueError):
                self.commands.set_selection(*args)
        with self.assertRaises(ValueError):
            self.commands.set_selection(self.pair, primary_id=self.c.entity_id)
        self.assertEqual(self.scene.selected_ids, self.pair)

    def test_move_preserves_relative_positions_and_undo_selection(self):
        self.commands.set_selection(self.pair, primary_id=self.a.entity_id)
        self.commands.transform_many(self.pair, translation=[3, 4, 5])
        np.testing.assert_allclose(self.a.pos, [2, 4, 5])
        np.testing.assert_allclose(self.b.pos - self.a.pos, [2, 0, 0])
        self.commands.set_selection([self.c.entity_id])
        self.commands.undo()
        np.testing.assert_allclose(self.a.pos, [-1, 0, 0])
        self.assertEqual(self.scene.selected_ids, self.pair)
        self.assertIs(self.scene.primary_selection, self.a)
        self.commands.redo()
        np.testing.assert_allclose(self.a.pos, [2, 4, 5])
        self.assertEqual(self.scene.selected_ids, self.pair)

    def test_rotation_about_center_also_rotates_individual_orientation(self):
        self.commands.set_transform(self.a, rotation=[.2, -.4, .8])
        old_rotation = rotation_xyz(self.a.rot)
        delta = [0, 0, np.pi / 2]
        self.commands.transform_many(self.pair, rotation=delta)
        np.testing.assert_allclose(self.a.pos, [0, -1, 0], atol=1e-12)
        np.testing.assert_allclose(self.b.pos, [0, 1, 0], atol=1e-12)
        np.testing.assert_allclose(rotation_xyz(self.a.rot), rotation_xyz(delta) @ old_rotation,
                                   atol=1e-12)

    def test_scale_changes_offsets_and_instance_scales(self):
        self.commands.transform_many(self.pair, scale=[2, 3, 4])
        np.testing.assert_allclose(self.a.pos, [-2, 0, 0])
        np.testing.assert_allclose(self.b.pos, [2, 0, 0])
        np.testing.assert_allclose(self.a.scale, [2, 3, 4])
        self.commands.undo()
        np.testing.assert_allclose(self.a.scale, [1, 1, 1])

    def test_locked_member_is_skipped_and_excluded_from_center(self):
        self.commands.set_selection(self.pair)
        self.commands.lock(self.b)
        self.assertEqual(self.scene.editable_selection, [self.a])
        self.commands.transform_many(self.pair, rotation=[0, 0, np.pi])
        np.testing.assert_allclose(self.a.pos, [-1, 0, 0])
        np.testing.assert_allclose(self.b.pos, [1, 0, 0])
        np.testing.assert_allclose(self.b.rot, [0, 0, 0])
        self.commands.transform_many(self.pair, translation=[2, 1, 0])
        np.testing.assert_allclose(self.a.pos, [1, 1, 0])
        np.testing.assert_allclose(self.b.pos, [1, 0, 0])

    def test_drag_initial_states_are_not_accumulated_and_one_undo(self):
        initial = {entity.entity_id: {"position": entity.pos.copy(), "rotation": entity.rot.copy(),
                                     "scale": entity.scale.copy()} for entity in (self.a, self.b)}
        self.commands.begin_transaction("Multi drag")
        for index in range(100):
            self.commands.transform_many(self.pair, translation=[index * .1, 0, 0], initial=initial)
        self.commands.commit_transaction()
        self.assertEqual(self.commands.undo_count, 1)
        np.testing.assert_allclose(self.a.pos, [8.9, 0, 0])
        self.commands.undo()
        np.testing.assert_allclose(self.a.pos, [-1, 0, 0])
        self.commands.redo()
        np.testing.assert_allclose(self.a.pos, [8.9, 0, 0])

    def test_bad_multi_transform_and_cancel_are_atomic(self):
        for args in ({"scale": [1, 0, 1]}, {"rotation": [0, np.nan, 0]},
                     {"initial": {self.a.entity_id: {"position": [9, 0, 0]}}}):
            with self.assertRaises(ValueError):
                self.commands.transform_many(self.pair, **args)
        self.assertEqual(self.commands.undo_count, 0)
        self.commands.begin_transaction("Cancelled group transform")
        self.commands.transform_many(self.pair, scale=[2, 2, 2], rotation=[0, .2, .6])
        self.commands.cancel_transaction()
        np.testing.assert_array_equal(self.a.pos, [-1, 0, 0])
        np.testing.assert_array_equal(self.a.rot, [0, 0, 0])
        np.testing.assert_array_equal(self.a.scale, [1, 1, 1])

    def test_group_and_ungroup_do_not_reparent_and_history_restores_group_identity(self):
        children = list(self.a.children)
        group = self.commands.create_group(self.pair, "Pair")
        group_id = group.group_id
        self.assertEqual(group_id, "grp_000001")
        self.assertEqual(self.scene.selected_group_id, group_id)
        self.assertEqual(self.a.children, children)
        self.assertIs(children[0].parent, self.a)
        self.assertIsNone(self.a.parent)
        self.commands.rename_group(group_id, "Renamed")
        self.assertEqual(group.group_id, group_id)
        self.commands.ungroup(group_id)
        self.assertEqual(self.scene.groups, [])
        self.assertEqual(self.scene.selected_ids, self.pair)
        self.assertEqual(self.scene.root_entities, [self.a, self.b, self.c])
        self.commands.undo()
        self.assertIs(self.scene.find_group_by_id(group_id), group)
        self.assertEqual(self.scene.selected_group_id, group_id)
        self.commands.undo()
        self.assertEqual(group.name, "Pair")
        self.commands.undo()
        self.assertEqual(self.scene.groups, [])
        self.assertEqual(self.scene.selected_ids, [])
        self.commands.redo()
        self.assertIs(self.scene.groups[0], group)
        self.assertIs(self.a.children[0].model, self.mesh)

    def test_group_ids_are_not_reused_after_undo_and_loaded_id_advances_counter(self):
        group = self.commands.create_group(self.pair)
        self.commands.undo()
        other = self.commands.create_group(self.pair)
        self.assertNotEqual(group.group_id, other.group_id)
        self.scene.add_group(SceneGroup("grp_000042", "Loaded", [self.c.entity_id]))
        newest = self.commands.create_group([self.a.entity_id])
        self.assertEqual(newest.group_id, "grp_000043")

    def test_groups_reject_missing_nested_duplicate_and_empty_members(self):
        group = self.commands.create_group(self.pair)
        count = self.commands.undo_count
        for members in ([], ["ent_999999"], [group.group_id], [self.a.entity_id] * 2):
            with self.assertRaises(ValueError):
                self.commands.create_group(members)
        with self.assertRaises(ValueError):
            self.scene.add_group(SceneGroup(group.group_id, "Duplicate ID", [self.c.entity_id]))
        self.assertEqual(self.commands.undo_count, count)
        self.assertEqual(self.scene.groups, [group])

    def test_delete_updates_members_and_selection_and_undo_restores_all(self):
        group = self.commands.create_group(self.pair)
        self.commands.delete(self.a)
        self.assertEqual(group.member_ids, [self.b.entity_id])
        self.assertEqual(self.scene.selected_ids, [self.b.entity_id])
        self.assertEqual(self.scene.selected_group_id, group.group_id)
        self.commands.delete(self.b)
        self.assertEqual(self.scene.groups, [])
        self.assertEqual(self.scene.selected_ids, [])
        self.commands.undo()
        self.commands.undo()
        self.assertIs(self.scene.groups[0], group)
        self.assertEqual(group.member_ids, self.pair)
        self.assertEqual(self.scene.selected_ids, self.pair)

    def test_batch_failure_restores_group_members_and_selection_without_resource_copy(self):
        self.commands.set_selection([self.c.entity_id])
        with self.assertRaises(ValueError):
            with self.commands.transaction("Bad batch"):
                self.commands.create_group(self.pair)
                self.commands.delete(self.a)
                self.commands.transform_many(["missing"], translation=[1, 0, 0])
        self.assertEqual(self.scene.groups, [])
        self.assertEqual(self.scene.selected_ids, [self.c.entity_id])
        self.assertEqual(self.scene.root_entities, [self.a, self.b, self.c])
        self.assertIs(self.a.children[0].model, self.mesh)
        self.assertEqual(self.commands.undo_count, 0)


if __name__ == "__main__":
    unittest.main()
