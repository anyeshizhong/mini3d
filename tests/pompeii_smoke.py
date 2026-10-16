"""Real GL photographs, floor regression and moving-frame scale measurements."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from OpenGL import GL
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import render_scene_view
from tools.capture_sunset import desktop_context
from tools.build_roman_street import build_scene as build_street
from tools.build_pompeii import build_scene, VIEWS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    out = parser.parse_args().output; out.mkdir(parents=True, exist_ok=False)
    report = dict(quality='Moving render: 960x540, 1x AA, 2048 PCF shadows; photos: 4x AA',
                  timing_includes=['scene update', 'render', 'GPU completion'],
                  timing_excludes=['editor UI', 'PNG encoding', 'presentation'], timings={})
    with desktop_context():
        renderer = GLRenderer(1920, 1080); target = RenderTarget()
        try:
            street = Mini3DAPI(renderer); build_street(street)
            street.create_shot_camera(position=[.4, -8, 2.4], target=[0, 3, .1], focal_mm=24)
            street.set_atmosphere(ground=True, ground_z=0)
            street.capture(out / 'floor-overlap.png')
            street.set_atmosphere(ground=False)
            street.capture(out / 'floor-authored.png')
            # Same illumination/camera; only the render-only floor changes.
            a = np.array(Image.open(out / 'floor-overlap.png'))
            b = np.array(Image.open(out / 'floor-authored.png'))
            report['floor_changed_pixels'] = int(np.any(a != b, axis=2).sum())
            assert report['floor_changed_pixels'] > 1000

            city = Mini3DAPI(renderer); report['map'] = build_scene(city)
            for name, (position, look) in VIEWS.items():
                city.create_shot_camera(position=position, target=look, focal_mm=24, near=.05, far=300)
                city.capture(out / (name + '.png'))
                reference = np.array(Image.open(out / (name + '.png')))
                renderer.gpu_instancing = False
                city.capture(out / (name + '-unbatched.png'))
                assert np.array_equal(reference, np.array(Image.open(out / (name + '-unbatched.png')))), name
                renderer.gpu_instancing = True
                print('photo', name, flush=True)
            city.create_shot_camera(position=VIEWS['market'][0], target=VIEWS['market'][1],
                                    focal_mm=24, near=.05, far=300)
            city.capture(out / 'saved-view.png'); city.save_scene(out / 'district.scene.json')
            fresh = Mini3DAPI(renderer); fresh.load_scene(out / 'district.scene.json')
            fresh.capture(out / 'reloaded.png')
            a = np.array(Image.open(out / 'saved-view.png'))
            b = np.array(Image.open(out / 'reloaded.png'))
            report['reload_max_difference'] = int(np.abs(a.astype(int)-b.astype(int)).max())
            assert np.array_equal(a, b), 'Saved map changed its photograph'
            for preset in ('sunset', 'moonlit'):
                city.sky_preset(preset)
                assert city.get_atmosphere()['ground_z'] == -.14
                city.capture(out / ('market-' + preset + '.png'))
            # Restore identical light settings for the scaling comparison.
            city.set_lighting(mode='Scene', diffuse=3., ambient=.28)
            city.set_atmosphere(enabled=True, sun_temperature=5200, azimuth=-45,
                elevation=38, haze=.003, exposure_ev=0, sky_texture='procedural',
                sky_intensity=.8, tone_mapping='filmic', celestial_body='sun', sun_size=0)
            street.set_atmosphere(ground=True, ground_z=-.14)
            street.create_shot_camera(position=VIEWS['street'][0], target=VIEWS['street'][1],
                                      focal_mm=24, near=.05, far=300)
            city.create_shot_camera(position=VIEWS['street'][0], target=VIEWS['street'][1],
                                    focal_mm=24, near=.05, far=300)
            cases = [('street-original', street, 'street'), ('street-expanded', city, 'street'),
                     ('market-expanded', city, 'market'), ('court-expanded', city, 'court'),
                     ('overview-expanded', city, 'overview')]
            for repeat in range(3):
                for label, api, view in (cases if repeat % 2 == 0 else cases[::-1]):
                    times, draws, gpu, tris = [], [], [], []
                    p, look = (np.array(v, dtype=float) for v in VIEWS[view])
                    direction = look - p; direction /= np.linalg.norm(direction)
                    query = int(np.asarray(GL.glGenQueries(1)).reshape(-1)[0])
                    try:
                        for frame in range(26):
                            t = max(0, frame-6)/19
                            shot = api._app.shot_camera
                            shot.position = p + direction * t * (8 if view == 'overview' else 3)
                            shot.look_at(look)
                            started = time.perf_counter(); api._app.scene.update()
                            GL.glBeginQuery(GL.GL_TIME_ELAPSED, query)
                            render_scene_view(api._app.scene, shot, renderer, target, (960, 540), 1)
                            GL.glEndQuery(GL.GL_TIME_ELAPSED); GL.glFinish()
                            elapsed = (time.perf_counter() - started) * 1000
                            device = int(GL.glGetQueryObjectuiv(query, GL.GL_QUERY_RESULT))/1e6
                            if frame >= 6:
                                times.append(elapsed); gpu.append(device)
                                draws.append(renderer.render_stats['draw_calls'])
                                tris.append(renderer.render_stats['submitted_triangles'])
                    finally:
                        GL.glDeleteQueries(1, [query])
                    report['timings'].setdefault(label, []).append(dict(frame_ms=times,
                        mean_ms=float(np.mean(times)), p95_ms=float(np.percentile(times,95)),
                        gpu_ms=float(np.mean(gpu)), draw_calls=float(np.mean(draws)),
                        triangles=float(np.mean(tris))))
                    print(label, repeat, round(np.mean(times), 2), 'ms', flush=True)
            report['gpu'] = GL.glGetString(GL.GL_RENDERER).decode()
            report['gl_error'] = int(GL.glGetError()); assert report['gl_error'] == 0
            (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        finally:
            target.close(); renderer.close()


if __name__ == '__main__':
    main()
