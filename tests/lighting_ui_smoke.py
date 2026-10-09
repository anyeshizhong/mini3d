"""Exercise real ImGui lighting inputs through SDL mouse/keyboard events."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import imgui
import numpy as np
import pygame
from OpenGL import GL as gl
import editor_app
from mini3d import editor
from mini3d.editor_ui import EditorUI
from mini3d.lighting import lighting_state
from mini3d.render_target import RenderTarget


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    state = dict(frame=0, items={}, pictures={}, checks=0)
    real_get, real_flip = pygame.event.get, pygame.display.flip
    real_button, real_float, real_float3 = imgui.button, imgui.input_float, imgui.input_float3

    class App(editor.Editor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.assets = [dict(name='Lighting PBR cube', path=str(ROOT/'docs/lighting/pbr-cube.gltf'))]
            self.show_grid = False
            self.set_lighting(mode='Studio', direction=[1, 0, 0], diffuse=1, ambient=0)
            state['app'] = self

    class UI(EditorUI):
        def __init__(self, *args):
            super().__init__(*args)
            state['ui'] = self

    class Target(RenderTarget):
        def __init__(self):
            super().__init__()
            state.setdefault('target', self)

    def remember(label, components=1):
        low, high = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        # Input width is 220; component fields are equally sized.
        if components == 3:
            for i in range(3):
                state['items']['direction'+str(i)] = (low.x+(i+.5)*220/3, (low.y+high.y)/2)
        else:
            state['items'][label] = (low.x+min(40, (high.x-low.x)/2), (low.y+high.y)/2)

    def button(label, *args, **kwargs):
        result = real_button(label, *args, **kwargs)
        remember(label)
        return result

    def number(label, *args, **kwargs):
        result = real_float(label, *args, **kwargs)
        if label in ('Direct strength', 'Ambient strength'):
            remember(label)
        return result

    def vector(label, *args, **kwargs):
        result = real_float3(label, *args, **kwargs)
        if label == '##light_direction':
            remember(label, 3)
        return result

    actions = [('Lighting...', None), ('direction0', '0'), ('direction1', '-1'),
               ('direction0', '0'), ('direction2', '0.5'), ('Direct strength', '0.25'),
               ('Ambient strength', '0.2')]

    def key(kind, code, text=''):
        return pygame.event.Event(kind, key=code, unicode=text, mod=0)

    def events():
        real_get()
        offset = state['frame']-3
        if offset < 0:
            return []
        index, phase = divmod(offset, 8)
        if index >= len(actions):
            return []
        label, text = actions[index]
        point = tuple(map(int, state['items'][label]))
        if phase == 0:
            return [pygame.event.Event(pygame.MOUSEMOTION, pos=point, rel=(0, 0), buttons=(0, 0, 0)),
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=point, button=1)]
        if phase == 1:
            return [pygame.event.Event(pygame.MOUSEBUTTONUP, pos=point, button=1)]
        if text is not None:
            if phase == 2:
                return [key(pygame.KEYDOWN, pygame.K_LCTRL), key(pygame.KEYDOWN, pygame.K_a)]
            if phase == 3:
                return [key(pygame.KEYUP, pygame.K_a), key(pygame.KEYUP, pygame.K_LCTRL),
                        key(pygame.KEYDOWN, pygame.K_0, text)]
            if phase == 4:
                return [key(pygame.KEYUP, pygame.K_0), key(pygame.KEYDOWN, pygame.K_RETURN)]
            if phase == 5:
                return [key(pygame.KEYUP, pygame.K_RETURN)]
        return []

    def pixels():
        target = state['target']
        with_target = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING))
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, target.framebuffer)
        width, height = state['app'].viewport_rect[2:]
        data = gl.glReadPixels(0, 0, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, with_target)
        return np.frombuffer(data, np.uint8).copy()

    def inspect():
        frame = state['frame']
        offset = frame-3
        index, phase = divmod(offset, 8)
        if frame == 2:
            state['before'] = lighting_state(state['app'].scene)
            state['initial_pixels'] = pixels()
        if offset >= 0 and index < len(actions) and phase == 6:
            current = lighting_state(state['app'].scene)
            if index == 0:
                assert state['ui']._show_lighting
            elif index == 1:
                assert current == state['before'], current
                assert 'nonzero' in state['ui'].lighting_error
                np.testing.assert_array_equal(pixels(), state['initial_pixels'])
            else:
                expected = {2: [1, -1, 0], 3: [0, -1, 0], 4: [0, -1, .5]}
                assert current['mode'] == 'Scene', current
                if index in expected:
                    np.testing.assert_allclose(current['direction'], expected[index])
                if index == 5:
                    assert current['diffuse'] == .25, current
                if index == 6:
                    assert abs(current['ambient']-.2) < 1e-6, current
                assert not state['ui'].lighting_error
                assert np.any(pixels() != state['initial_pixels'])
            if index in (0, 1, 6):
                size = pygame.display.get_window_size()
                data = gl.glReadPixels(0, 0, *size, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
                image = pygame.image.fromstring(data, size, 'RGB', True)
                pygame.image.save(image, str(output/('ui-'+str(index)+'.png')))
            state['checks'] += 1
        assert gl.glGetError() == gl.GL_NO_ERROR
        real_flip()
        state['frame'] += 1

    with patch.object(editor, 'Editor', App), patch('mini3d.editor_ui.EditorUI', UI), \
            patch('mini3d.render_target.RenderTarget', Target), \
            patch.object(imgui, 'button', button), patch.object(imgui, 'input_float', number), \
            patch.object(imgui, 'input_float3', vector), patch.object(pygame.event, 'get', events), \
            patch.object(pygame.display, 'flip', inspect):
        editor_app.main(['--asset', '1', '--hidden', '--frames', str(3+8*len(actions))])
    assert state['checks'] == len(actions)
    print('PASS: real Lighting button, X/Y/Z inputs, direct/ambient inputs; zero-vector rejection'
          ' preserves all parameters and pixels; valid edits immediately preview Scene Lighting')


if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT/'captures/lighting-v1-ui')
