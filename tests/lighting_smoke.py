"""Real GPU acceptance. --baseline captures the unchanged renderer before edits.

python -B tests/lighting_smoke.py [output-directory] [--baseline]
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from lighting_fixture import cube_geometry, write_pbr_cube
from mini3d.camera import Camera
from mini3d.gltf_loader import load_gltf
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.scene import Scene, Entity, Mesh
from mini3d.shot_camera import ShotCamera, render_shot

SIZE = (900, 600)


def run(output, baseline=False):
    output.mkdir(parents=True, exist_ok=True)
    fixture = output / 'pbr-cube.gltf'
    write_pbr_cube(fixture)
    pygame.init()
    pygame.display.set_mode(SIZE, pygame.OPENGL | pygame.DOUBLEBUF)
    renderer, target = GLRenderer(*SIZE), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    target.resize(*SIZE)
    scene = Scene()
    scene.show_grid = scene.show_axes = False
    pbr = load_gltf(fixture).instantiate()
    positions, normals, indices = cube_geometry()
    plain = Entity(Mesh(positions, indices, normals=normals), 'Plain geometry')
    plain.model.base_color = np.array([190, 140, 90], np.float32)
    scene.add(plain)
    scene.add(pbr)
    material = next(e.model.material for e in scene.get_flat_render_list()
                    if e.model.material is not None)
    assert 'KHR_materials_unlit' not in material.get('extensions', {})
    assert material['pbrMetallicRoughness']['metallicFactor'] == 0
    camera = Camera((4, -8, 5))
    camera.look_at((0, 0, 0))
    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(), baseline=baseline, probes={})

    def render(name=None):
        scene.update()
        target.bind()
        renderer.resize(*SIZE)
        gl.glDepthMask(True)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        renderer.render(scene, camera)
        rgb = gl.glReadPixels(0, 0, *SIZE, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        if name:
            pygame.image.save(pygame.image.fromstring(rgb, SIZE, 'RGB', True), str(output / (name+'.png')))
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return np.frombuffer(rgb, np.uint8).reshape(SIZE[1], SIZE[0], 3).copy()

    def sample(rgb, point):
        clip = camera.projection_matrix(SIZE[0]/SIZE[1]) @ camera.view_matrix @ np.append(point, 1)
        x, y = ((clip[:2]/clip[3]+1)*np.array(SIZE)/2).astype(int)
        assert 2 <= x < SIZE[0]-2 and 2 <= y < SIZE[1]-2
        return np.median(rgb[y-1:y+2, x-1:x+2], axis=(0, 1))

    try:
        # Identical geometry, camera, material and exposure before/after.
        plain.pos[0], pbr.pos[0] = -1.3, 1.3
        scene.light_dir = np.array([.8, -.15, .5])
        scene.ambient, scene.diffuse = .12, .9
        for view, position in (('a', (4, -8, 5)), ('b', (7, -5, 4))):
            camera.position = position
            camera.look_at((0, 0, 0))
            if baseline:
                render('before-'+view)
            else:
                for mode in ('Studio', 'Scene'):
                    scene.lighting_mode = mode
                    render(mode.lower()+'-'+view)
                before = output / ('before-'+view+'.png')
                if before.is_file():
                    old = pygame.surfarray.array3d(pygame.image.load(str(before)))
                    studio = pygame.surfarray.array3d(pygame.image.load(str(output / ('studio-'+view+'.png'))))
                    np.testing.assert_array_equal(old, studio)
                    report['studio_matches_baseline_'+view] = True
        if not baseline:
            # Probe the SAME WORLD faces, never the same screen coordinates.
            plain.pos[:] = pbr.pos[:] = 0
            scene.lighting_mode = 'Scene'
            scene.ambient, scene.diffuse = 0, 1
            scene.light_dir = np.array([5., 0, 0])  # normalization + sign
            for kind, active, inactive in (('plain', plain, pbr), ('pbr', pbr, plain)):
                active.visible, inactive.visible = True, False
                measurements = []
                for view, position, aim in (
                        ('a', (4, -6, 4), (0, 0, 0)),
                        ('orbit', (7, -3, 3), (0, 0, 0)),
                        ('translate', (7.4, -3, 3), None),
                        ('rotate', (7.4, -3, 3), (.2, .1, 0))):
                    camera.position = position
                    if aim is not None:
                        camera.look_at(aim)
                    rgb = render()
                    faces = [sample(rgb, point).tolist() for point in
                             ((.7, 0, 0), (0, -.7, 0), (0, 0, .7))]
                    assert min(faces[0]) > 30, (kind, view, faces)
                    assert max(faces[1]+faces[2]) == 0, (kind, view, faces)
                    measurements.append(dict(view=view, faces=faces))
                # GGX includes view-dependent Fresnel/specular, so brightness is
                # not required to be bit-identical. Lit/unlit faces must be stable.
                report['probes'][kind] = measurements
                scene.light_dir = np.array([0., -1, 0])
                rgb = render()
                assert max(sample(rgb, (.7, 0, 0))) == 0
                assert min(sample(rgb, (0, -.7, 0))) > 30
                scene.light_dir = np.array([5., 0, 0])
            # Zero direct and ambient strengths must leave no hidden studio light.
            scene.diffuse = 0
            rgb = render()
            for point in ((.7, 0, 0), (0, -.7, 0), (0, 0, .7)):
                assert max(sample(rgb, point)) == 0
            scene.diffuse = 1
            report['no_studio_light_leak'] = True
            # Studio cannot leak into either the Camera View or PNG pass.
            shot = ShotCamera(camera)
            scene.lighting_mode = 'Studio'
            render_shot(scene, shot, renderer, target)
            first = gl.glReadPixels(0, 0, *shot.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            scene.lighting_mode = 'Scene'
            render_shot(scene, shot, renderer, target)
            second = gl.glReadPixels(0, 0, *shot.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            assert first == second
            report['shot_independent_of_editor_mode'] = True
        (output / ('baseline.json' if baseline else 'results.json')).write_text(
            json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps(report))
    finally:
        target.close()
        if hasattr(renderer, 'material_renderer'):
            renderer.material_renderer.close()
        pygame.quit()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--baseline']
    run(Path(args[0]) if args else ROOT/'captures/lighting', '--baseline' in sys.argv)
