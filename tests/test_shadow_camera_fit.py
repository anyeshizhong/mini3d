"""Independent convex-intersection reference and directional-caster coverage."""
from itertools import combinations
import unittest

import numpy as np
from mini3d.camera import Camera
from mini3d.scene import Entity, Mesh, rotation_xyz
from mini3d.shot_camera import ShotCamera
from mini3d.shadow_fit import _corners, _planes, _intersection, receiver_matrix
from mini3d.shadow_map import light_matrix


def entity(bounds, position=(0,0,0), scale=(1,1,1), rotation=(0,0,0)):
    result=Entity(Mesh(_corners(bounds),[[0,1,2]]))
    result.pos[:],result.scale[:],result.rot[:]=position,scale,rotation
    result.update_transform()
    return result


def reference_vertices(planes):
    """Independent oracle: every feasible intersection of three boundary planes."""
    result=[]
    for indices in combinations(range(len(planes)),3):
        p=planes[list(indices)]
        if abs(np.linalg.det(p[:,:3]))<1e-9:
            continue
        point=np.linalg.solve(p[:,:3],-p[:,3])
        if np.all(planes[:,:3]@point+planes[:,3]>=-1e-7):
            result.append(point)
    return np.asarray(result)


class ShadowCameraFitTests(unittest.TestCase):
    def shot(self, scale=1):
        view=Camera(np.array([7,9,13])*scale,near=.05*scale,far=400*scale)
        view.look_at(np.array([.6,.5,0])*scale)
        shot=ShotCamera(view)
        shot.set_lens(50)
        shot.set_aspect('4:3')
        return shot

    def test_crossing_boxes_have_intersection_without_enclosed_corners(self):
        bounds=(np.array([-.2,-3,-.2]),np.array([.2,3,.2]))
        clip=(np.array([-3,-.2,-.2]),np.array([3,.2,.2]))
        result=_intersection(bounds,np.eye(4),_planes(*clip),_corners(clip))
        np.testing.assert_allclose(result.min(0),[-.2,-.2,-.2])
        np.testing.assert_allclose(result.max(0),[.2,.2,.2])

    def test_rotated_scaled_intersections_match_independent_halfspace_oracle(self):
        rng=np.random.RandomState(11)
        clip=(np.array([-1.,-1.,-1.]),np.array([1.,1.,1.]))
        planes=_planes(*clip)
        for _ in range(35):
            bounds=(np.array([-2.,-.4,-.3]),np.array([2.,.4,.3]))
            world=np.eye(4)
            world[:3,:3]=rotation_xyz(rng.uniform(-3,3,3))@np.diag(rng.uniform(.3,2,3))
            world[:3,3]=rng.uniform(-2,2,3)
            box_planes=_planes(*bounds)@np.linalg.inv(world)
            reference=reference_vertices(np.concatenate((planes,box_planes)))
            result=_intersection(bounds,world,planes,_corners(clip))
            with self.subTest(world=world):
                self.assertEqual(len(result)==0,len(reference)==0)
                if len(result):
                    np.testing.assert_allclose(result.min(0),reference.min(0),atol=1e-7)
                    np.testing.assert_allclose(result.max(0),reference.max(0),atol=1e-7)

    def test_large_ground_does_not_inflate_close_shot_fit(self):
        subject=entity(([-.5,-.5,0],[.5,.5,2]))
        matrices=[]
        for span in (32,200):
            ground=entity(([-.5,-.5,-.5],[.5,.5,.5]),position=[0,0,-.1],scale=[span,span,.2])
            matrices.append(receiver_matrix([ground,subject],[-3,-2,3],self.shot(),1024))
        np.testing.assert_allclose(matrices[0],matrices[1],atol=1e-10)

    def test_offscreen_and_beyond_far_plane_casters_are_covered(self):
        camera=ShotCamera(Camera([0,0,8],near=.01,far=20))
        camera.look_at([0,0,0]);camera.set_lens(85);camera.set_aspect('1:1')
        ground=entity(([-100,-100,-.2],[100,100,0]))
        for light,pos in (([1,0,1],[4,0,4]),([1,0,.2],[20,0,4]),([1,0,1],[100,0,100])):
            caster=entity(([-.5,-.5,-.5],[.5,.5,.5]),position=pos)
            matrix=receiver_matrix([ground,caster],light,camera,1024)
            for point in ([0,0,0],pos):
                clip=matrix@np.append(point,1)
                self.assertTrue(np.all(np.abs(clip[:3])<1), (light,pos,clip))

    def test_unrelated_caster_does_not_inflate_receiver_xy_or_depth(self):
        ground=entity(([-100,-100,-.2],[100,100,0]))
        subject=entity(([-.5,-.5,0],[.5,.5,2]))
        before=receiver_matrix([ground,subject],[-3,-2,3],self.shot(),1024)
        remote=entity(([-1,-1,-1],[1,1,1]),position=[1000,1000,1000])
        after=receiver_matrix([ground,subject,remote],[-3,-2,3],self.shot(),1024)
        np.testing.assert_allclose(before,after,atol=1e-10)

    def test_scene_scales_preserve_projected_coverage(self):
        projections=[]
        for scale in (.01,1,100):
            ground=entity(([-100,-100,-.2],[100,100,0]),scale=[scale]*3)
            subject=entity(([-.5,-.5,0],[.5,.5,2]),scale=[scale]*3)
            matrix=receiver_matrix([ground,subject],[-3,-2,3],self.shot(scale),1024)
            projections.append(matrix@np.column_stack((_corners(([-.5,-.5,0],[.5,.5,2]))*scale,np.ones(8))).T)
        np.testing.assert_allclose(projections[0],projections[1],atol=1e-8)
        np.testing.assert_allclose(projections[2],projections[1],atol=1e-8)

    def test_no_receivers_and_singular_transform_request_global_fallback(self):
        remote=entity(([-1,-1,-1],[1,1,1]),position=[1000,1000,1000])
        self.assertIsNone(receiver_matrix([remote],[-3,-2,3],self.shot(),1024))
        self.assertIsNone(receiver_matrix([],[-3,-2,3],self.shot(),1024))
        broken=entity(([-100,-100,-.2],[100,100,0]))
        broken.world_matrix[:3,:3]=0
        self.assertIsNone(receiver_matrix([broken],[-3,-2,3],self.shot(),1024))
        np.testing.assert_array_equal(light_matrix([remote],[-3,-2,3]),
                                      light_matrix([remote],[-3,-2,3],self.shot(),1024))

    def test_camera_and_light_changes_produce_finite_correct_coverage(self):
        ground=entity(([-100,-100,-.2],[100,100,0]))
        subject=entity(([-.5,-.5,0],[.5,.5,2]))
        for pos in ([7,9,13],[-7,-9,13],[0,0,8],[.5,-4,2]):
            camera=self.shot()
            camera.position=pos;camera.look_at([0,0,1])
            for light in ([0,0,1],[1,0,0],[-3,-2,3],[2,-1,-1]):
                matrix=receiver_matrix([ground,subject],light,camera,1024)
                self.assertIsNotNone(matrix)
                self.assertTrue(np.isfinite(matrix).all())
                # Center is a visible potential receiver in all these shots.
                clip=matrix@np.array([0,0,1,1])
                self.assertTrue(np.all(np.abs(clip[:3])<=1))


if __name__=='__main__':
    unittest.main()
