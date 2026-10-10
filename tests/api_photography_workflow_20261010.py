"""Photographer's arrangement/API round trip; no external assets or GL required."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mini3d.api import Mini3DAPI
from mini3d.api_dispatch import dispatch, dispatch_json

OUT = ROOT / 'captures/audit-20261010/api'
OUT.mkdir(parents=True, exist_ok=True)
checks = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

api = Mini3DAPI()
floor = api.spawn('builtin:ground', name='Photo stage', scale=[3, 3, 1])
api.lock(floor['entity_id'])
box = api.spawn(str(ROOT / 'model/06_stl_cube/cube.STL'), name='Sculpture')
bounds = api.get_entity(box['entity_id'], True)['bounds']
extent = max(b-a for a, b in zip(bounds['minimum'], bounds['maximum']))
api.set_transform(box['entity_id'], scale=[1/extent]*3)
api.place_on_ground(box['entity_id'], x=0, y=0)
check('place normalized STL on floor', abs(api.get_entity(box['entity_id'], True)['bounds']['minimum'][2]) < 1e-8)
group = api.create_rectangular_formation(box['entity_id'], 3, 3, 1.5, 1.5)
check('nine-object formation', len(group['member_ids']) == 9 and len(api.list_entities()) == 10)
api.undo()
check('formation undo keeps source and floor', len(api.list_entities()) == 2)
api.redo()
check('formation redo preserves member IDs', api.get_group(group['group_id']) == group)
with api.transaction('Arrange sculptures'):
    api.transform_many(group['member_ids'], translation=[2, 1, 0])
    api.transform_many(group['member_ids'], rotation=[0, 0, 0.35])
check('backdrop stays locked', api.get_entity(floor['entity_id'])['locked'])
before = api.get_scene_state()
result = dispatch(api, {'command': 'transaction', 'args': {'commands': [
    {'command': 'set_transform', 'args': {'entity_id': box['entity_id'], 'position': [7, 8, 9]}},
    {'command': 'delete', 'args': {'entity_id': floor['entity_id']}}
]}})
check('locked backdrop aborts entire placement batch', not result['ok'] and before == api.get_scene_state())
api.set_lighting(mode='Scene', direction=[-1, -2, 3], diffuse=0.8, ambient=0.2)
api.set_shadows(enabled=True, resolution=1024)
api.create_shot_camera(focal_mm=50, aspect='16:9')
for lens in (24, 35, 50, 85):
    api.set_lens(lens)
    for aspect in ('16:9', '3:2', '4:3', '1:1'):
        camera = api.set_aspect(aspect)
        check('lens/aspect %s %s' % (lens, aspect), abs(camera['focal_mm'] - lens) < 1e-8 and camera['aspect'] == aspect)
api.set_lens(50)
api.set_aspect('3:2')
before = api.get_scene_state()
scene_path = OUT / 'practical-scene.json'
api.save_scene(scene_path)
fresh = Mini3DAPI()
after = fresh.load_scene(scene_path)
for key in ('entities', 'groups', 'selected_ids', 'primary_selection_id', 'selected_group_id',
            'shot_camera', 'lighting', 'shadows', 'placement_plane'):
    check('save/reload ' + key, before[key] == after[key])
check('load resets placement undo history', after['history']['undo_count'] == after['history']['redo_count'] == 0)
result = json.loads(dispatch_json(fresh, '{"command":"get_scene_state","args":{"include_bounds":true}}'))
check('dispatcher returns complete JSON-safe scene', result['ok'] and len(result['result']['entities']) == 10)
copy = fresh.duplicate(box['entity_id'], name='Extra sculpture')
check('loaded scene allocates unique next ID', copy['entity_id'] not in {e['entity_id'] for e in after['entities']})
fresh.delete(copy['entity_id'])
fresh.undo()
check('undo deletion restores same instance ID', fresh.get_entity(copy['entity_id'])['name'] == 'Extra sculpture')
(OUT / 'practical-result.json').write_text(json.dumps({'passed': len(checks), 'checks': checks,
    'scene': str(scene_path), 'note': 'State/API test only; photo raster rendering tested separately.'}, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'scene': str(scene_path)}))
