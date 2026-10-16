"""Compare native RGB/depth captures against the exported Python reference.

Always reports exact equality and full difference metrics. Numerical tolerances
are explicit command-line choices, never automatically widened after a failure.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-color', type=int, default=0)
    parser.add_argument('--max-depth', type=float, default=0.)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(color_tolerance=args.max_color, depth_tolerance=args.max_depth, cases={})
    success = True
    references = sorted((args.bundle / 'reference').glob('*.png'))
    if not references:
        raise RuntimeError('No reference captures found')
    for reference in references:
        name = reference.stem
        native = args.native / 'captures' / (name + '.ppm')
        if not native.exists():
            report['cases'][name] = dict(passed=False, error='Native capture missing')
            success = False
            continue
        a = np.asarray(Image.open(reference).convert('RGB'))
        b = np.asarray(Image.open(native).convert('RGB'))
        if a.shape != b.shape:
            raise ValueError((name, a.shape, b.shape))
        delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
        depth_a = np.load(args.bundle / 'reference' / (name + '.depth.npy'))
        depth_b = np.fromfile(args.native / 'captures' / (name + '.depth.f32'), dtype='<f4').reshape(depth_a.shape)
        if not np.isfinite(depth_a).all() or not np.isfinite(depth_b).all():
            raise ValueError('Non-finite shadow depth: ' + name)
        depth_delta = np.abs(depth_a.astype(np.float64) - depth_b.astype(np.float64))
        row = dict(max_color=int(delta.max()), mean_absolute_color=float(delta.mean()),
                   changed_pixels=int(np.any(delta != 0, axis=2).sum()),
                   color_elements_over_tolerance=int((delta > args.max_color).sum()),
                   max_depth=float(depth_delta.max()), mean_absolute_depth=float(depth_delta.mean()),
                   changed_depth_texels=int((depth_delta != 0).sum()),
                   depth_texels_over_tolerance=int((depth_delta > args.max_depth).sum()))
        row['exact'] = row['changed_pixels'] == 0 and row['changed_depth_texels'] == 0
        row['passed'] = row['max_color'] <= args.max_color and row['max_depth'] <= args.max_depth
        report['cases'][name] = row
        success &= row['passed']
        Image.fromarray(b).save(args.output / (name + '-native.png'))
        Image.fromarray(np.clip(delta * 8, 0, 255).astype(np.uint8)).save(args.output / (name + '-difference-x8.png'))
        print(name, json.dumps(row), flush=True)
    report['passed'] = bool(success)
    (args.output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
