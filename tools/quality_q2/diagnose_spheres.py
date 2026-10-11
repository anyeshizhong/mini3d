"""Blender-only diagnosis; these altered scenes are separate from the A/B matrix.

blender -b --python tools/quality_q2/diagnose_spheres.py -- --output docs/renderer-v2/q2
"""
import argparse
from pathlib import Path
import sys
import bpy


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    output=parser.parse_args(sys.argv[sys.argv.index('--')+1:]).output.resolve()
    bpy.ops.wm.open_mainfile(filepath=str(output/'spheres.blend'))
    scene=bpy.context.scene
    bpy.data.objects['Directional'].data.use_shadow=False
    scene.render.filepath=str(output/'spheres-diagnostic-no-shadow.png')
    bpy.ops.render.render(write_still=True)
    bpy.data.objects['Directional'].data.use_shadow=True
    for obj in scene.objects:
        if obj.type=='MESH' and obj.parent and 'sphere' in obj.parent.name:
            obj.data.normals_split_custom_set_from_vertices([tuple(v.co.normalized()) for v in obj.data.vertices])
            obj.data.use_auto_smooth=True
    scene.render.filepath=str(output/'spheres-diagnostic-radial-normals.png')
    bpy.ops.render.render(write_still=True)
