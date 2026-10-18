"""Contracts for the shared Arrange/Shot native renderer adapter."""
import contextlib
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

from mini3d import native_renderer, scene_snapshot
from mini3d import atmosphere as atmosphere_module


class _FakeLibrary:
    def __init__(self):
        self.created = []
        self.shared_created = []
        self.destroyed = []
        self.rendered = []
        self.transform_calls = []
        self.transform_result = 1

    def spqr_photo_create(self, directory, width, height, samples):
        handle = object()
        self.created.append((handle, directory, width, height, samples))
        return handle

    def spqr_photo_create_shared(self, directory, width, height, samples):
        handle = object()
        self.shared_created.append((handle, directory, width, height, samples))
        return handle

    def spqr_photo_resize(self, handle, width, height, samples):
        return 1

    def spqr_photo_globals(self, *args):
        return 1

    def spqr_photo_transforms(self, handle, indices, matrices, normals, winding, count):
        uints = ctypes.POINTER(ctypes.c_uint32)
        doubles = ctypes.POINTER(ctypes.c_double)
        floats = ctypes.POINTER(ctypes.c_float)
        count = int(count)
        self.transform_calls.append((
            handle,
            np.ctypeslib.as_array(ctypes.cast(indices, uints), shape=(count,)).copy(),
            np.ctypeslib.as_array(ctypes.cast(matrices, doubles),
                                  shape=(count * 16,)).copy().reshape(count, 4, 4),
            np.ctypeslib.as_array(ctypes.cast(normals, floats),
                                  shape=(count * 9,)).copy().reshape(count, 3, 3),
            np.ctypeslib.as_array(ctypes.cast(winding, uints), shape=(count,)).copy(),
        ))
        return self.transform_result

    def spqr_photo_last_error(self):
        return b"fake transform failure"

    def spqr_photo_render(self, handle, camera, target, stats):
        self.rendered.append((handle, target))
        values = ctypes.cast(stats, ctypes.POINTER(ctypes.c_double))
        values[0] = 0.1
        values[1] = 100.0
        return 1

    def spqr_photo_destroy(self, handle):
        self.destroyed.append(handle)
        return 1


class NativeRendererContractTests(unittest.TestCase):
    def _native_import_stubs(self):
        gl = types.SimpleNamespace(
            GL_FRAMEBUFFER=0x8D40,
            glBindFramebuffer=Mock(),
            glViewport=Mock(),
        )
        opengl = types.ModuleType("OpenGL")
        opengl.GL = gl

        bundle = types.ModuleType("mini3d.native_photo_bundle")
        bundle.export_live_bundle = Mock()
        bundle.export_live_bundle.return_value = {"entity_bindings": []}
        bundle.collect_live_globals = Mock(return_value=([], []))
        bundle.pack_globals = Mock(return_value=b"globals")

        atmosphere = types.ModuleType("mini3d.atmosphere")
        atmosphere.atmosphere_state = Mock(return_value={"ground_z": 0.0})

        lighting = types.ModuleType("mini3d.lighting")
        lighting.scene_light_direction = Mock(return_value=np.array([0.0, 0.0, 1.0]))
        return gl, {
            "OpenGL": opengl,
            "OpenGL.GL": gl,
            "mini3d.native_photo_bundle": bundle,
            "mini3d.atmosphere": atmosphere,
            "mini3d.lighting": lighting,
        }

    def _render_arguments(self):
        camera = types.SimpleNamespace(
            position=np.array([1.0, 2.0, 3.0]),
            rotation=np.eye(3),
            view_matrix=np.eye(4),
            near=0.1,
            far=100.0,
            projection_matrix=lambda aspect: np.eye(4),
        )
        target = types.SimpleNamespace(framebuffer=37)
        scene = types.SimpleNamespace()
        return scene, camera, target

    def test_workspace_setting_overrides_common_backend_and_python_disables_native(self):
        with patch.dict(os.environ, {
            "MINI3D_RENDER_BACKEND": "native",
            "MINI3D_ARRANGE_BACKEND": "python",
        }, clear=True):
            self.assertEqual(native_renderer.backend_policy("arrange"), ("python", False))
            self.assertEqual(native_renderer.backend_policy("shot"), ("native", True))
            owner = types.SimpleNamespace()
            self.assertIsNone(native_renderer.scene_backend(owner, "arrange"))
            self.assertFalse(hasattr(owner, "native_renderer"))

        with patch.dict(os.environ, {
            "MINI3D_RENDER_BACKEND": "python",
            "MINI3D_PHOTO_BACKEND": "native",
        }, clear=True):
            self.assertEqual(native_renderer.backend_policy("arrange"), ("python", False))
            self.assertEqual(native_renderer.backend_policy("shot"), ("native", True))

        with patch.dict(os.environ, {"MINI3D_REQUIRE_NATIVE_PHOTO": "1"}, clear=True):
            self.assertEqual(native_renderer.backend_policy("arrange"), ("auto", False))
            self.assertEqual(native_renderer.backend_policy("shot"), ("auto", True))
        with patch.dict(os.environ, {"MINI3D_RENDER_BACKEND": "python",
                                     "MINI3D_REQUIRE_NATIVE_RENDER": "1"}, clear=True):
            for workspace in ("arrange", "shot"):
                with self.assertRaises(native_renderer.NativeRenderError):
                    native_renderer.backend_policy(workspace)

    def test_required_native_mode_raises_when_the_dll_cannot_load(self):
        gl, modules = self._native_import_stubs()
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())
        native._keys = lambda scene, camera: (("scene",), ("settings",))
        scene, camera, target = self._render_arguments()
        with patch.dict(sys.modules, modules), \
                patch.object(native_renderer, "preserved_native_state",
                             return_value=contextlib.nullcontext()), \
                patch.object(native_renderer.ctypes, "CDLL",
                             side_effect=OSError("spqr_photo.dll is missing")):
            with self.assertRaisesRegex(native_renderer.NativeRenderError, "missing"):
                native.render(scene, camera, target, (320, 200), 1,
                              workspace="arrange", required=True)
            with patch.dict(os.environ, {"MINI3D_REQUIRE_NATIVE_PHOTO": "1"}, clear=True):
                with self.assertRaisesRegex(native_renderer.NativeRenderError, "missing"):
                    native.render(scene, camera, target, (320, 200), 1)
        gl.glBindFramebuffer.assert_not_called()

    def test_old_dll_without_shared_texture_entrypoint_requests_rebuild(self):
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())
        old_library = types.SimpleNamespace(
            spqr_photo_abi_version=Mock(return_value=1),
            spqr_photo_last_error=Mock(return_value=b""),
            spqr_photo_create=Mock(),
        )
        with patch.object(native_renderer.ctypes, "CDLL", return_value=old_library):
            with self.assertRaisesRegex(
                    native_renderer.NativeRenderError,
                    "Rebuild spqr_photo.dll: shared texture API is missing"):
                native._load()
        self.assertIsNone(native.library)

    def test_shared_texture_dll_without_transform_entrypoint_requests_rebuild(self):
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())
        library = types.SimpleNamespace(
            spqr_photo_abi_version=Mock(return_value=1),
            spqr_photo_last_error=Mock(return_value=b""),
            spqr_photo_create=Mock(),
            spqr_photo_create_shared=Mock(),
        )
        with patch.object(native_renderer.ctypes, "CDLL", return_value=library):
            with self.assertRaisesRegex(
                    native_renderer.NativeRenderError,
                    "Rebuild spqr_photo.dll: transform update API is missing"):
                native._load()
        self.assertIsNone(native.library)

    def test_cached_native_failure_is_reported_and_strict_mode_still_raises(self):
        _gl, modules = self._native_import_stubs()
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())
        resource, parameters = ("scene",), ("settings",)
        native._keys = lambda scene, camera: (resource, parameters)
        native.failed_key = (resource, parameters, (320, 200), 1)
        native.last_reason = "spqr_photo.dll is missing"
        scene, camera, target = self._render_arguments()

        with patch.dict(sys.modules, modules), \
                patch.object(native_renderer, "preserved_native_state",
                             return_value=contextlib.nullcontext()):
            self.assertFalse(native.render(scene, camera, target, (320, 200), 1,
                                           workspace="arrange", required=False))
            with self.assertRaisesRegex(native_renderer.NativeRenderError, "missing"):
                native.render(scene, camera, target, (320, 200), 1,
                              workspace="arrange", required=True)

    def test_disabled_and_cached_failure_routes_are_visible_in_python_stats(self):
        gl, modules = self._native_import_stubs()
        gl.GL_SCISSOR_TEST = 0x0C11
        gl.GL_MULTISAMPLE = 0x809D
        gl.glDisable = Mock()
        gl.glDepthMask = Mock()
        gl.glIsEnabled = Mock(return_value=False)
        gl.glEnable = Mock()
        render_target_module = types.ModuleType("mini3d.render_target")
        render_target_module.RenderTarget = types.SimpleNamespace(
            validate_samples=lambda samples: samples)

        def run_scene(workspace_env, expected_backend, failing_native=None):
            scene = types.SimpleNamespace(render_mode="Lit")
            camera = types.SimpleNamespace(position=np.zeros(3))
            target = types.SimpleNamespace(
                resize=Mock(), bind=Mock(), resolve=Mock(), render_camera=None)
            renderer = types.SimpleNamespace(
                resize=Mock(), render=Mock(), render_stats={})
            patches = [
                patch.dict(sys.modules, {**modules,
                                        "mini3d.render_target": render_target_module}),
                patch.dict(os.environ, workspace_env, clear=True),
                patch.object(scene_snapshot, "scene_frame",
                      return_value=contextlib.nullcontext()),
            ]
            if failing_native is not None:
                patches.append(patch.object(native_renderer, "scene_backend",
                                            return_value=failing_native))
            with contextlib.ExitStack() as stack:
                for active_patch in patches:
                    stack.enter_context(active_patch)
                from mini3d.scene_renderer import render_scene
                render_scene(scene, camera, renderer, target, (320, 200),
                             workspace="arrange")
            self.assertEqual(renderer.render_stats["backend"], expected_backend)
            self.assertTrue(renderer.render.called)
            return renderer.render_stats

        disabled_stats = run_scene(
            {"MINI3D_ARRANGE_BACKEND": "python"}, "python")
        self.assertNotIn("native_fallback_reason", disabled_stats)

        failed_native = types.SimpleNamespace(
            last_reason="cached DLL load failure",
            render=Mock(return_value=False))
        fallback_stats = run_scene(
            {"MINI3D_ARRANGE_BACKEND": "auto"},
            "python-fallback", failing_native=failed_native)
        self.assertEqual(fallback_stats["native_fallback_reason"],
                         "cached DLL load failure")
        failed_native.render.assert_called_once()

    def test_studio_camera_rotation_invalidates_parameters_but_scene_lighting_does_not(self):
        geometry = types.SimpleNamespace(geometry_revision=3, material_revision=5)
        atmosphere = {"enabled": False, "ground": False,
                      "ground_texture": "procedural", "sky_texture": "procedural"}
        scene = types.SimpleNamespace(
            lighting_mode="Studio", render_mode="Lit", environment_enabled=False,
            _atmosphere={},
        )
        camera = types.SimpleNamespace(rotation=np.eye(3))
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())

        with patch.object(scene_snapshot, "snapshot", return_value=geometry), \
                patch.object(atmosphere_module, "atmosphere_state", return_value=atmosphere):
            _resource_a, studio_a = native._keys(scene, camera)
            camera.rotation = np.array([[0.0, -1.0, 0.0],
                                        [1.0,  0.0, 0.0],
                                        [0.0,  0.0, 1.0]])
            _resource_b, studio_b = native._keys(scene, camera)
            self.assertNotEqual(studio_a, studio_b)

            scene.lighting_mode = "Scene"
            _resource_c, scene_a = native._keys(scene, camera)
            camera.rotation = np.eye(3)
            _resource_d, scene_b = native._keys(scene, camera)
            self.assertEqual(scene_a, scene_b)

    def test_transform_sync_updates_only_changed_leaf_entities(self):
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())
        library = _FakeLibrary()
        native.library = library
        native.handle = object()

        unchanged_ground = None
        first_world = np.eye(4, dtype=np.float64)
        unchanged_world = np.eye(4, dtype=np.float64)
        last_world = np.eye(4, dtype=np.float64)
        first = types.SimpleNamespace(world_matrix=first_world.copy())
        unchanged = types.SimpleNamespace(world_matrix=unchanged_world.copy())
        last = types.SimpleNamespace(world_matrix=last_world.copy())
        native.entity_bindings = [first, unchanged_ground, unchanged, last]
        native.entity_matrices = [first_world.tobytes(), None,
                                  unchanged_world.tobytes(), last_world.tobytes()]

        first.world_matrix[0, 3] = 5.0
        last.world_matrix[1, 3] = -2.0
        unchanged_cache = native.entity_matrices[2]
        native._sync_transforms()

        self.assertEqual(len(library.transform_calls), 1)
        _handle, indices, matrices, normals, winding = library.transform_calls[0]
        np.testing.assert_array_equal(indices, np.array([0, 3], dtype=np.uint32))
        np.testing.assert_array_equal(matrices[0], first.world_matrix)
        np.testing.assert_array_equal(matrices[1], last.world_matrix)
        self.assertEqual(normals.shape, (2, 3, 3))
        np.testing.assert_array_equal(winding, np.zeros(2, dtype=np.uint32))
        self.assertEqual(native.entity_matrices[0], first.world_matrix.tobytes())
        self.assertIsNone(native.entity_matrices[1])
        self.assertEqual(native.entity_matrices[2], unchanged_cache)
        self.assertEqual(native.entity_matrices[3], last.world_matrix.tobytes())
        self.assertEqual(native.transform_updates, 1)

    def test_failed_transform_sync_does_not_commit_entity_matrix_cache(self):
        native = native_renderer.NativeSceneRenderer(types.SimpleNamespace())
        library = _FakeLibrary()
        library.transform_result = 0
        native.library = library
        native.handle = object()
        initial = np.eye(4, dtype=np.float64)
        entity = types.SimpleNamespace(world_matrix=initial.copy())
        native.entity_bindings = [entity]
        native.entity_matrices = [initial.tobytes()]
        entity.world_matrix[2, 3] = 3.0

        with self.assertRaisesRegex(native_renderer.NativeRenderError,
                                   "fake transform failure"):
            native._sync_transforms()

        self.assertEqual(native.entity_matrices, [initial.tobytes()])
        self.assertEqual(native.transform_updates, 0)
        self.assertEqual(len(library.transform_calls), 1)

    def test_geometry_revision_does_not_rebuild_bundle_but_material_revision_does(self):
        gl, modules = self._native_import_stubs()
        bundle_stub = modules["mini3d.native_photo_bundle"]
        atmosphere_stub = modules["mini3d.atmosphere"]
        atmosphere_stub.atmosphere_state.return_value = {
            "enabled": False, "ground": False,
            "ground_texture": "procedural", "sky_texture": "procedural",
            "ground_z": 0.0,
        }
        geometry = types.SimpleNamespace(geometry_revision=1, material_revision=4)
        owner = types.SimpleNamespace()
        native = native_renderer.NativeSceneRenderer(owner)
        native.library = _FakeLibrary()
        scene, camera, target = self._render_arguments()

        with tempfile.TemporaryDirectory() as work, \
                patch.dict(sys.modules, modules), \
                patch.object(native_renderer, "preserved_native_state",
                             return_value=contextlib.nullcontext()), \
                patch.object(scene_snapshot, "snapshot", return_value=geometry):
            native.root = Path(work) / "native"
            self.assertTrue(native.render(scene, camera, target, (320, 200), 1,
                                          workspace="arrange", required=True))
            initial_resource = native.resource_key
            self.assertEqual(native.bundle_builds, 1)

            geometry.geometry_revision += 1
            resource_after_transform, _parameters = native._keys(scene, camera)
            self.assertEqual(resource_after_transform, initial_resource)
            self.assertTrue(native.render(scene, camera, target, (320, 200), 1,
                                          workspace="arrange", required=True))
            self.assertEqual(native.bundle_builds, 1)
            self.assertEqual(bundle_stub.export_live_bundle.call_count, 1)

            # SceneSnapshot advances material_revision for render-list and
            # mesh/material changes, so these still cross the bundle boundary.
            geometry.material_revision += 1
            resource_after_topology, _parameters = native._keys(scene, camera)
            self.assertNotEqual(resource_after_topology, initial_resource)
            self.assertTrue(native.render(scene, camera, target, (320, 200), 1,
                                          workspace="arrange", required=True))
            self.assertEqual(native.bundle_builds, 2)
            self.assertEqual(bundle_stub.export_live_bundle.call_count, 2)
            self.assertEqual(len(native.library.destroyed), 1)
            native.close()

        gl.glBindFramebuffer.assert_called()

    def test_close_releases_handle_and_a_later_render_rebuilds_it(self):
        gl, modules = self._native_import_stubs()
        bundle_stub = modules["mini3d.native_photo_bundle"]
        owner = types.SimpleNamespace()
        native = native_renderer.NativeSceneRenderer(owner)
        library = _FakeLibrary()
        native.library = library
        resource, parameters = ("scene",), ("settings",)
        native._keys = lambda scene, camera: (resource, parameters)
        scene, camera, target = self._render_arguments()

        with tempfile.TemporaryDirectory() as work, \
                patch.dict(sys.modules, modules), \
                patch.object(native_renderer, "preserved_native_state",
                             return_value=contextlib.nullcontext()):
            native.root = Path(work) / "native"
            self.assertTrue(native.render(scene, camera, target, (320, 200), 1,
                                          workspace="arrange", required=True))
            first_handle = native.handle
            self.assertEqual(owner.render_stats["backend"], "native-arrange")
            self.assertEqual(native.bundle_builds, 1)
            self.assertEqual(len(library.shared_created), 1)
            self.assertEqual(bundle_stub.export_live_bundle.call_args.kwargs,
                             {"shared_textures": True})

            native.close()
            self.assertIsNone(native.handle)
            self.assertIsNone(native.resource_key)
            self.assertEqual(library.destroyed, [first_handle])

            self.assertTrue(native.render(scene, camera, target, (320, 200), 1,
                                          workspace="shot", required=True))
            self.assertIsNot(native.handle, first_handle)
            self.assertEqual(owner.render_stats["backend"], "native-photo")
            self.assertEqual(native.bundle_builds, 2)
            self.assertEqual(len(library.shared_created), 2)
            self.assertEqual(len(library.rendered), 2)
            native.close()

        gl.glBindFramebuffer.assert_called()
        gl.glViewport.assert_called()

    def test_shared_texture_protocol_deduplicates_without_readback_and_keeps_v1_capture(self):
        from mini3d import native_photo_bundle

        helpers = native_photo_bundle._export_helpers()
        gl = types.SimpleNamespace(GL_TEXTURE_2D=0x0DE1,
                                   GL_TEXTURE_CUBE_MAP=0x8513)
        texture_handle = 41
        records, by_handle = [], {}

        with patch.object(helpers, "capture_texture",
                          return_value={"target": gl.GL_TEXTURE_2D}) as capture:
            first = native_photo_bundle._add_texture(
                texture_handle, gl.GL_TEXTURE_2D, gl, records, by_handle,
                helpers, True)
            duplicate = native_photo_bundle._add_texture(
                texture_handle, gl.GL_TEXTURE_2D, gl, records, by_handle,
                helpers, True)
            self.assertEqual(first, 0)
            self.assertEqual(duplicate, first)
            self.assertEqual(records, [{"handle": texture_handle,
                                        "target": gl.GL_TEXTURE_2D}])
            capture.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "conflicting targets"):
                native_photo_bundle._add_texture(
                    texture_handle, gl.GL_TEXTURE_CUBE_MAP, gl, records,
                    by_handle, helpers, True)
            capture.assert_not_called()

            # Live v2 carries only (target, GL handle); it must not serialize
            # the texture's mip payload after the two empty uniform blocks.
            from mini3d.scene import Scene
            with tempfile.TemporaryDirectory() as work:
                path = Path(work) / "scene.bin"
                helpers.write_scene_binary(
                    path, records, [], [], [], [], [], [], Scene(), 0.0, gl,
                    shared_textures=True)
                payload = path.read_bytes()
            self.assertEqual(payload[:8], b"SPQRN001")
            self.assertEqual(int.from_bytes(payload[8:12], "little"), 2)
            self.assertEqual(int.from_bytes(payload[12:16], "little"), 1)
            self.assertEqual(int.from_bytes(payload[16:20], "little"),
                             gl.GL_TEXTURE_2D)
            self.assertEqual(int.from_bytes(payload[20:24], "little"),
                             texture_handle)
            self.assertEqual(payload[24:32], b"\0" * 8)

            # The legacy/offline route still delegates to pixel capture once
            # per distinct handle and therefore remains v1 compatible.
            legacy_records, legacy_by_handle = [], {}
            native_photo_bundle._add_texture(
                texture_handle, gl.GL_TEXTURE_2D, gl, legacy_records,
                legacy_by_handle, helpers, False)
            native_photo_bundle._add_texture(
                texture_handle, gl.GL_TEXTURE_2D, gl, legacy_records,
                legacy_by_handle, helpers, False)
            capture.assert_called_once_with(texture_handle, gl.GL_TEXTURE_2D, gl)


if __name__ == "__main__":
    unittest.main()
