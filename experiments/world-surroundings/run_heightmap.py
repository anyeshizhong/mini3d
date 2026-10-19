"""LAB-01: import grayscale PNG, validate the terrain surface, render in SPQR."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from run_baseline import (bundle_hashes, command, digest, inspect_capture,
                          source_hashes, write_json)
import baseline_scene as baseline


def fixture_samples(rows, cols, bits):
    """Original asymmetric terrain fixture; fixed amplitude, no per-image normalization."""
    y, x = np.meshgrid(np.linspace(0, 1, rows), np.linspace(0, 1, cols), indexing='ij')
    hill = .66 * np.exp(-(((x - .32) / .17) ** 2 + ((y - .62) / .23) ** 2))
    ridge = .28 * np.exp(-(((x - .76) / .12) ** 2 + ((y - .35) / .32) ** 2))
    elevation = .035 + .09 * x + .04 * y + hill + ridge
    return np.rint(elevation * ((1 << bits) - 1)).astype('uint16' if bits == 16 else 'uint8')


def check_surface(terrain, material, chunk_cells):
    """Compare the query to independent ray tests against the actual chunk meshes."""
    from mini3d.picking import _triangle_hit
    started = time.perf_counter()
    full = terrain.to_mesh(material)
    chunks = terrain.iter_mesh_chunks(material, chunk_cells=chunk_cells)
    rows, cols = terrain.heights.shape
    grid = full.vertices[:, :3].reshape(rows, cols, 3).astype('float64')
    points = [(grid[r, c, 0], grid[r, c, 1]) for r, c in
              ((0, 0), (0, cols - 1), (rows - 1, 0), (rows - 1, cols - 1),
               (rows // 2, cols // 2), (0, cols // 2), (rows - 1, cols // 2),
               (rows // 2, 0), (rows // 2, cols - 1))]
    # Includes interior points of both triangles, exact grid vertices/edges,
    # and chunk boundaries. Queries don't use the ray implementation below.
    for k in range(16):
        row, col = (k * 13) % (rows - 1), (k * 19) % (cols - 1)
        a, b, d = grid[row, col], grid[row, col + 1], grid[row + 1, col]
        for u, v in ((.73, .21), (.18, .67)):
            points.append((float(a[0] + (b[0] - a[0]) * u),
                           float(a[1] + (d[1] - a[1]) * v)))
    for chunk in chunks:
        points.append(tuple(grid[chunk['row_start'], chunk['col_start'], :2]))
    points = sorted(set(points))
    top = float(grid[:, :, 2].max()) + 10
    lower = float(grid[:, :, 2].min()) - 10
    results = []
    for x, y in points:
        actual = terrain.query_surface(float(x), float(y))
        assert actual['hit'], (x, y)
        ray = np.asarray((x, y, top), dtype='float64')
        hits = [_triangle_hit(chunk['mesh'], ray, np.array((0., 0., -1.)), 0., top - lower)
                for chunk in chunks]
        hits = [hit for hit in hits if hit is not None]
        assert hits, ('No mesh ray hit', x, y)
        ray_height = top - min(hit[0] for hit in hits)
        error = abs(actual['height'] - ray_height)
        assert error <= 1e-4, (x, y, actual, ray_height)
        row, col = actual['cell']
        triangle = (row * (cols - 1) + col) * 2 + actual['triangle']
        tri = full.vertices[full.indices[triangle], :3].astype('float64')
        normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
        normal /= np.linalg.norm(normal)
        assert np.allclose(normal, actual['normal'], rtol=0, atol=1e-6)
        results.append(dict(x=float(x), y=float(y), query=actual,
                            ray_height=float(ray_height), height_error=float(error)))
    assert len(results) >= 20
    xmin, xmax = float(grid[0, 0, 0]), float(grid[0, -1, 0])
    ymin, ymax = float(grid[0, 0, 1]), float(grid[-1, 0, 1])
    outside = [(xmin - 1, ymin), (xmax + 1, ymax), (xmin, ymin - 1), (xmax, ymax + 1)]
    assert all(not terrain.query_surface(x, y)['hit'] for x, y in outside)
    covered = np.zeros((rows - 1, cols - 1), dtype='uint8')
    normal_grid = full.vertex_normals.reshape(rows, cols, 3)
    for chunk in chunks:
        r0, c0, r1, c1 = (chunk[key] for key in ('row_start', 'col_start', 'row_end', 'col_end'))
        covered[r0:r1, c0:c1] += 1
        mesh = chunk['mesh']
        assert np.array_equal(mesh.vertices[:, :3], grid[r0:r1 + 1, c0:c1 + 1].reshape(-1, 3))
        assert np.array_equal(mesh.vertex_normals, normal_grid[r0:r1 + 1, c0:c1 + 1].reshape(-1, 3))
    assert np.all(covered == 1), 'Missing or duplicate chunk cells'
    assert sum(len(c['mesh'].indices) for c in chunks) == len(full.indices)
    return dict(query_count=len(results), queries=results, outside_queries=outside,
                max_height_error=max(row['height_error'] for row in results),
                chunks=len(chunks), vertices=len(full.vertices), triangles=len(full.indices),
                chunk_vertices=sum(len(c['mesh'].vertices) for c in chunks),
                chunk_geometry_bytes=sum(sum(getattr(c['mesh'], field).nbytes for field in
                    ('vertices', 'indices', 'vertex_normals', 'texcoords')) for c in chunks),
                surface_validation_seconds=time.perf_counter() - started,
                seam_positions_and_normals_exact=True)


def terrain_scene(terrain, chunk_cells):
    from mini3d.scene import Entity
    scene = baseline.create_baseline_scene()
    ground = scene.root_entities[0]
    chunks = terrain.iter_mesh_chunks(ground.model.material, chunk_cells=chunk_cells)
    ground.name, ground.model = 'Terrain chunk 0', chunks[0]['mesh']
    for index, chunk in enumerate(chunks[1:], 1):
        scene.add(Entity(chunk['mesh'], 'Terrain chunk ' + str(index)))
    # Reuse existing marker assets, anchored at one queried surface point.
    # This is a numeric probe, not a general building-foundation solver.
    for marker in scene.root_entities[1:4]:
        x, y = marker.pos[:2]
        u, v = (x + 18.) / 36., (y + 13.) / 26.
        x = terrain.origin[0] + u * terrain.size[0]
        y = terrain.origin[1] + v * terrain.size[1]
        hit = terrain.query_surface(float(x), float(y))
        assert hit['hit']
        marker.pos = np.asarray((x, y, hit['height']))
        marker.scale = np.full(3, max(terrain.size[0] / 36., terrain.size[1] / 26.))
    scene.update()
    return scene


def export_terrain(terrain, folder, view, renderer, chunk_cells, base_z, height_range):
    from mini3d.native_photo_bundle import export_live_bundle
    folder.mkdir(parents=True, exist_ok=True)
    scene = terrain_scene(terrain, chunk_cells)
    camera = baseline.camera_for_view(view)
    center = np.asarray(terrain.origin) + np.asarray(terrain.size) / 2
    scale = max(terrain.size[0] / 36., terrain.size[1] / 26., height_range / 8.)
    pose = baseline._CAMERA_POSES[view]
    position = np.asarray(pose['position']) * scale + np.asarray((*center, base_z))
    target = np.asarray(pose['target']) * scale + np.asarray((*center, base_z))
    camera.position = position
    camera.near *= scale
    camera.far *= scale
    camera.look_at(target, up=(0., 0., 1.))
    bundle = export_live_bundle(scene, camera, renderer, folder, ROOT / 'spqr-native', shared_textures=False)
    baseline.write_frames(folder, camera)
    metadata = dict(counts=bundle['counts'], view=view, camera=baseline._camera_metadata(
        camera, baseline.WIDTH, baseline.HEIGHT, target),
        shape=list(terrain.heights.shape), origin=list(terrain.origin), size=list(terrain.size),
        chunk_cells=chunk_cells, height_range=height_range, base_z=base_z,
        shadow_resolution=baseline.SHADOW_RESOLUTION)
    write_json(folder / 'metadata.json', metadata)
    return metadata


def run(args):
    from heightmap_io import load_heightmap, read_heightmap, save_heightmap
    output, build = args.output.resolve(), args.build_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new, empty --output directory')
    if output == build or output in build.parents or build in output.parents:
        raise ValueError('Build and result directories must be separate')
    output.mkdir(parents=True, exist_ok=True)
    import PIL
    report = dict(passed=False, stage='LAB-01', commands=[], _output=output, cases={},
                  environment=dict(python=sys.version, executable=sys.executable,
                                   os=platform.platform(), numpy=np.__version__, pillow=PIL.__version__),
                  settings=dict(size=args.size, origin=args.origin, base_z=args.base_z,
                                height_range=args.height_range, flip_y=args.flip_y,
                                chunk_cells=args.chunk_cells, max_samples=1048576),
                  experiment_requirements_sha256=digest(HERE / 'requirements.txt'))
    try:
        report['git_head'] = command(['git', 'rev-parse', 'HEAD'], output / 'git-head.log', report).strip()
        report['git_status_before'] = command(['git', 'status', '--short'], output / 'git-status.log', report)
        cmake, compiler, ninja = (shutil.which(name) for name in (args.cmake, args.compiler, 'ninja'))
        if not all((cmake, compiler, ninja)):
            raise RuntimeError('CMake, MinGW g++, and Ninja are required')
        report['tools'] = {name: command([tool, '--version'], output / (name + '-version.log'), report).splitlines()[0]
                           for name, tool in (('cmake', cmake), ('compiler', compiler), ('ninja', ninja))}
        command([cmake, '-S', ROOT / 'spqr-native', '-B', build, '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER=' + compiler,
                 '-DCMAKE_MAKE_PROGRAM=' + ninja], output / 'configure.log', report)
        command([cmake, '--build', build, '--target', 'spqr-native', '--parallel', '2'], output / 'build.log', report)
        viewer = build / 'bin/spqr-native.exe'
        report['viewer'] = dict(path=str(viewer), sha256=digest(viewer))
        report['source_sha256'] = source_hashes()
        nvidia = shutil.which('nvidia-smi')
        if nvidia:
            report['nvidia_inventory'] = command([nvidia, '--query-gpu=name,driver_version,memory.total',
                                                  '--format=csv,noheader'], output / 'nvidia.log', report).strip()
        inputs = output / 'inputs'
        inputs.mkdir()
        cases = []
        if args.heightmap:
            # Preserve original input bytes beside the report for reproduction.
            source = inputs / 'imported.png'
            source.write_bytes(args.heightmap.read_bytes())
            cases.append(('imported', source))
        else:
            for name, rows, cols, bits in (('gray16-65', 65, 65, 16), ('gray16-257', 257, 257, 16),
                                           ('gray8-rect', 33, 49, 8)):
                source = inputs / (name + '.png')
                save_heightmap(source, fixture_samples(rows, cols, bits), bits)
                cases.append((name, source))
        terrains = {}
        material = baseline.create_baseline_scene().root_entities[0].model.material
        for name, source in cases:
            raw = read_heightmap(source)
            started = time.perf_counter()
            terrain = load_heightmap(source, origin=tuple(args.origin), size=tuple(args.size),
                                     base_z=args.base_z, height_range=args.height_range, flip_y=args.flip_y)
            generation = time.perf_counter() - started
            surface = check_surface(terrain, material, args.chunk_cells)
            terrains[name] = terrain
            report['cases'][name] = dict(input=source.relative_to(output).as_posix(),
                input_sha256=raw['input_sha256'], bit_depth=raw['bit_depth'], shape=list(raw['shape']),
                raw_sample_min=int(raw['samples'].min()), raw_sample_max=int(raw['samples'].max()),
                raw_sample_unique=int(np.unique(raw['samples']).size),
                decoded_height_sha256=hashlib.sha256(terrain.heights.tobytes()).hexdigest(),
                import_seconds=generation, height_bytes=terrain.heights.nbytes,
                surface=surface, views={})
            print('CPU PASS {}: {} queries, {} triangles, {} chunks'.format(
                name, surface['query_count'], surface['triangles'], surface['chunks']), flush=True)
        from tools.capture_sunset import desktop_context
        from mini3d.gl_renderer import GLRenderer
        from OpenGL import GL
        for repeat in (1, 2):
            with desktop_context():
                report['export_gl'] = {key: GL.glGetString(value).decode() for key, value in
                    (('vendor', GL.GL_VENDOR), ('renderer', GL.GL_RENDERER), ('version', GL.GL_VERSION))}
                renderer = GLRenderer(baseline.WIDTH, baseline.HEIGHT)
                try:
                    for name, terrain in terrains.items():
                        for view in baseline.VIEW_NAMES:
                            folder = output / ('export-' + str(repeat)) / name / view
                            export_terrain(terrain, folder, view, renderer, args.chunk_cells, args.base_z, args.height_range)
                            report['cases'][name]['views'].setdefault(view, {})['bundle_' + str(repeat)] = bundle_hashes(folder)
                finally:
                    renderer.close()
        for name, case in report['cases'].items():
            assert len({row['bundle_1']['scene.bin'] for row in case['views'].values()}) == 1
            for view, row in case['views'].items():
                assert row['bundle_1'] == row['bundle_2'], (name, view, 'Bundle changed')
                images = []
                for repeat in (1, 2):
                    bundle = output / ('export-' + str(repeat)) / name / view
                    native = output / ('native-' + str(repeat)) / name / view
                    tag = '{}-{}-{}'.format(name, view, repeat)
                    validation = json.loads(command([viewer, '--bundle', bundle, '--route', 'orbit', '--validate-only'],
                                                     output / ('validate-' + tag + '.log'), report))
                    metadata = json.loads((bundle / 'metadata.json').read_text(encoding='utf-8'))
                    assert all(validation[k] == metadata['counts'][k] for k in
                               ('entities', 'meshes', 'materials', 'textures', 'opaque_order'))
                    assert validation['entities'] == case['surface']['chunks'] + 3
                    assert validation['meshes'] == case['surface']['chunks'] + 3
                    command([viewer, '--bundle', bundle, '--output', native, '--route', 'orbit',
                             '--warmup', '24', '--frames', '120', '--samples', '1', '--hidden', '--capture'],
                            output / ('native-' + tag + '.log'), report, timeout=180)
                    rgb, capture = inspect_capture(native, validation['shadow_resolution'])
                    images.append(rgb)
                    benchmark = json.loads((native / 'benchmark-orbit.json').read_text(encoding='utf-8'))
                    assert benchmark['frames'] == 120 and benchmark['warmup'] == 24
                    assert benchmark['msaa_samples'] == 1 and not benchmark['recording'] and not benchmark['vsync']
                    row['run_' + str(repeat)] = dict(validation=validation, benchmark=benchmark, capture=capture,
                        metadata=metadata, preview=(native / 'preview.png').relative_to(output).as_posix(),
                        bundle_bytes=sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file()))
                delta = np.abs(images[0].astype('int16') - images[1].astype('int16'))
                row['repeat_image_difference'] = dict(max_channel_delta=int(delta.max()),
                    changed_pixels=int(np.count_nonzero(np.any(delta, axis=2))))
                assert delta.max() <= 1
                assert row['run_1']['capture']['depth_sha256'] == row['run_2']['capture']['depth_sha256']
        report['passed'] = True
    except Exception as error:
        report['error'] = '{}: {}'.format(type(error).__name__, error)
        raise
    finally:
        report.pop('_output')
        write_json(output / 'report.json', report)
    print('PASS: ' + str(output / 'report.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'captures/world-surroundings/build-lab00')
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--heightmap', type=Path, help='Otherwise run the three original test fixtures')
    parser.add_argument('--size', type=float, nargs=2, default=(36., 26.))
    parser.add_argument('--origin', type=float, nargs=2, default=(-18., -13.))
    parser.add_argument('--base-z', type=float, default=0.)
    parser.add_argument('--height-range', type=float, default=6.)
    parser.add_argument('--flip-y', action='store_true')
    parser.add_argument('--chunk-cells', type=int, default=32)
    run(parser.parse_args())
