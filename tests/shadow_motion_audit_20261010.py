"""Temporal Shot shadow audit: fixed world probes, actual depth maps, locked-fit control.

No production changes. Run on the camera-fit branch with a real GL context.
Generated glTF assets, PNGs, video frames and measurements stay in captures/.
"""
import os
if os.name != 'nt' and not os.environ.get('DISPLAY'):
    os.environ.setdefault('SDL_VIDEODRIVER', 'offscreen')
if os.environ.get('SDL_VIDEODRIVER') == 'offscreen':
    os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pygame
from OpenGL import GL as gl
from PIL import Image, ImageDraw
import photographer_session as fixture
ROOT = fixture.ROOT
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.lighting import scene_light_direction
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot
from mini3d import shadow_map
from mini3d.shadow_fit import receiver_matrix


def depth_map(shadow):
    previous = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    try:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, shadow.fbo)
        raw = gl.glReadPixels(0, 0, shadow.size, shadow.size, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)
        return np.asarray(raw, np.float32).reshape(shadow.size, shadow.size).copy()
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, previous)


def visibility(depth, matrix, probes, light, bias):
    """CPU replay of production GL_NEAREST 3x3 PCF at fixed world points.

    Exact light uniform/depth data, float32 projection and production slope bias.
    Interior UVs avoid border-tie ambiguities. No screen-space image comparison.
    """
    q = (probes @ np.asarray(matrix, np.float32).T)[:, :3] * np.float32(.5) + np.float32(.5)
    valid = ((q >= 0) & (q <= 1)).all(axis=1)
    n = depth.shape[0]
    # Each nearest texture tap selects floor(uv * texture_size).
    x, y = np.floor(q[:, 0]*n).astype(int), np.floor(q[:, 1]*n).astype(int)
    threshold = q[:, 2] - np.float32(bias*(1+4*(1-max(float(light[2]), 0))))
    result = np.zeros(len(probes), np.float32)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            xx, yy = x+dx, y+dy
            inside = (xx >= 0) & (xx < n) & (yy >= 0) & (yy < n)
            closest = np.ones(len(probes), np.float32)
            closest[inside] = depth[yy[inside], xx[inside]]
            result += threshold <= closest
    result /= 9
    result[~valid] = 1
    return result


def union_fit(matrices):
    # Common light axes: unite all actual fitted light boxes, retaining caster Z.
    rotation = matrices[0][:3, :3] / np.linalg.norm(matrices[0][:3, :3], axis=1)[:, None]
    rotation[2] *= -1
    lows, highs = [], []
    for matrix in matrices:
        scale = np.linalg.norm(matrix[:3, :3], axis=1); scale[2] *= -1
        center = -matrix[:3, 3] / scale
        half = np.abs(1/scale)
        lows.append(center-half); highs.append(center+half)
    lo, hi = np.min(lows, axis=0), np.max(highs, axis=0)
    scale = 2/(hi-lo); scale[2] *= -1
    result = np.eye(4)
    result[:3, :3] = scale[:, None]*rotation
    result[:3, 3] = -scale*(lo+hi)*.5
    return result


def camera_path(api, label, count):
    poses = []
    for u in np.linspace(0, 1, count):
        if label in ('lateral', 'low-sun'):
            position = np.array([7, 9, 13.])+[.2*u, 0, 0]
            target = np.array([.6, .5, 0.])+[.2*u, 0, 0]
        else:
            position = (1-u)*np.array([7, 9, 13.])+u*np.array([6, 7.5, 10.])
            target = [.6, .5, 0]
        api.create_shot_camera(position=position, target=target, focal_mm=50,
                               aspect='4:3', near=.05, far=400)
        poses.append(api._app.shot_camera)
    return poses


def summary(series, common):
    values = np.stack(series)[:, common]
    step = np.abs(np.diff(values, axis=0))
    span = np.ptp(values, axis=0)
    boundary = (values.min(axis=0) < .999) & (values.max(axis=0) > .001)
    bsteps = step[:, boundary]
    return dict(probes=int(common.sum()), frames=len(series),
        variable_probes=int((span > 1e-6).sum()),
        variable_fraction=float((span > 1e-6).mean()),
        changes_per_step_median=int(np.median((step > 1e-6).sum(axis=1))),
        changes_per_step_max=int((step > 1e-6).sum(axis=1).max()),
        max_visibility_step=float(step.max()),
        max_visibility_span=float(span.max()),
        shadow_boundary_probes=int(boundary.sum()),
        variable_boundary_fraction=float((span[boundary] > 1e-6).mean()) if boundary.any() else 0,
        boundary_step_mean=float(bsteps.mean()) if boundary.any() else 0,
        full_half_threshold_flips=int(((values[:-1] < .5) != (values[1:] < .5)).sum()))


def picture(values, side):
    rgb = np.repeat((values[:side*side].reshape(side, side)[::-1]*255).astype(np.uint8)[..., None], 3, axis=2)
    return Image.fromarray(rgb)


def run(output, frames, resolutions):
    output.mkdir(parents=True, exist_ok=True)
    fixture.OUT = output
    floor = fixture.asset('motion-floor', fixture.make_box(1,1,1), (.4,.4,.4))
    box = fixture.asset('motion-caster', fixture.make_box(1,1,1), (.7,.3,.08))
    pygame.init(); pygame.display.set_mode((800,600), pygame.OPENGL|pygame.DOUBLEBUF|pygame.HIDDEN)
    renderer, target = GLRenderer(800,600), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    report = dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  renderer=gl.glGetString(gl.GL_RENDERER).decode(),gl=gl.glGetString(gl.GL_VERSION).decode(),
                  method='Fixed-world probes replay nearest 3x3 PCF from actual GL depth, with locked union-fit control.',
                  llvmpipe_threads=os.environ.get('LP_NUM_THREADS','default'),runs=[])
    side = 256
    xx, yy = np.meshgrid(np.linspace(-.8, 3.5, side), np.linspace(-.8, 3.2, side))
    # Include high-density cuts through both long shadow edges.
    points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(side*side)))
    cuts = np.vstack((np.column_stack((np.linspace(-.8,3.5,4096),np.full(4096,.8),np.zeros(4096))),
                      np.column_stack((np.full(4096,1.2),np.linspace(-.8,3.2,4096),np.zeros(4096)))))
    probes = np.column_stack((np.vstack((points,cuts)),np.ones(len(points)+len(cuts)))).astype(np.float32)
    try:
        for label in ('lateral','dolly','low-sun'):
            count = frames if label == 'lateral' else (frames+1)//2
            for resolution in resolutions:
                name = f'{label}-{resolution}'
                out = output/name;out.mkdir(exist_ok=True)
                api = Mini3DAPI(renderer)
                api.spawn(floor,name='Ground',position=[0,0,-.1],scale=[200,200,.2])
                api.spawn(box,name='Caster',position=[0,0,1],scale=[1,1,2])
                direction = [-3,-2,.8] if label == 'low-sun' else [-3,-2,3]
                api.set_lighting(mode='Scene',direction=direction,ambient=.3,diffuse=3)
                api.set_shadows(enabled=True,resolution=resolution,bias=.0003,pcf=True)
                scene = api._app.scene;scene.update();entities = scene.get_flat_render_list()
                light = scene_light_direction(scene)
                poses = camera_path(api,label,count)
                matrices = [receiver_matrix(entities,light,cam,resolution) for cam in poses]
                assert all(m is not None for m in matrices), 'Unexpected fallback'
                locked = union_fit(matrices)
                common = np.ones(len(probes),bool)
                for cam in poses:
                    clip = probes.astype(float) @ (cam.projection_matrix(cam.aspect) @ cam.view_matrix).T
                    # 2% inset: fixed probes remain inside each camera throughout path.
                    common &= (clip[:,3]>0) & (np.abs(clip[:,:2]) <= clip[:,3,None]*.98).all(axis=1) & (np.abs(clip[:,2]) <= clip[:,3])
                assert common.sum()>1000
                def render_depth(cam, matrix=None):
                    if matrix is None:
                        renderer.shadow_map.render(entities,scene,renderer,camera=cam)
                    else:
                        with patch.object(shadow_map,'light_matrix',return_value=matrix):
                            renderer.shadow_map.render(entities,scene,renderer,camera=cam)
                    gl.glFinish()
                    depth = depth_map(renderer.shadow_map)
                    if matrix is not None and os.environ.get('AUDIT_DEBUG'):
                        uniform=np.zeros(16,np.float32)
                        gl.glGetUniformfv(renderer.shadow_map.program,gl.glGetUniformLocation(renderer.shadow_map.program,'lightMatrix'),uniform)
                        print('DEPTH',depth.min(),np.count_nonzero(depth<1),'UNIFORM',float(np.max(np.abs(uniform.reshape(4,4).T-np.asarray(matrix,np.float32)))),flush=True)
                    assert gl.glGetError()==gl.GL_NO_ERROR
                    return visibility(depth,renderer.shadow_map.matrix,probes,light,scene.shadow_bias)
                render_shot(scene,poses[0],renderer,target)  # initialize production material/GPU caches
                baseline = render_depth(poses[0],locked)
                control = [render_depth(poses[j],locked) for j in (0,len(poses)//2,len(poses)-1)]
                if os.environ.get('AUDIT_DEBUG'): print('CONTROL',[(np.count_nonzero(v-baseline),float(np.max(np.abs(v-baseline)))) for v in control],flush=True)
                assert all(np.array_equal(v,baseline) for v in control), 'Locked static shadow unexpectedly changed'
                static = [render_depth(poses[0]) for _ in range(3)]
                assert all(np.array_equal(v,static[0]) for v in static), 'Repeated camera nondeterminism'
                series, trace = [], []
                videos = label == 'lateral' and resolution == resolutions[0]
                if videos: (out/'world-frames').mkdir(exist_ok=True);(out/'shot-frames').mkdir(exist_ok=True);(out/'diagnostic-frames').mkdir(exist_ok=True)
                diagnostic = []
                for index,(cam,matrix) in enumerate(zip(poses,matrices)):
                    v = render_depth(cam);series.append(v)
                    extent = 2/np.linalg.norm(matrix[:3,:3],axis=1)
                    phase = (matrix @ [1,1,0,1])[:2]*resolution/2
                    trace.append(dict(frame=index,camera=cam.to_dict(),matrix=matrix.tolist(),
                        extent=extent.tolist(),world_units_per_texel=(extent[:2]/resolution).tolist(),probe_texel=phase.tolist()))
                    if videos:
                        canvas = Image.new('RGB',(side*2,side+36),'white');draw = ImageDraw.Draw(canvas)
                        draw.text((5,5),'Dynamic fit: fixed world probes',fill='black')
                        draw.text((side+5,5),'Locked union fit (control)',fill='black')
                        draw.text((5,20),f'frame {index:03}: camera X +{.2*index/(len(poses)-1):.4f}',fill='black')
                        canvas.paste(picture(v,side),(0,36));canvas.paste(picture(baseline,side),(side,36))
                        canvas.save(out/'world-frames'/f'{index:03}.png')
                    if (videos and index%4==0) or index in (0,len(poses)//2,len(poses)-1):
                        render_shot(scene,cam,renderer,target)
                        pixels = gl.glReadPixels(0,0,*cam.size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
                        image = Image.frombytes('RGB',cam.size,pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                        if index in (0,len(poses)//2,len(poses)-1): image.save(out/f'shot-{index:03}.png')
                        if videos and index%4==0: image.resize((960,720)).save(out/'shot-frames'/f'{index//4:03}.png')
                    if index%4==0 or index==len(poses)-1:
                        # Exact production shading with a stationary observation camera.
                        # Only the fitted shadow matrix follows the moving Shot camera.
                        with patch.object(shadow_map,'light_matrix',return_value=matrix):
                            render_shot(scene,poses[0],renderer,target)
                        raw = gl.glReadPixels(0,0,*poses[0].size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
                        gpu_rgb = np.frombuffer(raw,np.uint8).reshape(poses[0].size[1],poses[0].size[0],3).copy()
                        if not diagnostic:
                            first_rgb=gpu_rgb.copy(); previous_rgb=gpu_rgb.copy()
                        diagnostic.append(dict(frame=index,changed_pixels_from_first=int(np.any(gpu_rgb!=first_rgb,axis=2).sum()),
                            max_channel_difference_from_first=int(np.abs(gpu_rgb.astype(int)-first_rgb).max()),
                            changed_pixels_from_previous=int(np.any(gpu_rgb!=previous_rgb,axis=2).sum())))
                        previous_rgb=gpu_rgb
                        if index in (0,len(poses)//2,len(poses)-1):
                            Image.fromarray(gpu_rgb[::-1]).save(out/f'fixed-view-{index:03}.png')
                        if videos:
                            Image.fromarray(gpu_rgb[::-1]).resize((960,720)).save(out/'diagnostic-frames'/f'{len(diagnostic)-1:03}.png')
                    if index%30==0: print(name,index,'/',len(poses),flush=True)
                values = np.stack(series)
                np.savez_compressed(out/'probes.npz',world=probes,common=common,visibility=values,locked=baseline)
                variability = np.ptp(values,axis=0)
                heat = np.zeros((side,side,3),np.uint8)
                heat[:,:,0] = (variability[:side*side].reshape(side,side)*255).astype(np.uint8)
                heat[:,:,1] = (values[0,:side*side].reshape(side,side)*80).astype(np.uint8)
                Image.fromarray(heat[::-1]).save(out/'variation.png')
                record=dict(name=name,resolution=resolution,direction=direction,pcf=True,bias=.0003,
                    counts=dict(roots=len(scene.root_entities),render_entities=len(entities)),
                    dynamic=summary(series,common),gpu_fixed_observation_camera=diagnostic,
                    static_repeat_exact=True,locked_repeat_exact=True,
                    locked_fit_extent=(2/np.linalg.norm(locked[:3,:3],axis=1)).tolist(),trace=trace)
                report['runs'].append(record)
                (output/'results.json').write_text(json.dumps(report,indent=2))
                print('RESULT',name,json.dumps(record['dynamic']),flush=True)
        report['all_gl_errors_zero']=gl.glGetError()==gl.GL_NO_ERROR
        (output/'results.json').write_text(json.dumps(report,indent=2))
    finally:
        target.close();renderer.close();pygame.quit()

def probe_caster_depth(output):
    """CPU-only corner-case: entering an off-camera caster can jump Z extent.

    A geometric diagnostic, not a claim that this setup has visible flicker.
    """
    from mini3d.scene import Entity, Mesh
    from mini3d.camera import Camera
    from mini3d.shot_camera import ShotCamera
    mesh=Mesh(*fixture.make_box(1,1,1))
    entities=[]
    for position,scale in [([0,0,-.1],[200,200,.2]),([0,0,1],[1,1,2]),([2.35,0,20.5],[1,1,1])]:
        e=Entity(mesh);e.pos[:]=position;e.scale[:]=scale;e.update_transform();entities.append(e)
    records=[]
    for x in np.linspace(0,.1,201):
        cam=ShotCamera(Camera([x,0,8],near=.01,far=100));cam.look_at([x,0,0]);cam.set_lens(85);cam.set_aspect('1:1')
        matrix=receiver_matrix(entities,[0,0,1],cam,1024)
        extent=2/np.linalg.norm(matrix[:3,:3],axis=1)
        records.append(dict(camera_x=float(x),extent=extent.tolist(),world_bias=float(.0003*extent[2])))
    delta=np.abs(np.diff([r['extent'][2] for r in records]));index=int(delta.argmax())
    result=dict(method='CPU-only caster-prism depth transition; no visible-artifact claim',
        before=records[index],after=records[index+1],z_extent_jump=float(delta[index]),
        ratio=float(records[index+1]['extent'][2]/records[index]['extent'][2]),trace=records)
    output.mkdir(parents=True,exist_ok=True);(output/'caster-z-probe.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='trace'},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'captures/shadow-motion-20261010')
    parser.add_argument('--z-probe-only',action='store_true');parser.add_argument('--frames',type=int,default=121);parser.add_argument('--resolutions',type=int,nargs='+',default=[1024,4096])
    args=parser.parse_args()
    if args.z_probe_only: probe_caster_depth(args.output)
    else: run(args.output,args.frames,args.resolutions)
