"""Compare canonical example frames against historical Git sources with fixed timing.

Uses the current GL renderer in both runs; shaders are checked separately by Q2.
Original sources are read from Git in memory, without another worktree.
"""
import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pygame
from render_smoke import run_demo


class FixedClock:
    def tick(self, *args):
        return 16


def run(output, reference='efd5ddc'):
    output.mkdir(parents=True, exist_ok=True)
    sources = {name: subprocess.check_output(
        ['git', 'show', reference + ':' + name], cwd=str(ROOT)).decode('utf8')
        for name in ('1.py', '1 copy.py', '2.py')}
    original_run_path = runpy.run_path

    def historical(path, run_name=None):
        name = Path(path).name
        if name not in sources:
            return original_run_path(path, run_name=run_name)
        namespace = dict(__file__=str(path), __name__=run_name, __package__='')
        exec(compile(sources[name], str(path), 'exec'), namespace)
        return namespace

    for phase in ('before', 'after'):
        directory = output / phase
        directory.mkdir(exist_ok=True)
        with patch.object(pygame.time, 'Clock', FixedClock):
            if phase == 'before':
                with patch.object(runpy, 'run_path', historical):
                    for name in sources:
                        run_demo(name, directory)
            else:
                for old_name, module_name in (
                    ('1.py', 'examples.primitives'),
                    ('1 copy.py', 'examples.circular_motion'),
                    ('2.py', 'examples.urdf_car'),
                ):
                    run_demo(module_name, directory, capture_stem=Path(old_name).stem)
    images = []
    for before in (output / 'before').glob('*.png'):
        after = output / 'after' / before.name
        assert before.read_bytes() == after.read_bytes(), before.name
        images.append(before.name)
    report = dict(reference=reference, fixed_frame_ms=16, identical_pngs=images)
    (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reference', default='efd5ddc')
    args = parser.parse_args()
    run(args.output, args.reference)
