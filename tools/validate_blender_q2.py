"""Reopen the three original Q2 .blend files with fixed Blender 3.6.23.

Writes only a new output directory; never resaves the benchmark scenes.
Blender and Pillow are validation tools, not new application dependencies.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def run(blender, output):
    version = subprocess.check_output([str(blender), '--version']).decode(errors='replace').splitlines()[0]
    if version != 'Blender 3.6.23':
        raise ValueError('Expected Blender 3.6.23, got ' + version)
    if output.exists():
        raise FileExistsError('Use a fresh output directory')
    output.mkdir(parents=True)
    report = dict(version=version, cases=[])
    for name in ('Lantern', 'Avocado', 'spheres'):
        source = ROOT/'docs/renderer-v2/q2'/(name+'.blend')
        started = time.perf_counter()
        with (output/(name+'.log')).open('w',encoding='utf8') as log:
            result = subprocess.run([str(blender), '--background', str(source),
                '--render-output', str(output/(name+'-')), '--render-format', 'PNG', '--render-frame', '1'],
                cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        current = output/(name+'-0001.png')
        reference = source.with_name(name+'-eevee.png')
        record = dict(name=name, exit_code=result.returncode, seconds=round(time.perf_counter()-started,3))
        if current.is_file():
            a=np.array(Image.open(current).convert('RGBA')).astype(np.int16)
            b=np.array(Image.open(reference).convert('RGBA')).astype(np.int16)
            delta=np.abs(a-b)
            record.update(changed_pixels=int(np.any(delta,axis=2).sum()), max_channel_delta=int(delta.max()),
                          exact_png_bytes=current.read_bytes()==reference.read_bytes())
        report['cases'].append(record)
        (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(record),flush=True)
    report['passed']=all(c['exit_code']==0 and c.get('changed_pixels')==0 for c in report['cases'])
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.exit(run(args.blender.resolve(),args.output.resolve()))
