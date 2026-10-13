import tempfile
from pathlib import Path
import unittest
from mini3d.api import Mini3DAPI


class VariationTests(unittest.TestCase):
    def test_roof_has_outward_top_and_closed_underside_on_both_slopes(self):
        import numpy as np
        from mini3d.roman_assets import _Builder, _roof
        builder=_Builder('builtin:roman-shop');_roof(builder,3.6)
        vertices,faces,_=builder.parts['terracotta']
        triangles=np.asarray(vertices)[np.asarray(faces)]
        normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        # Each full slope/underside triangle spans half the roof, unlike tile details.
        large=np.linalg.norm(normals,axis=1)>9
        for sign in (-1,1):
            self.assertTrue(np.any(large & (normals[:,0]*sign>0) & (normals[:,2]>0)))
            self.assertTrue(np.any(large & (normals[:,0]*sign>0) & (normals[:,2]<0)))

    def api(self):
        api=Mini3DAPI()
        self.addCleanup(api._app.model_dialog.close)
        return api

    def test_seeded_extension_edit_and_reload(self):
        a,b=self.api(),self.api()
        result=a.create_roman_street(variation=True, seed=17, extension_segments=4)
        b.create_roman_street(variation=True, seed=17, extension_segments=4)
        self.assertEqual(a.list_entities(),b.list_entities())
        self.assertEqual(result['total_length'],40)
        self.assertEqual(result['entity_count'],85)
        buildings=[e for e in a.list_entities() if 'house' in e['asset_path'] or 'shop' in e['asset_path']]
        self.assertGreater(len({e['asset_path'] for e in buildings}),2)
        self.assertTrue(any(e['position'][1]>14 for e in buildings))
        self.assertTrue(all(.86<=e['scale'][0]<=1. for e in buildings))
        self.assertGreater(len({e['scale'][2] for e in buildings}),2)
        a.set_transform(buildings[-1]['entity_id'],position=[12,24,0])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'street.json';a.save_scene(path);b.load_scene(path)
            self.assertEqual(a.list_entities(),b.list_entities())
            self.assertEqual(a.list_groups(),b.list_groups())
        a.undo();a.undo();self.assertEqual(a.list_entities(),[])
        a.redo();self.assertEqual(len(a.list_entities()),85)

    def test_new_arguments_reject_invalid_values_without_partial_mutation(self):
        a=self.api()
        for args in ({'variation':1},{'seed':-1},{'seed':True},{'extension_segments':7},{'extension_segments':1.5}):
            with self.assertRaises(ValueError):a.create_roman_street(**args)
            self.assertEqual(a.list_entities(),[])
            self.assertEqual(a.get_scene_state()['history']['undo_count'],0)
