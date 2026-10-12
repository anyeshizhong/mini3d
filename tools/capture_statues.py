"""Photograph optional British Museum scans at known sizes; no asset redistribution.

python -B tools/capture_statues.py --output captures/statue-dof
Download the two models linked in docs/statue-photography.md to model/12_vespasian
and model/13_asclepius before running. Uses a desktop GL context on Windows.
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.placement import geometry_bounds
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_shot
from mini3d.gl_state import read_rgb
from mini3d.viewport_cache import viewport_key
from tools.capture_sunset import desktop_context, build_scene


def subject(api, path, height, xy):
    eid = api.spawn(path, name=path.stem, placement_type='character', keep_upright=True)['entity_id']
    entity = api._app.scene.find_by_id(eid)
    lo, hi = geometry_bounds(entity)
    api.set_transform(eid, scale=[height/(hi[2]-lo[2])]*3)
    lo, hi = geometry_bounds(entity)
    api.set_transform(eid, position=[xy[0]-(lo[0]+hi[0])/2, xy[1]-(lo[1]+hi[1])/2, -lo[2]])
    return eid


def pixels(path):
    return pygame.surfarray.array3d(pygame.image.load(str(path))).transpose(1, 0, 2)


def run(output):
    head = ROOT/'model/12_vespasian/vespasian.glb'
    statue = ROOT/'model/13_asclepius/asclepius.glb'
    for path in (head, statue):
        if not path.is_file():
            raise FileNotFoundError('Download the optional scan first: '+str(path))
    output.mkdir(parents=True, exist_ok=True)
    with desktop_context():
        renderer = GLRenderer(1920, 1280); renderer.render_mode = 'REALISTIC'
        target = RenderTarget(); api = Mini3DAPI(renderer)
        report = {'gpu': gl.glGetString(gl.GL_RENDERER).decode(), 'checks': {}, 'assets': {}}
        try:
            front = subject(api, head, .4572, (-.085, 0))
            rear = subject(api, statue, .6223, (.30, 1.5))
            api.sunset_preset()
            api.set_atmosphere(azimuth=-70, elevation=18, sky_texture='sunset', sky_intensity=.65,
                ground_texture='gravel', ground_scale=.4, haze=.004, exposure_ev=-.2, tone_mapping='filmic')
            api.set_lighting(diffuse=4, ambient=.07)
            api.set_shadows(resolution=4096, bias=.000025)
            api.create_shot_camera(position=[0,-1.7,.29], target=[.055,0,.245], focal_mm=85,
                aspect='3:2', near=.01, far=50, dof_enabled=False)
            api.set_antialiasing(4)
            api.focus_at([-.085, -.075, .34])
            report['assets'] = {name: api.get_entity(eid, True) for name, eid in [('vespasian',front),('asclepius',rear)]}
            api.capture(output/'statues-sharp.png')
            report['settings'] = {}
            for aperture in (1.4, 2.8, 8):
                api.set_depth_of_field(enabled=True, f_number=aperture)
                name = 'statues-f'+str(aperture)+'.png'
                api.capture(output/name)
                camera = api._app.shot_camera
                report['settings'][name] = {'focus_distance_m':camera.focus_distance, 'f_number':aperture,
                    'background_radius_px':float(camera.circle_of_confusion(3.2))}
            # The three apertures must not all clamp to the 32px radius limit.
            assert report['settings']['statues-f2.8.png']['background_radius_px'] < 32
            large, small = pixels(output/'statues-f1.4.png'), pixels(output/'statues-f8.png')
            assert np.count_nonzero(large != small) > 10000, 'Aperture did not change the real photograph'
            report['checks']['three_apertures_distinct'] = True
            api.set_depth_of_field(f_number=2.8)
            api.save_scene(output/'statues-portrait.scene.json')
            render_shot(api._app.scene, api._app.shot_camera, renderer, target)
            preview = np.frombuffer(read_rgb(0,0,1920,1280),np.uint8).reshape(1280,1920,3)[::-1].copy()
            np.testing.assert_array_equal(preview, pixels(output/'statues-f2.8.png'))
            report['checks']['preview_png_exact'] = True
            api.set_depth_of_field(focus_distance=3.2, f_number=1.4)
            api.capture(output/'statues-focus-rear.png')
            assert np.count_nonzero(pixels(output/'statues-focus-rear.png') != large) > 10000
            report['checks']['real_statue_focus_swap'] = True
            api.load_scene(output/'statues-portrait.scene.json')
            api.capture(output/'statues-reloaded.png')
            np.testing.assert_array_equal(pixels(output/'statues-reloaded.png'), pixels(output/'statues-f2.8.png'))
            report['checks']['scene_reload_exact'] = True
            # Static photo preview must invalidate when only environment changes.
            app = api._app; app.camera_view = True
            before_key = viewport_key(app, (960,640), True, 'REALISTIC')
            api.set_atmosphere(exposure_ev=.4)
            assert viewport_key(app, (960,640), True, 'REALISTIC') != before_key
            render_shot(app.scene, app.shot_camera, renderer, target)
            changed_preview = np.frombuffer(read_rgb(0,0,1920,1280),np.uint8).reshape(1280,1920,3)[::-1].copy()
            api.capture(output/'statues-exposure-check.png')
            np.testing.assert_array_equal(changed_preview, pixels(output/'statues-exposure-check.png'))
            assert np.count_nonzero(changed_preview != preview) > 10000
            report['checks']['exposure_invalidates_preview_and_matches_png'] = True
            # Full composition uses an enlarged 2.4m display copy; the portrait above uses measured original sizes.
            for item in api.list_entities(): api.delete(item['entity_id'])
            app.camera_view = False
            build_scene(api, str(statue), hero=False)
            api.set_lighting(diffuse=4,ambient=.07)
            api.focus_at([0,0,2.1]); api.set_depth_of_field(enabled=True, f_number=8)
            api.save_scene(output/'asclepius-sunset.scene.json')
            api.capture(output/'asclepius-sunset.png')
            report['fullbody_display_height_m'] = 2.4
        finally:
            target.close(); renderer.close()
        (output/'statue-validation.json').write_text(json.dumps(report,indent=2), encoding='utf8')
        print(json.dumps(report,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output.resolve())
