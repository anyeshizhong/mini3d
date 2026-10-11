"""Legacy demo semantics must survive moving and sharing their scene types."""
import importlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pygame

from examples.legacy_scene import Entity, Mesh, Scene
from mini3d.math3d import get_rotation_matrix
from mini3d.urdf_loader import build_entity_tree, joint_transform, load_urdf


class ExampleCompatibilityTests(unittest.TestCase):
    def test_named_examples_share_types_without_opening_a_window(self):
        initialized = pygame.display.get_init()
        for name in ('primitives', 'circular_motion', 'urdf_car'):
            module = importlib.import_module('examples.' + name)
            self.assertIs(module.Entity, Entity)
            self.assertIs(module.Mesh, Mesh)
            self.assertTrue(issubclass(module.Scene, Scene))
        self.assertEqual(pygame.display.get_init(), initialized)

    def test_geometry_and_urdf_keep_their_original_flattening_rules(self):
        for name in ('primitives', 'circular_motion', 'urdf_car'):
            module = importlib.import_module('examples.' + name)
            scene = module.Scene()
            axes = Entity(name='axes-only')
            axes.isaxes = True
            mesh = Entity(Mesh([[0,0,0],[1,0,0],[0,1,0]], [[0,1,2]]))
            axes.add_child(mesh)
            scene.add(axes)
            expected = [axes, mesh] if name == 'urdf_car' else [mesh]
            self.assertEqual(scene.get_flat_render_list(), expected, name)

    def test_extra_transform_precedes_legacy_pose_and_scale(self):
        parent = Entity(pos=[3, -2, 1], rot=[.2, -.3, .1], scale=2)
        child = Entity(pos=[1, 2, 3], rot=[-.4, .5, -.6], scale=.25)
        child.extra_local = joint_transform([4, 1, -2], [.3, -.2, .4], [0, 0, 1], .7)
        parent.add_child(child)
        parent.update_transform()
        expected = np.eye(4)
        expected[:3, :3] = get_rotation_matrix(*child.rot) * child.scale
        expected[:3, 3] = child.pos
        np.testing.assert_allclose(child.world_matrix,
                                   parent.world_matrix @ child.extra_local @ expected,
                                   rtol=1e-6, atol=1e-6)

    def test_shared_scene_keeps_axes_only_urdf_nodes(self):
        scene = Scene()
        container = Entity(name='link')
        axes = Entity(name='axes')
        axes.isaxes = True
        geometry = Entity(Mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]))
        container.add_child(axes)
        axes.add_child(geometry)
        scene.add(container)
        self.assertEqual(scene.get_flat_render_list(), [axes, geometry])

    def test_urdf_adapter_preserves_joint_hierarchy(self):
        xml = '''<robot name="fixture">
          <link name="base"/><link name="wheel"/>
          <joint name="axle" type="continuous">
            <parent link="base"/><child link="wheel"/>
            <origin xyz="1 2 3" rpy="0.1 0.2 0.3"/><axis xyz="0 1 0"/>
          </joint></robot>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.urdf'
            path.write_text(xml, encoding='utf8')
            robot = load_urdf(str(path))
        entities, order = build_entity_tree(robot, EntityClass=Entity,
                                           model_loader=lambda *_: None)
        self.assertEqual(order, ['axle'])
        self.assertIs(entities['wheel'].parent, entities['base'])
        entities['base'].scale = 1000
        entities['base'].update_transform()
        np.testing.assert_allclose(entities['wheel'].world_matrix[:3, 3], [1000, 2000, 3000])
