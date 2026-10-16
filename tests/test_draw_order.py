import unittest
from unittest.mock import patch
import numpy as np
from mini3d.draw_order import OpaqueOrder, _group_order
from mini3d.scene import Entity, Mesh
from mini3d.shadow_fit import _receiver_boxes, _corners


class DrawOrderTests(unittest.TestCase):
    def test_disjoint_meshes_group_but_touching_and_invalid_bounds_are_barriers(self):
        boxes = [np.array([[x,0,0],[x+1,1,1]], float) for x in (0,3,6,9)]
        self.assertEqual(_group_order([1,2,1,2], boxes), [0,2,1,3])
        boxes[1] = boxes[2].copy()
        order = _group_order([1,2,1,2], boxes)
        self.assertLess(order.index(1), order.index(2))
        boxes[1] = None
        self.assertEqual(_group_order([1,2,1,2], boxes)[:2], [0,1])
        touching = [np.array([[x,0,0],[x+1,1,1]], float) for x in (0,1,2)]
        self.assertEqual(_group_order([1,2,1], touching), [0,1,2])

    def test_all_overlap_dependencies_survive_randomized_ordering(self):
        rng = np.random.RandomState(12)
        lo = rng.uniform(-5,5,(90,3)); hi = lo + rng.uniform(.1,4,(90,3))
        boxes = np.stack((lo,hi),axis=1)
        order = _group_order(rng.randint(0,5,90).tolist(), boxes)
        self.assertEqual(sorted(order), list(range(90)))
        ranks = np.argsort(order)
        for i in range(90):
            for j in range(i+1,90):
                if np.all((lo[i] <= hi[j]) & (hi[i] >= lo[j])):
                    self.assertLess(ranks[i],ranks[j])

    def test_cache_invalidates_on_edits_reorder_alpha_and_bounds(self):
        material = {}; meshes = [Mesh([[0,0,0],[1,1,1]],[[0,1,0]],material=material) for _ in range(2)]
        entities = [Entity(meshes[i%2]) for i in range(4)]
        for i,e in enumerate(entities): e.pos[0] = i*3; e.update_transform()
        cache = OpaqueOrder()
        first = cache.ranks_for(entities)
        with patch('mini3d.draw_order._group_order', side_effect=AssertionError('cache missed')):
            self.assertIs(cache.ranks_for(entities), first)
        for change in (lambda: entities[1].pos.__setitem__(0,6),
                       lambda: material.update(alphaMode='MASK'),
                       lambda: meshes[0].bounds[1].__setitem__(0,8),
                       lambda: entities.reverse()):
            change()
            for e in entities: e.update_transform()
            ranks = cache.ranks_for(entities)
            self.assertEqual(ranks, OpaqueOrder().ranks_for(entities))
        self.assertEqual(list(ranks), [id(e) for e in entities])

    def test_batched_ground_projection_matches_scalar_world_corners(self):
        rng = np.random.RandomState(7); entities = []
        for i in range(120):
            e=Entity(Mesh([[-1,-2,0],[2,1,3]],[[0,1,0]],material={}))
            e.pos[:]=rng.uniform(-80,80,3); e.rot[:]=rng.uniform(-1,1,3)
            e.scale[:]=rng.uniform(.3,2,3); e.update_transform(); entities.append(e)
        ground=Entity(Mesh([[-200,-200,0],[200,200,0]],[[0,1,0]],
                              material={'extras':{'photographicGround':True}}))
        ground.pos[2]=-.14; ground.update_transform()
        direction=np.array([.3,-.8,.5]); direction/=np.linalg.norm(direction)
        actual = _receiver_boxes(entities+[ground],direction)[-1][0]
        points=np.concatenate([_corners(e.model.bounds)@e.world_matrix[:3,:3].T+e.world_matrix[:3,3]
                               for e in entities])
        projected=points-((points[:,2]+.14)/direction[2])[:,None]*direction
        projected[:,2]=0
        np.testing.assert_allclose(actual,[projected.min(0),projected.max(0)],atol=1e-10)


if __name__ == '__main__': unittest.main()
