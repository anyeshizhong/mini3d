"""Run with Blender 3.6.23: aligned Eevee, exact custom Reinhard compositor.

blender --background --factory-startup --python blender.py -- --output ... --assets-root ...
The HDR and procedural glTFs are in output/assets; imported texture pixels are packed.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import bpy
from mathutils import Matrix,Vector


def build(case,output,assets):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene
    scene.render.engine='BLENDER_EEVEE'
    scene.eevee.taa_render_samples=64
    scene.eevee.use_gtao=False
    scene.eevee.use_ssr=False
    scene.eevee.use_soft_shadows=False
    scene.eevee.shadow_cube_size='1024';scene.eevee.shadow_cascade_size='1024'
    scene.render.resolution_x=1920;scene.render.resolution_y=1080;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB'
    scene.render.image_settings.color_depth='8'
    scene.render.film_transparent=True
    scene.display_settings.display_device='sRGB'
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.render.dither_intensity=0
    record=dict(name=case['name'],blender=bpy.app.version_string,engine=scene.render.engine,
        build_hash=bpy.app.build_hash.decode(),
        taa_samples=64,world_strength=.35,sun_energy=2,sun_angle=0,exposure_ev=0,
        display='sRGB',view_transform='Standard',look='None',gamma=1,
        compositor='componentwise Reinhard then sRGB; matching solid clear background',objects=[])
    for spec in case['objects']:
        path=output/'assets'/spec['asset'] if spec['fixture'] else assets/Path(spec['asset']).stem/spec['asset']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==spec['sha256']
        before=set(scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(path),import_shading='NORMALS')
        imported=set(scene.objects)-before
        parent=bpy.data.objects.new(spec['name']+' placement',None);scene.collection.objects.link(parent)
        for obj in imported:
            if obj.parent not in imported:obj.parent=parent
        parent.location=spec['position'];parent.rotation_euler=spec['rotation'];parent.scale=spec['scale']
        bpy.context.view_layer.update()
        points=[obj.matrix_world@v.co for obj in imported if obj.type=='MESH' for v in obj.data.vertices]
        low=[min(p[j] for p in points) for j in range(3)];high=[max(p[j] for p in points) for j in range(3)]
        error=max(abs(a-b) for a,b in zip(low+high,sum(spec['world_bounds'],[])))
        if error>2e-5:raise RuntimeError('Geometry alignment error '+spec['name']+': '+str(error))
        record['objects'].append(dict(name=spec['name'],world_bounds=[low,high],max_bound_error=error,
            vertices=len(points),materials=sorted({slot.material.name for obj in imported if obj.type=='MESH'
                for slot in obj.material_slots if slot.material})))
    camera=bpy.data.objects.new('Shot Camera',bpy.data.cameras.new('Shot Camera'))
    scene.collection.objects.link(camera);scene.camera=camera
    matrix=Matrix(case['camera']['rotation']).to_4x4();matrix.translation=Vector(case['camera']['position'])
    camera.matrix_world=matrix;camera.data.type='PERSP';camera.data.sensor_fit='HORIZONTAL'
    camera.data.sensor_width=36;camera.data.lens=case['camera']['focal_mm']
    camera.data.clip_start=case['camera']['near'];camera.data.clip_end=case['camera']['far']
    bpy.context.view_layer.update()
    projection=camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),x=1920,y=1080,scale_x=1,scale_y=1)
    error=max(abs(projection[i][j]-case['projection'][i][j]) for i in range(4) for j in range(4))
    assert error<2e-6,error
    record['projection_max_error']=error;record['camera_matrix_world']=[list(row) for row in matrix]
    light=bpy.data.objects.new('Directional',bpy.data.lights.new('Directional','SUN'))
    scene.collection.objects.link(light);light.data.energy=case['lighting']['diffuse'];light.data.color=(1,1,1)
    light.data.angle=0;light.location=(0,0,10)
    light.rotation_euler=Vector(case['lighting']['direction']).to_track_quat('Z','Y').to_euler()
    light.data.use_shadow=True
    record['sun_shadow_settings']={field:getattr(light.data,field) for field in (
        'shadow_buffer_bias','shadow_buffer_clip_start','use_contact_shadow',
        'shadow_cascade_count','shadow_cascade_max_distance','shadow_cascade_exponent','shadow_cascade_fade')}
    world=bpy.data.worlds.new('Studio Small 02');scene.world=world;world.use_nodes=True
    nodes=world.node_tree.nodes;nodes.clear();links=world.node_tree.links
    texture=nodes.new('ShaderNodeTexEnvironment');texture.image=bpy.data.images.load(str(output/'assets/studio_small_02_2k.hdr'))
    texture.image.filepath='//assets/studio_small_02_2k.hdr'
    texture.projection='EQUIRECTANGULAR';texture.image.colorspace_settings.name='Linear'
    background=nodes.new('ShaderNodeBackground');background.inputs['Strength'].default_value=case['environment']['intensity']
    links.new(texture.outputs['Color'],background.inputs['Color'])
    out=nodes.new('ShaderNodeOutputWorld');links.new(background.outputs['Background'],out.inputs['Surface'])
    # No 2D scene replacement: transparent world only hides the HDR behind real geometry.
    # Compositor performs the exact Mini3D tone curve on the real Eevee render result.
    scene.use_nodes=True;nodes=scene.node_tree.nodes;nodes.clear();links=scene.node_tree.links
    image=nodes.new('CompositorNodeRLayers');sep=nodes.new('CompositorNodeSepRGBA');combine=nodes.new('CompositorNodeCombRGBA')
    straight=nodes.new('CompositorNodePremulKey');straight.mapping='PREMUL_TO_STRAIGHT'
    links.new(image.outputs['Image'],straight.inputs[0]);links.new(straight.outputs[0],sep.inputs[0])
    links.new(sep.outputs['A'],combine.inputs['A'])
    for channel in ('R','G','B'):
        add=nodes.new('CompositorNodeMath');add.operation='ADD';add.inputs[1].default_value=1
        divide=nodes.new('CompositorNodeMath');divide.operation='DIVIDE'
        links.new(sep.outputs[channel],add.inputs[0]);links.new(sep.outputs[channel],divide.inputs[0])
        links.new(add.outputs[0],divide.inputs[1]);links.new(divide.outputs[0],combine.inputs[channel])
    over=nodes.new('CompositorNodeAlphaOver');over.inputs[0].default_value=1
    def linear(c):return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
    over.inputs[1].default_value=tuple(linear(c/255) for c in (30,30,35))+(1,)
    premul=nodes.new('CompositorNodePremulKey');premul.mapping='STRAIGHT_TO_PREMUL'
    links.new(combine.outputs[0],premul.inputs[0]);links.new(premul.outputs[0],over.inputs[2])
    composite=nodes.new('CompositorNodeComposite');links.new(over.outputs[0],composite.inputs[0])
    # Keep original glTF images self-contained; HDR is one shared CC0 file.
    for img in bpy.data.images:
        if img!=texture.image and img.source=='FILE' and not img.packed_file:img.pack()
    scene.render.filepath=str(output/(case['name']+'-eevee.png'))
    bpy.ops.wm.save_as_mainfile(filepath=str(output/(case['name']+'.blend')),compress=True,relative_remap=False)
    start=time.perf_counter();bpy.ops.render.render(write_still=True)
    record['complete_render_seconds']=time.perf_counter()-start
    (output/(case['name']+'-blender.json')).write_text(json.dumps(record,indent=2)+'\n')
    print('ALIGNED',case['name'],record['complete_render_seconds'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--assets-root',type=Path,required=True)
    parser.add_argument('--case')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    output=args.output.resolve()
    for case in json.loads((output/'cases.json').read_text())['cases']:
        if not args.case or case['name']==args.case:build(case,output,args.assets_root.resolve())
