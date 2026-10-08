"""Real GL image/depth comparisons, placement and actual Editor validation.

python -B tests/ground_separation_smoke.py [output-directory] [model-scale]
Legacy Ground + offset is reconstructed ONLY in the diagnostic baseline.
"""
import copy
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.editor import Editor
from mini3d.gl_renderer import GLRenderer
from mini3d.material_renderer import MaterialRenderer
from mini3d.placement import create_ground, geometry_bounds, SurfaceHit, raycast_surface
from mini3d.picking import pick_entity
from mini3d.camera import Camera
from mini3d.render_target import RenderTarget
from mini3d.shot_camera import ShotCamera, capture_png
from mini3d.scene import Scene

SIZE = (960,640)


def save_pixels(path,pixels,size=SIZE):
    pygame.image.save(pygame.image.fromstring(pixels,size,'RGB',True),str(path))


def run(output,scale=1.):
    output.mkdir(parents=True,exist_ok=True)
    pygame.init()
    pygame.display.set_mode(SIZE,pygame.OPENGL|pygame.DOUBLEBUF)
    pygame.display.set_caption('Ground separation: fixed near/far comparisons')
    renderer = GLRenderer(*SIZE)
    renderer.material_renderer = MaterialRenderer()
    target = RenderTarget()
    target.resize(*SIZE)
    app = Editor(*SIZE)
    scene = app.scene
    root = app.commands.spawn(ROOT/'model/08_rome_river/rome_river_side.glb',scale=[scale]*3)
    app.commands.place_on_surface(root,SurfaceHit([0,0,0],[0,0,1]))
    app.select(root)
    app.focus_selected()
    camera,controller = app.viewer.camera,app.viewer.controller
    fit = controller.distance
    scene.show_grid = scene.show_axes = False
    scene.update()
    reference = Scene()
    reference.add(root)
    reference.show_grid = reference.show_axes = False
    legacy = copy.copy(scene)
    helper = create_ground()
    legacy.root_entities = [root,helper]
    material_renderer = renderer.material_renderer
    real_material = material_renderer._material

    def render(current,name,old=False):
        def legacy_material(material,mode):
            if material is helper.model.material:
                gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
                gl.glPolygonOffset(1,1)
            else:
                gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
            real_material(material,mode)
        target.bind()
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDepthMask(True)
        renderer.resize(*SIZE)
        if old:
            with patch.object(material_renderer,'_material',legacy_material):
                renderer.render(current,camera)
        else:
            renderer.render(current,camera)
        rgb = gl.glReadPixels(0,0,*SIZE,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        depth = np.asarray(gl.glReadPixels(0,0,*SIZE,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT)).reshape(SIZE[1],SIZE[0]).copy()
        save_pixels(output/(name+'.png'),rgb)
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return np.frombuffer(rgb,np.uint8).reshape(SIZE[1],SIZE[0],3).copy(),depth

    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),scale=scale,views=[])
    try:
        for name,yaw,pitch,distance in (('far-river',.8,.7,1),('far-reverse',2.4,.7,1),
                                       ('near-road',0,.25,.4),('near-temples',-2.4,.25,.4)):
            controller.yaw,controller.pitch,controller.distance = yaw,pitch,fit*distance
            controller.update()
            scene.grid_scale = 10**math.floor(math.log10(controller.distance/10))/20
            expected,expected_depth = render(reference,name+'-reference')
            before,before_depth = render(legacy,name+'-before',old=True)
            after,after_depth = render(scene,name+'-after')
            model = expected_depth < 1
            bad_before = np.any(before != expected,axis=2) & model
            np.testing.assert_array_equal(after,expected)
            np.testing.assert_array_equal(after_depth,expected_depth)
            scene.show_grid = True
            grid,grid_depth = render(scene,name+'-grid-on')
            np.testing.assert_array_equal(grid_depth,after_depth)
            if distance == 1:
                assert np.any(grid != after), 'Grid must be visible outside the model in far views'
            scene.show_grid = False
            record = dict(name=name,position=camera.position.tolist(),rotation=camera.rotation.tolist(),
                          near=camera.near,far=camera.far,old_model_pixels_changed=int(bad_before.sum()),
                          new_model_pixels_changed=0,grid_depth_changed_pixels=0)
            report['views'].append(record)
            print(record,flush=True)
        if scale == 1:
            assert report['views'][2]['old_model_pixels_changed'] > 1000, 'Must reproduce close-up loss'

        scene.show_grid = True
        for mask in (True,False):
            gl.glDepthMask(mask)
            gl.glDisable(gl.GL_DEPTH_TEST)
            renderer.render_editor_grid(scene,camera)
            assert bool(gl.glGetBooleanv(gl.GL_DEPTH_WRITEMASK)) == mask
            assert not gl.glIsEnabled(gl.GL_DEPTH_TEST)
        gl.glDepthMask(True)
        gl.glEnable(gl.GL_DEPTH_TEST)
        shot = ShotCamera(camera)
        first = capture_png(scene,shot,renderer,output/'photo-grid-on.png')
        scene.show_grid = False
        second = capture_png(scene,shot,renderer,output/'photo-grid-off.png')
        third = capture_png(reference,shot,renderer,output/'photo-reference.png')
        arrays = [pygame.surfarray.array3d(pygame.image.load(str(path))) for path in (first,second,third)]
        np.testing.assert_array_equal(arrays[0],arrays[1])
        np.testing.assert_array_equal(arrays[1],arrays[2])
        report['photo_grid_and_mesh_reference_equal'] = True
        empty_ground_image,_ = render(scene,'explicit-ground-absent')
        real_ground = app.commands.spawn('builtin:ground',position=[0,0,.15*scale],
                                         scale=[.1*scale,.1*scale,1])
        ground_image,_ = render(scene,'explicit-ground-present')
        assert np.any(empty_ground_image != ground_image), 'Explicit ground must actually render'
        app.commands.delete(real_ground)
        report['explicit_ground_mesh_renders'] = True
        controller.yaw,controller.pitch,controller.distance = 0,np.pi/2,fit*.65
        controller.update()
        render(scene,'top-view')
        # Points verified on the top-view image: road and two temple stair treads.
        app.commands.lock(root)
        rect = (0,0,*SIZE)
        points = [('road',(397,315)),('step-low',(501,366)),('step-high',(511,366))]
        supports = []
        for label,pixel in points:
            assert pick_entity(scene,camera,pixel,rect) == (None,None)
            hit = raycast_surface(scene,camera,pixel,rect)
            assert hit.entity is root and hit.normal[2] > .99
            supports.append((label,hit))
        assert supports[0][1].position[2] < supports[1][1].position[2] < supports[2][1].position[2]
        soldier = app.commands.spawn(ROOT/'model/05_roman_soldier/roman_legionnaire.glb',
                                     scale=[.0006*scale]*3,rotation=[.2,-.3,.7])
        report['placement'] = []
        for label,hit in supports:
            app.commands.place_on_surface(soldier,hit)
            low,high = geometry_bounds(soldier)
            np.testing.assert_allclose(low[2],hit.position[2],atol=1e-10*scale)
            np.testing.assert_allclose((low[:2]+high[:2])/2,hit.position[:2],atol=1e-10*scale)
            np.testing.assert_allclose(soldier.rot,[0,0,.7])
            report['placement'].append(dict(surface=label,hit=hit.position.tolist(),
                                           foot_z=float(low[2]),root_position=soldier.pos.tolist()))
            controller.target = hit.position + [0,0,.012*scale]
            controller.yaw,controller.pitch,controller.distance = -1.6,.55,.12*scale
            controller.update()
            render(scene,'soldier-'+label)
        scene_path = output/'scene.json'
        app.save_scene(scene_path)
        document = json.loads(scene_path.read_text(encoding='utf8'))
        document.pop('placement_plane')
        document['ground_visible'] = True  # Real legacy v3 migration, with actual assets.
        scene_path.write_text(json.dumps(document),encoding='utf8')
        app.load_scene(scene_path)
        assert app.scene.ground is None
        assert app.scene.find_by_id(root.entity_id).locked
        assert len(app.scene.root_entities) == 2
        report['legacy_reload_no_ground'] = True
        assert gl.glGetError() == gl.GL_NO_ERROR
        (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    finally:
        target.close()
        material_renderer.close()
        pygame.quit()


def run_editor(output,scale=1.):
    from mini3d import editor
    state = dict(frame=0)
    flip = pygame.display.flip

    class RomeEditor(editor.Editor):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            state['app'] = self
            root = self.commands.spawn(ROOT/'model/08_rome_river/rome_river_side.glb',scale=[scale]*3)
            self.commands.place_on_surface(root,SurfaceHit([0,0,0],[0,0,1]))
            self.select(root)
            self.focus_selected()
            self.select(None)
            self.viewer.controller.yaw,self.viewer.controller.pitch = 0,.25
            self.viewer.controller.distance *= .4
            self.viewer.controller.update()
            self.show_grid = False
            self.tool = 'select'

    def capture():
        index = state['frame']
        app = state['app']
        if index in (3,6):
            size = pygame.display.get_window_size()
            pixels = gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
            save_pixels(output/('editor-grid-off.png' if index==3 else 'editor-grid-on.png'),pixels,size)
        if index == 3:
            app.show_grid = True
        if index == 6:
            ground = app.add_ground_mesh()
            assert ground in app.scene.root_entities and ground in app.scene.get_flat_render_list()
            app.undo()
            assert ground not in app.scene.root_entities
        assert gl.glGetError() == gl.GL_NO_ERROR
        state['frame'] += 1
        flip()
    with patch.object(editor,'Editor',RomeEditor),patch.object(pygame.display,'flip',capture):
        editor.run(initial_asset=None,frames=9)


if __name__ == '__main__':
    directory = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/ground-separation'
    scale = float(sys.argv[2]) if len(sys.argv)>2 else 1.
    run(directory,scale)
    run_editor(directory,scale)
