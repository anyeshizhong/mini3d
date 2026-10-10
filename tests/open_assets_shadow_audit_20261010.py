"""Downloaded CC0 House + CC-BY CesiumMan: CPU, Shot, motion and persistence.

No production edits. Assets stay in captures/, pinned and SHA verified. This is
an alternative asset benchmark, never the original Rome/legionnaire workload.
Requires the engine requirements plus Pillow and a current OpenGL context.
"""
import os
if os.name != 'nt' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
if os.environ.get('SDL_VIDEODRIVER') == 'offscreen':
    os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from PIL import Image
import shadow_fit_performance_20261010 as perf
from shadow_motion_audit_20261010 import union_fit
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.lighting import scene_light_direction
from mini3d.placement import geometry_bounds
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot
from mini3d.shadow_fit import receiver_matrix
from mini3d import shadow_map

HOUSE_PIN = 'f61371ee556a5e1f0e5c697bcbdfb95ca756bcfd'
MAN_PIN = 'edc7c9e67c639d230715049ee31f9a96a6babbbe'
HOUSE_RAW = 'https://raw.githubusercontent.com/ErfanMo77/gltf-research-scenes/' + HOUSE_PIN + '/scenes/house/'
MAN_RAW = 'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/' + MAN_PIN + '/Models/CesiumMan/'
SOURCES = {
    'house_core.gltf': HOUSE_RAW + 'gltf/house_core.gltf',
    # Git LFS raw is only a pointer. Fetch the pinned object via media endpoint.
    'house.bin': HOUSE_RAW.replace('raw.githubusercontent.com', 'media.githubusercontent.com/media') + 'gltf/house.bin',
    'house-license.txt': HOUSE_RAW + 'source/LICENSE.txt',
    'house-conversion.yaml': HOUSE_RAW + 'gltf/conversion.yaml',
    'CesiumMan.glb': MAN_RAW + 'glTF-Binary/CesiumMan.glb',
    'cesium-license.md': MAN_RAW + 'README.md',
}
EXPECTED = {
    'house_core.gltf': '7a7b3f1e4864d8e188f3992725db9998ca93a2e664f1bbe7467abffc0fdd5745',
    'house.bin': 'ba2d9875b4265ae704200f16758224e7c92107828a0bf3f597344ff26bc793aa',
    'CesiumMan.glb': 'b7001eaeea8254bd44773bcd247e78696d94169388fbb2a1800fc69434e777d9',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        path = directory / name
        if path.is_file():
            continue
        temporary = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(url, timeout=180) as response, temporary.open('wb') as stream:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                stream.write(block)
        temporary.replace(path)
        print('DOWNLOAD', name, path.stat().st_size, flush=True)
    assert (directory / 'house.bin').stat().st_size == 49583366
    for name, expected in EXPECTED.items():
        assert sha(directory / name) == expected, 'Asset hash mismatch: ' + name


def draw_pixels(scene, camera, renderer, target, matrix=None):
    gl.glFinish()
    if matrix is None:
        render_shot(scene, camera, renderer, target)
    else:
        with patch.object(shadow_map, 'light_matrix', return_value=matrix):
            render_shot(scene, camera, renderer, target)
    gl.glFinish()
    raw = gl.glReadPixels(0, 0, *camera.size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
    assert gl.glGetError() == gl.GL_NO_ERROR
    return np.frombuffer(raw, np.uint8).reshape(camera.size[1], camera.size[0], 3)[::-1].copy()


def configure_camera(api, position, target, lens):
    api.create_shot_camera(position=position, target=target, focal_mm=lens,
                           aspect='16:9', near=.05, far=400)
    return api._app.shot_camera


def run(output, cpu_samples, shot_samples, frames, resolutions):
    assets = output / 'assets'
    for name in SOURCES:
        if not (assets / name).is_file():
            raise FileNotFoundError('Missing ' + name + '; rerun with --download')
    for name, expected in EXPECTED.items():
        assert sha(assets / name) == expected, 'Asset hash mismatch: ' + name
    pygame.init()
    pygame.display.set_mode((800, 600), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer, target = GLRenderer(800, 600), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    report = dict(status='RUNNING', environment=perf.environment(),
                  renderer=gl.glGetString(gl.GL_RENDERER).decode(),
                  gl=gl.glGetString(gl.GL_VERSION).decode(), assets=[], cpu=[], shots=[], motion=[])
    for name, url in SOURCES.items():
        path = assets / name
        report['assets'].append(dict(file=name, url=url, bytes=path.stat().st_size, sha256=sha(path)))
    report['asset_licenses'] = dict(house='CC0-1.0; MrChimp2313; PBRT resources by Benedikt Bitterli; glTF conversion ErfanMo77',
                                    figure='CC-BY-4.0; Cesium; logo trademark separate; static default-pose skinning')
    report['layout'] = dict(house_xy_span=40, house_center_xy=[0, 10], floor_size=100,
                           figure_height=1.7, rows=5, columns=8, spacing=[1.2, 1.4],
                           formation_origin=[-4.2, -17], include_source=True)
    def save():
        (output / 'results.json').write_text(json.dumps(report, indent=2))
    try:
        api = Mini3DAPI(renderer)
        begin = time.perf_counter()
        house = api.spawn(assets / 'house_core.gltf', name='Victorian House')['entity_id']
        report['house_spawn_ms'] = (time.perf_counter() - begin) * 1000
        lo, hi = geometry_bounds(api._entity(house)); factor = 40 / max((hi - lo)[:2])
        api.set_transform(house, scale=[factor]*3,
                          position=[-(lo[0]+hi[0])/2*factor, 10-(lo[1]+hi[1])/2*factor, -lo[2]*factor])
        api.lock(house)
        api.spawn('builtin:ground', name='Photo Ground', scale=[10]*3)
        scene = api._app.scene
        api.set_lighting(mode='Scene', direction=[-3, -2, 3], ambient=.3, diffuse=3)
        light = scene_light_direction(scene)
        overview = ([-25, -35, 18], [0, 5, 3], 35)
        close = ([10, -26, 5], [0, -14, 1], 50)
        for population in (0, 1, 40):
            if population == 1:
                begin = time.perf_counter()
                figure = api.spawn(assets / 'CesiumMan.glb', name='CesiumMan', placement_type='character')['entity_id']
                report['figure_spawn_ms'] = (time.perf_counter() - begin) * 1000
                lo, hi = geometry_bounds(api._entity(figure)); factor = 1.7 / (hi[2]-lo[2])
                api.set_transform(figure, scale=[factor]*3,
                    position=[-4.2-(lo[0]+hi[0])/2*factor, -17-(lo[1]+hi[1])/2*factor, -lo[2]*factor])
            if population == 40:
                formation = api.create_rectangular_formation(figure, 5, 8, 1.2, 1.4)
                assert len(formation['member_ids']) == 40
                report['formation_undo'] = api.undo()['changed'] and len(api.list_entities()) == 3
                report['formation_redo'] = api.redo()['changed'] and len(api.list_entities()) == 42
                assert report['formation_undo'] and report['formation_redo']
            scene.update(); entities = scene.get_flat_render_list()
            for name, pose in (('overview', overview), ('people-close', close)):
                camera = configure_camera(api, *pose)
                record = dict(population=population, view=name, counts=perf.counts(scene),
                    fitting=perf.paired_fit(entities, light, camera, cpu_samples),
                    intersection_work=perf.intersection_counts(entities, light, camera, 1024),
                    scene_update=perf.measure(scene.update, cpu_samples),
                    flatten=perf.measure(scene.get_flat_render_list, cpu_samples))
                report['cpu'].append(record); save()
                print('CPU', population, name, record['counts'], record['fitting'], flush=True)
        for name, pose in (('overview', overview), ('people-close', close)):
            camera = configure_camera(api, *pose)
            for resolution in resolutions:
                api.set_shadows(enabled=True, resolution=resolution, bias=.0003, pcf=True)
                render_shot(scene, camera, renderer, target); gl.glFinish()
                record = dict(view=name, resolution=resolution, camera=camera.to_dict(), passes={})
                for mode in ('off', 'whole-scene', 'camera-fit'):
                    scene.shadows_enabled = mode != 'off'
                    original = shadow_map.light_matrix
                    def draw():
                        gl.glFinish()
                        if mode == 'whole-scene':
                            with patch.object(shadow_map, 'light_matrix', side_effect=lambda es,d,c=None,r=1024: original(es,d,None,r)):
                                render_shot(scene, camera, renderer, target)
                        else:
                            render_shot(scene, camera, renderer, target)
                        gl.glFinish()
                    record['passes'][mode] = perf.measure(draw, shot_samples, 3)
                    assert gl.glGetError() == gl.GL_NO_ERROR
                scene.shadows_enabled = True
                api.capture(output / ('%s-%s.png' % (name, resolution)))
                report['shots'].append(record); save()
                print('SHOT', name, resolution, record['passes'], flush=True)
        # Freeze the observation camera: RGB changes cannot be caused by image
        # projection or normal motion. Only the shadow fit follows moving Shot.
        for resolution in resolutions:
            api.set_shadows(enabled=True, resolution=resolution, bias=.0003, pcf=True)
            poses = []
            for u in np.linspace(0, 1, frames):
                offset = np.array([.4*u, 0, 0])
                poses.append(configure_camera(api, np.array(close[0])+offset,
                                              np.array(close[1])+offset, close[2]))
            matrices = [receiver_matrix(entities, light, c, resolution) for c in poses]
            assert all(m is not None and np.isfinite(m).all() for m in matrices)
            locked = union_fit(matrices)
            fixed = poses[0]
            static = [draw_pixels(scene, fixed, renderer, target) for _ in range(3)]
            control = [draw_pixels(scene, fixed, renderer, target, locked) for _ in range(3)]
            assert all(np.array_equal(x, static[0]) for x in static)
            assert all(np.array_equal(x, control[0]) for x in control)
            record = dict(resolution=resolution, frames=frames, movement=[.4,0,0],
                          camera_start=poses[0].to_dict(), camera_end=poses[-1].to_dict(),
                          static_repeat_exact=True, locked_repeat_exact=True, trace=[])
            folder = output / ('motion-%s' % resolution); folder.mkdir(exist_ok=True)
            (folder/'fixed-frames').mkdir(exist_ok=True)
            (folder/'shot-frames').mkdir(exist_ok=True)
            for index, (camera, matrix) in enumerate(zip(poses, matrices)):
                rgb = draw_pixels(scene, fixed, renderer, target, matrix)
                if index == 0:
                    first, previous = rgb.copy(), rgb.copy()
                difference = np.abs(rgb.astype(np.int16)-first.astype(np.int16))
                record['trace'].append(dict(frame=index, matrix=matrix.tolist(),
                    extent=(2/np.linalg.norm(matrix[:3,:3],axis=1)).tolist(),
                    changed_pixels_from_first=int(np.any(difference,axis=2).sum()),
                    max_channel_difference_from_first=int(difference.max()),
                    changed_pixels_from_previous=int(np.any(rgb!=previous,axis=2).sum())))
                previous = rgb
                Image.fromarray(rgb).resize((960,540)).save(folder/'fixed-frames'/('%03d.png'%index))
                if index in (0, frames//2, frames-1):
                    Image.fromarray(rgb).save(folder/('fixed-%03d.png'%index))
                moving = draw_pixels(scene, camera, renderer, target)
                Image.fromarray(moving).resize((960,540)).save(folder/'shot-frames'/('%03d.png'%index))
                if index in (0, frames//2, frames-1):
                    Image.fromarray(moving).save(folder/('shot-%03d.png'%index))
                if index % 8 == 0:
                    print('MOTION', resolution, index, '/', frames, flush=True)
            report['motion'].append(record); save()
        api._app.shot_camera = poses[0]
        before_state = api.get_scene_state(); before_counts = perf.counts(scene)
        before_rgb = draw_pixels(scene, poses[0], renderer, target)
        project = output/'house-40.scene.json'
        api.save_scene(project); api.load_scene(project)
        loaded = api._app.scene; loaded.update()
        after_state = api.get_scene_state()
        after_rgb = draw_pixels(loaded, api._app.shot_camera, renderer, target)
        # History intentionally resets on load; compare saved user state.
        before_state.pop('history'); after_state.pop('history')
        report['persistence'] = dict(state_equal=before_state==after_state,
                                    counts_equal=before_counts==perf.counts(loaded),
                                    rgb_exact=np.array_equal(before_rgb, after_rgb),
                                    changed_pixels=int(np.any(before_rgb!=after_rgb,axis=2).sum()))
        assert all(report['persistence'][key] for key in ('state_equal','counts_equal','rgb_exact'))
        report['all_gl_errors_zero'] = gl.glGetError() == gl.GL_NO_ERROR
        report['status'] = 'COMPLETED_OPEN_ASSETS_NOT_ROME'
        save(); print('DONE', report['persistence'], flush=True)
    finally:
        target.close(); renderer.close(); pygame.quit()


def refine_common_receivers(output):
    """Exclude moving-frustum / shadow-fit edges from fixed-view RGB evidence.

    Reconstruct visible opaque world positions from the fixed camera's depth.
    Foreground excludes the house's transparent glass, whose blended RGB has
    no unique depth. Keep 2% camera inset and 1.5 shadow-texel PCF border margin.
    """
    from mini3d.shot_camera import ShotCamera
    report = json.loads((output/'results.json').read_text())
    assert report['status'] == 'COMPLETED_OPEN_ASSETS_NOT_ROME'
    pygame.init()
    pygame.display.set_mode((800,600), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
    renderer, target = GLRenderer(800,600), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    try:
        api = Mini3DAPI(renderer); api.load_scene(output/'house-40.scene.json')
        scene = api._app.scene; scene.update()
        for run in report['motion']:
            resolution = run['resolution']
            api.set_shadows(enabled=True, resolution=resolution, bias=.0003, pcf=True)
            camera = ShotCamera.from_dict(run['camera_start'])
            first = draw_pixels(scene, camera, renderer, target)
            w,h = camera.size
            depth = np.asarray(gl.glReadPixels(0,0,w,h,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT),np.float32).reshape(h,w)[::-1].copy()
            xx,yy = np.meshgrid((np.arange(w)+.5)*2/w-1, 1-(np.arange(h)+.5)*2/h)
            clip = np.column_stack((xx.ravel(),yy.ravel(),depth.ravel()*2-1,np.ones(w*h)))
            world = clip @ np.linalg.inv(camera.projection_matrix(camera.aspect) @ camera.view_matrix).T
            world /= world[:,3,None]
            common = (depth.ravel()<1) & np.isfinite(world).all(axis=1)
            start = np.array(run['camera_start']['position']); end = np.array(run['camera_end']['position'])
            matrices = [np.asarray(item['matrix']) for item in run['trace']]
            for u,matrix in zip(np.linspace(0,1,run['frames']),matrices):
                pose = ShotCamera.from_dict(run['camera_start']); pose.position = start*(1-u)+end*u
                q = world @ (pose.projection_matrix(pose.aspect) @ pose.view_matrix).T
                common &= (q[:,3]>0) & (np.abs(q[:,:2])<=q[:,3,None]*.98).all(axis=1) & (np.abs(q[:,2])<=q[:,3])
                shadow = (world @ matrix.T)[:,:3]*.5+.5
                margin = 1.5/resolution
                common &= ((shadow[:,:2]>=margin)&(shadow[:,:2]<=1-margin)).all(axis=1)
                common &= ((shadow[:,2]>=0)&(shadow[:,2]<=1))
            foreground = common & (np.abs(world[:,0])<7) & (world[:,1]>-19) & (world[:,1]<-9) & (world[:,2]>-.05) & (world[:,2]<2.1)
            common = common.reshape(h,w); foreground = foreground.reshape(h,w)
            assert foreground.sum()>10000
            locked = union_fit(matrices)
            controls = [draw_pixels(scene,camera,renderer,target,locked) for _ in range(3)]
            assert all(np.array_equal(x,controls[0]) for x in controls)
            measured = dict(common_pixels=int(common.sum()),foreground_pixels=int(foreground.sum()),
                            locked_control_exact=True,trace=[])
            previous = first
            for item,matrix in zip(run['trace'],matrices):
                rgb = draw_pixels(scene,camera,renderer,target,matrix)
                diff = np.abs(rgb.astype(np.int16)-first.astype(np.int16))
                step = np.abs(rgb.astype(np.int16)-previous.astype(np.int16))
                measured['trace'].append(dict(frame=item['frame'],
                    common_changed_from_first=int(np.any(diff[common],axis=1).sum()),
                    foreground_changed_from_first=int(np.any(diff[foreground],axis=1).sum()),
                    foreground_over8_from_first=int((diff[foreground].max(axis=1)>8).sum()),
                    foreground_over16_from_first=int((diff[foreground].max(axis=1)>16).sum()),
                    foreground_max_channel_from_first=int(diff[foreground].max()),
                    foreground_changed_from_previous=int(np.any(step[foreground],axis=1).sum()),
                    foreground_over8_from_previous=int((step[foreground].max(axis=1)>8).sum()),
                    foreground_over16_from_previous=int((step[foreground].max(axis=1)>16).sum()),
                    foreground_max_channel_from_previous=int(step[foreground].max())))
                previous = rgb
                if item['frame']%8==0:
                    print('REFINE',resolution,item['frame'],'foreground',measured['trace'][-1],flush=True)
            run['common_receiver_rgb'] = measured
            np.savez_compressed(output/('common-mask-%s.npz'%resolution),common=common,foreground=foreground)
            Image.fromarray((foreground*255).astype(np.uint8)).save(output/('foreground-mask-%s.png'%resolution))
            (output/'results.json').write_text(json.dumps(report,indent=2))
        # A photographer's full composition, separate from benchmark cameras.
        api.set_lighting(mode='Scene',direction=[-3,-2,2],ambient=.18,diffuse=2)
        configure_camera(api,[-27,-37,14],[-1,-3,3],35)
        api.capture(output/'photographer-house-40.png')
        report['photographer_shot'] = dict(camera=api.get_shot_camera(),lighting=api.get_lighting(),shadows=api.get_shadows())
        (output/'results.json').write_text(json.dumps(report,indent=2))
        print('REFINE DONE',flush=True)
    finally:
        target.close(); renderer.close(); pygame.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'captures/open-assets-20261010')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--refine-only', action='store_true')
    parser.add_argument('--cpu-samples', type=int, default=51)
    parser.add_argument('--shot-samples', type=int, default=9)
    parser.add_argument('--frames', type=int, default=33)
    parser.add_argument('--resolutions', type=int, nargs='+', default=[1024,4096])
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    if args.download:
        download(args.output/'assets')
    if args.refine_only:
        refine_common_receivers(args.output)
    else:
        run(args.output, args.cpu_samples, args.shot_samples, args.frames, args.resolutions)
        refine_common_receivers(args.output)
