"""Repeatable composition workflow audit using only the tracked STL cube.

Runs Editor/Commands and real surface queries without a GL window. Rendering
and visual quality are deliberately outside this script's pass criteria.
"""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "captures/audit-20261010/placement"

from mini3d.editor import Editor
from mini3d.geometry import make_box, make_cylinder, make_sphere
from mini3d.placement import SurfaceHit, geometry_bounds


def state(app):
    return {
        "objects": [{"id": e.entity_id, "name": e.name,
                     "position": e.pos.tolist(), "rotation": e.rot.tolist(),
                     "scale": e.scale.tolist(), "locked": e.locked,
                     "visible": e.visible}
                    for e in app.scene.root_entities],
        "groups": [{"id": g.group_id, "name": g.name, "members": list(g.member_ids)}
                   for g in app.scene.groups],
        "selection": list(app.scene.selected_ids),
        "primary": app.scene.primary_selection_id,
        "selected_group": app.scene.selected_group_id,
    }


class CompositionWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from stl import mesh, Mode
        OUT.mkdir(parents=True, exist_ok=True)
        source = mesh.Mesh.from_file(str(ROOT / "model/06_stl_cube/cube.STL"), mode=Mode.BINARY)
        low, high = source.vectors.min(axis=(0, 1)), source.vectors.max(axis=(0, 1))
        source.vectors[:] = (source.vectors - (low + high) / 2) / (high - low)
        cls.fixture = OUT / "unit_cube.stl"
        source.save(str(cls.fixture), mode=Mode.BINARY)

    def setUp(self):
        self.apps = []
        self.app = self.new_editor()

    def tearDown(self):
        for app in self.apps:
            app.model_dialog.close()

    def new_editor(self):
        app = Editor(800, 600)
        self.apps.append(app)
        return app

    def cube(self, name, pos, scale):
        app = self.app
        index = len(app.assets)
        app.assets.append({"name": name, "path": str(self.fixture)})
        entity = app.add_asset(index, pos)
        app.commands.set_transform(entity, scale=scale)
        return entity

    def test_portico_build_duplicate_group_transform_save_reopen(self):
        app = self.app
        platform = self.cube("Plinth", [0, 0, 0.25], [12, 8, .5])
        app.lock_selected()
        column = self.cube("Column block", [-4, -2.5, 4], [.6, .6, 3])
        app.commands.place_on_surface(column, SurfaceHit([-4, -2.5, .5], [0, 0, 1]))
        self.assertAlmostEqual(geometry_bounds(column)[0][2], .5)
        app.commands.clear_history()

        before = state(app)
        group = app.create_formation(2, 5, 2, 5)
        self.assertEqual(len(group.member_ids), 10)
        self.assertEqual(len(app.scene.root_entities), 11)
        self.assertEqual(app.commands.undo_count, 1)
        members = [app.scene.find_by_id(i) for i in group.member_ids]
        self.assertTrue(all(e.model is column.model for e in members))
        formed = state(app)
        app.undo()
        self.assertEqual(state(app), before)
        app.redo()
        self.assertEqual(state(app), formed)

        app.rename_group("Portico columns")
        original_ids = list(group.member_ids)
        app.duplicate_selected()
        copy_ids = list(app.scene.selected_ids)
        self.assertEqual(len(copy_ids), 10)
        self.assertFalse(set(original_ids) & set(copy_ids))
        copied = app.group_selected()
        app.rename_group("Second portico columns")
        with app.commands.transaction("Arrange second portico"):
            app.commands.transform_many(copy_ids, translation=[0, 10, 0])
            app.commands.transform_many(copy_ids, rotation=[0, 0, np.pi / 2])
        self.assertEqual(len(app.scene.root_entities), 21)
        self.assertEqual(len(app.scene.groups), 2)
        self.assertTrue(platform.locked)

        arranged = state(app)
        app.undo()
        app.redo()
        self.assertEqual(state(app), arranged)
        scene_path = OUT / "portico_scene.json"
        app.save_scene(scene_path)
        restored = self.new_editor()
        restored.load_scene(scene_path)
        self.assertEqual(state(restored), state(app))
        self.assertEqual(restored.commands.undo_count, 0)
        restored.select_group(copied.group_id)
        before_delete = state(restored)
        restored.delete_selected()
        self.assertEqual(len(restored.scene.root_entities), 11)
        self.assertEqual(len(restored.scene.groups), 1)
        restored.undo()
        self.assertEqual(state(restored), before_delete)
        restored.redo()
        self.assertEqual(len(restored.scene.root_entities), 11)
        (OUT / "workflow_state.json").write_text(json.dumps(arranged, indent=2), encoding="utf8")

    def test_locked_support_real_surface_drag_cancel_undo(self):
        app = self.app
        platform = self.cube("Locked tabletop", [0, 0, 1], [8, 8, 2])
        app.lock_selected()
        prop = self.cube("Prop", [0, 0, 8], [1, 1, 2])
        camera = app.viewer.camera
        camera.position = [0, 0, 20]
        camera.rotation = np.eye(3)
        app.viewer.update_clipping()
        rect = (0, 0, 800, 600)
        app.commands.clear_history()
        initial = prop.pos.copy()
        drag = app.commands.begin_surface_drag(prop.entity_id)
        for x in np.linspace(370, 430, 25):
            self.assertTrue(drag.update(camera, (x, 300), rect))
        self.assertAlmostEqual(geometry_bounds(prop)[0][2], 2)
        drag.finish(cancel=True)
        np.testing.assert_array_equal(prop.pos, initial)
        self.assertEqual(app.commands.undo_count, 0)
        drag = app.commands.begin_surface_drag(prop.entity_id)
        self.assertTrue(drag.update(camera, (410, 300), rect))
        drag.finish()
        placed = prop.pos.copy()
        self.assertEqual(app.commands.undo_count, 1)
        app.undo()
        np.testing.assert_array_equal(prop.pos, initial)
        app.redo()
        np.testing.assert_array_equal(prop.pos, placed)
        self.assertTrue(platform.locked)

    def test_overlapping_groups_hidden_and_locked_members(self):
        app = self.app
        a = self.cube("A", [-2, 0, 1], [1, 1, 1])
        b = self.cube("B", [0, 0, 1], [1, 1, 1])
        c = self.cube("C", [2, 0, 1], [1, 1, 1])
        first = app.commands.create_group([a.entity_id, b.entity_id], "AB")
        second = app.commands.create_group([b.entity_id, c.entity_id], "BC")
        app.commands.set_metadata(a, visible=False)
        app.commands.lock(b)
        app.select_group(first.group_id)
        app.commands.transform_many(app.scene.selected_ids, translation=[1, 2, 0])
        np.testing.assert_allclose(a.pos, [-1, 2, 1])
        np.testing.assert_allclose(b.pos, [0, 0, 1])
        app.commands.unlock(b)
        before = state(app)
        app.commands.delete(b)
        self.assertEqual(first.member_ids, [a.entity_id])
        self.assertEqual(second.member_ids, [c.entity_id])
        app.undo()
        self.assertEqual(state(app), before)

    def test_generated_primitives_non_degenerate_faces_point_outward(self):
        results = {}
        for name, generator in (("box", make_box), ("sphere", make_sphere), ("cylinder", make_cylinder)):
            vertices, faces = generator()
            triangles = vertices[faces].astype(float)
            normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            valid = np.linalg.norm(normals, axis=1) > 1e-7
            dots = np.einsum("ij,ij->i", normals, triangles.mean(axis=1))
            self.assertTrue(np.all(dots[valid] > 0), name)
            results[name] = {"triangles": len(faces), "outward": int((dots[valid] > 0).sum()),
                             "inward": int((dots[valid] < 0).sum()), "degenerate": int((~valid).sum())}
        (OUT / "primitive_winding.json").write_text(json.dumps(results, indent=2), encoding="utf8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
