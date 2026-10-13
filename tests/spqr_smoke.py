"""Real desktop GL acceptance for the self-contained SPQR street."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    import numpy as np
    from PIL import Image
    from OpenGL import GL
    from mini3d.api import Mini3DAPI
    from mini3d.gl_renderer import GLRenderer
    from tools.capture_sunset import desktop_context
    from tools.build_roman_street import build_scene
    with desktop_context():
        renderer = GLRenderer(1920, 1080)
        try:
            api = Mini3DAPI(renderer)
            start = time.perf_counter()
            street = build_scene(api)
            creation = time.perf_counter() - start
            def photo(app, name):
                start = time.perf_counter()
                path = args.output / (name + '.png')
                app.capture(path)
                return np.array(Image.open(path)), time.perf_counter() - start
            original, capture_seconds = photo(api, 'street')
            assert original[:, :, :3].std() > 15, 'Street image lacks visible detail'
            path = args.output / 'street.scene.json'
            api.save_scene(path)
            fresh = Mini3DAPI(renderer)
            fresh.load_scene(path)
            reloaded, _ = photo(fresh, 'reloaded')
            reload_delta = np.abs(original.astype(int) - reloaded.astype(int))
            reload_pixels = int(np.any(reload_delta, axis=2).sum())
            assert reload_delta.max() <= 32 and reload_pixels <= original.shape[0] * original.shape[1] * .0001, 'Reload changes photograph beyond raster tolerance'
            building = api.get_group(street['groups']['buildings'])['member_ids'][0]
            position = np.asarray(api.get_entity(building)['position']) + [4, 0, 0]
            api.set_transform(building, position=position)
            changed, _ = photo(api, 'edited')
            changed_pixels = int(np.any(changed != original, axis=2).sum())
            assert changed_pixels > 100, 'Editing building did not affect photograph'
            api.undo()
            undone, _ = photo(api, 'undone')
            assert np.array_equal(original, undone), 'Undo did not restore photograph'
            api.create_shot_camera(position=[26, -36, 25], target=[0, 0, 2], focal_mm=35,
                                   aspect='16:9', near=.05, far=200)
            overview, _ = photo(api, 'overview')
            api.create_shot_camera(position=[.5, 15, 1.7], target=[0, 27, 2.8], focal_mm=24, aspect='16:9', near=.05, far=200)
            photo(api, 'beyond-arch')
            assert overview[:, :, :3].std() > 15
            flat = api._app.scene.get_flat_render_list()
            models = [node.model for node in flat if node.model is not None]
            unique = {id(model): model for model in models}
            error = int(GL.glGetError())
            assert error == 0, error
            from mini3d.render_target import RenderTarget
            from mini3d.shot_camera import render_scene_view
            target = RenderTarget(); target.resize(960, 540)
            timings=[]
            try:
                for frame in range(24):
                    api._app.shot_camera.position = [.5 + frame * .015, 15, 1.7]
                    start=time.perf_counter()
                    render_scene_view(api._app.scene, api._app.shot_camera, renderer, target, (960,540), 1)
                    GL.glFinish()
                    if frame >= 4: timings.append(time.perf_counter()-start)
                draw_stats=dict(renderer.render_stats)
            finally: target.close()
            report = dict(navigation_resolution=[960,540], samples=1,
                navigation_mean_ms=float(np.mean(timings)*1000),
                navigation_fps=float(1/np.mean(timings)), draw_stats=draw_stats,
                vram='Not measured: no portable dedicated-VRAM counter on this integrated GPU', renderer=GL.glGetString(GL.GL_RENDERER).decode(),
                roots=len(api.list_entities()), mesh_instances=len(models), unique_meshes=len(unique),
                triangles=sum(len(model.indices) for model in models),
                unique_triangles=sum(len(model.indices) for model in unique.values()),
                creation_seconds=creation, first_capture_seconds=capture_seconds,
                reload_max_channel_difference=int(reload_delta.max()), reload_changed_pixels=reload_pixels, undo_max_channel_difference=0,
                edited_pixels=changed_pixels, gl_error=error)
            (args.output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps(report, indent=2))
        finally:
            renderer.close()


if __name__ == '__main__':
    main()
