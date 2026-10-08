"""API-only Roman 5x8 -> transform -> save/reload -> 50mm 16:9 PNG -> state.

Requires a desktop OpenGL context. The small SDL window contains no Editor UI.
Run: python -B tests/ai_api_smoke.py [output-directory]
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch_json
from mini3d.gl_renderer import GLRenderer


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    # The caller explicitly owns the real context and renderer. No UI import/run.
    pygame.init()
    pygame.display.set_mode((640, 360), pygame.OPENGL | pygame.DOUBLEBUF)
    pygame.display.set_caption('Mini3D API capture context (no Editor UI)')
    renderer = None
    try:
        renderer = GLRenderer(640, 360)
        api = Mini3DAPI(renderer=renderer)
        asset = ROOT / 'model/05_roman_soldier/roman_legionnaire.glb'
        with api.transaction('Spawn and ground character'):
            entity = api.spawn(str(asset), scale=[.06] * 3, rotation=[0, 0, .3])
            api.place_on_ground(entity['entity_id'], x=0, y=0)
        group = api.create_rectangular_formation(entity['entity_id'], 5, 8, 1.2, 1.4)
        assert len(api.list_entities()) == 40
        api.undo()
        assert len(api.list_entities()) == 1
        api.redo()
        assert api.get_group(group['group_id']) == group
        with api.transaction('Move and rotate formation'):
            api.transform_many(group['member_ids'], translation=[2, 1, 0])
            api.transform_many(group['member_ids'], rotation=[0, 0, .25])
        saved = api.save_scene(output / 'scene.json')
        before = api.get_scene_state()
        # A fresh API instance verifies actual persistence, not just live memory.
        restored = Mini3DAPI(renderer=renderer)
        restored.load_scene(saved['path'])
        assert restored.list_entities() == before['entities']
        assert restored.list_groups() == before['groups']
        camera = restored.create_shot_camera(focal_mm=50, aspect='16:9')
        assert abs(camera['focal_mm'] - 50) < 1e-6
        capture = restored.capture(output / 'formation-50mm-16x9.png')
        picture = pygame.image.load(capture['path'])
        assert picture.get_size() == (1920, 1080)
        rgb = pygame.surfarray.array3d(picture).astype(float)
        assert rgb.std() > 10, 'Expected scene geometry in capture'
        response = json.loads(dispatch_json(restored, '{"command":"get_scene_state"}'))
        assert response['ok'] and len(response['result']['entities']) == 40
        assert len(set(e['entity_id'] for e in response['result']['entities'])) == 40
        assert response['result']['groups'][0]['member_ids'] == group['member_ids']
        assert gl.glGetError() == gl.GL_NO_ERROR
        assert 'imgui' not in sys.modules, 'Smoke must never import Editor UI'
        (output / 'state.json').write_text(json.dumps(response['result'], indent=2), encoding='utf8')
        (output / 'result.json').write_text(json.dumps(dict(ok=True, entities=40,
            group_id=group['group_id'], camera=camera, capture=capture['path'],
            renderer=gl.glGetString(gl.GL_RENDERER).decode(), editor_ui_imported=False), indent=2), encoding='utf8')
        print('PASS: API only -> 40 Roman -> transform -> save/reload -> 50mm 16:9 PNG -> JSON state')
        print(capture['path'])
    finally:
        if renderer is not None and hasattr(renderer, 'material_renderer'):
            renderer.material_renderer.close()
        pygame.quit()


if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'captures/ai-api-v1')
