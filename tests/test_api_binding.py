"""API binding must share the editor's existing state and history."""
import unittest
from mini3d.api import Mini3DAPI
from mini3d.editor import Editor, PROJECT


class ApiBindingTests(unittest.TestCase):
    def test_existing_editor_and_api_share_history_and_shot(self):
        app = Editor()
        api = Mini3DAPI(editor=app)
        self.assertIs(api._app, app)
        self.assertIs(api._commands, app.commands)
        actor = api.spawn(PROJECT / 'model/06_stl_cube/cube.STL')
        self.assertIsNotNone(app.scene.find_by_id(actor['entity_id']))
        app.undo()
        self.assertIsNone(app.scene.find_by_id(actor['entity_id']))
        app.redo()
        self.assertEqual(api.get_entity(actor['entity_id'])['entity_id'], actor['entity_id'])
        api.create_shot_camera(position=[100, -150, 80], target=[0, 0, 20])
        api.set_antialiasing(4)
        self.assertEqual(app.shot_camera.samples, 4)
        app.set_shot_lens(85)
        self.assertAlmostEqual(api.get_shot_camera()['focal_mm'], 85)
        self.assertEqual(Mini3DAPI().list_entities(), [])
