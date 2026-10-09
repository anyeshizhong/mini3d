"""Directional depth pass, adapted from iamyoukou/shadowMapping (MIT).

Copyright (c) 2021, Jiang Ye. See third_party/shadowMapping/LICENSE and
docs/shadow-mapping-v1.md for the pinned source and adaptation mapping.
No Camera near/far dependency; input consists only of real scene entities.
"""
from itertools import product

import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader

from .lighting import scene_light_direction


# Adapted light-space divide/remap, depth comparison and 3x3 PCF from
# shader/fsScene.glsl. Visibility multiplies direct radiance, never scene color.
SHADOW_GLSL = """
uniform bool shadowEnabled, shadowPCF;
uniform sampler2D shadowDepth;
uniform mat4 shadowMatrix;
uniform float shadowBias;
float shadowVisibility(vec3 world, vec3 normal, vec3 light) {
    if (!shadowEnabled) return 1.0;
    vec4 p = shadowMatrix * vec4(world, 1.0);
    vec3 q = p.xyz / p.w * 0.5 + 0.5;
    if (any(lessThan(q, vec3(0.0))) || any(greaterThan(q, vec3(1.0)))) return 1.0;
    float bias = shadowBias * (1.0 + 4.0 * (1.0 - max(dot(normal, light), 0.0)));
    vec2 texel = 1.0 / vec2(textureSize(shadowDepth, 0));
    float visibility = 0.0;
    int radius = shadowPCF ? 1 : 0;
    for (int x = -radius; x <= radius; ++x)
        for (int y = -radius; y <= radius; ++y) {
            float closest = texture(shadowDepth, q.xy + vec2(x,y)*texel).r;
            visibility += q.z - bias <= closest ? 1.0 : 0.0;
        }
    return visibility / (shadowPCF ? 9.0 : 1.0);
}
"""

DEPTH_VERTEX = """#version 330 core
layout(location=0) in vec3 position;
layout(location=2) in vec2 texcoord;
layout(location=3) in vec4 color;
uniform mat4 model, lightMatrix;
out vec2 uv;
out float alpha;
void main() {
    uv = texcoord; alpha = color.a;
    gl_Position = lightMatrix * model * vec4(position, 1.0);
}
"""
DEPTH_FRAGMENT = """#version 330 core
in vec2 uv;
in float alpha;
uniform bool alphaMask, hasBase;
uniform float baseAlpha, cutoff;
uniform sampler2D baseMap;
void main() {
    if (alphaMask) {
        float a = baseAlpha * alpha;
        if (hasBase) a *= texture(baseMap, uv).a;
        if (a < cutoff) discard;
    }
}
"""


def light_matrix(entities, direction):
    """Fit orthographic clip space to cached local AABBs, independent of Camera."""
    light = np.array(direction, dtype=np.float64, copy=True)
    light /= np.max(np.abs(light))
    light /= np.linalg.norm(light)
    up = np.eye(3)[np.argmin(np.abs(light))]
    right = np.cross(up, light)
    right /= np.linalg.norm(right)
    rotation = np.stack((right, np.cross(light, right), light))
    boxes = []
    for entity in entities:
        bounds = getattr(entity.model, 'bounds', None)
        if bounds is None:
            continue
        corners = np.array(list(product(*zip(*bounds))), dtype=np.float64)
        world = np.asarray(entity.world_matrix, dtype=np.float64)
        boxes.append((corners @ world[:3,:3].T + world[:3,3]) @ rotation.T)
    if not boxes:
        return None
    points = np.concatenate(boxes)
    lo, hi = points.min(axis=0), points.max(axis=0)
    extent = hi-lo
    margin = max(float(extent.max()) * .02, 1e-12)
    lo -= margin
    hi += margin
    # Light camera looks down -Z: points towards +light are closer (depth 0).
    scale = 2 / (hi-lo)
    scale[2] *= -1
    matrix = np.eye(4)
    matrix[:3,:3] = scale[:,None] * rotation
    matrix[:3,3] = -scale * ((lo+hi)*.5)
    return matrix


class ShadowMap:
    """One lazy depth texture/FBO. GPU geometry is owned by existing renderers."""
    UNIT = 7  # MaterialRenderer uses units 0..6.

    def __init__(self):
        self.fbo = self.texture = self.program = self.size = 0
        self.matrix = None

    def _allocate(self, size):
        if self.size == size:
            return
        if size > int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)):
            raise ValueError('Shadow resolution exceeds GL_MAX_TEXTURE_SIZE')
        self.close()
        try:
            self.program = compileProgram(compileShader(DEPTH_VERTEX, gl.GL_VERTEX_SHADER),
                                          compileShader(DEPTH_FRAGMENT, gl.GL_FRAGMENT_SHADER))
            self.texture = int(gl.glGenTextures(1))
            gl.glActiveTexture(gl.GL_TEXTURE0+self.UNIT)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
            # Port of src/main.cpp depth attachment setup; depth-only FBO.
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_DEPTH_COMPONENT24, size, size,
                            0, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT, None)
            for param in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, param, gl.GL_NEAREST)
            for param in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, param, gl.GL_CLAMP_TO_BORDER)
            gl.glTexParameterfv(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_BORDER_COLOR, np.ones(4,np.float32))
            self.fbo = int(gl.glGenFramebuffers(1))
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                      gl.GL_TEXTURE_2D, self.texture, 0)
            gl.glDrawBuffer(gl.GL_NONE)
            gl.glReadBuffer(gl.GL_NONE)
            if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('Incomplete shadow depth framebuffer')
            self.size = size
        except Exception:
            self.close()
            raise

    def render(self, entities, scene, renderer):
        from .material_renderer import MaterialRenderer
        matrix = light_matrix(entities, scene_light_direction(scene))
        if matrix is None:
            self.matrix = None
            return
        state = MaterialRenderer._save_state()
        draw = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
        viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
        clear = float(gl.glGetDoublev(gl.GL_DEPTH_CLEAR_VALUE))
        depth_range = gl.glGetDoublev(gl.GL_DEPTH_RANGE)
        try:
            self._allocate(scene.shadow_resolution)
            self.matrix = matrix
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
            gl.glViewport(0, 0, self.size, self.size)
            for cap in (gl.GL_SCISSOR_TEST, gl.GL_STENCIL_TEST, gl.GL_BLEND,
                        gl.GL_CULL_FACE, gl.GL_POLYGON_OFFSET_FILL, gl.GL_RASTERIZER_DISCARD):
                gl.glDisable(cap)
            # Upstream slope-scale raster bias; no model displacement or front-face culling.
            gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(2.0, 4.0)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LESS)
            gl.glDepthMask(True)
            gl.glDepthRange(0, 1)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glClearDepth(1)
            gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
            gl.glUseProgram(self.program)
            loc = lambda name: gl.glGetUniformLocation(self.program, name)
            gl.glUniformMatrix4fv(loc('lightMatrix'),1,gl.GL_TRUE,np.asarray(matrix,np.float32))
            gl.glUniform1i(loc('baseMap'),0)
            for entity in entities:
                material = getattr(entity.model, 'material', None)
                if material is not None and material.get('alphaMode') == 'BLEND':
                    continue  # No physically meaningful transmissive shadow in V1.
                masked = material is not None and material.get('alphaMode') == 'MASK'
                gl.glUniform1i(loc('alphaMask'),masked)
                if material is not None:
                    mr = renderer.material_renderer
                    mesh = mr._mesh(entity.model)
                    vao, count = mesh[1], mesh[4]
                    if masked:
                        tex = material.get('textures',{}).get('baseColor')
                        gl.glUniform1i(loc('hasBase'),tex is not None)
                        gl.glUniform1f(loc('baseAlpha'),material.get('pbrMetallicRoughness',{}).get('baseColorFactor',[1,1,1,1])[3])
                        gl.glUniform1f(loc('cutoff'),material.get('alphaCutoff',.5))
                        gl.glActiveTexture(gl.GL_TEXTURE0)
                        gl.glBindTexture(gl.GL_TEXTURE_2D,mr._texture(tex) if tex else 0)
                else:
                    gpu = renderer._get_gpu(entity.model)
                    vao, count = gpu.vao, gpu.count
                gl.glUniformMatrix4fv(loc('model'),1,gl.GL_TRUE,np.asarray(entity.world_matrix,np.float32))
                gl.glBindVertexArray(vao)
                gl.glDrawElements(gl.GL_TRIANGLES,count,gl.GL_UNSIGNED_INT,None)
        finally:
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER,draw)
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,read)
            gl.glViewport(*viewport)
            gl.glClearDepth(clear)
            gl.glDepthRange(*depth_range)
            MaterialRenderer._restore_state(state)

    @staticmethod
    def bind(program, shadow, scene):
        """Caller saves/restores unit 7; an absent map always means full light."""
        loc = lambda name: gl.glGetUniformLocation(program, name)
        active = shadow is not None and shadow.matrix is not None
        gl.glUniform1i(loc('shadowEnabled'),active)
        gl.glUniform1i(loc('shadowDepth'),ShadowMap.UNIT)
        if active:
            gl.glUniformMatrix4fv(loc('shadowMatrix'),1,gl.GL_TRUE,np.asarray(shadow.matrix,np.float32))
            gl.glUniform1f(loc('shadowBias'),scene.shadow_bias)
            gl.glUniform1i(loc('shadowPCF'),scene.shadow_pcf)
            gl.glActiveTexture(gl.GL_TEXTURE0+ShadowMap.UNIT)
            gl.glBindTexture(gl.GL_TEXTURE_2D,shadow.texture)

    def save_depth_png(self, path):
        """Raw orthographic depth [0,1] as grayscale, white = empty/far."""
        import pygame
        if not self.fbo:
            raise RuntimeError('Render a shadow map first')
        read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
        names = (gl.GL_PACK_ALIGNMENT,gl.GL_PACK_ROW_LENGTH,gl.GL_PACK_SKIP_ROWS,gl.GL_PACK_SKIP_PIXELS)
        previous = [int(gl.glGetIntegerv(n)) for n in names]
        try:
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,self.fbo)
            for name, value in zip(names,(1,0,0,0)):
                gl.glPixelStorei(name,value)
            depth = np.asarray(gl.glReadPixels(0,0,self.size,self.size,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT),np.float32).reshape(self.size,self.size)
            rgb = np.repeat(np.round(np.clip(depth,0,1)*255).astype(np.uint8)[:,:,None],3,axis=2)
            pygame.image.save(pygame.image.fromstring(rgb.tobytes(),(self.size,self.size),'RGB',True),str(path))
            return depth.copy()
        finally:
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,read)
            for name,value in zip(names,previous):
                gl.glPixelStorei(name,value)

    def close(self):
        if self.fbo:
            gl.glDeleteFramebuffers(1,[self.fbo])
        if self.texture:
            gl.glDeleteTextures([self.texture])
        if self.program:
            gl.glDeleteProgram(self.program)
        self.fbo = self.texture = self.program = self.size = 0
        self.matrix = None
