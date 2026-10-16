"""Compare the native shadow fit against the full editable Pompeii scene.

No OpenGL is used. Reference values are computed independently by the existing
Python implementation; no fitted matrix is used by native render benchmarks.
"""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import time
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project.resolve()))
    sys.path.insert(0, str(args.project.resolve() / 'tests'))
    from mini3d.api import Mini3DAPI
    from mini3d.atmosphere import prepare_photographic_scene
    from mini3d.lighting import scene_light_direction
    from mini3d.shadow_fit import receiver_matrix
    from tools.build_pompeii import build_scene
    from spqr_performance_benchmark import pose
    from threadpoolctl import threadpool_limits
    library = ctypes.CDLL(str(args.library.resolve()))
    function = library.spqr_fit_shadow
    doubles = np.ctypeslib.ndpointer(dtype=np.float64, flags='C_CONTIGUOUS')
    flags_type = np.ctypeslib.ndpointer(dtype=np.uint32, flags='C_CONTIGUOUS')
    function.argtypes = [doubles, doubles, flags_type, ctypes.c_uint32,
                        doubles, doubles, doubles, ctypes.c_uint32, doubles]
    function.restype = ctypes.c_int
    api = Mini3DAPI()
    build_scene(api)
    app = api._app
    camera = app.viewer.camera
    camera.fov_y = 48.
    aspect = 1081. / 662.
    ground = None
    report = dict(entity_roots=len(api.list_entities()), cases={}, tolerance=1e-10)
    with threadpool_limits(1, user_api='blas'):
        for elevation in (38., 3., -3.):
            api.set_atmosphere(elevation=elevation)
            for route, t in (('walk', 0.), ('walk', .5), ('orbit', 0.), ('orbit', .5)):
                camera.position, target = pose(route, t)
                camera.look_at(target)
                app.scene.update()
                app.viewer.update_clipping()
                scene, ground = prepare_photographic_scene(app.scene, camera, ground)
                scene.update()
                entities = scene.get_flat_render_list()
                bounds = np.ascontiguousarray([entity.model.bounds for entity in entities], dtype=np.float64)
                worlds = np.ascontiguousarray([entity.world_matrix for entity in entities], dtype=np.float64)
                flags = np.asarray([int(bool((getattr(entity.model, 'material', None) or {}).get('extras', {}).get('photographicGround')))
                                    for entity in entities], dtype=np.uint32)
                direction = np.ascontiguousarray(scene_light_direction(scene), dtype=np.float64)
                view = np.ascontiguousarray(camera.view_matrix, dtype=np.float64)
                projection = np.ascontiguousarray(camera.projection_matrix(aspect), dtype=np.float64)
                reference = receiver_matrix(entities, direction, camera, 2048, aspect=aspect)
                actual = np.zeros((4, 4), dtype=np.float64)
                started = time.perf_counter()
                result = function(bounds, worlds, flags, len(entities), direction, view, projection, 2048, actual)
                elapsed = (time.perf_counter() - started) * 1000
                if reference is None or not result:
                    raise AssertionError(('Unexpected fitting fallback', elevation, route, t))
                difference = float(np.abs(actual - reference).max())
                key = '{}-{}-sun{}'.format(route, t, elevation)
                row = dict(primitives=len(entities), max_matrix_difference=difference,
                           native_fit_observed_ms=elapsed, float32_matrix_exact=bool(np.array_equal(actual.astype('f4'), reference.astype('f4'))),
                           passed=difference <= report['tolerance'])
                report['cases'][key] = row
                print(key, row, flush=True)
                if not row['passed']:
                    raise AssertionError((key, row))
    report['passed'] = all(row['passed'] for row in report['cases'].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
