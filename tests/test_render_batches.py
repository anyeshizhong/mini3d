"""Persistent preparation must retain legacy ordering and mutation semantics."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from mini3d.draw_order import OpaqueOrder
from mini3d.geometry_cache import box_geometry, normal_transform
from mini3d.material_renderer import MaterialRenderer
from mini3d.render_plan import DrawItem
from mini3d.scene import Entity, Mesh, Scene


def renderer_without_context():
    renderer = MaterialRenderer.__new__(MaterialRenderer)
    renderer._instances = {}
    renderer._opaque_groups = {}
    renderer._normal_cache = {}
    renderer._opaque_order = OpaqueOrder()
    renderer.gpu_instancing = True
    renderer._mesh = lambda mesh: (mesh, 1, 2, 3, 3, np.zeros(3))
    return renderer


def mesh(material):
    return Mesh([[-1, -1, -1], [1, 1, 1]], [[0, 1, 0]], material=material)


class PreparedScene:
    """Producer contract: replace record/token when geometry/material changes."""
    def __init__(self, entities):
        self.scene = Scene()
        for entity in entities:
            self.scene.add(entity)
        self.records = {}

    def plan(self, visible=None):
        self.scene.update()
        entities = self.scene.get_flat_render_list()
        records, items = {}, []
        for entity in entities:
            key = (entity.world_matrix.tobytes(), id(entity.model),
                   repr(entity.model.material), repr(entity.model.bounds))
            cached = self.records.get(id(entity))
            if cached is None or cached['key'] != key:
                matrix = entity.world_matrix.astype(np.float32)
                normal, mirrored = normal_transform(matrix, {})
                cached = dict(key=key, token=object(), matrix=matrix, normal=normal,
                              mirrored=mirrored, geometry=box_geometry(entity))
            records[id(entity)] = cached
            if visible is None or entity in visible:
                items.append(DrawItem(entity, entity.model, cached['matrix'], entity.model.material,
                                      cached['geometry'][3], cached))
        self.records = records
        return SimpleNamespace(shadow_candidates=entities, geometry=SimpleNamespace(records=records),
                               opaque=[item for item in items if item.material.get('alphaMode') != 'BLEND'],
                               transparent=[item for item in items if item.material.get('alphaMode') == 'BLEND'])


def signature(batches):
    return [[(entry[0][0], id(getattr(entry[0][2], 'entity', entry[0][2])),
              entry[0][3].tobytes(), entry[1].tobytes(), entry[2]) for entry in batch[1]]
            for batch in batches]


class RenderBatchTests(unittest.TestCase):
    def test_shared_snapshot_invalidates_batches_for_direct_material_and_array_edits(self):
        from mini3d.camera import Camera
        from mini3d.render_plan import build_render_plan
        from mini3d.scene_snapshot import scene_frame
        model = mesh({})
        scene = Scene()
        first, second = Entity(model), Entity(model)
        scene.add(first); scene.add(second)
        renderer = renderer_without_context()
        camera = Camera()
        def batches():
            with scene_frame(scene):
                plan = build_render_plan(scene, camera, 640, 480, culling=False)
                return renderer._persistent_batches(plan, plan.view)
        initial = batches()
        self.assertIs(initial[0], batches()[0])
        first.pos[0] = 4
        changed = batches()
        self.assertIsNot(initial[0][2], changed[0][2])
        model.material['alphaMode'] = 'MASK'
        self.assertEqual([len(batch[1]) for batch in batches()], [1, 1])
        model.material['alphaMode'] = 'BLEND'
        self.assertTrue(all(batch[1][0][0][0] for batch in batches()))

    def test_persistent_order_matches_standalone_after_edits(self):
        common = {}
        first, second = mesh(common), mesh(common)
        cutout, glass = mesh({'alphaMode': 'MASK'}), mesh({'alphaMode': 'BLEND'})
        entities = [Entity(model) for model in (first, first, second, first, first, cutout, glass)]
        entities[4].scale[0] = -1
        prepared = PreparedScene(entities)
        retained, reference = renderer_without_context(), renderer_without_context()
        changes = (lambda: None,
                   lambda: entities[2].pos.__setitem__(0, 10),
                   lambda: common.update(alphaMode='MASK'),
                   lambda: common.update(alphaMode='OPAQUE'),
                   lambda: prepared.scene.root_entities.reverse(),
                   lambda: setattr(entities[0], 'model', second),
                   lambda: setattr(entities[1], 'visible', False))
        for change in changes:
            change()
            plan = prepared.plan()
            actual = retained._persistent_batches(plan, np.eye(4))
            expected = reference._transient_batches(plan.shadow_candidates, np.eye(4), None, 'Lit')
            self.assertEqual(signature(actual), signature(expected))

    def test_camera_and_moving_floor_retain_static_payload(self):
        building = mesh({})
        entities = [Entity(building), Entity(building), Entity(mesh({'extras': {'photographicGround': True}}))]
        prepared = PreparedScene(entities)
        renderer = renderer_without_context()
        first = renderer._persistent_batches(prepared.plan(), np.eye(4))
        payload = first[0][2]
        self.assertIsNotNone(payload)
        entities[-1].pos[0] = 100
        view = np.eye(4); view[2, 3] = 4
        second = renderer._persistent_batches(prepared.plan(), view)
        self.assertIs(first[0], second[0])
        self.assertIs(payload, second[0][2])
        with self.assertRaises(ValueError):
            payload[0, 0] = 9
        entities[0].pos[0] = 2
        third = renderer._persistent_batches(prepared.plan(), view)
        self.assertIsNot(payload, third[0][2])
        building.material['doubleSided'] = True
        fourth = renderer._persistent_batches(prepared.plan(), view)
        self.assertIsNot(third[0], fourth[0])

    def test_visibility_removal_and_transparent_depth_order(self):
        opaque, glass = mesh({}), mesh({'alphaMode': 'BLEND'})
        entities = [Entity(opaque), Entity(opaque), Entity(glass), Entity(glass)]
        entities[-2].pos[2], entities[-1].pos[2] = -2, -8
        prepared = PreparedScene(entities)
        renderer = renderer_without_context()
        first = renderer._persistent_batches(prepared.plan(), np.eye(4))
        self.assertIs(first[-2][1][0][0][2].entity, entities[-1])
        view = np.eye(4); view[2, 2] = -1
        second = renderer._persistent_batches(prepared.plan(entities[1:]), view)
        self.assertIs(second[-2][1][0][0][2].entity, entities[-2])
        self.assertEqual(len(second[0][1]), 1)
        self.assertNotIn(id(entities[0]), [entry[1] for group in signature(second) for entry in group])

    def test_separated_same_mesh_batches_keep_independent_gpu_payloads(self):
        material = {}
        one, two = mesh(material), mesh(material)
        entities = [Entity(model) for model in (one, one, two, one, one)]
        renderer = renderer_without_context()
        batches = renderer._persistent_batches(PreparedScene(entities).plan(), np.eye(4))
        instanced = [batch for batch in batches if batch[2] is not None]
        self.assertEqual(len(instanced), 2)
        self.assertNotEqual(instanced[0][3], instanced[1][3])
        fake_gl = MagicMock()
        fake_gl.glGenVertexArrays.side_effect = [10, 11]
        fake_gl.glGenBuffers.side_effect = [20, 21]
        with patch('mini3d.material_renderer.gl', fake_gl):
            for _ in range(2):
                for batch in instanced:
                    renderer.draw_instances(renderer._mesh(one), payload=batch[2], cache_key=batch[3])
            self.assertEqual(fake_gl.glBufferData.call_count, 2)
            self.assertEqual(fake_gl.glDrawElementsInstanced.call_count, 4)
            renderer._instances[(id(one), False)] = [30, 40, b'shadow']
            keep = (id(one), instanced[1][3])
            renderer._prune_color_instances({keep})
            self.assertEqual(set(renderer._instances), {keep, (id(one), False)})
            fake_gl.glDeleteVertexArrays.assert_called_once_with(1, [10])
            fake_gl.glDeleteBuffers.assert_called_once_with(1, [20])

    def test_standalone_instances_still_detect_in_place_matrix_edits(self):
        renderer = renderer_without_context()
        matrices = np.tile(np.eye(4, dtype=np.float32), (2, 1, 1))
        fake_gl = MagicMock()
        fake_gl.glGenVertexArrays.return_value = 10
        fake_gl.glGenBuffers.return_value = 20
        resource = renderer._mesh(mesh({}))
        with patch('mini3d.material_renderer.gl', fake_gl):
            renderer.draw_instances(resource, matrices)
            renderer.draw_instances(resource, matrices)
            self.assertEqual(fake_gl.glBufferData.call_count, 1)
            matrices[0, 0, 3] = 5
            renderer.draw_instances(resource, matrices)
            self.assertEqual(fake_gl.glBufferData.call_count, 2)

    def test_retirement_preserves_caller_bindings_and_release_clears_owned_caches(self):
        renderer = renderer_without_context()
        key = (1, ('color_batch', (2, 3), False))
        renderer._instances[key] = [10, 20, np.zeros((2, 25), np.float32)]
        renderer._opaque_groups[1] = ('token', ['cached'])
        renderer._meshes, renderer._textures = {}, {}
        renderer.photo_environment, renderer.environment = MagicMock(), None
        fake_gl = MagicMock()
        with patch('mini3d.material_renderer.gl', fake_gl):
            renderer._prune_color_instances(set(), {'VERTEX_ARRAY_BINDING': 10, 'ARRAY_BUFFER_BINDING': 0})
            self.assertIn(key, renderer._instances)
            fake_gl.glDeleteVertexArrays.assert_not_called()
            renderer.release()
            self.assertFalse(renderer._instances)
            self.assertFalse(renderer._opaque_groups)
            fake_gl.glDeleteVertexArrays.assert_called_once_with(1, [10])
            fake_gl.glDeleteBuffers.assert_called_once_with(1, [20])


if __name__ == '__main__':
    unittest.main()
