"""Capture an unobstructed slope diagnostic from completed Q-1 inputs.

Does not change benchmark cameras, performance samples or source bundles. The
original side camera overlaps the red marker; this separate reproducible view
records the correction explicitly instead of overwriting benchmark evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from sculpt_native import NativeTerrain
from material_maps import weight_rgba
from run_sculpt import png_from_ppm
from run_baseline import write_json
import baseline_scene as baseline


def run(args):
    import pygame as pg
    source, output = args.input.resolve(), args.output.resolve()
    report = json.loads((source/'report.json').read_text(encoding='utf-8'))
    if not report['passed'] or report['stage'] != 'LAB-02B-Q1':
        raise ValueError('A completed Q1 measurement input is required')
    if output == source or output in source.parents or source in output.parents:
        raise ValueError('Keep capture output separate from benchmark evidence')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new empty output directory')
    library = args.library.resolve()
    if hashlib.sha256(library.read_bytes()).hexdigest() != report['library_sha256']:
        raise ValueError('DLL must match the input measurement exactly')
    output.mkdir(parents=True, exist_ok=True)
    result = dict(passed=False, visual_only=True, performance_remeasured=False,
                  input_report_sha256=hashlib.sha256((source/'report.json').read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  camera=dict(position=[-7., 4., 5.8], target=[0., 2., 3.3], up=[0.,0.,1.]), fixtures={})
    native = None
    try:
        pg.display.init()
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION,3); pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK,pg.GL_CONTEXT_PROFILE_CORE)
        pg.display.set_mode((1081,662),pg.OPENGL|pg.DOUBLEBUF|pg.HIDDEN)
        camera = baseline.camera_for_view('oblique')
        camera.position = result['camera']['position']; camera.look_at(result['camera']['target'])
        result['camera'].update(fov_y=float(camera.fov_y), near=float(camera.near), far=float(camera.far),
                                view=np.asarray(camera.view_matrix).tolist(),
                                projection=np.asarray(camera.projection_matrix(1081./662.)).tolist())
        for fixture, variants in report['fixtures'].items():
            result['fixtures'][fixture] = {}
            for variant in variants:
                folder = output/fixture/variant; folder.mkdir(parents=True)
                bundle = folder/'bundle'
                original = source/fixture/variant
                shutil.copytree(original/'initial-bundle',bundle)
                (bundle/'frames.bin').write_bytes(baseline._frame_bytes(camera,1081,662))
                native = NativeTerrain(library,bundle)
                tid = native.texture_id(0,3)
                assert native.texture_info(tid)==(257,257)
                records = {}
                for name, filename in (('painted','weights.npy'),('diagnostic','diagnostic-weights.npy')):
                    weights = np.load(original/filename,allow_pickle=False)
                    native.update_textures([(tid,0,0,weight_rgba(weights))])
                    assert np.array_equal(native.read_texture(tid),weight_rgba(weights))
                    for _ in range(48):
                        native.render(0)
                    ppm = folder/('steep-'+name+'.ppm'); native.capture_color(ppm)
                    png = ppm.with_suffix('.png'); png_from_ppm(ppm,png)
                    records[name] = dict(png=png.relative_to(output).as_posix(),
                                         sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                                         weight_sha256=hashlib.sha256(weights.tobytes()).hexdigest())
                result['fixtures'][fixture][variant] = records
                native.close(); native = None
        result['passed'] = True
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        try:
            if native:
                native.close()
        finally:
            pg.display.quit(); write_json(output/'report.json',result)
    print('PASS '+str(output/'report.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--library',type=Path,default=ROOT/'captures/world-surroundings/build-lab02b-q/bin/terrain_lab.dll')
    run(parser.parse_args())
