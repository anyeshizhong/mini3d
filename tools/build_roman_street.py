"""Build the self-contained SPQR scene using the normal scene API.

Run from the project root: python -B tools/build_roman_street.py
Open: python -B -m mini3d --scene examples/roman_street/street.json
No window, downloaded models or renderer is required to build/save the scene.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_scene(api, segments=6, road_width=6.0, variation=True, seed=17, extension_segments=4):
    """Example art direction only; the street command itself preserves lighting."""
    result = api.create_roman_street(segments=segments, road_width=road_width,
                                     variation=variation, seed=seed, extension_segments=extension_segments)
    api.set_lighting(mode='Scene', diffuse=3.0, ambient=.28)
    api.set_atmosphere(enabled=True, ground=False, sun_temperature=5200,
        azimuth=-45, elevation=38, haze=.003, exposure_ev=0,
        sky_texture='procedural', sky_intensity=.8, tone_mapping='filmic')
    api.set_shadows(enabled=True, resolution=2048, bias=.00015, pcf=True)
    half_length = segments * 2
    api.set_editor_camera(position=[26, -half_length - 24, 25], target=[0, 0, 2], fov_y=48)
    api.create_shot_camera(position=[1.1, -half_length + .8, 1.7],
        target=[0, half_length + .5, 3.0], focal_mm=24, aspect='16:9', near=.05, far=200)
    api.set_antialiasing(4)
    api.select_entities([])
    api._app.show_grid = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'examples/roman_street/street.json')
    parser.add_argument('--segments', type=int, default=6)
    parser.add_argument('--road-width', type=float, default=6.0)
    args = parser.parse_args()
    from mini3d.api import Mini3DAPI
    api = Mini3DAPI()
    result = build_scene(api, args.segments, args.road_width)
    api.save_scene(args.output)
    print('{}: {} modules, {:g} m'.format(args.output, result['entity_count'], result['length']))


if __name__ == '__main__':
    main()
