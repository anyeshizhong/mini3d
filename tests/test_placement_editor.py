"""Placement editor integration and atomic persistence, without an OpenGL window."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
import pygame
from stl import mesh, Mode

from mini3d.editor import Editor, PROJECT
from mini3d.picking import pick_entity
from mini3d.placement import geometry_bounds, raycast_surface


class PlacementEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "scene.json"
        source = mesh.Mesh.from_file(str(PROJECT / "model/06_stl_cube/cube.STL"), mode=Mode.BINARY)
        low, high = source.vectors.min(axis=(0, 1)), source.vectors.max(axis=(0, 1))
        source.vectors[:] = (source.vectors - (low + high) / 2) / (high - low)
        self.asset = self.directory / "unit_cube.stl"
        source.save(str(self.asset), mode=Mode.BINARY)
        self.app = Editor(800, 600)
        self.index = len(self.app.assets)
        self.app.assets.append(dict(name="Unit cube", path=str(self.asset)))
        self.app.viewport_rect = (100, 50, 800, 600)
        self.center = (500, 350)
        self.ui = SimpleNamespace(modal_open=False, viewport_hovered=True, asset_dragging=False,
                                  keyboard_captured=False, mouse_captured=False)

    def tearDown(self):
        self.temporary.cleanup()

    def add(self, position=(0, 0, 0)):
        return self.app.add_asset(self.index, position=position)

    def read_document(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write_document(self, document):
        self.path.write_text(json.dumps(document), encoding="utf-8")

    def assert_valid_selection(self):
        self.assertTrue(self.app.selection is None or self.app.selection in self.app.scene.root_entities)
        self.assertIs(self.app.viewer.selected_entity, self.app.selection)

    def test_default_spawn_anchors_bottom_but_explicit_position_preserves_pivot(self):
        ground_placed = self.app.add_asset(self.index)
        self.assertAlmostEqual(geometry_bounds(ground_placed)[0][2], 0)
        positioned = self.add([2, 3, 4])
        np.testing.assert_allclose(positioned.pos, [2, 3, 4])
        self.assertEqual(self.app.commands.undo_count, 2)
        self.assertNotIn(self.app.scene.ground, self.app.scene.root_entities)

    def test_save_load_preserves_ids_transforms_and_placement_metadata(self):
        first = self.add([1, 2, 3])
        self.app.commands.set_transform(first, rotation=[.1, -.2, .3], scale=[2, 3, 4])
        self.app.commands.set_metadata(first, name="Renamed character", placement_type="character",
                                       placement_anchor="pivot", keep_upright=True)
        self.app.lock_selected()
        second = self.app.duplicate_selected()
        self.app.commands.set_metadata(second, visible=False, placement_type="prop",
                                       placement_anchor="bounds_bottom", keep_upright=False)
        self.app.save_scene(self.path)
        document = self.read_document()
        self.assertEqual(document["version"], 3)
        self.assertEqual(len(document["objects"]), 2)
        first_id, second_id = first.entity_id, second.entity_id
        self.app.load_scene(self.path)
        restored, duplicate = self.app.scene.root_entities
        self.assertEqual((restored.entity_id, duplicate.entity_id), (first_id, second_id))
        self.assertEqual(restored.name, "Renamed character")
        self.assertTrue(restored.locked)
        self.assertEqual(restored.placement_type, "character")
        self.assertEqual(restored.placement_anchor, "pivot")
        self.assertTrue(restored.keep_upright)
        np.testing.assert_array_equal(restored.pos, first.pos)
        np.testing.assert_array_equal(restored.rot, first.rot)
        np.testing.assert_array_equal(restored.scale, first.scale)
        self.assertFalse(duplicate.locked)
        self.assertFalse(duplicate.visible)
        self.assertFalse(duplicate.keep_upright)
        self.assertEqual(duplicate.placement_type, "prop")
        self.assertEqual(duplicate.placement_anchor, "bounds_bottom")
        self.assertIs(self.app.scene.find_by_id(first_id), restored)
        self.assertEqual(self.app.commands.undo_count, 0)
        self.assertEqual(self.app.commands.redo_count, 0)
        self.assert_valid_selection()

    def test_v1_scene_load_assigns_unique_ids_and_defaults(self):
        self.add()
        self.add([3, 0, 0])
        self.app.save_scene(self.path)
        document = self.read_document()
        document["version"] = 1
        for record in document["objects"]:
            for key in ("entity_id", "locked", "placement_type", "placement_anchor", "keep_upright"):
                record.pop(key, None)
        self.write_document(document)
        self.app.load_scene(self.path)
        first, second = self.app.scene.root_entities
        self.assertTrue(first.entity_id.startswith("ent_"))
        self.assertNotEqual(first.entity_id, second.entity_id)
        self.assertFalse(first.locked)
        self.assertEqual(first.placement_type, "prop")
        self.assertEqual(first.placement_anchor, "bounds_bottom")
        self.assert_valid_selection()

    def test_duplicate_id_load_is_atomic_including_selection_and_history(self):
        first, second = self.add(), self.add([3, 0, 0])
        self.app.save_scene(self.path)
        document = self.read_document()
        document["objects"][1]["entity_id"] = document["objects"][0]["entity_id"]
        self.write_document(document)
        before = self.app.commands.undo_count
        with self.assertRaises(ValueError):
            self.app.load_scene(self.path)
        self.assertEqual(self.app.scene.root_entities, [first, second])
        self.assertIs(self.app.selection, second)
        self.assertEqual(self.app.commands.undo_count, before)
        self.assert_valid_selection()

    def test_invalid_placement_metadata_load_is_atomic(self):
        original = self.add()
        self.app.save_scene(self.path)
        document = self.read_document()
        for key, value in (("locked", "false"), ("placement_type", "rigidbody"),
                           ("placement_anchor", "vertex"), ("keep_upright", "true")):
            bad = json.loads(json.dumps(document))
            bad["objects"][0][key] = value
            self.write_document(bad)
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.app.load_scene(self.path)
            self.assertEqual(self.app.scene.root_entities, [original])
            self.assertIs(self.app.selection, original)

    def test_ids_are_not_reused_after_undo_or_loading_an_older_scene(self):
        first = self.add()
        self.app.save_scene(self.path)
        second = self.add()
        self.app.undo()
        third = self.add()
        self.assertGreater(int(third.entity_id[4:]), int(second.entity_id[4:]))
        self.app.load_scene(self.path)
        fourth = self.add()
        self.assertGreater(int(fourth.entity_id[4:]), int(third.entity_id[4:]))
        self.assertIsNotNone(self.app.scene.find_by_id(first.entity_id))

    def test_undo_redo_and_delete_never_leave_selection_on_removed_instances(self):
        original = self.add()
        duplicate = self.app.duplicate_selected()
        self.app.undo()
        self.assertNotIn(duplicate, self.app.scene.root_entities)
        self.assert_valid_selection()
        self.app.redo()
        self.assertIn(duplicate, self.app.scene.root_entities)
        self.assert_valid_selection()
        self.app.select(original)
        self.app.delete_selected()
        self.assert_valid_selection()
        self.app.undo()
        self.assertIn(original, self.app.scene.root_entities)
        self.assert_valid_selection()
        self.app.redo()
        self.assertNotIn(original, self.app.scene.root_entities)
        self.assert_valid_selection()

    def test_saved_counter_prevents_deleted_id_reuse_in_new_editor(self):
        self.add()
        deleted = self.add()
        self.app.delete_selected()
        self.app.save_scene(self.path)
        restored = Editor()
        restored.load_scene(self.path)
        added = restored.commands.spawn(self.asset)
        self.assertGreater(int(added.entity_id[4:]), int(deleted.entity_id[4:]))

    def test_undo_redo_shortcuts_obey_keyboard_capture(self):
        original = self.add()
        def key(code, mod):
            self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code, mod=mod), self.ui)
        self.ui.keyboard_captured = True
        key(pygame.K_z, pygame.KMOD_CTRL)
        self.assertEqual(self.app.scene.root_entities, [original])
        self.ui.keyboard_captured = False
        key(pygame.K_z, pygame.KMOD_CTRL)
        self.assertEqual(self.app.scene.root_entities, [])
        key(pygame.K_y, pygame.KMOD_CTRL)
        self.assertEqual(self.app.scene.root_entities, [original])
        key(pygame.K_z, pygame.KMOD_CTRL)
        key(pygame.K_z, pygame.KMOD_CTRL | pygame.KMOD_SHIFT)
        self.assertEqual(self.app.scene.root_entities, [original])
        self.assert_valid_selection()

    def test_locked_model_remains_surface_and_drop_is_one_undo(self):
        table = self.add([0, 0, .5])
        self.app.commands.set_transform(table, scale=[4, 4, 1])
        self.app.lock_selected()
        self.app.viewer.camera.position = [0, -5, 10]
        self.app.viewer.camera.look_at([0, 0, 1])
        selected, _ = pick_entity(self.app.scene, self.app.viewer.camera, self.center, self.app.viewport_rect)
        self.assertIsNone(selected)
        hit = raycast_surface(self.app.scene, self.app.viewer.camera, self.center, self.app.viewport_rect)
        self.assertIs(hit.entity, table)
        self.assertAlmostEqual(hit.position[2], 1)
        count = self.app.commands.undo_count
        placed = self.app.drop_asset(self.index, self.center)
        self.assertAlmostEqual(geometry_bounds(placed)[0][2], 1)
        self.assertEqual(self.app.commands.undo_count, count + 1)
        self.app.undo()
        self.assertEqual(self.app.scene.root_entities, [table])
        self.app.redo()
        self.assertIn(placed, self.app.scene.root_entities)
        self.assertAlmostEqual(geometry_bounds(placed)[0][2], 1)

    def test_surface_placement_click_respects_ui_capture_and_is_one_undo(self):
        table = self.add([0, 0, .5])
        self.app.commands.set_transform(table, scale=[4, 4, 1])
        character = self.add([10, 10, 10])
        self.app.commands.set_metadata(character, placement_type="character")
        self.app.commands.set_transform(character, rotation=[.2, .3, .4])
        before_pos, before_rot = character.pos.copy(), character.rot.copy()
        self.app.viewer.camera.position = [0, -5, 10]
        self.app.viewer.camera.look_at([0, 0, 1])
        count = self.app.commands.undo_count
        self.app.begin_surface_placement()
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=self.center)
        self.ui.mouse_captured = True
        self.app.handle_event(event, self.ui)
        np.testing.assert_array_equal(character.pos, before_pos)
        self.assertEqual(self.app.commands.undo_count, count)
        self.ui.mouse_captured = False
        self.app.handle_event(event, self.ui)
        self.assertAlmostEqual(geometry_bounds(character)[0][2], 1)
        np.testing.assert_allclose(character.rot, [0, 0, .4])
        self.assertEqual(self.app.commands.undo_count, count + 1)
        self.assertEqual(len(self.app.scene.root_entities), 2)
        self.app.undo()
        np.testing.assert_array_equal(character.pos, before_pos)
        np.testing.assert_array_equal(character.rot, before_rot)

    def test_surface_placement_escape_cancels_and_locked_instance_is_rejected(self):
        entity = self.add()
        count = self.app.commands.undo_count
        self.app.begin_surface_placement()
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0), self.ui)
        self.assertFalse(self.app.place_selected_mode)
        self.assertEqual(self.app.commands.undo_count, count)
        self.app.lock_selected()
        with self.assertRaises(ValueError):
            self.app.begin_surface_placement()
        np.testing.assert_array_equal(entity.pos, [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
