import tempfile
from pathlib import Path
import unittest
import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch
from mini3d.placement import geometry_bounds
from mini3d.render_plan import batch_world_bounds, world_bounds
from mini3d.atmosphere import direct_light_strength


class Phase2Tests(unittest.TestCase):
    def test_real_imgui_moon_preset_and_adjacent_controls(self):
        import imgui
        from unittest.mock import patch
        from mini3d.editor_ui import EditorUI
        context=imgui.create_context();api=self.api();app=api._app
        try:
            io=imgui.get_io();io.display_size=(1280,800);io.delta_time=1/60
            io.ini_file_name=None;io.fonts.get_tex_data_as_rgba32()
            ui=EditorUI(app);app.set_workspace('Lighting')
            button=imgui.button
            def click(label,*args,**kwargs):
                value=button(label,*args,**kwargs)
                return label=='Moonlight##sky_preset' or value
            with patch.object(imgui,'button',click):
                imgui.new_frame();ui.draw(1280,800,0);imgui.render()
            self.assertEqual(api.get_atmosphere()['celestial_body'],'moon')
            self.assertEqual(api.get_atmosphere()['sky_texture'],'moonlit')
            a=api.spawn('builtin:roman-shop')['entity_id']
            b=api.spawn('builtin:roman-house',position=[20,0,0])['entity_id']
            app.set_workspace('Arrange');api.select_entities([a,b],primary_id=b)
            def align(label,*args,**kwargs):
                value=button(label,*args,**kwargs)
                return label=='+X##adjacent' or value
            with patch.object(imgui,'button',align):
                imgui.new_frame();ui.draw(1280,800,0);imgui.render()
            self.assertAlmostEqual(geometry_bounds(api._entity(a))[0][0],geometry_bounds(api._entity(b))[1][0])
        finally:imgui.destroy_context(context)

    def api(self):
        api=Mini3DAPI(); self.addCleanup(api._app.model_dialog.close); return api

    def test_batch_bounds_matches_scalar_under_rotation_and_nonuniform_scale(self):
        api=self.api(); api.create_roman_street(segments=2, variation=True)
        roots=api._app.scene.root_entities
        for root in roots:
            api.set_transform(root.entity_id, rotation=[.2,.7,-1.1],scale=[.3,2,1.3])
        nodes=api._app.scene.get_flat_render_list()
        for node,bound in zip(nodes,batch_world_bounds(nodes)):
            np.testing.assert_allclose(bound,world_bounds(node.model,node.world_matrix),atol=1e-12)
        nodes[0].world_matrix[0,0]=np.nan
        self.assertIsNone(batch_world_bounds(nodes)[0])

    def test_alignment_bounds_locked_reference_undo_and_roundtrip(self):
        api=self.api()
        ref=api.spawn('builtin:roman-house',rotation=[0,0,.7],scale=[.7,1.4,1.2])['entity_id']
        a=api.spawn('builtin:roman-shop',position=[20,4,0],rotation=[0,0,-.3])['entity_id']
        b=api.spawn('builtin:roman-column',position=[30,2,0])['entity_id']
        api.lock(ref); before=api.list_entities(); count=api.get_scene_state()['history']['undo_count']
        result=dispatch(api,dict(command='align_adjacent',args=dict(entity_ids=[ref,a,b],reference_id=ref,axis='y',side=-1,gap=.2)))
        self.assertTrue(result['ok'],result)
        self.assertEqual(api.get_scene_state()['history']['undo_count'],count+1)
        bounds=[geometry_bounds(api._entity(e)) for e in (ref,a,b)]
        self.assertAlmostEqual(bounds[0][0][1]-.2,bounds[1][1][1])
        self.assertAlmostEqual(bounds[1][0][1]-.2,bounds[2][1][1])
        self.assertEqual(api.get_entity(ref),before[0])
        after=api.list_entities(); api.undo();self.assertEqual(before,api.list_entities())
        api.redo();self.assertEqual(after,api.list_entities())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'aligned.json';api.save_scene(path)
            fresh=self.api();fresh.load_scene(path);self.assertEqual(after,fresh.list_entities())
        for args in ({'gap':-1},{'gap':float('inf')},{'axis':'bad'},{'side':True}):
            with self.assertRaises(ValueError):api.align_adjacent([a,b],ref,**args)
            self.assertEqual(after,api.list_entities())

    def test_celestial_presets_horizon_poles_and_atomic_validation(self):
        api=self.api()
        for name in ('day','sunset','stars','moonlit'):
            self.assertTrue(dispatch(api,dict(command='sky_preset',args=dict(name=name)))['ok'])
            for az in (-180,0,180):
                for elevation in (-90,0,90):
                    api.set_atmosphere(azimuth=az,elevation=elevation)
                    self.assertTrue(np.isfinite(api.get_lighting()['direction']).all())
                    if elevation<=0:self.assertEqual(direct_light_strength(api._app.scene),0)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'sky.json';api.save_scene(path)
                fresh=self.api();fresh.load_scene(path)
                self.assertEqual(fresh.get_atmosphere(),api.get_atmosphere())
        before=api.get_scene_state()
        for args in ({'celestial_body':'mars'},{'sky_texture':'bad.hdr'},{'elevation':90.01}):
            with self.assertRaises((ValueError,OSError)):api.set_atmosphere(**args)
            self.assertEqual(before,api.get_scene_state())
        with self.assertRaises(ValueError):api.sky_preset('bad')
        api.set_lighting(diffuse=2,direction=[0,0,-1]);api.set_atmosphere(enabled=False)
        self.assertEqual(direct_light_strength(api._app.scene),2)
