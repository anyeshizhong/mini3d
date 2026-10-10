"""Actual ImGui/GL event-loop journeys: drag ownership, photo isolation, scene changes."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pygame
from OpenGL import GL as gl
from mini3d import editor
from mini3d.editor_ui import EditorUI
from mini3d.placement import geometry_bounds

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=ROOT / 'captures/second-session/ui-study')
parser.add_argument('--panel-release', action='store_true', help='Add cross-panel release/Undo/Redo journey')
args = parser.parse_args()
OUT = args.output
OUT.mkdir(parents=True, exist_ok=True)
state = {'frame': 0, 'mouse': (0, 0), 'checks': [], 'trace': []}
real_get, real_flip, real_capture = pygame.event.get, pygame.display.flip, editor.capture_png

class App(editor.Editor):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        state['app'] = self
        box = self.commands.spawn(ROOT / 'model/06_stl_cube/cube.STL', name='Subject')
        lo, hi = geometry_bounds(box)
        factor = 1 / max(hi-lo)
        self.commands.set_transform(box, scale=[factor]*3, position=-(lo+hi)/2*factor+[0, 0, .5])
        self.select(box)
        self.frame_all()
        self.set_view('top')
        self.commands.clear_history()
        self.show_grid = True
        state['box'] = box

class UI(EditorUI):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        state['ui'] = self

def check(name, condition):
    state['checks'].append({'name': name, 'passed': bool(condition), 'frame': state['frame']})

def move(pos, buttons=(0,0,0)):
    last = state['mouse']
    state['mouse'] = tuple(map(int, pos))
    return pygame.event.Event(pygame.MOUSEMOTION, pos=state['mouse'],
        rel=(state['mouse'][0]-last[0], state['mouse'][1]-last[1]), buttons=buttons)

def button(kind, number=1):
    return pygame.event.Event(kind, pos=state['mouse'], button=number)

def escape(kind=pygame.KEYDOWN):
    return pygame.event.Event(kind, key=pygame.K_ESCAPE, mod=0, unicode='')

def center():
    x,y,w,h = state['app'].viewport_rect
    return (x+w/2, y+h/2)

def prepare(tool):
    app = state['app']
    app.finish_edit()
    app.commands.set_transform(state['box'], position=state['initial'])
    app.select(state['box'])
    app.tool = tool
    app.frame_all()
    app.set_view('top')
    app.commands.clear_history()

def capture(label):
    state['capture_label'] = label
    state['app'].request_capture()

def capture_wrapper(scene, camera, renderer, path):
    return real_capture(scene, camera, renderer, OUT/(state['capture_label']+'.png'))

def events():
    real_get()
    f, app, box = state['frame'], state['app'], state['box']
    c = center()
    if f == 1:
        state['initial'] = box.pos.copy()
        app.tool = 'move'
        state['gizmo_start'] = app.gizmo.geometry(app.viewport_rect)[1]
        return [move(state['gizmo_start'])]
    if f == 2: return [button(pygame.MOUSEBUTTONDOWN)]
    if f == 3: return [move(state['gizmo_start']+[60, 0], (1,0,0))]
    if f == 4: return [move((30,500), (1,0,0))]
    if f == 5: return [escape()]
    if f == 6: return [escape(pygame.KEYUP), button(pygame.MOUSEBUTTONUP)]
    if f == 8:
        prepare('surface')
        return [move(c)]
    if f == 9: return [button(pygame.MOUSEBUTTONDOWN)]
    if f == 10: return [move((c[0]+50,c[1]), (1,0,0))]
    if f == 11: return [move((30,500), (1,0,0))]
    if f == 12: return [escape()]
    if f == 13: return [escape(pygame.KEYUP), button(pygame.MOUSEBUTTONUP)]
    if f == 15:
        prepare('surface')
        return [move(c)]
    if f == 16: return [button(pygame.MOUSEBUTTONDOWN)]
    if f == 17: return [move((c[0]+50,c[1]), (1,0,0))]
    if f == 18: return [move((30,500), (1,0,0))]
    if f == 19: return [button(pygame.MOUSEBUTTONUP)]
    if f == 21:
        app.commands.spawn('builtin:ground')
        app.frame_all()
        app.set_view('front')
        app.viewer.controller.orbit(80, -40)
        app.create_camera_from_view()
        app.set_shot_lens(35)
        app.set_camera_view(True)
        state['shot_before'] = app.shot_camera.to_dict()
        state['editor_before'] = app.viewer.camera.view_matrix.copy()
        app.save_scene(OUT/'scene-a.json')
        legacy = json.loads((OUT/'scene-a.json').read_text())
        legacy.pop('shot_camera')
        legacy.update(version=2, objects=[], groups=[], selected_ids=[], primary_selection_id=None,
                      selected_group_id=None, ground_visible=True, show_grid=False)
        (OUT/'scene-b-legacy.json').write_text(json.dumps(legacy))
        capture('photo-before')
        return []
    if f == 22:
        return [move(c), pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=3), button(pygame.MOUSEBUTTONDOWN,2)]
    if f == 23: return [move((c[0]+40,c[1]+20),(0,1,0))]
    if f == 24: return [button(pygame.MOUSEBUTTONUP,2)]
    if f == 25:
        capture('photo-after-events')
    if f == 26:
        app.show_grid=False
        capture('photo-grid-off')
    if f == 27:
        app.load_scene(OUT/'scene-b-legacy.json')
    if f == 28:
        app.load_scene(OUT/'scene-a.json')
    if f == 29:
        app.set_camera_view(True)
        capture('photo-after-scene-switch')
    if f == 30:
        app.set_camera_view(False)
        state['distance_before'] = app.viewer.controller.distance
        return [move(center())]
    if f == 31:
        return [pygame.event.Event(pygame.MOUSEWHEEL,x=0,y=1)]
    if f == 33:
        state['box'] = app.scene.root_entities[0]
        prepare('move')
        app.focus_selected()
        state['gizmo_start'] = app.gizmo.geometry(app.viewport_rect)[1]
        return [move(state['gizmo_start'])]
    if f == 34:
        state['gizmo_start'] = app.gizmo.geometry(app.viewport_rect)[1]
        return [move(state['gizmo_start']), button(pygame.MOUSEBUTTONDOWN)]
    if f == 35: return [move(state['gizmo_start']+[60,0], (1,0,0))]
    if f == 36: return [escape()]
    if f == 37: return [escape(pygame.KEYUP), button(pygame.MOUSEBUTTONUP)]
    if args.panel_release:
        if f == 40:
            prepare('move')
            app.focus_selected()
            state['gizmo_start'] = app.gizmo.geometry(app.viewport_rect)[1]
            return [move(state['gizmo_start'])]
        if f == 41:
            state['gizmo_start'] = app.gizmo.geometry(app.viewport_rect)[1]
            return [move(state['gizmo_start']), button(pygame.MOUSEBUTTONDOWN)]
        if f == 42: return [move(state['gizmo_start']+[60,0], (1,0,0))]
        if f == 43: return [move((30,500), (1,0,0))]
        if f == 44: return [button(pygame.MOUSEBUTTONUP)]
        if f == 45:
            app.undo()
            return [button(pygame.MOUSEBUTTONUP)]
        if f == 46: app.redo()
    return []

def inspect():
    f, app, box, ui = state['frame'], state['app'], state['box'], state['ui']
    state['trace'].append(dict(frame=f, pos=box.pos.tolist(), gizmo=app.gizmo.drag is not None,
        surface=app.surface_drag is not None, transaction=app.commands.active_transaction,
        undo=app.commands.undo_count, mouse_captured=ui.mouse_captured, viewport_hovered=ui.viewport_hovered))
    if app.gizmo.drag is not None:
        state['trace'][-1]['drag_axis'] = str(app.gizmo.drag['axis'])
    if f == 2: check('Gizmo starts through actual mouse click', app.gizmo.drag is not None)
    if f == 3: check('Gizmo moves subject in viewport', not np.allclose(box.pos,state['initial']))
    if f == 4: check('Gizmo crossing panel is captured by real ImGui', ui.mouse_captured)
    if f == 5:
        check('Gizmo Escape after panel crossing restores position', np.allclose(box.pos,state['initial']))
        check('Gizmo Escape after panel crossing leaves no history', app.commands.undo_count==0)
    if f == 9: check('Surface drag starts through mouse click', app.surface_drag is not None)
    if f == 10: check('Surface drag moves subject', not np.allclose(box.pos,state['initial']))
    if f == 11: check('Surface crossing panel retains transaction', ui.mouse_captured and app.commands.active_transaction)
    if f == 12:
        check('Surface Escape after panel crossing restores pose', np.allclose(box.pos,state['initial']))
        check('Surface Escape leaves no history/transaction', app.commands.undo_count==0 and not app.commands.active_transaction)
    if f == 19:
        check('Surface release over panel commits once', app.commands.undo_count==1 and not app.commands.active_transaction and app.surface_drag is None)
    if f == 25:
        check('Shot pose/lens isolate wheel and middle drag', app.shot_camera.to_dict()==state['shot_before'])
        check('Editor pose unchanged during Camera View events', np.array_equal(app.viewer.camera.view_matrix,state['editor_before']))
    if f == 27:
        check('Legacy scene clears old shot and exits Camera View', app.shot_camera is None and not app.camera_view)
        check('Legacy ground flag creates no phantom floor', not app.scene.root_entities and not app.scene.get_flat_render_list())
        check('Legacy scene restores Grid Off', not app.show_grid)
    if f == 28:
        check('Returning scene restores exact shot', app.shot_camera.to_dict()==state['shot_before'])
        check('Returning scene restores explicit floor and Grid On', len(app.scene.root_entities)==2 and app.show_grid)
    if f == 31: check('Wheel works again after returning to Editor View', app.viewer.controller.distance != state['distance_before'])
    if f == 34: check('Control: in-viewport Gizmo starts', app.gizmo.drag is not None)
    if f == 35: check('Control: in-viewport Gizmo moves', not np.allclose(box.pos,state['initial']))
    if f == 36:
        check('Control: in-viewport Gizmo Escape restores pose', np.allclose(box.pos,state['initial']))
        check('Control: in-viewport Gizmo Escape leaves no history', app.commands.undo_count==0)
    if args.panel_release:
        if f == 41: check('Gizmo release journey starts', app.gizmo.drag is not None)
        if f == 42:
            state['release_position'] = box.pos.copy()
            check('Gizmo release journey moves', not np.allclose(box.pos,state['initial']))
        if f == 43:
            check('Gizmo held over panel retains transaction', ui.mouse_captured and app.gizmo.drag is not None and app.commands.active_transaction)
            check('Gizmo panel crossing pauses geometry', np.array_equal(box.pos,state['release_position']))
            check('Gizmo panel crossing has no early Undo', app.commands.undo_count==0)
        if f == 44:
            check('Gizmo release over panel commits exactly once', app.gizmo.drag is None and not app.commands.active_transaction and app.commands.undo_count==1)
        if f == 45:
            check('Gizmo duplicate release creates no Undo and Undo restores', app.commands.undo_count==0 and np.array_equal(box.pos,state['initial']))
        if f == 46:
            check('Gizmo Redo restores committed panel-release pose', app.commands.undo_count==1 and np.array_equal(box.pos,state['release_position']))
    if f in (3,4,5,11,12,19,27,28,34,35,43,44):
        size=pygame.display.get_window_size()
        rgb=gl.glReadPixels(0,0,*size,gl.GL_RGB,gl.GL_UNSIGNED_BYTE)
        pygame.image.save(pygame.image.fromstring(rgb,size,'RGB',True),str(OUT/('ui-frame-%02d.png'%f)))
    check('GL frame %02d'%f, gl.glGetError()==gl.GL_NO_ERROR)
    real_flip()
    state['frame']+=1

with patch.object(editor,'Editor',App), patch('mini3d.editor_ui.EditorUI',UI), \
     patch.object(pygame.event,'get',events), patch.object(pygame.display,'flip',inspect), \
     patch.object(pygame.key,'get_mods',return_value=0), patch.object(editor,'capture_png',capture_wrapper):
    editor.run(initial_asset=None,frames=47 if args.panel_release else 39,hidden=True)

def pixels(name):
    return pygame.surfarray.array3d(pygame.image.load(str(OUT/(name+'.png'))))

reference = pixels('photo-before')
for name in ('photo-after-events','photo-grid-off','photo-after-scene-switch'):
    check('Photo pixel identity: '+name,np.array_equal(reference,pixels(name)))
result={'checks':state['checks'],'trace':state['trace'],
        'failed':[c for c in state['checks'] if not c['passed']]}
(OUT/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'total':len(result['checks']),'failed':result['failed']},indent=2))

sys.exit(1 if result["failed"] else 0)
