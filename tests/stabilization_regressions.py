"""Sequential real GPU regressions; generated PNGs stay in ignored captures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run(report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for name in ('ground_separation', 'placement', 'placement_v2', 'photo',
                 'ai_api', 'lighting', 'lighting_api', 'lighting_ui',
                 'scene_clipping', 'shadow_baseline', 'shadow', 'shadow_ui', 'shot_camera_persistence'):
        script = ROOT / 'tests' / (('shadow' if name == 'shadow_baseline' else name) + '_smoke.py')
        output = ROOT / 'captures/stabilization-regressions' / ('shadow' if name == 'shadow_baseline' else name)
        command = [sys.executable, '-B', str(script), str(output)]
        if name == 'shadow_baseline':
            command.append('--baseline')  # Requires isolated 1033e5e at captures/shadow-baseline.
        started = time.perf_counter()
        print('RUN ' + name, flush=True)
        with (report_dir / (name + '.log')).open('w', encoding='utf8') as log:
            result = subprocess.run(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        records.append(dict(name=name, exit_code=result.returncode,
                            seconds=round(time.perf_counter()-started, 3),
                            command=['python', '-B', 'tests/'+script.name,
                                     str(output.relative_to(ROOT))] + (['--baseline'] if name == 'shadow_baseline' else [])))
        (report_dir / 'regressions.json').write_text(json.dumps(records, indent=2), encoding='utf8')
        print(name + ': exit ' + str(result.returncode), flush=True)
    return 1 if any(r['exit_code'] for r in records) else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('report_dir', type=Path)
    sys.exit(run(parser.parse_args().report_dir))
