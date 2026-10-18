"""Real Scene v3 shadow-fit motion, observed through a fixed Python photo camera.

Only the shadow camera moves; color/depth observation stays fixed to isolate
shadow changes. This correctness diagnostic does not measure frame rate.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['MINI3D_PHOTO_BACKEND'] = 'python'

import numpy as np
from OpenGL import GL as gl
from PIL import Image
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.lighting import scene_light_direction
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_scene_view
from mini3d.shadow_map import ShadowMap
from mini3d import shadow_map
from mini3d.atmosphere import atmosphere_state, prepare_photographic_scene
from mini3d.scene_snapshot import snapshot
from tools.capture_sunset import desktop_context


def run(scene_file, output, frames, ground='saved', size=(960, 540)):
    output.mkdir(parents=True, exist_ok=True)
    report = dict(scene=str(scene_file), backend='python',
                  method='Fixed observation camera; only actual shadow fit follows the API camera track. Not a frame-time benchmark.',
                  size=list(size), runs=[])
    with desktop_context():
        renderer, target = GLRenderer(800, 600), RenderTarget()
        try:
            api = Mini3DAPI(renderer)
            api.load_scene(str(scene_file))
            if ground != 'saved':
                api.set_atmosphere(ground=ground == 'on')
            scene = api._app.scene
            scene.update()
            entities = scene.get_flat_render_list()
            observer = deepcopy(api._app.shot_camera)
            if observer is None:
                raise ValueError('Scene needs a saved Shot camera')
            report.update(camera=observer.to_dict(), renderer=gl.glGetString(gl.GL_RENDERER).decode(),
                          resolution=scene.shadow_resolution, bias=scene.shadow_bias, pcf=scene.shadow_pcf,
                          atmosphere=atmosphere_state(scene),
                          fit_geometry='Actual photographic overlay and prepared geometry for every moving pose')
            api.save_scene(str(output / 'scene.json'))
            direction = scene_light_direction(scene)
            for track, vector in (('lateral', observer.rotation[:, 0] * .2),
                                  ('dolly', -observer.rotation[:, 2] * 3)):
                poses = []
                for amount in np.linspace(0, 1, frames):
                    api.set_shot_camera_pose(position=(observer.position + vector * amount).tolist(),
                                             rotation=observer.rotation.tolist())
                    poses.append(deepcopy(api._app.shot_camera))
                for mode in ('legacy', 'stabilized'):
                    folder = output / (track + '-' + mode)
                    folder.mkdir(exist_ok=True)
                    (folder / 'poses.json').write_text(json.dumps([cam.to_dict() for cam in poses], indent=2))
                    renderer.shadow_map.close()
                    renderer.shadow_map = ShadowMap()
                    # Initialize the production material renderer before direct
                    # shadow-pass control. The observer never advances fit/fade.
                    render_scene_view(scene, observer, renderer, target, size, observer.samples)
                    renderer.shadow_map.close()
                    renderer.shadow_map = ShadowMap()
                    audited = renderer.shadow_map
                    fit_ground = None
                    common = None
                    previous, first, trace, max_step, max_image = None, None, [], -1, None
                    for index, camera in enumerate(poses):
                        fit_scene, fit_ground = prepare_photographic_scene(scene, camera, fit_ground)
                        geometry = snapshot(fit_scene)
                        if mode == 'legacy':
                            audited._fit_state.clear()  # Original fit has no depth hysteresis.
                            with patch('mini3d.shadow_fit._stabilize_bounds', side_effect=lambda lo, hi, *rest: (lo, hi)):
                                audited.render(geometry.entities, fit_scene, renderer, camera, geometry=geometry)
                            audited._temporal.transition = False
                        else:
                            audited.render(geometry.entities, fit_scene, renderer, camera, geometry=geometry)
                        matrix = audited.matrix.copy()
                        if mode != 'legacy' and index == 14:
                            step = audited._temporal.transition_steps
                            for repeat in range(2):
                                audited.render(geometry.entities, fit_scene, renderer, camera, geometry=geometry)
                                assert audited.cache_hit, 'Identical-pose depth cache missed'
                                assert audited._temporal.transition_steps == step, 'Still camera advanced transition'
                            report['mid_transition_repeat_exact'] = True
                        with patch.object(audited, 'render', return_value=None):
                            render_scene_view(scene, observer, renderer, target, size, observer.samples)
                        raw = gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                        rgb = np.frombuffer(raw, np.uint8).reshape(size[1], size[0], 3).copy()
                        if first is None:
                            # Unproject the stationary observer's resolved depth;
                            # score only world points visible in every moving
                            # camera. Coverage discarded behind a dolly camera
                            # is allowed to disappear from the old observer.
                            depth = np.frombuffer(gl.glReadPixels(0, 0, *size, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT), np.float32).reshape(size[1], size[0])
                            yy, xx = np.mgrid[:size[1], :size[0]]
                            clip = np.stack(((xx+.5)/size[0]*2-1, (yy+.5)/size[1]*2-1, depth*2-1, np.ones_like(depth)), axis=-1)
                            projection = observer.projection_matrix(size[0]/size[1]).astype(np.float32).astype(float)
                            view = observer.view_matrix.astype(np.float32).astype(float)
                            world = clip.reshape(-1, 4) @ np.linalg.inv(projection @ view).T
                            world /= world[:, 3:4]
                            common = (depth < 1).reshape(-1)
                            for moving in poses:
                                q = world @ (moving.projection_matrix(size[0]/size[1]) @ moving.view_matrix).T
                                common &= (q[:,3]>0) & (np.abs(q[:,:2]) <= q[:,3:4]*.98).all(axis=1) & (np.abs(q[:,2])<=q[:,3])
                            common = common.reshape(size[1], size[0])
                            Image.fromarray(common[::-1].astype(np.uint8)*255).save(folder/'common-visible.png')
                            first = rgb.copy()
                            Image.fromarray(rgb[::-1]).save(folder / 'first.png')
                        difference = np.zeros_like(rgb) if previous is None else np.abs(rgb.astype(np.int16) - previous.astype(np.int16))
                        row = dict(frame=index, matrix=matrix.tolist(), transition=audited._temporal.transition, blend_step=audited._temporal.transition_steps,
                                   world_units_per_texel=(2 / np.linalg.norm(matrix[:2, :3], axis=1) / scene.shadow_resolution).tolist(),
                                   changed_pixels=int(np.any(difference != 0, axis=2).sum()),
                                   pixels_over_4=int(np.any(difference > 4, axis=2).sum()),
                                   pixels_over_16=int(np.any(difference > 16, axis=2).sum()),
                                   max_channel_step=int(difference.max()), mean_channel_step=float(difference.mean()))
                        row.update(common_visible_pixels=int(common.sum()),
                                   common_pixels_over_4=int((np.any(difference > 4, axis=2) & common).sum()),
                                   common_max_channel_step=int(difference[common].max()))
                        trace.append(row)
                        if row['pixels_over_4'] > max_step:
                            max_step, max_image = row['pixels_over_4'], rgb.copy()
                            if previous is not None:
                                Image.fromarray(previous[::-1]).save(folder / 'max-step-before.png')
                        previous = rgb
                        if int(gl.glGetError()) != int(gl.GL_NO_ERROR):
                            raise AssertionError('OpenGL error')
                    Image.fromarray(max_image[::-1]).save(folder / 'max-step-after.png')
                    Image.fromarray(previous[::-1]).save(folder / 'last.png')
                    pitches = np.array([row['world_units_per_texel'] for row in trace])
                    record = dict(track=track, mode=mode, frames=frames,
                                  pitch_refits=int(np.any(np.abs(np.diff(pitches, axis=0)) > 1e-12, axis=1).sum()),
                                  max_changed_pixels=max(row['changed_pixels'] for row in trace),
                                  max_pixels_over_4=max(row['pixels_over_4'] for row in trace),
                                  max_pixels_over_16=max(row['pixels_over_16'] for row in trace),
                                  max_channel_step=max(row['max_channel_step'] for row in trace),
                                  common_max_pixels_over_4=max(row['common_pixels_over_4'] for row in trace),
                                  common_max_channel_step=max(row['common_max_channel_step'] for row in trace), trace=trace)
                    report['runs'].append(record)
                    (output / 'results.json').write_text(json.dumps(report, indent=2))
                    print(json.dumps({key: value for key, value in record.items() if key != 'trace'}), flush=True)
        finally:
            target.close()
            renderer.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, default=ROOT / 'examples/roman_street/street.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'captures/roman-street-shadow-motion-20261017')
    parser.add_argument('--frames', type=int, default=41)
    parser.add_argument('--ground', choices=('saved', 'off', 'on'), default='saved')
    args = parser.parse_args()
    run(args.scene.resolve(), args.output.resolve(), args.frames, args.ground)
