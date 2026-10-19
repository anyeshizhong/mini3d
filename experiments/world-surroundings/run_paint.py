"""LAB-02B: persistent SPQR material painting, bake/layer comparison and replay."""
import argparse
from pathlib import Path
import hashlib
import io
import json
import math
import shutil
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(HERE))
from run_baseline import command,digest,source_hashes,write_json
from run_heightmap import fixture_samples,terrain_scene
from run_sculpt import SculptWindow,png_from_ppm,summarize
from sculpt import SculptSession
from sculpt_native import NativeTerrain
from heightfield import Heightfield
from paint import PaintSession,HistoryBudgetExceeded
from material_maps import MaterialMaps,weight_rgba,shader_source
import baseline_scene as baseline
from native.export_scene import BinaryWriter

SLOTS={'baseColor':0,'metallicRoughness':1,'normal':2,'occlusion':3}
VIEW_FRAMES={'close':24,'oblique':168,'distant':312}


def weights_hash(weights):
    return hashlib.sha256(weights.tobytes()).hexdigest()


def camera_for(view):
    if view!='close':
        return baseline.camera_for_view(view)
    camera=baseline.camera_for_view('oblique')
    camera.position=(1.,-14.,10.)
    camera.look_at((0.,0.,1.5))
    return camera


def encode_texture(array):
    from PIL import Image
    stream=io.BytesIO()
    Image.fromarray(array,'RGBA').save(stream,format='PNG')
    return dict(image=stream.getvalue(),sampler=dict(minFilter=9729,magFilter=9729,
                                                  wrapS=33071,wrapT=33071))


def texture_maps(maps,weights,scheme):
    if scheme=='layered':
        result=maps.atlas_maps()
        result['occlusion']=weight_rgba(weights)
        return result
    result=maps.bake(weights)
    result['occlusion']=np.full((1,1,4),255,dtype='uint8')
    return result


def export_state(terrain,weights,maps,scheme,folder,exporter):
    from mini3d.native_photo_bundle import export_live_bundle,_export_helpers,_ensure_renderers
    scene=terrain_scene(terrain,32)
    terrain_entities=[scene.root_entities[0]]+scene.root_entities[4:]
    arrays=texture_maps(maps,weights,scheme)
    material=dict(pbrMetallicRoughness=dict(baseColorFactor=[1.,1.,1.,1.],metallicFactor=0.,roughnessFactor=1.),
                  textures={key:encode_texture(value) for key,value in arrays.items()},alphaMode='OPAQUE')
    for entity in terrain_entities:
        entity.model.material=material
    material_renderer,_=_ensure_renderers(exporter)
    handles={material_renderer._texture(texture) for texture in material['textures'].values()}
    helpers=_export_helpers()
    capture=helpers.capture_texture
    def capture_single_level(handle,target,gl):
        record=capture(handle,target,gl)
        if handle in handles:
            # MAX_LEVEL does not deallocate generated mips. Explicitly export
            # only level zero for this experiment's independently owned maps.
            record['levels']=record['levels'][:1]
            record['parameters']['min_filter']=int(gl.GL_LINEAR)
        return record
    helpers.capture_texture=capture_single_level
    try:
        bundle=export_live_bundle(scene,camera_for('oblique'),exporter,folder,ROOT/'spqr-native',shared_textures=False)
    finally:
        helpers.capture_texture=capture
    path=folder/'shaders/material.frag'
    path.write_text(shader_source(path.read_text(encoding='utf-8'),scheme),encoding='utf-8')
    writer=BinaryWriter(); writer.raw(b'SPQRF001'); writer.u32(144*3)
    for view in VIEW_FRAMES:
        writer.raw(baseline._frame_bytes(camera_for(view),1081,662)[12:])
    (folder/'frames.bin').write_bytes(writer.data)
    return [next(i for i,obj in enumerate(bundle['entity_bindings']) if obj is entity) for entity in terrain_entities]


class PaintWindow(SculptWindow):
    def __init__(self,terrain,session,native,entities,maps,scheme):
        super().__init__(SculptSession(terrain),native,entities)
        self.paint,self.maps,self.scheme=session,maps,scheme
        self.last_error=None
        self.layer,self.erase,self.radius,self.strength=1,False,3.8,5.
        self.last_weights=session.weights
        self.paint_revision=session.revision
        self.arrays=texture_maps(maps,session.weights,scheme)
        self.texture_ids={key:native.texture_id(entities[0],slot) for key,slot in SLOTS.items()}
        for key,value in self.arrays.items():
            assert native.texture_info(self.texture_ids[key])==(value.shape[1],value.shape[0])
            assert np.array_equal(native.read_texture(self.texture_ids[key]),value),key

    def events(self,events):
        import pygame as pg
        for event in events:
            if event.type==pg.QUIT:
                if self.paint.active:
                    self.paint.cancel_stroke()
                return False
            if event.type==pg.KEYDOWN:
                modes={pg.K_1:0,pg.K_2:1,pg.K_3:2}
                if event.key in modes or event.key==pg.K_e:
                    if self.paint.active:
                        self.paint.cancel_stroke()
                    self.drawing,self.last_point=False,None
                    if event.key in modes:
                        self.layer=modes[event.key]
                    else:
                        self.erase=not self.erase
                elif event.key==pg.K_ESCAPE:
                    if self.paint.active:
                        self.paint.cancel_stroke()
                    self.drawing,self.last_point=False,None
                elif event.key in (pg.K_z,pg.K_y) and not self.paint.active:
                    (self.paint.undo if event.key==pg.K_z else self.paint.redo)()
            elif event.type==pg.MOUSEWHEEL:
                self.radius=min(12.,max(.25,self.radius*1.15**event.y))
            elif event.type==pg.MOUSEMOTION:
                self.pointer=event.pos
            elif event.type==pg.MOUSEBUTTONDOWN and event.button==1:
                self.pointer=event.pos
                if not self.paint.active and self.pick(event.pos) is not None:
                    self.last_error=None
                    self.paint.begin_stroke(self.layer,self.radius,self.strength,erase=self.erase)
                    self.stroke_radius=self.radius
                    self.drawing,self.last_point=True,None
            elif event.type==pg.MOUSEBUTTONUP and event.button==1:
                if self.paint.active:
                    try:
                        self.paint.end_stroke()
                    except HistoryBudgetExceeded as error:
                        self.last_error=str(error)
                self.drawing,self.last_point=False,None
        return True

    def sync_paint(self):
        if self.paint_revision==self.paint.revision:
            return dict(rect=None,bytes=0)
        weights=self.paint.weights
        rows,cols=np.nonzero(np.any(weights!=self.last_weights,axis=2))
        uploads=[]
        rect=None
        if len(rows):
            r0,c0,r1,c1=int(rows.min()),int(cols.min()),int(rows.max()+1),int(cols.max()+1)
            rect=(r0,c0,r1,c1)
            arrays=({'occlusion':weight_rgba(weights[r0:r1,c0:c1])} if self.scheme=='layered'
                    else self.maps.bake(weights,rect=rect))
            for key,array in arrays.items():
                uploads.append((self.texture_ids[key],c0,r0,array))
                self.arrays[key][r0:r1,c0:c1]=array
            self.native.update_textures(uploads)
        self.last_weights,self.paint_revision=weights,self.paint.revision
        return dict(rect=rect,bytes=sum(row[3].nbytes for row in uploads))

    def tick(self,dt):
        if self.drawing and self.paint.active:
            point=self.pick(self.pointer)
            if point is not None:
                current=np.asarray(point[:2])
                start=current if self.last_point is None else self.last_point
                count=max(1,int(math.ceil(np.linalg.norm(current-start)/(self.stroke_radius*.2))))
                for step in range(1,count+1):
                    sample=start+(current-start)*step/count
                    self.paint.dab(float(sample[0]),float(sample[1]),amount=dt/count)
                self.last_point=current
            else:
                self.last_point=None
        return self.sync_paint()


def replay(control,output,checkpoint=None,recording=False):
    import pygame as pg
    timings,log,images=[],[],[]
    def key(number):
        return pg.event.Event(pg.KEYDOWN,key=number,mod=0)
    def frame(events):
        for event in events:
            pg.event.post(event)
        started=time.perf_counter()
        assert control.events(pg.event.get())
        update=control.tick(1/30.)
        uploaded=time.perf_counter()
        control.native.render()
        rendered=time.perf_counter()
        pg.display.flip()
        ended=time.perf_counter()
        index=len(timings)
        timings.append(dict(frame=index,frame_ms=(ended-started)*1000,
                            cpu_and_upload_ms=(uploaded-started)*1000,
                            render_finish_ms=(rendered-uploaded)*1000,
                            swap_ms=(ended-rendered)*1000,**update))
        log.append([dict(type=e.type,**e.dict) for e in events])
        if recording and index%5==0:
            path=output/'animation-frames'/('frame-%04d.ppm'%index)
            control.native.capture_color(path); images.append(path)
    for layer,erase,start,end,count,tag in (
            (1,False,(-10.,3.),(8.,3.),32,'rock'),
            (2,False,(-9.,-3.),(9.,-3.),32,'grass'),
            (0,False,(-3.,0.),(3.,0.),16,'soil'),
            (2,True,(1.,-3.),(5.,-3.),16,'erase')):
        for index in range(count):
            xy=np.asarray(start)+(np.asarray(end)-start)*index/max(1,count-1)
            screen=control.screen_point(*xy)
            events=[pg.event.Event(pg.MOUSEMOTION,pos=screen,rel=(0,0),buttons=(1,0,0))]
            if index==0:
                events=[key(pg.K_ESCAPE),key((pg.K_1,pg.K_2,pg.K_3)[layer])]
                if erase!=control.erase:
                    events.append(key(pg.K_e))
                events.append(pg.event.Event(pg.MOUSEBUTTONDOWN,button=1,pos=screen))
            frame(events)
        frame([pg.event.Event(pg.MOUSEBUTTONUP,button=1,pos=control.pointer)])
        if checkpoint:
            checkpoint(tag)
    edited=weights_hash(control.paint.weights)
    screen=control.screen_point(4.,-4.)
    frame([key(pg.K_e),key(pg.K_2),pg.event.Event(pg.MOUSEBUTTONDOWN,button=1,pos=screen)])
    for _ in range(10):
        frame([])
    assert weights_hash(control.paint.weights)!=edited
    frame([key(pg.K_ESCAPE)])
    assert weights_hash(control.paint.weights)==edited and control.paint.undo_count==4
    if checkpoint:
        checkpoint('cancel')
    frame([key(pg.K_z)])
    assert weights_hash(control.paint.weights)!=edited
    if checkpoint:
        checkpoint('undo')
    frame([key(pg.K_y)])
    assert weights_hash(control.paint.weights)==edited
    if checkpoint:
        checkpoint('redo')
    return dict(frames=timings,events=log,animation_frames=images,weight_sha256=edited,
                history_bytes=control.paint.history_bytes)


def checkpoint(control,terrain,exporter,library,output,tag):
    folder=output/'checkpoints'/tag; folder.mkdir(parents=True)
    control.native.capture(folder/'dynamic')
    png_from_ppm(folder/'dynamic.ppm',folder/'preview.png')
    for name,array in control.arrays.items():
        assert np.array_equal(control.native.read_texture(control.texture_ids[name]),array),name
    for mesh_id,payload in zip(control.mesh_ids,control.payloads):
        assert np.array_equal(control.native.read(mesh_id),payload),'Painting changed geometry'
    weights=control.paint.weights
    assert np.isfinite(weights).all() and weights.min()>=0
    assert np.max(np.abs(weights.sum(axis=2)-1.))<2e-6
    row=dict(weight_sha256=weights_hash(weights),gpu_textures_exact=True,geometry_unchanged=True)
    if tag not in ('cancel','redo'):
        bundle=folder/'fresh-bundle'
        export_state(terrain,weights,control.maps,control.scheme,bundle,exporter)
        fresh=NativeTerrain(library,bundle)
        try:
            fresh.capture(folder/'fresh')
        finally:
            fresh.close()
        for suffix in ('.rgba','.depth.f32'):
            assert (folder/('dynamic'+suffix)).read_bytes()==(folder/('fresh'+suffix)).read_bytes(),tag+suffix
        row['fresh_color_far_shadow_exact']=True
    else:
        for suffix in ('.rgba','.depth.f32'):
            assert (folder/('dynamic'+suffix)).read_bytes()==(output/'checkpoints/erase'/('dynamic'+suffix)).read_bytes()
    return row


def invalid_textures(control):
    native=control.native
    tid=control.texture_ids['occlusion' if control.scheme=='layered' else 'baseColor']
    original=native.read_texture(tid)
    pixel=np.asarray([[[0,255,0,255]]],dtype='uint8')
    before=native.stats()
    cases=[('later-id',[(tid,0,0,pixel),(999999,0,0,pixel)]),
           ('duplicate',[(tid,0,0,pixel),(tid,1,1,pixel)]),
           ('out-of-bounds',[(tid,original.shape[1],0,pixel)])]
    errors=[]
    for label,rows in cases:
        try:
            native.update_textures(rows)
        except RuntimeError as error:
            errors.append(dict(case=label,error=str(error)))
        else:
            raise AssertionError('Accepted '+label)
        assert np.array_equal(original,native.read_texture(tid))
        assert native.stats()['texture_updates']==before['texture_updates']
    return errors


def transfer_state_check(control):
    from OpenGL import GL as gl
    import ctypes as C
    import threading
    native=control.native
    tid=control.texture_ids['occlusion' if control.scheme=='layered' else 'baseColor']
    pixel=native.read_texture(tid)[:1,:1].copy()
    names=(gl.GL_PACK_ALIGNMENT,gl.GL_PACK_ROW_LENGTH,gl.GL_PACK_SKIP_ROWS,gl.GL_PACK_SKIP_PIXELS,
           gl.GL_UNPACK_ALIGNMENT,gl.GL_UNPACK_ROW_LENGTH,gl.GL_UNPACK_SKIP_ROWS,gl.GL_UNPACK_SKIP_PIXELS)
    old=[int(gl.glGetIntegerv(name)) for name in names]
    active=int(gl.glGetIntegerv(gl.GL_ACTIVE_TEXTURE))
    pack=int(gl.glGetIntegerv(gl.GL_PIXEL_PACK_BUFFER_BINDING))
    unpack=int(gl.glGetIntegerv(gl.GL_PIXEL_UNPACK_BUFFER_BINDING))
    gl.glActiveTexture(gl.GL_TEXTURE5)
    binding=int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D))
    buffers=gl.glGenBuffers(2)
    test_texture=int(gl.glGenTextures(1))
    try:
        gl.glBindTexture(gl.GL_TEXTURE_2D,test_texture)
        gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER,int(buffers[0]))
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER,int(buffers[1]))
        for name,value in zip(names,(8,13,2,3,8,17,3,2)):
            gl.glPixelStorei(name,value)
        query=names+(gl.GL_ACTIVE_TEXTURE,gl.GL_TEXTURE_BINDING_2D,
                     gl.GL_PIXEL_PACK_BUFFER_BINDING,gl.GL_PIXEL_UNPACK_BUFFER_BINDING)
        expected=[int(gl.glGetIntegerv(name)) for name in query]
        native.update_textures([(tid,0,0,pixel)])
        assert [int(gl.glGetIntegerv(name)) for name in query]==expected
        assert np.array_equal(native.read_texture(tid)[:1,:1],pixel)
        assert [int(gl.glGetIntegerv(name)) for name in query]==expected
    finally:
        gl.glBindTexture(gl.GL_TEXTURE_2D,binding)
        gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER,pack)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER,unpack)
        for name,value in zip(names,old):
            gl.glPixelStorei(name,value)
        gl.glDeleteTextures([test_texture]); gl.glDeleteBuffers(2,buffers)
        gl.glActiveTexture(active)
    result=[]
    def wrong_thread():
        result.append((native.update_textures([(tid,0,0,pixel)],check=False),native.error()))
    thread=threading.Thread(target=wrong_thread); thread.start(); thread.join()
    assert result[0][0]==0
    wgl=C.WinDLL('opengl32')
    wgl.wglGetCurrentContext.restype=wgl.wglGetCurrentDC.restype=C.c_void_p
    wgl.wglMakeCurrent.argtypes=[C.c_void_p,C.c_void_p]
    context,dc=wgl.wglGetCurrentContext(),wgl.wglGetCurrentDC()
    assert wgl.wglMakeCurrent(None,None)
    try:
        assert native.update_textures([(tid,0,0,pixel)],check=False)==0
        context_error=native.error()
    finally:
        assert wgl.wglMakeCurrent(dc,context)
    return dict(pixel_transfer_state_exact=True,wrong_thread=result[0][1],wrong_context=context_error)


def budget_event_check(terrain,native,entities,maps,scheme):
    import pygame as pg
    probe=PaintWindow(terrain,PaintSession(history_budget_bytes=0),native,entities,maps,scheme)
    position=probe.screen_point(0.,0.)
    probe.events([pg.event.Event(pg.MOUSEBUTTONDOWN,button=1,pos=position)])
    probe.tick(1/30.)
    assert probe.paint.active
    probe.events([pg.event.Event(pg.MOUSEBUTTONUP,button=1,pos=position)])
    probe.tick(0.)
    assert not probe.paint.active and probe.paint.undo_count==0 and probe.last_error
    assert np.array_equal(probe.paint.weights,PaintSession().weights)
    for name,array in probe.arrays.items():
        assert np.array_equal(native.read_texture(probe.texture_ids[name]),array)
    return dict(rejected_without_exiting=True,rollback_gpu_exact=True)


def capture_views(control,terrain,exporter,library,output):
    folder=output/'views'; folder.mkdir()
    bundle=folder/'fresh-bundle'
    export_state(terrain,control.paint.weights,control.maps,control.scheme,bundle,exporter)
    fresh=NativeTerrain(library,bundle)
    try:
        # Stable shadow fitting has camera history. Start the reference on the
        # same oblique pose before replaying the three camera changes.
        for _ in range(48):
            fresh.render(VIEW_FRAMES['oblique'])
        for view,index in VIEW_FRAMES.items():
            for _ in range(48):
                control.native.render(index); fresh.render(index)
            control.native.capture(folder/view,index)
            fresh.capture(folder/('fresh-'+view),index)
            png_from_ppm(folder/(view+'.ppm'),folder/(view+'.png'))
            for suffix in ('.rgba','.depth.f32'):
                assert (folder/(view+suffix)).read_bytes()==(folder/('fresh-'+view+suffix)).read_bytes(),view+suffix
    finally:
        fresh.close()


def interactive(control,limit):
    import pygame as pg
    clock=pg.time.Clock(); frames=0
    while control.events(pg.event.get()):
        control.tick(clock.tick(60)/1000.)
        control.native.render(); pg.display.flip()
        pg.display.set_caption('SPQR Paint {} | {} {} radius {:.2f} | 1/2/3 E LMB wheel Esc Z/Y'.format(
            control.scheme,('soil','rock','grass')[control.layer],'erase' if control.erase else 'paint',control.radius)
            + (' | '+control.last_error if control.last_error else ''))
        frames+=1
        if limit and frames>=limit:
            break
    return frames


def run(args):
    import pygame as pg
    from PIL import Image
    from mini3d.gl_renderer import GLRenderer
    output,build=args.output.resolve(),args.build_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a new empty output directory')
    if output==build or output in build.parents or build in output.parents:
        raise ValueError('Keep build and results separate')
    output.mkdir(parents=True,exist_ok=True)
    report=dict(passed=False,stage='LAB-02B',commands=[],_output=output,schemes={})
    native=exporter=None
    try:
        report['git_head']=command(['git','rev-parse','HEAD'],output/'git-head.log',report).strip()
        report['git_status_before']=command(['git','status','--short'],output/'git-status.log',report)
        cmake,compiler,ninja=[shutil.which(tool) for tool in ('cmake','g++','ninja')]
        if not all((cmake,compiler,ninja)):
            raise RuntimeError('CMake, MinGW g++ and Ninja required')
        command([cmake,'-S',HERE,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_CXX_COMPILER='+compiler,'-DCMAKE_MAKE_PROGRAM='+ninja],output/'configure.log',report)
        command([cmake,'--build',build,'--target','terrain_lab','--parallel','2'],output/'build.log',report)
        library=build/'bin/terrain_lab.dll'
        report['library_sha256']=digest(library)
        report['source_sha256']=source_hashes()
        for path in [HERE/'terrain_bridge.cpp',HERE/'CMakeLists.txt']+list((HERE/'assets/materials').rglob('*')):
            if path.is_file():
                report['source_sha256'][path.relative_to(ROOT).as_posix()]=digest(path)
        maps=MaterialMaps()
        terrain=Heightfield(fixture_samples(65,65,16).astype('float64')/65535.*6.)
        pg.display.init()
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MAJOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_MINOR_VERSION,3)
        pg.display.gl_set_attribute(pg.GL_CONTEXT_PROFILE_MASK,pg.GL_CONTEXT_PROFILE_CORE)
        pg.display.set_mode((1081,662),pg.OPENGL|pg.DOUBLEBUF|(0 if args.interactive else pg.HIDDEN))
        exporter=GLRenderer(1081,662)
        schemes=(['layered'] if args.scheme=='both' else [args.scheme]) if args.interactive else (
                 ['baked','layered'] if args.scheme=='both' else [args.scheme])
        report['mode']='interactive' if args.interactive else 'automated-replay'
        report['automated_checks']=not args.interactive
        final_hashes=[]
        for scheme in schemes:
            print('SCHEME '+scheme,flush=True)
            folder=output/scheme; folder.mkdir()
            session=PaintSession()
            entities=export_state(terrain,session.weights,maps,scheme,folder/'initial-bundle',exporter)
            native=NativeTerrain(library,folder/'initial-bundle')
            control=PaintWindow(terrain,session,native,entities,maps,scheme)
            native.render(); pg.display.flip()
            row=dict(initial_stats=native.stats())
            report['schemes'][scheme]=row
            if args.interactive:
                row['interactive_frames']=interactive(control,args.live_frames)
                row['final_stats']=native.stats()
                native.close(); native=None
                continue
            row['invalid_batches']=invalid_textures(control)
            row['transfer_state_check']=transfer_state_check(control)
            row['budget_event_check']=budget_event_check(terrain,native,entities,maps,scheme)
            row['measurement_start_stats']=native.stats()
            checkpoints={}
            def check(tag):
                print('CHECK '+scheme+' '+tag,flush=True)
                checkpoints[tag]=checkpoint(control,terrain,exporter,library,folder,tag)
            check('initial')
            measured=replay(control,folder,check)
            row['checkpoints']=checkpoints
            row['measured_frames']=measured['frames']
            row['timing_ms']={name:summarize([frame[name] for frame in measured['frames']]) for name in
                              ('frame_ms','cpu_and_upload_ms','render_finish_ms','swap_ms')}
            row['history_bytes']=measured['history_bytes']
            row['weight_sha256']=measured['weight_sha256']
            row['weight_bytes']=session.weights.nbytes
            row['texture_level0_bytes']=sum(a.nbytes for a in control.arrays.values())
            row['measured_stats']=native.stats()
            row['measured_texture_updates']=row['measured_stats']['texture_updates']-row['measurement_start_stats']['texture_updates']
            row['measured_uploaded_bytes']=row['measured_stats']['texture_uploaded_bytes']-row['measurement_start_stats']['texture_uploaded_bytes']
            assert row['measured_stats']['shader_compiles']==row['initial_stats']['shader_compiles']
            assert row['measured_stats']['updates']==0
            write_json(folder/'input-replay.json',measured['events'])
            np.save(folder/'weights.npy',session.weights,allow_pickle=False)
            final_hashes.append(measured['weight_sha256'])
            capture_views(control,terrain,exporter,library,folder)
            if scheme=='layered':
                restored=texture_maps(maps,PaintSession().weights,scheme)
                native.update_textures([(control.texture_ids['occlusion'],0,0,restored['occlusion'])])
                recorded_control=PaintWindow(terrain,PaintSession(),native,entities,maps,scheme)
                recorded=replay(recorded_control,folder,recording=True)
                assert recorded['weight_sha256']==measured['weight_sha256']
                images=[]
                for path in recorded['animation_frames']:
                    with Image.open(path) as image:
                        copy=image.copy(); copy.thumbnail((648,397)); images.append(copy)
                images[0].save(folder/'paint-replay.gif',save_all=True,append_images=images[1:],duration=167,loop=0)
                row['recording']=dict(separate_replay=True,frames=len(images),file='paint-replay.gif')
                for image in images:
                    image.close()
            row['final_stats']=native.stats()
            assert row['final_stats']['shader_compiles']==row['initial_stats']['shader_compiles']
            native.close(); native=None
        assert len(set(final_hashes))<=1,'Schemes replayed different weights'
        if not args.interactive and len(schemes)==2:
            assert (output/schemes[0]/'input-replay.json').read_bytes()==(output/schemes[1]/'input-replay.json').read_bytes()
            report['identical_input_events']=True
        report['passed']=True
    except Exception as error:
        report['error']='{}: {}'.format(type(error).__name__,error)
        raise
    finally:
        errors=[]
        for name,cleanup in (('native',native.close if native else None),
                             ('exporter',exporter.close if exporter else None),('display',pg.display.quit)):
            if cleanup:
                try:
                    cleanup()
                except Exception as error:
                    errors.append('{}: {}'.format(name,error))
        if errors:
            report['passed']=False; report['cleanup_errors']=errors
        report.pop('_output')
        write_json(output/'report.json',report)
        if errors:
            raise RuntimeError('; '.join(errors))
    print('PASS: '+str(output/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--build-dir',type=Path,default=ROOT/'captures/world-surroundings/build-lab02b')
    parser.add_argument('--scheme',choices=('both','baked','layered'),default='both')
    parser.add_argument('--interactive',action='store_true')
    parser.add_argument('--live-frames',type=int,default=0)
    run(parser.parse_args())
