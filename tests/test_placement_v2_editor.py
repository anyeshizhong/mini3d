"""Placement V2 editor input and scene-format integration, without a GL window."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pygame

from mini3d.editor import Editor, PROJECT
from mini3d.viewer import world_bounds


class PlacementV2EditorTests(unittest.TestCase):
    def setUp(self):
        self.app = Editor(800, 600)
        self.app.viewport_rect = (100, 50, 800, 600)
        self.center = (500, 350)
        self.ui = SimpleNamespace(modal_open=False, viewport_hovered=True,
                                  asset_dragging=False, keyboard_captured=False,
                                  mouse_captured=False)
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "scene.json"
        from stl import mesh, Mode
        source = mesh.Mesh.from_file(str(PROJECT / "model/06_stl_cube/cube.STL"), mode=Mode.BINARY)
        low, high = source.vectors.min(axis=(0, 1)), source.vectors.max(axis=(0, 1))
        source.vectors[:] = (source.vectors - (low + high) / 2) / (high - low)
        fixture = Path(self.temporary.name) / "unit_cube.stl"
        source.save(str(fixture), mode=Mode.BINARY)
        self.box_index = len(self.app.assets)
        self.app.assets.append(dict(name="Unit cube", path=str(fixture)))

    def tearDown(self):
        self.app.model_dialog.close()
        self.temporary.cleanup()

    def add_box(self, position=(0, 0, 0)):
        return self.app.add_asset(self.box_index, position)

    def click(self, shift=False):
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
            pos=self.center, button=1, mod=pygame.KMOD_SHIFT if shift else 0), self.ui)

    def test_shift_viewport_toggle_precedes_gizmo_and_blank_clears_selection(self):
        first, second = self.add_box((-2, 0, 0)), self.add_box((2, 0, 0))
        self.app.select(first)
        self.app.tool = "move"
        with patch("mini3d.editor.pick_entity", return_value=(second, np.zeros(3))), \
                patch.object(self.app.gizmo, "begin", return_value=True) as begin:
            self.click(shift=True)
            begin.assert_not_called()
            self.assertEqual(set(self.app.scene.selected_ids), {first.entity_id, second.entity_id})
            self.assertIs(self.app.primary_selection, second)
            self.click(shift=True)
            self.assertEqual(self.app.scene.selected_ids, [first.entity_id])
        self.app.tool = "select"
        with patch("mini3d.editor.pick_entity", return_value=(None, None)):
            self.click()
        self.assertEqual(self.app.selected_entities, [])
        self.assertIsNone(self.app.selection)

    def test_outliner_toggle_keeps_locked_managed_but_not_editable(self):
        first, second = self.add_box(), self.add_box((3, 0, 0))
        self.app.commands.lock(second)
        self.app.select(first)
        self.app.select(second, toggle=True)
        self.assertEqual(self.app.selected_entities, [first, second])
        self.assertEqual(self.app.editable_selection, [first])
        self.assertIs(self.app.primary_selection, second)
        self.app.select(second, toggle=True)
        self.assertEqual(self.app.selected_entities, [first])
        self.assertIs(self.app.primary_selection, first)

    def test_group_selection_focuses_members_and_ungroup_preserves_entities(self):
        first, second = self.add_box((-3, 1, 0)), self.add_box((3, 1, 0))
        self.app.select(first)
        self.app.select(second, toggle=True)
        group = self.app.group_selected()
        self.assertEqual(group.member_ids, [first.entity_id, second.entity_id])
        self.assertEqual(self.app.scene.selected_group_id, group.group_id)
        self.app.select(None)
        self.app.select_group(group.group_id)
        self.app.focus_selected()
        self.app.scene.update()
        low, high = world_bounds([first, second])
        np.testing.assert_allclose(self.app.viewer.controller.target, (low + high) / 2)
        self.app.ungroup_selected()
        self.assertEqual(self.app.scene.groups, [])
        self.assertEqual(self.app.scene.root_entities, [first, second])
        self.app.undo()
        self.assertEqual(self.app.scene.selected_group_id, group.group_id)
        self.assertEqual(self.app.scene.selected_ids, group.member_ids)
        self.app.redo()
        self.assertEqual(self.app.scene.groups, [])

    def test_scene_v3_roundtrip_keeps_groups_selection_metadata_and_shared_mesh(self):
        first, second = self.add_box((-2, 0, .5)), self.add_box((2, 0, .5))
        self.app.commands.set_metadata(first, name="Same", placement_type="character", keep_upright=True)
        self.app.commands.set_metadata(second, name="Same", placement_anchor="pivot")
        self.app.commands.set_transform(first, rotation=[.1, .2, .3], scale=[1, 2, 3])
        self.app.commands.lock(second)
        self.app.select(first)
        self.app.select(second, toggle=True)
        group = self.app.group_selected()
        self.app.save_scene(self.path)
        document = json.loads(self.path.read_text(encoding="utf8"))
        self.assertEqual(document["version"], 3)
        self.assertEqual(document["groups"][0]["member_ids"], group.member_ids)
        loaded = Editor(800, 600)
        loaded.load_scene(self.path)
        restored = loaded.scene.find_group_by_id(group.group_id)
        self.assertEqual(restored.member_ids, group.member_ids)
        self.assertEqual(restored.name, group.name)
        self.assertEqual(loaded.scene.selected_ids, self.app.scene.selected_ids)
        self.assertEqual(loaded.scene.primary_selection_id, self.app.scene.primary_selection_id)
        self.assertEqual(loaded.scene.selected_group_id, group.group_id)
        a, b = loaded.scene.root_entities
        self.assertEqual(a.entity_id, first.entity_id)
        self.assertTrue(a.keep_upright)
        self.assertTrue(b.locked)
        self.assertEqual(b.placement_anchor, "pivot")
        np.testing.assert_array_equal(a.pos, first.pos)
        np.testing.assert_array_equal(a.rot, first.rot)
        np.testing.assert_array_equal(a.scale, first.scale)
        self.assertIs(a.model, b.model)
        self.assertEqual(loaded.commands.undo_count, 0)

    def test_legacy_v1_v2_documents_without_groups_load_with_empty_groups(self):
        first = self.add_box()
        self.app.save_scene(self.path)
        base = json.loads(self.path.read_text(encoding="utf8"))
        for version in (1, 2):
            with self.subTest(version=version):
                document = copy.deepcopy(base)
                document["version"] = version
                for key in ("groups", "next_group_id", "selected_ids", "primary_selection_id", "selected_group_id"):
                    document.pop(key, None)
                if version == 1:
                    document["objects"][0].pop("entity_id", None)
                self.path.write_text(json.dumps(document), encoding="utf8")
                loaded = Editor(800, 600)
                loaded.load_scene(self.path)
                self.assertEqual(loaded.scene.groups, [])
                self.assertEqual(len(loaded.scene.root_entities), 1)
                self.assertEqual(loaded.selection.entity_id, first.entity_id)

    def test_invalid_group_or_selection_load_is_atomic(self):
        first, second = self.add_box(), self.add_box((2, 0, 0))
        self.app.select(first)
        self.app.select(second, toggle=True)
        group = self.app.group_selected()
        self.app.save_scene(self.path)
        base = json.loads(self.path.read_text(encoding="utf8"))
        documents = []
        for members in ([], [first.entity_id] * 2, ["ent_999999"], [group.group_id]):
            document = copy.deepcopy(base)
            document["groups"][0]["member_ids"] = members
            documents.append(document)
        duplicate = copy.deepcopy(base)
        duplicate["groups"].append(copy.deepcopy(duplicate["groups"][0]))
        documents.append(duplicate)
        bad_selected = copy.deepcopy(base)
        bad_selected["selected_ids"] = ["ent_999999"]
        documents.append(bad_selected)
        undo_count = self.app.commands.undo_count
        camera = self.app.viewer.controller.snapshot()
        for document in documents:
            with self.subTest(document=document):
                self.path.write_text(json.dumps(document), encoding="utf8")
                with self.assertRaises(ValueError):
                    self.app.load_scene(self.path)
                self.assertEqual(self.app.scene.root_entities, [first, second])
                self.assertIs(self.app.scene.groups[0], group)
                self.assertEqual(group.member_ids, [first.entity_id, second.entity_id])
                self.assertEqual(self.app.scene.selected_group_id, group.group_id)
                self.assertEqual(self.app.commands.undo_count, undo_count)
                for key, value in camera.items():
                    np.testing.assert_array_equal(self.app.viewer.controller.snapshot()[key], value)

    def test_saved_counter_prevents_entity_and_group_id_reuse_after_undo_reload(self):
        first = self.add_box()
        group = self.app.group_selected()
        self.app.undo()
        duplicate = self.app.duplicate_selected()
        self.app.undo()
        self.app.save_scene(self.path)
        loaded = Editor(800, 600)
        loaded.load_scene(self.path)
        self.assertEqual(loaded.scene.groups, [])
        self.assertEqual(loaded.selection.entity_id, first.entity_id)
        new_group = loaded.group_selected()
        self.assertNotEqual(new_group.group_id, group.group_id)
        new_copy = loaded.duplicate_selected()
        self.assertNotEqual(new_copy.entity_id, duplicate.entity_id)

    def test_formation_wrapper_selects_group_and_undo_keeps_source(self):
        source = self.add_box()
        self.app.commands.clear_history()
        group = self.app.create_formation(5, 8, 1.2, 1.4)
        self.assertEqual(len(self.app.scene.root_entities), 40)
        self.assertEqual(len(self.app.selected_entities), 40)
        self.assertEqual(self.app.scene.selected_group_id, group.group_id)
        self.assertEqual(self.app.commands.undo_count, 1)
        ids = list(group.member_ids)
        self.app.undo()
        self.assertEqual(self.app.scene.root_entities, [source])
        self.assertIs(self.app.selection, source)
        self.app.redo()
        self.assertEqual(self.app.scene.selected_ids, ids)
        self.assertEqual(self.app.scene.selected_group_id, group.group_id)

    def test_surface_input_mouseup_and_escape_commit_or_cancel_one_gesture(self):
        source = self.add_box((0, 0, .5))
        self.app.viewer.camera.position = [0, 0, 10]
        self.app.viewer.camera.rotation = np.eye(3)
        self.app.tool = "surface"
        self.app.commands.clear_history()
        self.click()
        self.assertIsNotNone(self.app.surface_drag)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
            pos=(620, 350), rel=(120, 0), buttons=(1, 0, 0)), self.ui)
        self.assertFalse(np.allclose(source.pos, [0, 0, .5]))
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), self.ui)
        self.assertFalse(self.app.commands.active_transaction)
        self.assertEqual(self.app.commands.undo_count, 1)
        placed = source.pos.copy()
        self.click()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
            pos=(400, 350), rel=(-100, 0), buttons=(1, 0, 0)), self.ui)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN,
            key=pygame.K_ESCAPE, mod=0), self.ui)
        np.testing.assert_array_equal(source.pos, placed)
        self.assertEqual(self.app.commands.undo_count, 1)
        self.assertFalse(self.app.commands.active_transaction)

    def test_surface_escape_over_ui_rolls_back_and_captured_motion_does_not_move(self):
        entity = self.add_box((0, 0, .5))
        self.app.viewer.camera.position = [0, 0, 10]
        self.app.viewer.camera.rotation = np.eye(3)
        self.app.tool = "surface"
        self.app.commands.clear_history()
        before = entity.pos.copy()
        self.click()
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
            pos=(620, 350), rel=(120, 0), buttons=(1, 0, 0)), self.ui)
        placed = entity.pos.copy()
        self.ui.mouse_captured = self.ui.keyboard_captured = True
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
            pos=(10, 10), rel=(120, 0), buttons=(1, 0, 0)), self.ui)
        np.testing.assert_array_equal(entity.pos, placed)
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN,
            key=pygame.K_ESCAPE, mod=0), self.ui)
        np.testing.assert_array_equal(entity.pos, before)
        self.assertIsNone(self.app.surface_drag)
        self.assertEqual(self.app.commands.undo_count, 0)


if __name__ == "__main__":
    unittest.main()
