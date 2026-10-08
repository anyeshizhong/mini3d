"""Rectangular formation identity, resource sharing, atomicity and yaw rules."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from mini3d.commands import PlacementCommands
from mini3d.formation import create_rectangular_formation
from mini3d.scene import Entity, Mesh, Scene


class FormationTests(unittest.TestCase):
    def setUp(self):
        self.scene = Scene()
        self.mesh = Mesh([[0, 0, 0], [1, 0, 0], [0, 1, 2]], [[0, 1, 2]],
                         material={"textures": {"baseColor": {"image": b"image"}}})
        template = Entity(name="Same name")
        template.add_child(Entity(self.mesh, "Imported mesh"))
        self.commands = PlacementCommands(self.scene, SimpleNamespace(
            load=lambda _: SimpleNamespace(instantiate=template.clone)))
        self.source = self.commands.spawn("roman_legionnaire.glb", position=[3, 4, 5],
            rotation=[.1, -.2, np.pi / 2], scale=[2, 3, 4], anchor="pivot")
        self.commands.set_selection([self.source.entity_id], primary_id=self.source.entity_id)
        self.commands.clear_history()

    def formation(self, **kwargs):
        values = dict(source_id=self.source.entity_id, rows=5, columns=8,
                      spacing_x=1.2, spacing_y=1.4)
        values.update(kwargs)
        return create_rectangular_formation(self.commands, **values)

    def test_5_by_8_count_ids_selection_and_local_yaw_spacing(self):
        group = self.formation()
        self.assertEqual(len(self.scene.root_entities), 40)
        self.assertEqual(len(set(group.member_ids)), 40)
        self.assertEqual(group.member_ids[0], self.source.entity_id)
        self.assertEqual(self.scene.selected_ids, group.member_ids)
        self.assertEqual(self.scene.selected_group_id, group.group_id)
        for index, entity_id in enumerate(group.member_ids):
            entity = self.scene.find_by_id(entity_id)
            row, column = divmod(index, 8)
            np.testing.assert_allclose(entity.pos, [3 - row * 1.4, 4 + column * 1.2, 5])
            np.testing.assert_array_equal(entity.rot, self.source.rot)
            np.testing.assert_array_equal(entity.scale, self.source.scale)
            self.assertEqual((entity.placement_type, entity.placement_anchor, entity.keep_upright),
                             ("character", "pivot", True))

    def test_mesh_material_texture_shared_but_transforms_independent(self):
        group = self.formation()
        for entity_id in group.member_ids:
            entity = self.scene.find_by_id(entity_id)
            mesh = entity.children[0].model
            self.assertIs(mesh, self.mesh)
            self.assertIs(mesh.material, self.mesh.material)
            self.assertIs(mesh.material["textures"], self.mesh.material["textures"])
            self.assertIs(entity.children[0].parent, entity)
            if entity is not self.source:
                self.assertFalse(np.shares_memory(entity.pos, self.source.pos))
                self.assertFalse(np.shares_memory(entity.rot, self.source.rot))
                self.assertFalse(np.shares_memory(entity.scale, self.source.scale))

    def test_one_undo_restores_original_and_redo_same_entities_group_ids_selection(self):
        before_position, before_rotation = self.source.pos.copy(), self.source.rot.copy()
        group = self.formation(facing=.3)
        members = list(self.scene.root_entities)
        ids = list(group.member_ids)
        self.assertEqual(self.commands.undo_count, 1)
        self.assertTrue(self.commands.undo())
        self.assertEqual(self.scene.root_entities, [self.source])
        self.assertEqual(self.scene.groups, [])
        self.assertEqual(self.scene.selected_ids, [self.source.entity_id])
        np.testing.assert_array_equal(self.source.pos, before_position)
        np.testing.assert_array_equal(self.source.rot, before_rotation)
        self.assertTrue(self.commands.redo())
        self.assertEqual(self.scene.root_entities, members)
        self.assertEqual(self.scene.groups[0].group_id, group.group_id)
        self.assertEqual(self.scene.groups[0].member_ids, ids)
        self.assertEqual(self.scene.selected_ids, ids)
        np.testing.assert_allclose(self.source.rot, [.1, -.2, .3])

    def test_excluding_source_creates_40_copies_and_preserves_original(self):
        original = self.source.rot.copy()
        group = self.formation(include_source=False, facing=0)
        self.assertEqual(len(self.scene.root_entities), 41)
        self.assertEqual(len(group.member_ids), 40)
        self.assertNotIn(self.source.entity_id, group.member_ids)
        np.testing.assert_array_equal(self.source.rot, original)
        for entity_id in group.member_ids:
            np.testing.assert_allclose(self.scene.find_by_id(entity_id).rot, [.1, -.2, 0])
        self.commands.undo()
        self.assertEqual(self.scene.root_entities, [self.source])

    def test_invalid_arguments_never_mutate_scene_or_history(self):
        for kwargs in (dict(rows=0), dict(columns=-1), dict(rows=2.5), dict(rows=True),
                       dict(columns="8"), dict(spacing_x=0), dict(spacing_y=-2),
                       dict(spacing_x=float("nan")), dict(spacing_y=float("inf")),
                       dict(spacing_x=True), dict(facing=float("nan")), dict(facing=True),
                       dict(include_source=1), dict(source_id="Same name"),
                       dict(spacing_x=1e308)):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.formation(**kwargs)
                self.assertEqual(self.scene.root_entities, [self.source])
                self.assertEqual(self.scene.groups, [])
                self.assertEqual(self.commands.undo_count, 0)

    def test_partial_failure_restores_source_and_selection_atomically(self):
        original = self.commands.duplicate
        calls = []
        def fail_later(*args, **kwargs):
            calls.append(1)
            if len(calls) == 4:
                raise RuntimeError("Simulated clone failure")
            return original(*args, **kwargs)
        with patch.object(self.commands, "duplicate", fail_later):
            with self.assertRaisesRegex(RuntimeError, "clone failure"):
                self.formation(facing=.8)
        self.assertEqual(self.scene.root_entities, [self.source])
        np.testing.assert_allclose(self.source.rot, [.1, -.2, np.pi / 2])
        self.assertEqual(self.scene.groups, [])
        self.assertEqual(self.scene.selected_ids, [self.source.entity_id])
        self.assertEqual(self.commands.undo_count, 0)
        self.assertFalse(self.commands.active_transaction)

    def test_locked_source_is_rejected_for_both_include_modes(self):
        self.commands.lock(self.source)
        for include in (True, False):
            with self.assertRaisesRegex(ValueError, "locked"):
                self.formation(include_source=include)
        self.assertEqual(len(self.scene.root_entities), 1)

    def test_names_unique_without_using_names_as_entity_ids(self):
        first = self.formation(rows=1, columns=2)
        second = self.formation(rows=1, columns=2, include_source=False)
        self.assertEqual(first.name, "Legion_Formation_001")
        self.assertEqual(second.name, "Legion_Formation_002")
        self.assertNotEqual(first.group_id, second.group_id)
        self.assertEqual(len(self.scene.root_entities), 4)

    def test_public_command_wrapper_is_available(self):
        group = self.commands.create_rectangular_formation(self.source.entity_id, 1, 1, 1, 1)
        self.assertEqual(group.member_ids, [self.source.entity_id])
        self.assertEqual(self.commands.undo_count, 1)


if __name__ == "__main__":
    unittest.main()
