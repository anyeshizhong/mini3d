"""Fixed, offline-filtered CC0 studio IBL; no baking on the render path.

Resource provenance and split-sum approximation: docs/renderer-v2/quality-q1.md.
"""
from numbers import Real
from pathlib import Path

import numpy as np

RESOURCE = Path(__file__).parent / 'resources' / 'ibl' / 'neutral.npz'


def environment_state(scene):
    return dict(enabled=scene.environment_enabled, intensity=scene.environment_intensity)


def update_environment(scene, enabled=None, intensity=None):
    candidate = environment_state(scene)
    if enabled is not None:
        candidate['enabled'] = enabled
    if intensity is not None:
        candidate['intensity'] = intensity
    if not isinstance(candidate['enabled'], bool):
        raise ValueError('enabled must be boolean')
    value = candidate['intensity']
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('intensity must be finite and between 0 and 100')
    scene.environment_enabled = candidate['enabled']
    scene.environment_intensity = float(value)
    return environment_state(scene)


def load_environment():
    """Read only bundled numeric arrays; RGB is linear radiance, LUT is linear RG."""
    with np.load(RESOURCE, allow_pickle=False) as data:
        arrays = {name: np.ascontiguousarray(data[name], dtype=np.float16) for name in data.files}
    expected = dict(diffuse=(6,32,32,3), brdf=(256,256,2))
    expected.update({'specular_'+str(i): (6,256 >> i,256 >> i,3) for i in range(9)})
    if set(arrays) != set(expected) or any(arrays[k].shape != shape or
            not np.isfinite(arrays[k]).all() or arrays[k].min() < 0 for k, shape in expected.items()):
        raise ValueError('Invalid bundled IBL resource')
    return arrays


class EnvironmentMap:
    """Own three GL textures. Created lazily once per MaterialRenderer/context."""
    mip_count = 9

    def __init__(self):
        from OpenGL import GL as gl
        arrays = load_environment()
        self.texture_bytes = sum(a.nbytes for a in arrays.values())
        self.handles = [int(x) for x in gl.glGenTextures(3)]
        parameters = (gl.GL_UNPACK_ALIGNMENT, gl.GL_UNPACK_ROW_LENGTH,
                      gl.GL_UNPACK_SKIP_ROWS, gl.GL_UNPACK_SKIP_PIXELS)
        previous = [int(gl.glGetIntegerv(p)) for p in parameters]
        try:
            for p, v in zip(parameters, (1,0,0,0)):
                gl.glPixelStorei(p, v)
            for unit, handle, name, levels in ((8,self.handles[0],'diffuse',1),
                                              (9,self.handles[1],'specular_',9)):
                gl.glActiveTexture(gl.GL_TEXTURE0+unit)
                gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, handle)
                for level in range(levels):
                    a = arrays[name+str(level) if levels > 1 else name]
                    for face in range(6):
                        gl.glTexImage2D(gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X+face, level, gl.GL_RGB16F,
                                        a.shape[2], a.shape[1], 0, gl.GL_RGB, gl.GL_HALF_FLOAT, a[face])
                gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_MIN_FILTER,
                                    gl.GL_LINEAR_MIPMAP_LINEAR if levels > 1 else gl.GL_LINEAR)
                gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
                gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_MAX_LEVEL, levels-1)
                for axis in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T, gl.GL_TEXTURE_WRAP_R):
                    gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, axis, gl.GL_CLAMP_TO_EDGE)
            gl.glActiveTexture(gl.GL_TEXTURE0+10)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.handles[2])
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RG16F, 256, 256, 0,
                            gl.GL_RG, gl.GL_HALF_FLOAT, arrays['brdf'])
            for p, v in ((gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR), (gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR),
                         (gl.GL_TEXTURE_WRAP_S,gl.GL_CLAMP_TO_EDGE), (gl.GL_TEXTURE_WRAP_T,gl.GL_CLAMP_TO_EDGE)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, p, v)
        except Exception:
            self.close()
            raise
        finally:
            for p, v in zip(parameters, previous):
                gl.glPixelStorei(p, v)

    def bind(self):
        from OpenGL import GL as gl
        for unit, target, handle in ((8,gl.GL_TEXTURE_CUBE_MAP,self.handles[0]),
                                     (9,gl.GL_TEXTURE_CUBE_MAP,self.handles[1]),
                                     (10,gl.GL_TEXTURE_2D,self.handles[2])):
            gl.glActiveTexture(gl.GL_TEXTURE0+unit)
            gl.glBindTexture(target, handle)
        gl.glEnable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)

    def close(self):
        from OpenGL import GL as gl
        if self.handles:
            gl.glDeleteTextures(self.handles)
            self.handles = []
