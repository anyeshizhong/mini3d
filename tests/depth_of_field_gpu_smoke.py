"""Real GPU focus swaps, aperture response, PNG parity, reload and GL lifetime.

python -B tests/depth_of_field_gpu_smoke.py [new-output-directory]
Generated textured planes at 2m/8m are saved as a real importable glTF fixture.
"""
import base64
import io
import json
from pathlib import Path
import sys
import time
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot, render_scene_view
from mini3d.gl_state import read_rgb, save_state, restore_state
from tools.capture_sunset import desktop_context


def write_fixture(output):
    xy = np.indices((128, 128))
    checker = (((xy[0] // 8 + xy[1] // 8) % 2) * 210 + 25).astype(np.uint8)
    rgb = np.repeat(checker[..., None], 3, axis=2)
    image = pygame.image.fromstring(rgb.tobytes(), (128, 128), 'RGB')
    encoded = io.BytesIO(); pygame.image.save(image, encoded, 'checker.png')
    positions = np.array([[-.5, 0, .5], [.5, 0, .5], [.5, 0, -.5], [-.5, 0, -.5]], '<f4')
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], '<f4')
    indices = np.array([0, 1, 2, 0, 2, 3], '<u4')
    chunks = [positions.tobytes(), uv.tobytes(), indices.tobytes()]
    blob = b''.join(chunks)
    document = dict(asset={'version': '2.0'}, scene=0, scenes=[{'nodes': [0]}],
        nodes=[{'mesh': 0}], meshes=[{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
            'indices': 2, 'material': 0}]}],
        buffers=[{'byteLength': len(blob), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(blob).decode()}],
        bufferViews=[{'buffer': 0, 'byteOffset': offset, 'byteLength': len(chunk)}
                     for offset, chunk in zip((0, len(chunks[0]), len(chunks[0])+len(chunks[1])), chunks)],
        accessors=[{'bufferView': 0, 'componentType': 5126, 'count': 4, 'type': 'VEC3'},
                   {'bufferView': 1, 'componentType': 5126, 'count': 4, 'type': 'VEC2'},
                   {'bufferView': 2, 'componentType': 5125, 'count': 6, 'type': 'SCALAR'}],
        images=[{'uri': 'data:image/png;base64,' + base64.b64encode(encoded.getvalue()).decode()}],
        textures=[{'source': 0, 'sampler': 0}], samplers=[{'magFilter': 9728, 'minFilter': 9728}],
        materials=[{'doubleSided': True, 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                     'metallicFactor': 0, 'roughnessFactor': 1}, 'extensions': {'KHR_materials_unlit': {}}}],
        extensionsUsed=['KHR_materials_unlit'])
    path = output / 'focus-checker.gltf'
    path.write_text(json.dumps(document), encoding='utf8')
    return path


def image_pixels(path):
    return pygame.surfarray.array3d(pygame.image.load(str(path))).transpose(1, 0, 2)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    fixture = write_fixture(output)
    with desktop_context():
        renderer = GLRenderer(960, 640); renderer.render_mode = 'REALISTIC'
        target, caller = RenderTarget(), RenderTarget()
        api = Mini3DAPI(renderer)
        try:
            api.spawn(fixture, position=[-.2, 0, -2], scale=[.3]*3)
            api.spawn(fixture, position=[.8, 0, -8], scale=[1.2]*3)
            api.create_shot_camera(position=[0, 0, 0], target=[0, 0, -2], focal_mm=85,
                                   aspect='3:2', near=.01, far=100)
            api.set_antialiasing(4)
            scene, shot = api._app.scene, api._app.shot_camera
            scene.update()
            report = {'gpu': gl.glGetString(gl.GL_RENDERER).decode(), 'checks': {}}
            def frame(name):
                start = time.perf_counter()
                render_scene_view(scene, shot, renderer, target, (960, 640), 4)
                rgb = np.frombuffer(read_rgb(0, 0, 960, 640), np.uint8).reshape(640, 960, 3)[::-1].copy()
                pygame.image.save(pygame.image.fromstring(rgb.tobytes(), (960, 640), 'RGB'), str(output/(name+'.png')))
                report.setdefault('frame_ms', {})[name] = round((time.perf_counter()-start)*1000, 2)
                return rgb
            sharp = frame('disabled')
            original_depth = np.array(gl.glReadPixels(0, 0, 960, 640, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT))
            api.set_depth_of_field(True, 2, 1.4)
            near = frame('focus-near-f1.4')
            np.testing.assert_array_equal(original_depth, gl.glReadPixels(0, 0, 960, 640, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT))
            left, right = (slice(240, 400), slice(195, 335)), (slice(240, 400), slice(625, 765))
            def detail(image, region):
                patch = image[region].astype(float).mean(axis=2)
                return float(np.mean(np.abs(np.diff(patch, axis=0))) + np.mean(np.abs(np.diff(patch, axis=1))))
            assert np.max(np.abs(near[left].astype(int)-sharp[left].astype(int))) <= 1, 'Focus plane lost sharpness'
            assert detail(near, right) < detail(sharp, right)*.65, 'Distant plane did not blur'
            api.set_depth_of_field(focus_distance=8)
            far = frame('focus-far-f1.4')
            assert np.max(np.abs(far[right].astype(int)-sharp[right].astype(int))) <= 1, 'Far focus plane lost sharpness'
            assert detail(far, left) < detail(sharp, left)*.65, 'Near plane did not blur'
            api.set_depth_of_field(focus_distance=2, f_number=16)
            stopped = frame('focus-near-f16')
            assert detail(stopped, right) > detail(near, right)*1.15, 'Stopping down did not restore detail'
            report['detail'] = {name: [detail(image, left), detail(image, right)] for name, image in
                                [('disabled', sharp), ('near', near), ('far', far), ('f16', stopped)]}
            report['checks']['focus_swap_aperture_response_and_depth_unchanged'] = True
            api.set_depth_of_field(True, 2, 1.4)
            render_shot(scene, shot, renderer, target)
            preview = np.frombuffer(read_rgb(0, 0, *shot.size), np.uint8).reshape(1280, 1920, 3)[::-1].copy()
            caller.bind(); gl.glViewport(3, 4, 11, 13)
            api.capture(output/'export.png')
            assert int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)) == caller.framebuffer
            np.testing.assert_array_equal(gl.glGetIntegerv(gl.GL_VIEWPORT), [3, 4, 11, 13])
            np.testing.assert_array_equal(preview, image_pixels(output/'export.png'))
            api.save_scene(output/'scene.json')
            fresh = Mini3DAPI(renderer); fresh.load_scene(output/'scene.json')
            fresh.capture(output/'reload.png')
            np.testing.assert_array_equal(preview, image_pixels(output/'reload.png'))
            report['checks']['full_resolution_preview_png_reload_exact'] = True
            # Adversarial caller state is restored by the depth filter itself.
            target.bind(); gl.glEnable(gl.GL_SCISSOR_TEST); gl.glScissor(1, 2, 3, 4)
            gl.glEnable(gl.GL_BLEND); gl.glColorMask(False, True, False, True)
            gl.glActiveTexture(gl.GL_TEXTURE5)
            expected = save_state(); gl.glActiveTexture(expected['ACTIVE_TEXTURE'])
            renderer.depth_of_field.apply(target, shot)
            actual = save_state()
            for key in expected:
                if isinstance(expected[key], np.ndarray):
                    np.testing.assert_array_equal(expected[key], actual[key])
                else:
                    assert expected[key] == actual[key], 'GL state leaked: '+key
            restore_state(expected)
            assert gl.glGetError() == gl.GL_NO_ERROR
            report['checks']['filter_caller_gl_state_preserved'] = True
            handles = (renderer.depth_of_field.program, renderer.depth_of_field.vao,
                       renderer.depth_of_field.depth_texture, renderer.depth_of_field.output.texture)
            renderer.close(); renderer.close()
            assert not gl.glIsProgram(handles[0]) and not gl.glIsVertexArray(handles[1])
            assert not gl.glIsTexture(handles[2]) and not gl.glIsTexture(handles[3])
            report['checks']['idempotent_resource_cleanup'] = True
            report['passed'] = True
            (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps(report, indent=2))
        finally:
            target.close(); caller.close(); renderer.close()


if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/depth-of-field')
