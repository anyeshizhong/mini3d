"""Native GPU fixed-world/fixed-observer shadow audit; correctness, not timing."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ['MINI3D_PHOTO_BACKEND'] = 'python'  # Only bundle preparation uses Python GL.


def prepare(output, labels):
    import photographer_session as fixture
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from mini3d.native_photo_bundle import export_live_bundle
    from mini3d.shadow_map import SHADOW_GLSL
    from tools.capture_sunset import desktop_context
    from shadow_motion_audit_20261010 import camera_path
    fixture.OUT = output
    floor = fixture.asset('native-motion-floor', fixture.make_box(1, 1, 1), (.4, .4, .4))
    box = fixture.asset('native-motion-caster', fixture.make_box(1, 1, 1), (.7, .3, .08))
    xx, yy = np.meshgrid(np.linspace(-.8, 3.5, 256), np.linspace(-.8, 3.2, 256))
    points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(256*256)))
    cuts = np.vstack((np.column_stack((np.linspace(-.8, 3.5, 4096), np.full(4096, .8), np.zeros(4096))),
                      np.column_stack((np.full(4096, 1.2), np.linspace(-.8, 3.2, 4096), np.zeros(4096)))))
    probes = np.ascontiguousarray(np.vstack((points, cuts)), dtype=np.float32)
    with desktop_context():
        renderer = GLRenderer(800, 600)
        try:
            for label in labels:
                folder = output / label
                folder.mkdir(parents=True, exist_ok=True)
                api = Mini3DAPI(renderer)
                if label.startswith('street-'):
                    api.load_scene(str(ROOT / 'examples/roman_street/street.json'))
                    api.set_atmosphere(ground=True)  # Current Roman Street after Bug2.
                    observer = deepcopy(api._app.shot_camera)
                    vector = observer.rotation[:, 0] * .2 if label.endswith('lateral') else -observer.rotation[:, 2] * 3
                    poses = []
                    for amount in np.linspace(0, 1, 41):
                        api.set_shot_camera_pose(position=(observer.position + vector*amount).tolist(),
                                                 rotation=observer.rotation.tolist())
                        poses.append(deepcopy(api._app.shot_camera))
                else:
                    api.spawn(floor, name='Ground', position=[0, 0, -.1], scale=[200, 200, .2])
                    api.spawn(box, name='Caster', position=[0, 0, 1], scale=[1, 1, 2])
                    api.set_lighting(mode='Scene', direction=[-3, -2, .8] if label.endswith('low-sun') else [-3, -2, 3],
                                     ambient=.3, diffuse=3)
                    api.set_shadows(enabled=True, resolution=1024, bias=.0003, pcf=True)
                    api.set_atmosphere(enabled=False, ground=False, sun_size=0)
                    track = label[len('small-'):]
                    poses = camera_path(api, track, 121 if track == 'lateral' else 61)
                scene = api._app.scene
                scene.update()
                export_live_bundle(scene, poses[0], renderer, folder, ROOT / 'spqr-native')
                raw = bytearray(b'SPQRF001' + struct.pack('<I', len(poses)))
                for i, cam in enumerate(poses):
                    route = b'walk'
                    raw += struct.pack('<I', len(route)) + route + struct.pack('<d', i/max(1, len(poses)-1))
                    data = [*cam.position, *cam.rotation.reshape(-1), *cam.view_matrix.reshape(-1),
                            *cam.projection_matrix(cam.aspect).reshape(-1), cam.near, cam.far]
                    raw += struct.pack('<46d', *data)
                (folder / 'frames.bin').write_bytes(raw)
                probes.tofile(folder / 'probes.f32')
                np.save(folder / 'probes.npy', probes)
                api.save_scene(str(folder / 'scene.json'))
                (folder / 'poses.json').write_text(json.dumps([cam.to_dict() for cam in poses], indent=2))
                (folder / 'shaders/probe.vert').write_text('''#version 330 core
void main() { vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2)*2.-1.;gl_Position=vec4(p,0,1); }
''')
                (folder / 'shaders/probe.frag').write_text('''#version 330 core
uniform sampler2D auditPoints;
uniform vec3 auditLight;
out vec4 fragColor;
''' + SHADOW_GLSL + '''
uniform bool photoColorEnabled;
void main() {
    vec3 world=texelFetch(auditPoints,ivec2(gl_FragCoord.xy),0).xyz;
    float combined=shadowVisibility(world,vec3(0,0,1),auditLight);
    float farV=combined, nearV=1.;
#ifdef AUDIT_STABLE
    vec3 farQ,nearQ;
    float bias=shadowBias*(1.+4.*(1.-max(auditLight.z,0.)));
    farV=shadowFarVisibility(world,vec3(0,0,1),auditLight);
    if(shadowNearEnabled && projectShadowCoordinate(shadowNearMatrix,world,nearQ))
        nearV=sampleShadowMap(shadowNearDepth,shadowNearRaw,nearQ,shadowNearWorldScale,bias);
#endif
    fragColor=vec4(combined,nearV,farV,1.);
}
''')
                print('PREPARED', label, len(poses), flush=True)
        finally:
            renderer.close()


def analyze(folder):
    trace = json.loads((folder / 'trace.json').read_text())
    count = len(trace['frames'])
    values = np.memmap(folder / 'probes.rgba.f32', dtype=np.float32, mode='r', shape=(count, 73728, 4))
    static = np.fromfile(folder / 'static.rgba.f32', dtype=np.float32).reshape(3, 73728, 4)
    static_exact = bool(np.array_equal(static[0], static[1]) and np.array_equal(static[0], static[2]))
    if not static_exact or not trace['all_gl_errors_zero']:
        raise AssertionError('Static determinism or GL error control failed')
    result = dict(frames=count, renderer=trace['renderer'], static_repeat_exact=static_exact,
                  all_gl_errors_zero=bool(trace['all_gl_errors_zero']))
    cache_path = folder / 'cache-control.json'
    if cache_path.is_file():
        result['cache'] = json.loads(cache_path.read_text())
        result['cache']['cached_vs_forced_image_exact'] = bool(np.array_equal(
            np.asarray(Image.open(folder / 'cached.ppm')), np.asarray(Image.open(folder / 'forced.ppm'))))
        if not result['cache']['cached_vs_forced_image_exact']:
            raise AssertionError('Cached and forced-redraw observation images differ')
    for channel, name in enumerate(('combined', 'near', 'far')):
        series = np.asarray(values[:, :, channel])
        steps = np.abs(np.diff(series, axis=0))
        result[name] = dict(variable_probes=int((np.ptp(series, axis=0) > 1e-6).sum()),
                            changes_per_step_max=int((steps > 1e-6).sum(axis=1).max()),
                            max_visibility_step=float(steps.max()),
                            threshold_flips=int(((series[:-1] < .5) != (series[1:] < .5)).sum()))
    for name in ('near', 'far'):
        matrices = np.array([row[name] for row in trace['frames']]).reshape(-1, 4, 4)
        pitches = np.linalg.norm(matrices[:, :2, :3], axis=2)
        phase = matrices[:, :2, 3] * (4096 if name == 'near' else (2048 if 'street' in str(folder) else 1024)) / 2
        result[name].update(scale_refits=int((np.abs(np.diff(pitches, axis=0)) > 1e-12).any(axis=1).sum()),
                            max_depth_row_drift=float(np.ptp(matrices[:, 2], axis=0).max()),
                            texel_step_integer_error=float(np.abs(np.diff(phase, axis=0)-np.rint(np.diff(phase, axis=0))).max()))
    images = sorted(folder.glob('fixed-*.ppm'))
    previous = first = np.asarray(Image.open(images[0])).astype(np.int16)
    changed, over4, maxchan = [], [], []
    for path in images[1:]:
        image = np.asarray(Image.open(path)).astype(np.int16)
        delta = np.abs(image-previous)
        changed.append(int((delta > 0).any(axis=2).sum()))
        over4.append(int((delta > 4).any(axis=2).sum()))
        maxchan.append(int(delta.max()))
        previous = image
    result['fixed_observer'] = dict(samples=len(images), max_changed_pixels=max(changed),
                                    max_pixels_over4=max(over4), max_channel_step=max(maxchan),
                                    last_changed_from_first=int((previous != first).any(axis=2).sum()))
    (folder / 'summary.json').write_text(json.dumps(result, indent=2))
    timing = json.loads((folder / 'shadow-timing.json').read_text())
    result['forced_shadow_gpu_ms'] = dict(zip(('p50','p95','p99'),np.percentile(timing['gpu_ms'],[50,95,99])))
    (folder / 'summary.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', default=['small-lateral', 'small-dolly', 'small-low-sun', 'street-lateral', 'street-dolly'])
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--skip-prepare', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not args.analyze_only and not args.skip_prepare:
        prepare(output, args.cases)
    if args.prepare_only:
        return
    report = dict(method='Native production shadow maps and production GPU shadowVisibility at 73728 fixed world probes; separate fixed observation camera. Correctness only; no timing conclusion.', runs=[])
    for label in args.cases:
        for mode in ('before', 'nofade', 'stable'):
            folder = output / label / mode
            if not args.analyze_only:
                subprocess.run([str(args.executable.resolve()), str(output / label), str(folder), mode], check=True)
            row = dict(case=label, mode=mode, **analyze(folder))
            report['runs'].append(row)
            (output / 'results.json').write_text(json.dumps(report, indent=2))
            print('RESULT', json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
