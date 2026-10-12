import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
import pygame
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch, BATCH_METHODS
from mini3d.camera import Camera
from mini3d.photo_focus import image_pixel, unproject_depth, PhotoPreviewQuality
from mini3d.photo_color import adjust_linear, white_balance_gains
from mini3d.shot_camera import ShotCamera
from mini3d.viewport_cache import viewport_key


class PhotoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.api=Mini3DAPI()
        self.api.create_shot_camera(position=[0,0,0],target=[0,0,-3],aspect='3:2')
        self.app=self.api._app

    def test_color_atomic_invalid_reset_and_light_independence(self):
        before=self.api.get_scene_state()
        for params in ({'white_balance_kelvin':True},{'white_balance_kelvin':'6500'},
                       {'white_balance_kelvin':float('nan')},{'white_balance_kelvin':1000},
                       {'preset':'arbitrary'},{'white_balance_kelvin':7000,'preset':False}):
            with self.assertRaises(ValueError):self.api.set_photo_color(**params)
            self.assertEqual(self.api.get_scene_state(),before)
        self.api.set_photo_color(8000,'Warm')
        self.assertEqual(self.api.get_lighting(),before['lighting'])
        self.assertEqual(self.api.get_atmosphere(),before['atmosphere'])
        self.api.reset_photo_color()
        self.assertEqual(self.api.get_scene_state(),before)
        np.testing.assert_array_equal(white_balance_gains(6500),[1,1,1])
        self.assertGreater(white_balance_gains(9000)[0],white_balance_gains(9000)[2])
        gray=np.array([.5,.5,.5]);np.testing.assert_allclose(adjust_linear(gray,preset='Low saturation'),gray)
        color=np.array([.7,.2,.1]);low=adjust_linear(color,preset='Low saturation')
        self.assertLess(np.ptp(low),np.ptp(color))
        self.assertAlmostEqual(float(np.dot(low,[.2126,.7152,.0722])),float(np.dot(color,[.2126,.7152,.0722])))

    def test_json_legacy_roundtrip_marker_and_atomic_failed_load(self):
        self.assertTrue(dispatch(self.api,dict(command='set_photo_color',args=dict(white_balance_kelvin=7800,preset='Low saturation')))['ok'])
        self.api.focus_at([.3,.4,-3])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'scene.json';self.api.save_scene(path)
            fresh=Mini3DAPI();self.assertEqual(fresh.load_scene(path)['shot_camera'],self.api.get_shot_camera())
            document=json.loads(path.read_text());legacy=copy.deepcopy(document)
            for key in ('white_balance_kelvin','color_preset','focus_point'):legacy['shot_camera'].pop(key)
            path.write_text(json.dumps(legacy));shot=fresh.load_scene(path)['shot_camera']
            self.assertEqual((shot['white_balance_kelvin'],shot['color_preset'],shot['focus_point']),(6500,'Original',None))
            for bad in ({'white_balance_kelvin':None},{'color_preset':'Other'},{'focus_point':[0,0,-8]}):
                invalid=copy.deepcopy(document);invalid['shot_camera'].update(bad);path.write_text(json.dumps(invalid))
                before=fresh.get_scene_state()
                with self.assertRaises(ValueError):fresh.load_scene(path)
                self.assertEqual(fresh.get_scene_state(),before)
        for method in ('focus_screen','set_photo_color','reset_photo_color'):self.assertNotIn(method,BATCH_METHODS)

    def test_black_borders_scaled_image_and_depth_unprojection_all_aspects(self):
        shot=self.app.shot_camera
        for aspect in ShotCamera.ASPECTS:
            shot.set_aspect(aspect)
            for outer in ((10,50,850,630),(101,27,379,237)):
                rect=shot.fit_rect(outer);x,y,w,h=rect
                point=[x+w*.5,y+h*.5]
                pixel=image_pixel(point,rect,shot.size)
                self.assertIsNone(image_pixel([x-1,y],rect,shot.size))
                self.assertIsNone(image_pixel([x+w,y+h/2],rect,shot.size))
                z=-3.;clip=shot.projection_matrix(shot.aspect)@np.array([0,0,z,1])
                depth=(clip[2]/clip[3]+1)/2
                world=unproject_depth(shot,pixel,shot.size,depth)
                self.assertAlmostEqual(world[2],z,places=8)
                self.assertLess(np.linalg.norm(world[:2]),.01)
                self.assertIsNone(unproject_depth(shot,pixel,shot.size,1))
                self.assertIsNone(unproject_depth(shot,pixel,shot.size,float('nan')))

    def test_photo_click_routes_only_unblocked_left_image_click_and_manual_focus_clears_marker(self):
        app=self.app;app.set_camera_view(True)
        app.photo_focus_reader=lambda point,rect: None if point[0]<100 else np.array([.1,.2,-3])
        ui=SimpleNamespace(modal_open=False,mouse_captured=False,asset_dragging=False,viewport_hovered=True)
        original=app.shot_camera.to_dict()
        event=pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=(120,130))
        ui.modal_open=True;app.handle_event(event,ui);self.assertEqual(app.shot_camera.to_dict(),original)
        ui.modal_open=False;ui.mouse_captured=True;app.handle_event(event,ui);self.assertEqual(app.shot_camera.to_dict(),original)
        ui.mouse_captured=False;app.handle_event(event,ui)
        self.assertEqual(app.shot_camera.focus_point.tolist(),[.1,.2,-3])
        focused=app.shot_camera.to_dict()
        self.assertFalse(self.api.focus_screen([0,0])['focused'])
        self.assertEqual(app.shot_camera.to_dict(),focused)
        app.handle_event(event,ui);self.assertEqual(app.shot_camera.to_dict(),focused)
        self.api.set_depth_of_field(focus_distance=4)
        self.assertIsNone(app.shot_camera.focus_point)

    def test_color_cache_and_interaction_quality_settles_without_export_change(self):
        app=self.app;app.set_camera_view(True)
        baseline=viewport_key(app,(800,600),True,'REALISTIC')
        self.api.set_photo_color(7500,'Warm')
        changed=viewport_key(app,(800,600),True,'REALISTIC');self.assertNotEqual(changed,baseline)
        q=PhotoPreviewQuality();full=app.shot_camera.size
        self.assertEqual(q.size(baseline,full,False,0),full)
        self.assertEqual(q.size(changed,full,False,.1),(960,640))
        self.assertEqual(q.size(changed,full,True,.25),(960,640))
        self.assertEqual(q.size(changed,full,False,.4),(960,640))
        self.assertEqual(q.size(changed,full,False,.44),full)
        self.assertEqual(app.shot_camera.size,full)


if __name__=='__main__':unittest.main()
