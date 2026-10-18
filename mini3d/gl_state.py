"""GL state preservation shared by material, selection and shadow passes.

These helpers borrow the current context and own no GPU resources.
"""
import numpy as np
from contextlib import contextmanager
from OpenGL import GL as gl


@contextmanager
def preserved_pixel_pack(reset=False):
    """Preserve pack state across readback and PyOpenGL texture allocation."""
    names = ('ALIGNMENT', 'ROW_LENGTH', 'SKIP_ROWS', 'SKIP_PIXELS',
             'IMAGE_HEIGHT', 'SKIP_IMAGES', 'SWAP_BYTES', 'LSB_FIRST')
    state = {name: int(gl.glGetIntegerv(getattr(gl, 'GL_PACK_' + name)))
             for name in names}
    buffer = int(gl.glGetIntegerv(gl.GL_PIXEL_PACK_BUFFER_BINDING))
    try:
        if reset:
            gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, 0)
            for name in names:
                gl.glPixelStorei(getattr(gl, 'GL_PACK_' + name), 1 if name == 'ALIGNMENT' else 0)
        yield
    finally:
        for name, value in state.items():
            gl.glPixelStorei(getattr(gl, 'GL_PACK_' + name), value)
        gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, buffer)


def read_rgb(x, y, width, height):
    """Read tightly packed CPU bytes; a caller PBO must not reinterpret them."""
    with preserved_pixel_pack(reset=True):
        return gl.glReadPixels(x, y, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)


def save_state(texture_units=13, all_cubemaps=False):
    integer_names = ("CURRENT_PROGRAM","VERTEX_ARRAY_BINDING","ARRAY_BUFFER_BINDING",
                     "ACTIVE_TEXTURE","DEPTH_FUNC","CULL_FACE_MODE","FRONT_FACE",
                     "BLEND_SRC_RGB","BLEND_DST_RGB","BLEND_SRC_ALPHA","BLEND_DST_ALPHA",
                     "BLEND_EQUATION_RGB","BLEND_EQUATION_ALPHA","STENCIL_CLEAR_VALUE",
                     "STENCIL_FUNC","STENCIL_REF","STENCIL_VALUE_MASK","STENCIL_WRITEMASK",
                     "STENCIL_FAIL","STENCIL_PASS_DEPTH_FAIL","STENCIL_PASS_DEPTH_PASS",
                     "STENCIL_BACK_FUNC","STENCIL_BACK_REF","STENCIL_BACK_VALUE_MASK",
                     "STENCIL_BACK_WRITEMASK","STENCIL_BACK_FAIL","STENCIL_BACK_PASS_DEPTH_FAIL",
                     "STENCIL_BACK_PASS_DEPTH_PASS")
    state = {name:int(gl.glGetIntegerv(getattr(gl,"GL_"+name))) for name in integer_names}
    state["enabled"] = {cap:bool(gl.glIsEnabled(cap)) for cap in
                        (gl.GL_DEPTH_TEST,gl.GL_CULL_FACE,gl.GL_BLEND,gl.GL_FRAMEBUFFER_SRGB,
                         gl.GL_STENCIL_TEST,gl.GL_SCISSOR_TEST,gl.GL_POLYGON_OFFSET_FILL,gl.GL_RASTERIZER_DISCARD,
                         gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)}
    state["polygon_offset"] = (float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_FACTOR)),
                               float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_UNITS)))
    state["depth_mask"] = bool(gl.glGetBooleanv(gl.GL_DEPTH_WRITEMASK))
    state["color_mask"] = np.asarray(gl.glGetBooleanv(gl.GL_COLOR_WRITEMASK)).reshape(-1)
    state["polygon"] = np.asarray(gl.glGetIntegerv(gl.GL_POLYGON_MODE)).reshape(-1)
    state["textures"] = []
    state["texture_arrays"] = []
    state["cubemaps"] = []
    state["samplers"] = []
    for unit in range(texture_units):
        gl.glActiveTexture(gl.GL_TEXTURE0+unit)
        state["textures"].append(int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D)))
        state["texture_arrays"].append(int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D_ARRAY)))
        state["samplers"].append(int(gl.glGetIntegerv(gl.GL_SAMPLER_BINDING)))
        if all_cubemaps or unit in (8,9):
            state["cubemaps"].append((unit,int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_CUBE_MAP))))
    gl.glActiveTexture(state["ACTIVE_TEXTURE"])
    return state

def restore_state(state):
    for cap, enabled in state["enabled"].items():
        (gl.glEnable if enabled else gl.glDisable)(cap)
    gl.glDepthMask(state["depth_mask"])
    gl.glPolygonOffset(*state["polygon_offset"])
    gl.glColorMask(*[bool(value) for value in state["color_mask"]])
    gl.glClearStencil(state["STENCIL_CLEAR_VALUE"])
    for face, prefix in ((gl.GL_FRONT,"STENCIL_"),(gl.GL_BACK,"STENCIL_BACK_")):
        gl.glStencilMaskSeparate(face,state[prefix+"WRITEMASK"])
        gl.glStencilFuncSeparate(face,state[prefix+"FUNC"],state[prefix+"REF"],state[prefix+"VALUE_MASK"])
        gl.glStencilOpSeparate(face,state[prefix+"FAIL"],state[prefix+"PASS_DEPTH_FAIL"],state[prefix+"PASS_DEPTH_PASS"])
    gl.glDepthFunc(state["DEPTH_FUNC"])
    gl.glCullFace(state["CULL_FACE_MODE"])
    gl.glFrontFace(state["FRONT_FACE"])
    gl.glBlendFuncSeparate(state["BLEND_SRC_RGB"],state["BLEND_DST_RGB"],
                           state["BLEND_SRC_ALPHA"],state["BLEND_DST_ALPHA"])
    gl.glBlendEquationSeparate(state["BLEND_EQUATION_RGB"],state["BLEND_EQUATION_ALPHA"])
    gl.glPolygonMode(gl.GL_FRONT_AND_BACK,int(state["polygon"][0]))
    gl.glUseProgram(state["CURRENT_PROGRAM"])
    gl.glBindVertexArray(state["VERTEX_ARRAY_BINDING"])
    gl.glBindBuffer(gl.GL_ARRAY_BUFFER,state["ARRAY_BUFFER_BINDING"])
    for unit, texture in enumerate(state["textures"]):
        gl.glActiveTexture(gl.GL_TEXTURE0+unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D,texture)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY,state["texture_arrays"][unit])
        gl.glBindSampler(unit,state["samplers"][unit])
    for unit, texture in state["cubemaps"]:
        gl.glActiveTexture(gl.GL_TEXTURE0+unit)
        gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP,texture)
    gl.glActiveTexture(state["ACTIVE_TEXTURE"])

