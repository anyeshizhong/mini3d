"""Real GPU directional shadows. --baseline uses isolated 1033e5e checkout."""
import io
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '--baseline' in sys.argv
sys.path.insert(0,str(ROOT/'captures/shadow-baseline' if BASELINE else ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from lighting_fixture import cube_geometry, write_pbr_cube
from mini3d.camera import Camera
from mini3d.gltf_loader import load_gltf
from mini3d.gl_renderer import GLRenderer
from mini3d.material_renderer import MaterialRenderer
from mini3d.render_target import RenderTarget
from mini3d.scene import Scene, Entity, Mesh
from mini3d.shot_camera import ShotCamera, render_shot, capture_png

SIZE = (900,600)


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    path = output/'pbr-cube.gltf'
    write_pbr_cube(path)
    pygame.init()
    pygame.display.set_mode(SIZE,pygame.OPENGL|pygame.DOUBLEBUF)
    renderer, target = GLRenderer(*SIZE), RenderTarget()
    renderer.render_mode = 'REALISTIC'
    target.resize(*SIZE)
    scene = Scene()
    scene.show_grid = scene.show_axes = False
    scene.lighting_mode = 'Scene'
    scene.light_dir = np.array([1.,-1.,2.])
    scene.ambient, scene.diffuse = .12, 2.
    ground = load_gltf(path).instantiate()
    ground.scale[:] = [5,5,.2]
    ground.pos[2] = -.14
    scene.add(ground)
    material = next(e.model.material for e in scene.get_flat_render_list())
    material['pbrMetallicRoughness']['baseColorFactor'] = [.65,.65,.65,1]
    v,n,i = cube_geometry()
    cube = Entity(Mesh(v,i,normals=n),'ordinary caster')
    cube.pos[2] = .7
    scene.add(cube)
    camera = Camera((-4,6,9),near=.1,far=100)
    camera.look_at((0,0,0))
    report = dict(gpu=gl.glGetString(gl.GL_RENDERER).decode(),gl=gl.glGetString(gl.GL_VERSION).decode(),checks={})

    def draw(name=None, enabled=True):
        scene.shadows_enabled = enabled
        scene.update()
        target.bind()
        renderer.resize(*SIZE)
        gl.glDepthMask(True)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        renderer.render(scene,camera)
        raw = gl.glReadPixels(0,0,*SIZE,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        if name:
            pygame.image.save(pygame.image.fromstring(raw,SIZE,'RGB',True),str(output/(name+'.png')))
        assert gl.glGetError() == gl.GL_NO_ERROR
        pygame.event.pump()
        return np.frombuffer(raw,np.uint8).reshape(SIZE[1],SIZE[0],3).copy()

    def probe(rgb,point):
        clip = camera.projection_matrix(SIZE[0]/SIZE[1]) @ camera.view_matrix @ np.append(point,1)
        x,y = ((clip[:2]/clip[3]+1)*np.array(SIZE)/2).astype(int)
        assert 2 <= x < SIZE[0]-2 and 2 <= y < SIZE[1]-2
        return np.median(rgb[y-1:y+2,x-1:x+2],axis=(0,1))

    try:
        off = draw('baseline-off' if BASELINE else 'shadow-off',False)
        scene.lighting_mode = 'Studio'
        studio = draw('baseline-studio' if BASELINE else None,False)
        if BASELINE:
            return
        np.testing.assert_array_equal(studio,draw(enabled=True))
        for name,rgb in [('baseline-off',off),('baseline-studio',studio)]:
            old = pygame.image.tostring(pygame.image.load(str(output/(name+'.png'))),'RGB',True)
            np.testing.assert_array_equal(rgb,np.frombuffer(old,np.uint8).reshape(rgb.shape))
        report['checks']['disabled_and_studio_exact_baseline'] = True
        scene.lighting_mode = 'Scene'
        on = draw('shadow-on')
        shadow_point, lit_point = (-1.,1.,0), (2.,-2.,0)
        assert np.mean(probe(off,shadow_point)-probe(on,shadow_point)) > 40
        np.testing.assert_allclose(probe(off,lit_point),probe(on,lit_point),atol=1)
        report['checks']['world_probes'] = dict(shadow_off=probe(off,shadow_point).tolist(),shadow_on=probe(on,shadow_point).tolist(),lit=probe(on,lit_point).tolist())
        # Uniform exposed ground has no acne/stripes; near-contact shadow stays attached.
        for x in (-2.5,2.5):
            for y in (-2.5,-1,0,1,2.5):
                np.testing.assert_allclose(probe(off,(x,y,0)),probe(on,(x,y,0)),atol=1)
        assert np.mean(probe(off,(-.82,.2,0))-probe(on,(-.82,.2,0))) > 40
        report['checks']['exposed_ground_no_acne_and_contact_shadow'] = True
        initial_matrix = renderer.shadow_map.matrix.copy()
        depth = renderer.shadow_map.save_depth_png(output/'shadow-depth.png')
        assert (depth<1).sum() > 10000 and np.isfinite(depth).all()
        # Camera navigation cannot move the light-space projection or shadow.
        for name,position,aim in [('orbit',(-7,3,8),(0,0,0)),('translate',(-7.3,3,8),None),('rotate',(-7.3,3,8),(.4,.2,0))]:
            camera.position = position
            if aim is not None:
                camera.look_at(aim)
            a,b = draw(enabled=False),draw('camera-'+name)
            np.testing.assert_array_equal(initial_matrix,renderer.shadow_map.matrix)
            assert np.mean(probe(a,shadow_point)-probe(b,shadow_point)) > 40
        camera.position = (-4,6,9)
        camera.look_at((0,0,0))
        scene.light_dir = np.array([-1.,-1.,2.])
        changed = draw('light-changed')
        assert np.mean(probe(changed,shadow_point)-probe(on,shadow_point)) > 40
        assert np.mean(probe(changed,(1,1,0))) < np.mean(probe(changed,shadow_point))-40
        scene.light_dir = np.array([1.,-1.,2.])
        # Ambient and emission remain identical with direct intensity zero.
        scene.diffuse = 0
        material['emissiveFactor'] = [.1,.04,.02]
        np.testing.assert_array_equal(draw(enabled=False),draw())
        material.pop('emissiveFactor')
        scene.diffuse = 2
        material['extensions'] = {'KHR_materials_unlit':{}}
        a,b = draw(enabled=False),draw()
        np.testing.assert_array_equal(probe(a,shadow_point),probe(b,shadow_point))
        material.pop('extensions')
        report['checks']['ambient_emission_unlit_preserved'] = True
        # Imported PBR caster -> ordinary receiver. Two shared imported instances.
        imported = load_gltf(path)
        top = imported.instantiate()
        top.pos[:] = [0,0,1.8]
        top.scale[:] = .6
        scene.add(top)
        cube.scale[:] = [2,2,.25]
        cube.pos[2] = .175
        a,b = draw('mutual-off',False),draw('mutual-on')
        assert np.mean(probe(a,(-.65,.65,.35))-probe(b,(-.65,.65,.35))) > 30
        top.visible = False
        cube.scale[:] = 1
        cube.pos[2] = .7
        # Cutout texture: transparent half must neither occlude nor cast.
        cube.visible = False
        pixels = pygame.Surface((8,8),pygame.SRCALPHA)
        pixels.fill((255,255,255,0))
        pixels.fill((255,255,255,255),(4,0,4,8))
        encoded = io.BytesIO()
        pygame.image.save(pixels,encoded,'mask.png')
        mask_material = dict(alphaMode='MASK',alphaCutoff=.5,doubleSided=True,
            pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1],metallicFactor=0,roughnessFactor=1),
            textures=dict(baseColor=dict(image=encoded.getvalue(),sampler=dict(magFilter=9728,minFilter=9728))))
        mask = Entity(Mesh([[-.7,-.7,1.4],[.7,-.7,1.4],[.7,.7,1.4],[-.7,.7,1.4]],
            [0,1,2,0,2,3],normals=[[0,0,1]]*4,texcoords=[[0,0],[1,0],[1,1],[0,1]],material=mask_material))
        scene.add(mask)
        a,b = draw(enabled=False),draw('alpha-mask')
        hole,solid = (-1.1,.7,0),(-.3,.7,0)
        np.testing.assert_allclose(probe(a,hole),probe(b,hole),atol=1)
        assert np.mean(probe(a,solid)-probe(b,solid)) > 40
        mask_material['alphaMode'] = 'BLEND'
        np.testing.assert_allclose(probe(draw(enabled=False),solid),probe(draw(),solid),atol=1)
        mask.visible = False
        cube.visible = True
        report['checks']['alpha_mask_texture_and_blend_noncasting'] = True
        # Opaque unlit casters retain silhouettes, but do not receive PBR shadows.
        top.visible = True
        caster_mat = next(e.model.material for e in scene.get_flat_render_list() if e.model.material is not None and e.model.material is not material)
        caster_mat['extensions'] = {'KHR_materials_unlit':{}}
        cube.visible = False
        a,b = draw(enabled=False),draw()
        assert np.mean(probe(a,(-.9,.9,0))-probe(b,(-.9,.9,0))) > 40
        caster_mat.pop('extensions')
        top.visible = False
        cube.visible = True
        # 10000x scene size range, same projected result and fitted coverage.
        for scale in (.01,100.):
            for entity,pos,sz in ((ground,[0,0,-.14],[5,5,.2]),(cube,[0,0,.7],[1,1,1])):
                entity.pos[:] = np.array(pos)*scale
                entity.scale[:] = np.array(sz)*scale
            camera.position = np.array([-4,6,9])*scale
            camera.near, camera.far = .1*scale,100*scale
            camera.look_at((0,0,0))
            a,b = draw(enabled=False),draw('scale-'+str(scale))
            assert np.mean(probe(a,np.array(shadow_point)*scale)-probe(b,np.array(shadow_point)*scale)) > 40
        ground.pos[:],ground.scale[:] = [0,0,-.14],[5,5,.2]
        cube.pos[:],cube.scale[:] = [0,0,.7],[1,1,1]
        camera.position = [-4,6,9]
        camera.near,camera.far = .1,100
        camera.look_at((0,0,0))
        # Bias/PCF actually influence the result; no camera clips are changed.
        scene.shadow_pcf = False
        hard = draw('pcf-off')
        scene.shadow_pcf = True
        soft = draw()
        assert np.count_nonzero(hard != soft) > 50
        scene.shadow_bias = .05
        excessive = draw('bias-excessive')
        assert np.count_nonzero(excessive != soft) > 100
        scene.shadow_bias = .0005
        # Full Shot export uses Scene mode even with Studio Editor preview.
        shot = ShotCamera(camera)
        scene.lighting_mode = 'Studio'
        scene.shadows_enabled = True
        scene.update()
        render_shot(scene,shot,renderer,target)
        preview = gl.glReadPixels(0,0,*shot.size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        capture_png(scene,shot,renderer,output/'shot.png')
        png = pygame.image.tostring(pygame.image.load(str(output/'shot.png')),'RGB',True)
        assert preview == png
        scene.lighting_mode = 'Scene'
        target.resize(*SIZE)
        # Deliberately dirty GL state is restored by depth pass, including FBOs.
        draw()
        state = MaterialRenderer._save_state()
        MaterialRenderer._restore_state(state)
        fbo,viewport = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING)),gl.glGetIntegerv(gl.GL_VIEWPORT).copy()
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glDepthMask(False)
        before = MaterialRenderer._save_state()
        MaterialRenderer._restore_state(before)
        renderer.shadow_map.render(scene.get_flat_render_list(),scene,renderer)
        after = MaterialRenderer._save_state()
        for key in before:
            if isinstance(before[key],dict):
                assert before[key] == after[key],key
            else:
                np.testing.assert_array_equal(before[key],after[key],err_msg=key)
        assert fbo == int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
        np.testing.assert_array_equal(viewport,gl.glGetIntegerv(gl.GL_VIEWPORT))
        MaterialRenderer._restore_state(state)
        # GPU elapsed timer query, synchronized CPU frame times also recorded.
        report['timing'] = {}
        for enabled in (False,True):
            for _ in range(3): draw(enabled=enabled)
            gpu_ms,cpu_ms = [],[]
            query = int(np.asarray(gl.glGenQueries(1)).reshape(-1)[0])
            for _ in range(12):
                scene.shadows_enabled = enabled
                target.bind()
                gl.glFinish()
                start = time.perf_counter()
                gl.glBeginQuery(gl.GL_TIME_ELAPSED,query)
                renderer.render(scene,camera)
                gl.glEndQuery(gl.GL_TIME_ELAPSED)
                gl.glFinish()
                cpu_ms.append((time.perf_counter()-start)*1000)
                gpu_ms.append(int(gl.glGetQueryObjectuiv(query,gl.GL_QUERY_RESULT))/1e6)
            gl.glDeleteQueries(1,[query])
            report['timing']['on' if enabled else 'off'] = dict(gpu_median_ms=statistics.median(gpu_ms),cpu_median_ms=statistics.median(cpu_ms))
        # 100 transformed shared PBR instances; record draw/fit cost and coverage.
        instances = []
        for x in range(10):
            for y in range(10):
                instance = imported.instantiate()
                instance.pos[:] = [(x-4.5)*2,(y-4.5)*2,.7]
                instance.rot[2] = (x+y)*.1
                scene.add(instance)
                instances.append(instance)
        ground.scale[:] = [16,16,.2]
        camera.position = [-18,25,32]
        camera.far = 150
        camera.look_at((0,0,0))
        large_off,large_on = draw('large-off',False),draw('large-on')
        assert np.count_nonzero(large_off != large_on) > 1000
        mesh_ids = {id(e.model) for e in scene.get_flat_render_list() if e.model.material is not None}
        assert len(renderer.material_renderer._meshes) == len(mesh_ids)+1  # hidden mask retains its cached buffer
        timings = []
        for _ in range(6):
            gl.glFinish()
            start = time.perf_counter()
            draw()
            gl.glFinish()
            timings.append((time.perf_counter()-start)*1000)
        report['large_scene'] = dict(instances=100,shared_imported_meshes=len(mesh_ids),synchronized_frame_readback_median_ms=statistics.median(timings),camera_far=camera.far)
        renderer.shadow_map.save_depth_png(output/'large-depth.png')
        # Resolution changes delete superseded resources and remain renderable.
        old = (renderer.shadow_map.texture,renderer.shadow_map.fbo)
        scene.shadow_resolution = 512
        draw()
        # GL names may be reused immediately after deletion.
        if old[0] != renderer.shadow_map.texture:
            assert not gl.glIsTexture(old[0])
        if old[1] != renderer.shadow_map.fbo:
            assert not gl.glIsFramebuffer(old[1])
        assert renderer.shadow_map.size == 512
        scene.shadow_resolution = 1024
        draw()
        report['depth'] = dict(resolution=renderer.shadow_map.size,format='DEPTH_COMPONENT24',nominal_bytes=1024*1024*3,typical_allocated_bytes=1024*1024*4,covered_pixels=int((depth<1).sum()),minimum=float(depth.min()))
        report['checks']['shot_png_equals_camera_view'] = True
        report['checks']['depth_pass_state_restored'] = True
        report['checks']['scales_mutual_shadows_bias_pcf'] = True
        report['camera_clips'] = dict(near=camera.near,far=camera.far)
        (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report),flush=True)
    finally:
        target.close()
        if hasattr(renderer,'close'):
            handles = (renderer.shadow_map.texture,renderer.shadow_map.fbo,renderer.shadow_map.program)
            renderer.close()
            renderer.close()
            assert not gl.glIsTexture(handles[0]) and not gl.glIsFramebuffer(handles[1]) and not gl.glIsProgram(handles[2])
        elif hasattr(renderer,'material_renderer'):
            renderer.material_renderer.close()
        pygame.quit()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--baseline']
    run(Path(args[0]) if args else ROOT/'captures/shadows')
