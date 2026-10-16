"""End-to-end Shot motion driven only through public AI API commands.

This is an image correctness smoke, NOT a frame-rate benchmark: PNG encoding,
readback and first-time GPU uploads are included. Requires real desktop GL.
Example:
  python -B tests/api_camera_trajectory_smoke.py --output captures/api-camera-track --frames 6
  python -B tests/api_camera_trajectory_smoke.py --output captures/api-native-track --backend native
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api_camera_trajectories import orbit_path


def run(output, frames=6, backend='auto'):
    os.environ['MINI3D_PHOTO_BACKEND'] = backend
    if backend == 'native':
        os.environ['MINI3D_REQUIRE_NATIVE_PHOTO'] = '1'
    else:
        os.environ.pop('MINI3D_REQUIRE_NATIVE_PHOTO', None)
    from OpenGL import GL as gl
    from tools.capture_sunset import desktop_context
    from mini3d.api import Mini3DAPI
    from mini3d.api_dispatch import dispatch
    from mini3d.gl_renderer import GLRenderer

    output.mkdir(parents=True, exist_ok=True)
    records = []
    with desktop_context():
        renderer = GLRenderer(800, 600)
        try:
            api = Mini3DAPI(renderer=renderer)
            api.create_roman_street(segments=2)
            api.create_shot_camera(position=[9, -9, 4], target=[0, 0, 1],
                                   focal_mm=35, aspect='16:9', near=.05, far=150)
            for index, pose in enumerate(orbit_path([0, 0, 1], radius=9, height=3,
                                                    frames=frames, turns=.25,
                                                    start_angle=-math.pi / 2)):
                change = dispatch(api, {'command': 'set_shot_camera_pose', 'args': pose})
                if not change['ok']:
                    raise AssertionError('Failed to set camera: {}'.format(change))
                file = output / ('frame-{:03}.png'.format(index))
                api.capture(file)
                if not file.is_file() or file.stat().st_size == 0:
                    raise AssertionError('Missing capture: {}'.format(file))
                stats = dict(renderer.render_stats)
                if backend == 'native' and stats.get('backend') != 'native-photo':
                    raise AssertionError('Native renderer was not used: {}'.format(stats))
                error = int(gl.glGetError())
                if error != int(gl.GL_NO_ERROR):
                    raise AssertionError('OpenGL error {} at frame {}'.format(error, index))
                records.append(dict(index=index, pose=pose,
                                    camera=api.get_shot_camera(),
                                    backend=stats.get('backend', 'python'),
                                    sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                                    gl_error=error))
        finally:
            renderer.close()
    if len({row['sha256'] for row in records}) < 2:
        raise AssertionError('Camera motion did not produce different frames')
    report = dict(backend_requested=backend, frames=records,
                  test_type='API-driven captures, not frame-time benchmark')
    (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=6)
    parser.add_argument('--backend', choices=('auto', 'native', 'python'), default='auto')
    args = parser.parse_args()
    if args.frames < 2:
        parser.error('--frames must be at least 2')
    print(json.dumps(run(args.output.resolve(), args.frames, args.backend),
                     indent=2), flush=True)


if __name__ == '__main__':
    main()
