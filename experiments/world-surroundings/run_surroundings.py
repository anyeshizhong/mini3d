"""SUR-00: one Roman fixture, minimal baked background and world-space terrain.

Uses the existing SPQR core via the isolated terrain_lab DLL. Captures,
recordings, lens diagnostics and performance samples are separate workloads.
No production Scene/UI/ABI or old terrain fixture is changed.
"""
import argparse
import copy
import io
import json
from pathlib import Path
import shutil
import struct
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from run_baseline import command, digest, source_hashes, write_json, bundle_hashes
from sculpt_native import NativeTerrain
from surroundings_scene import build_scene, terrain_height, DEFAULT_CONFIG
from surroundings_routes import (fixed_views, route_frames, write_route_frames,
                                  camera_record, in_envelope, CAMERA_BOUNDS)

WIDTH, HEIGHT = 1081, 662
ROUTES = ('outbound', 'lateral', 'ascent', 'orbit', 'boundary', 'boundary_low')
CONDITIONS = {'day-clear': ('day', 0.), 'day-haze': ('day', .0001),
              'day-haze-strong': ('day', .0003), 'sunset-haze': ('sunset', .0001)}
FACE_AXES = ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
BACKDROP_RADIUS = 3000.


def validate_backdrop_far(variants, far):
    # A finite cube has corners farther than its face centres. Six kilometres
    # conservatively covers all faces from this fixture's camera envelope.
    if 'B' in variants and far < 6000.:
        raise ValueError('B uses a 3km background cube and requires far>=6000m; '
                         'use --variants A C for shorter projection diagnostics')


def summary(values):
    a = np.asarray(values, dtype=np.float64)
    if a.size == 0 or not np.isfinite(a).all():
        raise ValueError('Expected nonempty finite measurement samples')
    return dict(n=int(a.size), **{name:float(np.percentile(a, p)) for name,p in
                (('p50',50),('p95',95),('p99',99))}, maximum=float(a.max()))


def texture_inventory(path):
    """Read only the v1 texture prefix; account all faces and exported mips."""
    sizes = {32856:4, 34842:8, 34836:16, 34843:6, 34837:12, 33327:4,
             33328:8, 33325:2, 33326:4, 32849:3, 33323:2, 33321:1}
    rows = []
    with Path(path).open('rb') as stream:
        def u32():
            raw = stream.read(4)
            if len(raw) != 4:
                raise ValueError('Truncated texture prefix')
            return struct.unpack('<I', raw)[0]
        if stream.read(8) != b'SPQRN001' or u32() != 1:
            raise ValueError('SUR expects an offline v1 bundle')
        count = u32()
        for index in range(count):
            target, internal = u32(), u32()
            parameters = [u32() for _ in range(5)]
            levels = u32(); records = []
            if target not in (3553,34067) or not 1 <= levels <= 32:
                raise ValueError('Invalid texture header')
            faces = 1 if target == 3553 else 6
            for _ in range(levels):
                w,h = u32(),u32()
                if not 0 < w <= 32768 or not 0 < h <= 32768:
                    raise ValueError('Invalid texture size')
                payload = w*h*faces*16
                if stream.tell()+payload > Path(path).stat().st_size:
                    raise ValueError('Truncated texture payload')
                stream.seek(payload, 1)
                records.append(dict(width=w,height=h,faces=faces,source_bytes=payload))
            texels = sum(r['width']*r['height']*faces for r in records)
            rows.append(dict(index=index,target=target,internal_format=internal,
                             parameters=parameters,levels=records,
                             allocated_bytes_estimate=texels*sizes[internal] if internal in sizes else None))
    return dict(textures=rows, initial_float32_source_bytes=sum(
                r['source_bytes'] for t in rows for r in t['levels']),
                known_storage_bytes=sum(t['allocated_bytes_estimate'] or 0 for t in rows),
                unknown_internal_formats=sorted({t['internal_format'] for t in rows
                                                if t['allocated_bytes_estimate'] is None}),
                excludes='framebuffers, shadows, drivers, CPU exporter cache; not peak VRAM')


def frame_bank(samples, near, far):
    views = fixed_views(terrain_height, near=near, far=far)
    from mini3d.camera import Camera
    anchor = np.array((0.,0.,float(terrain_height(0.,0.))+15.))
    match = Camera(position=anchor, fov_y=52., near=near, far=far)
    match.look_at(anchor + (0.,1000.,0.)); views['bake_anchor'] = match
    # Look out of the footprint as well as back toward the city; add actual
    # wide/narrow projections rather than assuming a single FOV is sufficient.
    for name in ('aerial_35','aerial_75'):
        camera=copy.deepcopy(views['aerial']); camera.fov_y=float(name.rsplit('_',1)[1])
        views[name]=camera
    for name,xy in (('west',(-200.,0.)),('east',(200.,0.)),
                    ('south',(0.,-200.)),('north',(0.,200.))):
        position=np.asarray((*xy,float(terrain_height(*xy))+120.))
        camera=Camera(position=position,fov_y=52.,near=near,far=far)
        direction=np.asarray((*xy,0.)); direction/=np.linalg.norm(direction)
        camera.look_at(position+direction*1000.)
        views['outward_'+name]=camera
    cameras = list(views.values())
    indices = {name:i for i,name in enumerate(views)}
    routes = {}
    for name in ROUTES:
        path = route_frames(name,terrain_height,samples=samples,near=near,far=far)
        start = len(cameras); cameras.extend(path)
        routes[name] = list(range(start,len(cameras)))
    assert all(in_envelope(camera,terrain_height) for camera in cameras)
    return cameras, indices, routes


def export_scene(scene, folder, exporter, cameras, *, aspect=WIDTH/HEIGHT):
    from mini3d.native_photo_bundle import export_live_bundle
    bundle = export_live_bundle(scene,cameras[0],exporter,folder,ROOT/'spqr-native',shared_textures=False)
    write_route_frames(folder/'frames.bin',cameras,aspect=aspect)
    return bundle


def raw_png(native, path):
    """Lossless format conversion; retain the exact RGB values, no enhancement."""
    from PIL import Image
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    ppm = path.with_suffix('.ppm')
    native.capture_color(ppm)
    with Image.open(ppm) as source:
        pixels = np.asarray(source).copy()
        source.save(path)
    with Image.open(path) as check:
        assert np.array_equal(pixels,np.asarray(check))
    ppm.unlink()  # Only the just-created capture; the lossless PNG is retained.
    return pixels


def settle(native,index,count=16):
    for _ in range(count):
        native.render(index)


def backdrop_shader(source):
    marker = 'void main() {'
    if source.count(marker) != 1:
        raise ValueError('Material main() contract changed')
    return source.replace(marker, marker + '''
    // SUR-00 B only: AO slot carries display RGB + silhouette alpha from
    // the same C geography rendered by SPQR at one frozen anchor/light/haze.
    // Do not tone-map, light or haze this already rendered image a second time.
    if (hasAO) {
        vec4 baked=texture(aoMap,uv);
        // A cutout silhouette avoids writing transparent sky texels and the
        // depth/sorting ambiguity of a whole cubemap-sized blended rectangle.
        if (baked.a<.5) discard;
        fragColor=vec4(baked.rgb,1.);
        return;
    }
''',1)


def cube_cameras(anchor,near,far):
    from mini3d.camera import Camera
    cameras = []
    for axis in FACE_AXES:
        camera = Camera(position=anchor, fov_y=90., near=near, far=far)
        camera.look_at(np.asarray(anchor)+np.asarray(axis),up=(0.,0.,1.))
        cameras.append(camera)
    return cameras


def bake_background(scene,metadata,folder,exporter,library,*,size,near,far):
    """Six true SPQR RGB/mask captures; no external backdrop image source."""
    from PIL import Image
    anchor = (0.,0.,float(terrain_height(0.,0.))+15.)
    cameras = cube_cameras(anchor,near,far)
    far_scene = copy.copy(scene)
    far_scene.root_entities = [e for e in scene.root_entities if e.name in metadata['far_entities']]
    if not far_scene.root_entities:
        raise ValueError('C needs explicit far_entities for B bake')
    far_scene._snapshot_bank = {}
    far_scene.update()
    bundle = folder/'rgb-bundle'
    export_scene(far_scene,bundle,exporter,cameras,aspect=1.)
    masks = folder/'mask-bundle'; masks.mkdir(parents=True)
    shutil.copyfile(bundle/'scene.bin',masks/'scene.bin')
    shutil.copyfile(bundle/'frames.bin',masks/'frames.bin')
    shutil.copytree(bundle/'shaders',masks/'shaders')
    mask_material=(masks/'shaders/material.frag').read_text(encoding='utf-8')
    if mask_material.count('void main() {') != 1:
        raise ValueError('Mask source main contract changed')
    # Preserve SPQR's native shadow replacement markers in the copied shader.
    (masks/'shaders/material.frag').write_text(mask_material.replace(
        'void main() {','void main() {\n    fragColor=vec4(1.); return;\n',1),encoding='utf-8')
    (masks/'shaders/sky.frag').write_text(
        '#version 330 core\nout vec4 fragColor; void main(){fragColor=vec4(0.,0.,0.,1.);}\n',encoding='utf-8')
    arrays = []
    native = NativeTerrain(library,bundle,size,size)
    try:
        for i in range(6):
            settle(native,i)
            arrays.append(raw_png(native,folder/('face-%d-rgb.png'%i)))
    finally:
        native.close()
    native = NativeTerrain(library,masks,size,size)
    records = []
    try:
        for i in range(6):
            settle(native,i)
            mask = raw_png(native,folder/('face-%d-mask.png'%i))[:,:,0]
            rgba = np.dstack((arrays[i],mask))
            path = folder/('face-%d.png'%i); Image.fromarray(rgba).save(path)
            records.append(dict(path=str(path.resolve()),sha256=digest(path),
                                opaque_pixels=int(np.count_nonzero(mask))))
    finally:
        native.close()
    return dict(anchor=list(anchor),size=size,cameras=[camera_record(c,aspect=1.) for c in cameras],
                faces=records,source_entities=metadata['far_entities'],
                method='six SPQR renders plus separate silhouette mask; display RGB, baked haze once')


def add_backdrop(scene,bake,*,radius=BACKDROP_RADIUS):
    from mini3d.scene import Entity,Mesh
    anchor = np.asarray(bake['anchor'])
    for i,(camera,face) in enumerate(zip(cube_cameras(anchor,.1,8000.),bake['faces'])):
        centre = anchor + camera.forward*radius
        points = [centre+camera.right*(u*radius)+camera.up*(v*radius)
                  for u,v in ((-1,-1),(1,-1),(1,1),(-1,1))]
        material = dict(pbrMetallicRoughness=dict(baseColorFactor=[1.,1.,1.,1.],
                          metallicFactor=0.,roughnessFactor=1.),alphaMode='BLEND',doubleSided=True,
                          textures=dict(occlusion=dict(image=Path(face['path']).read_bytes(),
                            sampler=dict(wrapS=33071,wrapT=33071))))
        mesh = Mesh(points,[0,1,2,0,2,3],normals=[-camera.forward]*4,
                    texcoords=[(0,1),(1,1),(1,0),(0,0)],material=material)
        scene.add(Entity(mesh,'SUR B Baked Face %d'%i))
    scene.update()


def capture_views(native,folder,indices,cameras):
    rows = {}
    for name,index in indices.items():
        settle(native,index)
        stem = folder/name
        full = name in ('street','aerial','telephoto','nadir')
        if full:
            native.capture(stem,index)
            # Keep matrices and far-shadow depth for representative views.
            from PIL import Image
            with Image.open(stem.with_suffix('.ppm')) as source:
                pixels=np.asarray(source).copy(); source.save(stem.with_suffix('.png'))
            with Image.open(stem.with_suffix('.png')) as check:
                assert np.array_equal(pixels,np.asarray(check))
            row=json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))
            for suffix in ('.ppm','.rgba'):
                stem.with_suffix(suffix).unlink()  # Redundant, just-created RGB/RGBA copies.
        else:
            raw_png(native,stem.with_suffix('.png')); row={}
        row.update(camera=camera_record(cameras[index]),frame_stats=native.frame_stats(),
                   full_native_capture=full,png=name+'.png',png_sha256=digest(stem.with_suffix('.png')))
        rows[name] = row
    return rows


def measure(native,frames,warmup):
    import pygame as pg
    for i in range(warmup):
        native.render(frames[i%len(frames)]); pg.display.flip()
    before = native.stats(); rows = []
    for index in frames:
        start = time.perf_counter()
        for event in pg.event.get():
            if event.type == pg.QUIT:
                raise RuntimeError('Experiment window closed')
        submitted = time.perf_counter()
        native.render(index)
        rendered = time.perf_counter()
        pg.display.flip(); end = time.perf_counter()
        stats = native.frame_stats()  # CPU snapshot after timed interval, no GL readback.
        rows.append(dict(frame=index,frame_ms=(end-start)*1000.,
                         events_ms=(submitted-start)*1000.,render_finish_ms=(rendered-submitted)*1000.,
                         swap_ms=(end-rendered)*1000.,**stats))
    after = native.stats()
    for key in ('shader_compiles','updates','texture_updates','uploaded_bytes','texture_uploaded_bytes'):
        assert before[key] == after[key], 'Static navigation mutated resources: '+key
    return dict(frames=rows,timing_ms={name:summary([r[name] for r in rows]) for name in
                 ('frame_ms','render_finish_ms','swap_ms')},before=before,after=after)


def record_route(native,frames,folder):
    import pygame as pg
    from PIL import Image
    images = []
    for ordinal,index in enumerate(frames):
        native.render(index); pg.display.flip()
        if ordinal%6 == 0:
            pixels = raw_png(native,folder/('%04d.png'%ordinal))
            images.append(Image.fromarray(pixels).resize((648,397),Image.Resampling.LANCZOS))
    images[0].save(folder.with_suffix('.gif'),save_all=True,append_images=images[1:],
                   duration=200,loop=0)
    return dict(frames=len(images),separate_from_timing=True,simulated_ms_per_saved_frame=200,
                wall_clock_fps=False)


def run(args):
    validate_backdrop_far(args.variants,args.far)
    import pygame as pg
    from OpenGL import GL
    from mini3d.gl_renderer import GLRenderer
    output,build = args.output.resolve(),args.build_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new empty output directory')
    if output == build or output in build.parents or build in output.parents:
        raise ValueError('Keep output and build separate')
    output.mkdir(parents=True,exist_ok=True)
    report = dict(stage='SUR-00',passed=False,commands=[],_output=output,conditions={},
        scope='Isolated SPQR comparison; no production UI/Scene/API or manual free-flight',
        world_build_acceptance='SUR-01..03 pending',performance_acceptance='diagnostic only; SUR-PERF pending',
        gpu_timestamp_ms=None,gpu_timestamp_note='Q hasAO timing does not measure all surroundings; not reused',
        configuration=DEFAULT_CONFIG,camera_envelope=CAMERA_BOUNDS)
    native = exporter = None
    try:
        report['git_head'] = command(['git','rev-parse','HEAD'],output/'git-head.log',report).strip()
        report['git_status_before'] = command(['git','status','--short'],output/'git-status.log',report)
        cmake,compiler,ninja = [shutil.which(tool) for tool in ('cmake','g++','ninja')]
        if not all((cmake,compiler,ninja)):
            raise RuntimeError('CMake, MinGW g++ and Ninja required')
        command([cmake,'-S',HERE,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_CXX_COMPILER='+compiler,'-DCMAKE_MAKE_PROGRAM='+ninja],output/'configure.log',report)
        command([cmake,'--build',build,'--target','terrain_lab','--parallel','2'],output/'build.log',report)
        library = build/'bin/terrain_lab.dll'
        report['library_sha256'] = digest(library)
        report['source_sha256'] = source_hashes()
        pg.display.init()
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK,pg.GL_CONTEXT_PROFILE_CORE)
        flags = pg.OPENGL|pg.DOUBLEBUF|(0 if args.visible else pg.HIDDEN)
        pg.display.set_mode((WIDTH,HEIGHT),flags,vsync=0)
        report['environment'] = {name:GL.glGetString(value).decode() for name,value in
            (('vendor',GL.GL_VENDOR),('renderer',GL.GL_RENDERER),('version',GL.GL_VERSION))}
        report['environment'].update(width=WIDTH,height=HEIGHT,msaa=1,shadow_far=1024,shadow_near=4096)
        exporter = GLRenderer(WIDTH,HEIGHT)
        cameras,indices,routes = frame_bank(args.samples,args.near,args.far)
        report['camera_frames'] = [camera_record(c) for c in cameras]
        report['view_indices'],report['route_indices'] = indices,routes
        report['protocol'] = dict(samples=args.samples,warmup=args.warmup,repeats=args.repeats,
                                  timings_condition=args.measure_condition,
                                  rotating_variant_order=True,capture_not_in_timing=True)
        for condition in args.conditions:
            sun,haze = CONDITIONS[condition]
            folder = output/condition; folder.mkdir()
            print('SUR-00 '+condition,flush=True)
            scene_c,metadata = build_scene('C',haze=haze,sun=sun)
            row = dict(sun=sun,haze=haze,geography=metadata,variants={})
            report['conditions'][condition] = row
            bake = None
            if 'B' in args.variants:
                started = time.perf_counter()
                bake = bake_background(scene_c,metadata,folder/'bake',exporter,library,
                                       size=args.bake_size,near=args.near,far=args.far)
                bake['preparation_seconds'] = time.perf_counter()-started
                row['bake'] = bake; write_json(folder/'bake.json',bake)
            # Export all variants before measuring; sources are identical common inputs.
            for variant in args.variants:
                vf = folder/variant; vf.mkdir()
                scene,meta = (scene_c,metadata) if variant=='C' else build_scene('A',haze=haze,sun=sun)
                assert not any((e.model and e.model.material and
                    e.model.material.get('textures',{}).get('occlusion')) for e in scene.root_entities)
                if variant=='B':
                    add_backdrop(scene,bake)
                started = time.perf_counter()
                bundle = export_scene(scene,vf/'bundle',exporter,cameras)
                if variant=='B':
                    path = vf/'bundle/shaders/material.frag'
                    path.write_text(backdrop_shader(path.read_text(encoding='utf-8')),encoding='utf-8')
                row['variants'][variant] = dict(export_seconds=time.perf_counter()-started,
                    counts=bundle['counts'],metadata=meta,bundle_sha256=bundle_hashes(vf/'bundle'),
                    texture_inventory=texture_inventory(vf/'bundle/scene.bin'),measurements={})
                write_json(vf/'metadata.json',meta)
                native = NativeTerrain(library,vf/'bundle')
                before=native.stats()
                captured=capture_views(native,vf/'views',indices,cameras)
                row['variants'][variant]['views'] = captured
                row['variants'][variant]['initial_stats'] = before
                assert all(np.isfinite(v['frame_stats']['near_shadow_depth_span']) for v in captured.values())
                native.close(); native=None
            if condition==args.measure_condition:
                for repeat in range(args.repeats):
                    order = args.variants[repeat%len(args.variants):]+args.variants[:repeat%len(args.variants)]
                    for variant in order:
                        print('MEASURE %s %s round %d'%(condition,variant,repeat+1),flush=True)
                        vf=folder/variant; record=row['variants'][variant]
                        native=NativeTerrain(library,vf/'bundle')
                        for name,frames in [('static',[indices['street']]*args.samples)]+list(routes.items()):
                            block=measure(native,frames,args.warmup)
                            record['measurements'].setdefault(name,[]).append(block)
                        native.close(); native=None
                        write_json(vf/'result.json',record)
                if not args.skip_recordings:
                    for variant in args.variants:
                        vf=folder/variant; native=NativeTerrain(library,vf/'bundle')
                        record=row['variants'][variant]
                        record['recordings']={name:record_route(native,frames,vf/'motion'/name)
                                               for name,frames in routes.items()}
                        native.close(); native=None
            for variant,record in row['variants'].items():
                for name,blocks in record['measurements'].items():
                    frames=[frame for block in blocks for frame in block['frames']]
                    record.setdefault('pooled_timing_ms',{})[name]={key:summary([f[key] for f in frames])
                        for key in ('frame_ms','render_finish_ms','swap_ms')}
                write_json(folder/variant/'result.json',record)
        if not args.skip_sweep:
            report['lens_sweep'] = []
            scene,_ = build_scene('C',haze=0.,sun='day')
            for near in (.05,.1,.2):
                for far in (2000.,4000.,8000.):
                    vf=output/'lens-sweep'/('n%g-f%g'%(near,far)); vf.mkdir(parents=True)
                    poses=fixed_views(terrain_height,near=near,far=far)
                    poses={name:poses[name] for name in ('street','aerial','telephoto')}
                    export_scene(scene,vf/'bundle',exporter,list(poses.values()))
                    native=NativeTerrain(library,vf/'bundle')
                    captures=capture_views(native,vf/'views',{name:i for i,name in enumerate(poses)},list(poses.values()))
                    report['lens_sweep'].append(dict(near=near,far=far,views=captures))
                    native.close(); native=None
        report['passed'] = True
    except Exception as error:
        report['error'] = '%s: %s'%(type(error).__name__,error)
        raise
    finally:
        cleanup=[]
        for operation in (native.close if native else None,exporter.close if exporter else None,pg.display.quit):
            if operation:
                try: operation()
                except Exception as error: cleanup.append(str(error))
        if cleanup: report['passed']=False; report['cleanup_errors']=cleanup
        report.pop('_output'); write_json(output/'report.json',report)
    if not report['passed']:
        raise RuntimeError('SUR-00 cleanup failed; see '+str(output/'report.json'))
    print('PASS '+str(output/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--build-dir',type=Path,default=ROOT/'captures/world-surroundings/build-sur00')
    parser.add_argument('--variants',nargs='+',choices=('A','B','C'),default=['A','B','C'])
    parser.add_argument('--conditions',nargs='+',choices=tuple(CONDITIONS),default=['day-clear','day-haze','sunset-haze'])
    parser.add_argument('--measure-condition',choices=tuple(CONDITIONS),default='day-haze')
    parser.add_argument('--samples',type=int,default=120)
    parser.add_argument('--warmup',type=int,default=24)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--near',type=float,default=.1)
    parser.add_argument('--far',type=float,default=8000.)
    parser.add_argument('--bake-size',type=int,default=512)
    parser.add_argument('--skip-sweep',action='store_true')
    parser.add_argument('--skip-recordings',action='store_true')
    parser.add_argument('--visible',action='store_true')
    args=parser.parse_args()
    if args.samples<24 or args.warmup<1 or args.repeats<1 or not 64<=args.bake_size<=2048:
        parser.error('samples>=24, warmup/repeats>=1 and bake-size 64..2048 required')
    if len(set(args.variants))!=len(args.variants) or len(set(args.conditions))!=len(args.conditions):
        parser.error('Do not duplicate variants/conditions')
    if args.measure_condition not in args.conditions:
        parser.error('measure-condition must be included in conditions')
    if not np.isfinite(args.near) or not np.isfinite(args.far) or not 0<args.near<args.far:
        parser.error('Expected finite 0<near<far')
    run(args)
