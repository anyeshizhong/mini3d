"""Sequential V2 unit/UI/GPU acceptance; no downloads or existing worktrees needed.

Run from the project root using the installed Python environment. Full quality
and Rome suites require the original licensed local assets. Outputs are ignored.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]


def snapshot(output):
    """Make a new read-only-input baseline from Git, never touch a worktree."""
    destination = output / 'reference-1033e5e'
    if destination.exists():
        raise FileExistsError('Use a fresh output directory for the reference snapshot')
    archive = subprocess.check_output(['git', 'archive', '1033e5e', 'mini3d'], cwd=str(ROOT))
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            path = (destination / member.name).resolve()
            if destination.resolve() not in path.parents or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe Git archive member')
        tar.extractall(str(destination))
    # Old source is a namespace package; isolate it from today's regular package.
    (destination / 'mini3d/__init__.py').write_text('"""Historical test snapshot."""\n')
    return destination


def run(output, suite):
    if output.exists():
        raise FileExistsError('Choose a new output directory to preserve previous evidence')
    output.mkdir(parents=True)
    commands = []
    def smoke(name, *extra):
        commands.append((name, ['tests/' + name + '.py', str(output / name)] + list(extra)))
    if suite in ('core', 'all'):
        commands.append(('unit', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v']))
        for name in ('editor_smoke', 'editor_integration_smoke', 'file_dialog_smoke',
                     'ground_separation_smoke', 'placement_smoke', 'placement_v2_smoke',
                     'lighting_smoke', 'lighting_api_smoke', 'lighting_ui_smoke',
                     'scene_clipping_smoke', 'shadow_ui_smoke', 'photo_smoke', 'ai_api_smoke',
                     'shot_camera_persistence_smoke', 'shot_msaa_smoke', 'consolidation_gpu_regression'):
            smoke(name)
        smoke('stl_render_smoke')
        commands[-1] = ('stl_render_smoke', ['tests/stl_render_smoke.py',
                           'model/06_stl_cube/cube.STL', str(output/'stl_render_smoke')])
        smoke('ibl_gpu_regression')
        commands.append(('ibl_gpu_4x', ['tests/ibl_gpu_regression.py', str(output/'ibl_gpu_4x'), '4']))
        smoke('demo_equivalence')
        commands.append(('ui_photography_81', ['tests/ui_photography_journey_20261010.py',
                         '--output', str(output/'ui_photography_81'), '--panel-release']))
        commands.append(('api_photography', ['tests/api_photography_workflow_20261010.py']))
        baseline = snapshot(output)
        commands.append(('shadow_baseline', ['tests/shadow_smoke.py', str(output/'shadow'),
                          '--baseline', '--baseline-root', str(baseline)]))
        commands.append(('shadow', ['tests/shadow_smoke.py', str(output/'shadow')]))
    if suite in ('quality', 'all'):
        commands.extend([
            ('renderer_v2', ['tests/renderer_v2_smoke.py', '--assets-root', '.', '--output', str(output/'renderer_v2')]),
            ('cpu_cache', ['tests/renderer_v2_cpu_cache_benchmark.py', '--assets-root', '.', '--output',
                           str(output/'cpu_cache'), '--gpu', '--samples', '21']),
            ('q1', ['tests/ibl_quality_q1.py', '--assets-root', 'model/11_benchmark_round01',
                    '--output', str(output/'q1'), '--original', 'docs/renderer-v2/q1']),
            ('q2', ['tools/quality_q2/mini.py', '--assets-root', 'model/11_benchmark_round01',
                    '--output', str(output/'q2'), '--hdr', 'docs/renderer-v2/q2/assets/studio_small_02_2k.hdr'])])
    if suite in ('rome', 'all'):
        smoke('shadow_assets_smoke')
        smoke('rome_integration_smoke')
        commands.append(('rome_ui', ['tests/rome_integration_ui_smoke.py', str(output/'rome_integration_smoke')]))
        smoke('rome_added_models_smoke')
        commands.append(('rome_performance', ['tests/shadow_fit_performance_20261010.py', 'real',
                         '--output', str(output/'rome_performance/results.json'), '--cpu-samples', '21',
                         '--gpu-samples', '5', '--resolutions', '1024', '4096']))
        commands.append(('shadow_motion', ['tests/shadow_motion_audit_20261010.py', '--output',
                         str(output/'shadow_motion'), '--frames', '121', '--resolutions', '1024', '4096']))
        commands.append(('caster_depth', ['tests/shadow_motion_audit_20261010.py', '--output',
                         str(output/'caster_depth'), '--z-probe-only']))
    report = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'], cwd=str(ROOT)).decode().strip(),
                  suite=suite, runs=[])
    for name, arguments in commands:
        started = time.perf_counter()
        print('RUN ' + name, flush=True)
        with (output/(name+'.log')).open('w', encoding='utf8') as log:
            result = subprocess.run([sys.executable, '-B'] + arguments, cwd=str(ROOT),
                                    stdout=log, stderr=subprocess.STDOUT)
        report['runs'].append(dict(name=name, exit_code=result.returncode,
                                  seconds=round(time.perf_counter()-started,3)))
        (output/'runs.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(name + ': exit ' + str(result.returncode), flush=True)
    report['identical_images'] = []
    for case, reference in (('q1','docs/renderer-v2/q1'), ('q2','docs/renderer-v2/q2')):
        if (output/case).is_dir():
            patterns = ('*-A.png','*-B.png') if case=='q1' else ('*-mini-*.png','*-coverage-*.png')
            for pattern in patterns:
                for image in sorted((output/case).glob(pattern)):
                    old = ROOT/reference/image.name
                    same = old.is_file() and image.read_bytes() == old.read_bytes()
                    report['identical_images'].append(dict(name=case+'/'+image.name, exact_bytes=same,
                        sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
    report['passed'] = all(r['exit_code']==0 for r in report['runs']) and all(
        r['exact_bytes'] for r in report['identical_images'])
    (output/'runs.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', choices=('core','quality','rome','all'), default='all')
    args = parser.parse_args()
    sys.exit(run(args.output.resolve(), args.suite))
