"""Placement API history is atomic and never copies shared rendering resources."""
from types import SimpleNamespace
import unittest

import numpy as np

from mini3d.commands import PlacementCommands
from mini3d.scene import Entity, Mesh, Scene


class CommandsTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.template = Entity(name="Template")
        self.mesh = Mesh([[-1, -1, 0], [1, -1, 0], [0, 1, 2]], [[0, 1, 2]],
                         material={"textures": {"baseColor": {"image": b"shared"}}})
        self.template.add_child(Entity(self.mesh))
        self.template.asset_path = "model.glb"
        self.cache = SimpleNamespace(load=lambda path: SimpleNamespace(instantiate=self.template.clone))
        self.commands = PlacementCommands(self.scene, self.cache)

    def spawn(self, **kwargs):
        return self.commands.spawn("model.glb", **kwargs)

    def test_known_roman_default_is_shared_by_non_ui_clients(self):
        roman = self.commands.spawn("model/05_roman_soldier/roman_legionnaire.glb")
        self.assertEqual(roman.placement_type, "character")
        self.assertTrue(roman.keep_upright)
        prop = self.commands.spawn("roman_legionnaire.glb", placement_type="prop")
        self.assertFalse(prop.keep_upright)

    def test_ids_survive_rename_undo_redo_and_are_not_reused(self):
        first = self.spawn()
        self.assertEqual(first.entity_id, "ent_000001")
        self.commands.set_metadata(first.entity_id, name="Renamed")
        self.assertIs(self.scene.find_by_id("ent_000001"), first)
        self.commands.undo()
        self.assertEqual(first.name, "Template")
        self.commands.undo()
        self.assertIsNone(self.scene.find_by_id(first.entity_id))
        self.commands.redo()
        self.assertIs(self.scene.find_by_id(first.entity_id), first)
        self.commands.undo()
        second = self.spawn()
        self.assertEqual(second.entity_id, "ent_000002")
        self.assertFalse(self.commands.redo())

    def test_scene_loaded_ids_advance_counter_and_duplicates_are_rejected(self):
        loaded = self.template.clone()
        loaded.entity_id = "ent_000042"
        self.scene.add(loaded)
        self.assertEqual(self.spawn().entity_id, "ent_000043")
        collision = self.template.clone()
        collision.entity_id = loaded.entity_id
        with self.assertRaises(ValueError):
            self.scene.add(collision)
        with self.assertRaises(ValueError):
            self.scene.add(loaded)
        self.assertEqual(len(self.scene.root_entities), 2)

    def test_duplicate_shares_mesh_texture_and_has_independent_transform_and_id(self):
        first = self.spawn(position=[1, 2, 3], rotation=[.1, .2, .3], scale=[2, 3, 4],
                           placement_type="character")
        self.commands.lock(first)
        duplicate = self.commands.duplicate(first)
        self.assertNotEqual(duplicate.entity_id, first.entity_id)
        self.assertIs(duplicate.children[0].model, self.mesh)
        self.assertIs(duplicate.children[0].model.material, first.children[0].model.material)
        self.assertFalse(duplicate.locked)
        self.assertTrue(duplicate.keep_upright)
        self.assertEqual(duplicate.placement_type, "character")
        self.commands.set_transform(duplicate, position=[9, 8, 7])
        np.testing.assert_array_equal(first.pos, [1, 2, 3])
        self.commands.undo()
        np.testing.assert_array_equal(duplicate.pos, first.pos)
        self.commands.undo()
        self.assertEqual(self.scene.root_entities, [first])
        self.commands.redo()
        self.assertIs(self.scene.root_entities[1], duplicate)

    def test_lock_rejects_edits_without_polluting_history_and_can_be_undone(self):
        entity = self.spawn()
        self.commands.lock(entity.entity_id)
        count = self.commands.undo_count
        for operation in (lambda: self.commands.set_transform(entity, position=[1, 2, 3]),
                          lambda: self.commands.delete(entity)):
            with self.assertRaisesRegex(ValueError, "locked"):
                operation()
        self.assertEqual(self.commands.undo_count, count)
        self.commands.undo()
        self.assertFalse(entity.locked)
        self.commands.redo()
        self.assertTrue(entity.locked)
        self.commands.unlock(entity)
        self.assertFalse(entity.locked)
        self.commands.undo()
        self.assertTrue(entity.locked)

    def test_delete_undo_restores_identity_order_and_metadata(self):
        first, second, third = self.spawn(), self.spawn(), self.spawn()
        self.commands.set_metadata(second, visible=False, placement_anchor="pivot")
        self.commands.delete(second)
        self.assertEqual(self.scene.root_entities, [first, third])
        self.commands.undo()
        self.assertEqual(self.scene.root_entities, [first, second, third])
        self.assertFalse(second.visible)
        self.assertEqual(second.placement_anchor, "pivot")
        self.commands.redo()
        self.assertEqual(self.scene.root_entities, [first, third])

    def test_gesture_is_one_transaction_and_cancel_restores_transform(self):
        entity = self.spawn()
        self.commands.begin_transaction("Move drag")
        self.assertTrue(self.commands.active_transaction)
        for index in range(50):
            self.commands.set_transform(entity, position=[index, 0, 0])
        self.commands.commit_transaction()
        self.assertEqual(self.commands.undo_count, 2)
        self.commands.undo()
        np.testing.assert_array_equal(entity.pos, [0, 0, 0])
        self.commands.redo()
        np.testing.assert_array_equal(entity.pos, [49, 0, 0])
        self.commands.begin_transaction("Cancelled drag")
        self.commands.set_transform(entity, rotation=[1, 2, 3])
        self.commands.cancel_transaction()
        np.testing.assert_array_equal(entity.rot, [0, 0, 0])
        self.assertEqual(self.commands.undo_count, 2)

    def test_batch_transaction_rolls_back_on_error_and_does_not_reuse_ids(self):
        with self.assertRaises(ValueError):
            with self.commands.transaction("Batch"):
                first = self.spawn()
                self.spawn()
                self.commands.set_transform(first, scale=[0, 1, 1])
        self.assertEqual(self.scene.root_entities, [])
        self.assertEqual(self.commands.undo_count, 0)
        self.assertFalse(self.commands.active_transaction)
        with self.commands.transaction("Two props"):
            third, fourth = self.spawn(), self.spawn()
        self.assertEqual(third.entity_id, "ent_000003")
        self.assertEqual(self.commands.undo_count, 1)
        self.commands.undo()
        self.assertEqual(self.scene.root_entities, [])
        self.commands.redo()
        self.assertEqual(self.scene.root_entities, [third, fourth])

    def test_noop_transaction_and_failed_command_preserve_redo(self):
        entity = self.spawn()
        self.commands.set_transform(entity, position=[1, 2, 3])
        self.commands.undo()
        with self.commands.transaction("No-op"):
            self.commands.set_transform(entity, position=[0, 0, 0])
        with self.assertRaises(ValueError):
            self.commands.set_transform(entity, position=[8, 9, 0], scale=[1, float("nan"), 2])
        with self.assertRaises(ValueError):
            self.commands.set_metadata(entity, name="Bad", placement_anchor="")
        self.assertEqual(entity.name, "Template")
        np.testing.assert_array_equal(entity.pos, [0, 0, 0])
        self.assertEqual(self.commands.undo_count, 1)
        self.assertEqual(self.commands.redo_count, 1)
        self.commands.redo()
        np.testing.assert_array_equal(entity.pos, [1, 2, 3])

    def test_transaction_api_rejects_nested_transactions_and_history_navigation(self):
        self.commands.begin_transaction("Drag")
        for action in (self.commands.begin_transaction, self.commands.undo, self.commands.redo,
                       self.commands.clear_history):
            with self.assertRaises(RuntimeError):
                action()
        self.commands.cancel_transaction()
        for action in (self.commands.commit_transaction, self.commands.cancel_transaction):
            with self.assertRaises(RuntimeError):
                action()

    def test_invalid_spawn_is_atomic_and_ground_is_outside_instance_history(self):
        ground = Entity(self.mesh, "Ground")
        self.scene.ground = ground
        with self.assertRaises(ValueError):
            self.spawn(placement_type="invalid")
        with self.assertRaises(ValueError):
            self.spawn(scale=[1, 0, 1])
        self.assertEqual(self.scene.root_entities, [])
        self.assertEqual(self.commands.undo_count, 0)
        self.scene.update()
        self.assertEqual(self.scene.get_flat_render_list(), [])  # Legacy helper is ignored.
        entity = self.spawn()
        self.commands.undo()
        self.assertIs(self.scene.ground, ground)
        self.assertIsNone(self.scene.find_by_id(entity.entity_id))
        with self.assertRaises(ValueError):
            self.commands.delete(ground)

    def test_clone_copies_metadata_without_id_even_when_source_was_in_scene(self):
        entity = self.spawn(placement_type="character", anchor="pivot")
        self.commands.lock(entity)
        clone = entity.clone()
        self.assertIsNone(clone.entity_id)
        self.assertTrue(clone.locked)
        self.assertTrue(clone.keep_upright)
        self.assertEqual(clone.placement_anchor, "pivot")
        self.assertIs(clone.children[0].model, self.mesh)

    def test_surface_placement_undo_redo_restores_position_and_upright_rotation(self):
        from mini3d.placement import SurfaceHit, geometry_bounds
        entity = self.spawn(position=[8, 9, 10], rotation=[.4, -.3, .7],
                            placement_type="character")
        original_pos, original_rot = entity.pos.copy(), entity.rot.copy()
        vertices = self.mesh.vertices.copy()
        hit = SurfaceHit([3, 4, 5], [.2, 0, 1])
        self.commands.place_on_surface(entity.entity_id, hit)
        low, high = geometry_bounds(entity)
        np.testing.assert_allclose([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]],
                                   hit.position)
        np.testing.assert_allclose(entity.rot, [0, 0, .7])
        np.testing.assert_array_equal(self.mesh.vertices, vertices)
        placed_pos = entity.pos.copy()
        self.commands.undo()
        np.testing.assert_array_equal(entity.pos, original_pos)
        np.testing.assert_array_equal(entity.rot, original_rot)
        self.commands.redo()
        np.testing.assert_array_equal(entity.pos, placed_pos)
        np.testing.assert_allclose(entity.rot, [0, 0, .7])
        self.commands.lock(entity)
        with self.assertRaisesRegex(ValueError, "locked"):
            self.commands.place_on_surface(entity, hit)


if __name__ == "__main__":
    unittest.main()
