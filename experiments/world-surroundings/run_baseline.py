"""Build, export and measure the isolated LAB-00 SPQR baseline.

Run with the project's installed Python environment. Outputs are never written
into the editor's scene directory or the production native bin directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def command(args, log, report, timeout=600):
    args = [str(item) for item in args]
    print('RUN ' + subprocess.list2cmdline(args), flush=True)
    started = time.perf_counter()
    result = subprocess.run(args, cwd=str(ROOT), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    log.write_text(result.stdout, encoding='utf-8')
    report['commands'].append(dict(argv=args, log=str(log.relative_to(report['_output'])),
                                   exit_code=result.returncode,
                                   wall_seconds=time.perf_counter() - started))
    if result.returncode:
        raise RuntimeError('Command failed; see {}\n{}'.format(log, result.stdout[-4000:]))
    return result.stdout


def bundle_hashes(folder):
    paths = [folder / 'scene.bin', folder / 'frames.bin']
    paths += sorted((folder / 'shaders').glob('*'))
    return {p.relative_to(folder).as_posix(): digest(p) for p in paths if p.is_file()}


def source_hashes():
    paths = list((ROOT / 'spqr-native/src').glob('*'))
    paths += [ROOT / 'spqr-native/CMakeLists.txt', ROOT / 'spqr-native/FORMAT.md',
              ROOT / 'spqr-native/shaders/shadow_cascade.glsl',
              ROOT / 'native/export_scene.py', ROOT / 'mini3d/native_photo_bundle.py',
              ROOT / 'mini3d/resources/ibl/neutral.npz',
              ROOT / 'mini3d/resources/ibl/neutral.json',
              ROOT / 'mini3d/resources/ibl/NOTICE.md']
    paths += list((ROOT / 'experiments/world-surroundings').glob('*.py'))
    paths += [ROOT / 'mini3d' / name for name in
              ('material_shaders.py', 'material_renderer.py', 'gl_renderer.py',
               'sky_renderer.py', 'shadow_map.py', 'environment.py',
               'photo_environment.py', 'atmosphere.py', 'lighting.py',
               'scene.py', 'camera.py')]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths) if p.is_file()}


def inspect_capture(folder, shadow_resolution):
    import numpy as np
    import pygame

    def read_ppm(path):
        # This is the viewer's exact P6 output, with no optional comment lines.
        with path.open('rb') as stream:
            assert stream.readline().strip() == b'P6'
            width, height = map(int, stream.readline().split())
            assert stream.readline().strip() == b'255'
            return np.frombuffer(stream.read(), dtype='uint8').reshape(height, width, 3).copy()

    source = folder / 'captures/orbit-0'
    metadata = json.loads(source.with_suffix('.json').read_text(encoding='utf-8'))
    rgb = read_ppm(source.with_suffix('.ppm'))
    surface = pygame.image.frombuffer(rgb.tobytes(), (rgb.shape[1], rgb.shape[0]), 'RGB')
    pygame.image.save(surface, str(folder / 'preview.png'))
    assert rgb.shape == (662, 1081, 3), 'Unexpected viewer capture size'
    assert float(rgb.std()) > 5, 'Capture appears blank'
    assert metadata['color_triangles'] > 0 and metadata['color_draws'] > 0
    # Fixed cameras reuse valid shadow depth after warmup, so capture-time
    # shadow_draws can legitimately be zero. Inspect the actual depth below.
    assert metadata['shadow_active']
    depth = np.fromfile(str(source.with_suffix('.depth.f32')), dtype='<f4')
    assert depth.size == shadow_resolution * shadow_resolution
    assert np.isfinite(depth).all() and depth.min() >= 0 and depth.max() <= 1
    occupied = int(np.count_nonzero(depth < 1 - 1e-6))
    assert occupied > 0, 'No geometry found in the captured far shadow depth'
    middle = read_ppm(folder / 'captures/orbit-mid.ppm')
    assert np.array_equal(rgb, middle), 'A fixed camera changed during one run'
    return rgb, dict(metadata=metadata, rgb_std=float(rgb.std()),
                     occupied_shadow_texels=occupied, png='preview.png',
                     depth_sha256=digest(source.with_suffix('.depth.f32')),
                     rgb_sha256=digest(source.with_suffix('.ppm')))


def run(args):
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new, empty --output directory: ' + str(output))
    build = args.build_dir.resolve()
    if output == build or output in build.parents or build in output.parents:
        raise ValueError('--output and --build-dir must be separate directories')
    output.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, stage='LAB-00', commands=[], _output=output,
                  environment=dict(python=sys.version, executable=sys.executable,
                                   os=platform.platform()), views={},
                  scope='Isolated native viewer; fixed cameras; no editor UI or terrain editing')
    try:
        report['git_head'] = command(['git', 'rev-parse', 'HEAD'], output / 'git-head.log', report).strip()
        report['git_status_before'] = command(['git', 'status', '--short'], output / 'git-status.log', report)
        cmake = shutil.which(args.cmake)
        compiler = shutil.which(args.compiler)
        ninja = shutil.which('ninja')
        if not all((cmake, compiler, ninja)):
            raise RuntimeError('CMake, a C++20 g++ compiler, and Ninja must be installed/on PATH')
        report['tool_versions'] = {
            name: command([tool, '--version'], output / (name + '-version.log'), report).splitlines()[0]
            for name, tool in (('cmake', cmake), ('compiler', compiler), ('ninja', ninja))}
        command([cmake, '-S', ROOT / 'spqr-native', '-B', build, '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER=' + compiler,
                 '-DCMAKE_MAKE_PROGRAM=' + ninja], output / 'configure.log', report)
        command([cmake, '--build', build, '--target', 'spqr-native', '--parallel', '2'],
                output / 'build.log', report)
        viewer = build / 'bin/spqr-native.exe'
        report['viewer'] = dict(path=str(viewer), sha256=digest(viewer))
        report['source_sha256'] = source_hashes()
        nvidia = shutil.which('nvidia-smi')
        if nvidia:
            try:
                report['environment']['nvidia_inventory'] = command(
                    [nvidia, '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
                    output / 'nvidia.log', report, timeout=20).strip()
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                report['environment']['nvidia_inventory_error'] = str(error)

        from baseline_scene import export_baseline
        from tools.capture_sunset import desktop_context
        from mini3d.gl_renderer import GLRenderer
        from OpenGL import GL
        views = ('horizontal', 'oblique', 'distant')
        print('Exporting two independent sets of offline v1 bundles', flush=True)
        for repeat in (1, 2):
            with desktop_context():
                report['environment']['export_gl'] = {
                    key: GL.glGetString(value).decode('utf-8') for key, value in
                    (('vendor', GL.GL_VENDOR), ('renderer', GL.GL_RENDERER), ('version', GL.GL_VERSION))}
                renderer = GLRenderer(1081, 662)
                try:
                    for view in views:
                        bundle = output / ('export-' + str(repeat)) / view
                        export_baseline(bundle, view=view, renderer=renderer)
                        report['views'].setdefault(view, {})['bundle_' + str(repeat)] = bundle_hashes(bundle)
                finally:
                    renderer.close()
        for view in views:
            row = report['views'][view]
            assert row['bundle_1'] == row['bundle_2'], 'Non-deterministic bundle: ' + view
        scene_hashes = {report['views'][view]['bundle_1']['scene.bin'] for view in views}
        assert len(scene_hashes) == 1, 'Changing only the camera changed scene.bin'

        # Export context has closed before native measurement: no competing GL workload.
        for view in views:
            images = []
            row = report['views'][view]
            for repeat in (1, 2):
                bundle = output / ('export-' + str(repeat)) / view
                native_output = output / ('native-' + str(repeat)) / view
                metadata = json.loads((bundle / 'metadata.json').read_text(encoding='utf-8'))
                validation = command([viewer, '--bundle', bundle, '--route', 'orbit', '--validate-only'],
                                     output / ('validate-{}-{}.log'.format(view, repeat)), report)
                row['validation_' + str(repeat)] = json.loads(validation)
                command([viewer, '--bundle', bundle, '--output', native_output,
                         '--route', 'orbit', '--warmup', '24', '--frames', '120',
                         '--samples', '1', '--hidden', '--capture'],
                        output / ('native-{}-{}.log'.format(view, repeat)), report, timeout=180)
                benchmark = json.loads((native_output / 'benchmark-orbit.json').read_text(encoding='utf-8'))
                assert benchmark['frames'] == 120 and benchmark['warmup'] == 24
                assert not benchmark['recording'] and not benchmark['vsync']
                assert benchmark['msaa_samples'] == 1
                image, capture = inspect_capture(native_output, row['validation_' + str(repeat)]['shadow_resolution'])
                images.append(image)
                row['run_' + str(repeat)] = dict(
                    benchmark=benchmark, capture=capture,
                    bundle_metadata=metadata,
                    preview=str((native_output / 'preview.png').relative_to(output)))
            import numpy as np
            difference = np.abs(images[0].astype('int16') - images[1].astype('int16'))
            row['repeat_image_difference'] = dict(max_channel_delta=int(difference.max()),
                                                  changed_pixels=int(np.count_nonzero(np.any(difference, axis=2))))
            assert int(difference.max()) <= 1, 'Repeat capture differs by more than one RGB code: ' + view
            assert row['run_1']['capture']['depth_sha256'] == row['run_2']['capture']['depth_sha256'], \
                'Repeat shadow depth differs: ' + view
        report['passed'] = True
    except Exception as error:
        report['error'] = '{}: {}'.format(type(error).__name__, error)
        raise
    finally:
        report.pop('_output')
        write_json(output / 'report.json', report)
    print('PASS: ' + str(output / 'report.json'), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New/empty result directory')
    parser.add_argument('--build-dir', type=Path,
                        default=ROOT / 'captures/world-surroundings/build-lab00')
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--compiler', default='g++')
    run(parser.parse_args())
