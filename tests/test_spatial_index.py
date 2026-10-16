import unittest
import numpy as np
from mini3d.spatial_index import SpatialIndex
from mini3d.render_plan import aabb_visible, frustum_planes
from mini3d.camera import Camera


class SpatialIndexTests(unittest.TestCase):
    def test_scene_opt_in_matches_flat_plan_after_direct_edits_and_visibility(self):
        from mini3d.scene import Scene, Entity, Mesh
        from mini3d.render_plan import build_render_plan
        scene=Scene();mesh=Mesh([[-1,-1,-1],[1,1,1]],[[0,1,0]],material={})
        rng=np.random.RandomState(31)
        for i in range(600):
            e=Entity(mesh);e.pos[:]=rng.uniform(-100,100,3);scene.root_entities.append(e)
        camera=Camera([0,-110,20],near=.1,far=300);camera.look_at([0,0,0])
        for step in range(4):
            scene.root_entities[step].pos[:]=[0,-10,step]
            scene.root_entities[step+10].visible=False
            scene.update();scene.spatial_culling_enabled=False
            flat=build_render_plan(scene,camera,960,540)
            scene.spatial_culling_enabled=True
            tree=build_render_plan(scene,camera,960,540)
            self.assertEqual([id(i.entity) for i in flat.imported],[id(i.entity) for i in tree.imported])
            self.assertEqual(flat.shadow_candidates,tree.shadow_candidates)

    def test_query_matches_exhaustive_visibility_after_refits_and_rebuilds(self):
        rng = np.random.RandomState(17)
        lo = rng.uniform(-100,100,(600,3))
        boxes = np.stack((lo,lo+rng.uniform(.01,15,(600,3))),axis=1)
        index = SpatialIndex()
        for step in range(16):
            if step: boxes[step] += [13,-9,4]
            if step == 8: boxes = boxes[::-1].copy()
            index.update(boxes)
            camera=Camera([0,-150,40],near=.1,far=400)
            camera.look_at([step*4-30,0,0])
            planes=frustum_planes(camera.view_matrix,camera.projection_matrix(16/9))
            ids=index.query(planes)
            actual=np.zeros(len(boxes),bool);actual[ids]=aabb_visible(boxes[ids],planes)
            np.testing.assert_array_equal(actual,aabb_visible(boxes,planes))
        index.update(boxes);self.assertEqual(index.refitted_leaves,0)
        boxes[0] += 3;index.update(boxes);self.assertEqual(index.refitted_leaves,1)
        index.update(boxes[:5]);self.assertEqual(len(index.leaves),5)
        index.update([]);self.assertEqual(index.nodes,[])

    def test_invalid_planes_keep_every_candidate(self):
        boxes=np.array([[[i,0,0],[i+1,1,1]] for i in range(160)],float)
        index=SpatialIndex();index.update(boxes)
        self.assertEqual(len(index.query(np.full((6,4),np.nan))),len(boxes))


if __name__=='__main__': unittest.main()
