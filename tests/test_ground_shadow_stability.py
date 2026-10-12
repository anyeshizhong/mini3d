"""Infinite photographic receivers retain nearby shadows at grazing views."""
import math
import unittest
import numpy as np
from mini3d.camera import Camera
from mini3d.scene import Entity, Mesh
from mini3d.shadow_fit import _corners, _receiver_boxes, receiver_matrix


def entity(bounds, photographic=False):
    obj=Entity(Mesh(_corners(bounds),[[0,1,2]]))
    if photographic:
        obj.model.material={'extras':{'photographicGround':True}}
    obj.update_transform()
    return obj


class GroundShadowStabilityTests(unittest.TestCase):
    def test_projected_caster_footprint_includes_long_offscreen_shadows(self):
        caster=entity(([19,-.5,3.5],[20,.5,4.5]))
        ground=entity(([-200,-200,0],[200,200,0]),True)
        light=np.array([1,0,.2])
        boxes=_receiver_boxes([caster,ground],light)
        lo,hi=boxes[-1][0]
        points=_corners(caster.model.bounds)
        projected=points-points[:,2,None]/light[2]*light
        self.assertTrue(np.all(projected>=lo-1e-12))
        self.assertTrue(np.all(projected<=hi+1e-12))
        self.assertLess(np.linalg.norm(hi-lo),10)

    def test_horizon_crossing_keeps_shadow_texels_local_and_covers_shadow(self):
        caster=entity(([-.2,-.2,0],[.2,.2,.62]))
        ground=entity(([-200,-200,0],[200,200,0]),True)
        light=np.array([-.7,-.5,.5])
        for pitch in (4,6,8,12,20):
            angle=math.radians(pitch)
            camera=Camera([3*math.cos(angle),0,.3+3*math.sin(angle)],fov_y=23,near=.02,far=100)
            camera.look_at([0,0,.3])
            matrix=receiver_matrix([caster,ground],light,camera,2048,aspect=16/9)
            self.assertIsNotNone(matrix)
            # A horizon-crossing 100 m frustum must not consume shadow texels.
            spans=2/np.linalg.norm(matrix[:2,:3],axis=1)
            self.assertLess(float(spans.max()),4)
            projected=np.array([0,0,.62])-.62/light[2]*light
            clip=matrix@np.r_[projected,1]
            self.assertTrue(np.all(np.abs(clip[:3])<=1+1e-9),clip)

    def test_no_casters_and_parallel_light_are_safe(self):
        ground=entity(([-200,-200,0],[200,200,0]),True)
        self.assertEqual(_receiver_boxes([ground],[1,0,1]),[])
        caster=entity(([-.2,-.2,0],[.2,.2,.62]))
        boxes=_receiver_boxes([caster,ground],[1,0,0])
        np.testing.assert_array_equal(boxes[-1][0],ground.model.bounds)


if __name__=='__main__':unittest.main()
