"""Deterministic depth-aware thin-lens post-process; borrows a desktop GL context.

Lens equation: NVIDIA GPU Gems 3, chapter 28 (see docs/depth-of-field.md).
The renderer owns these resources. Only resolved color is replaced; depth and
stencil stay available for selection and readback. No CPU frame readbacks.
"""
import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from .gl_state import save_state, restore_state
from .render_target import RenderTarget

VERTEX = '''#version 330 core
out vec2 uv;
void main() {
    vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);
    uv=p; gl_Position=vec4(p*2.0-1.0,0.0,1.0);
}'''

FRAGMENT = '''#version 330 core
in vec2 uv;
out vec4 fragColor;
uniform sampler2D colorMap, depthMap;
uniform vec2 frameSize;
uniform float nearPlane, farPlane, focusDistance, cocScale, radiusLimit;
float viewDepth(vec2 p) {
    float d=texture(depthMap,p).r;
    return nearPlane*farPlane/(farPlane-d*(farPlane-nearPlane));
}
float coc(float depth) {
    return clamp(cocScale*(depth-focusDistance)/depth,-radiusLimit,radiusLimit);
}
vec3 decode(vec3 c) {
    return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));
}
vec3 encode(vec3 c) {
    return mix(c*12.92,1.055*pow(max(c,vec3(0)),vec3(1.0/2.4))-.055,step(vec3(.0031308),c));
}
void main() {
    vec4 centre=texture(colorMap,uv);
    float z=viewDepth(uv), signedRadius=coc(z), radius=abs(signedRadius);
    if(radius<=.5) { fragColor=centre; return; }
    vec3 sum=decode(centre.rgb);
    float weight=1.0;
    // Equal-area golden-angle disk, stable across frames and PNG exports.
    for(int i=0;i<48;i++) {
        float r=sqrt((float(i)+.5)/48.0)*radius;
        float angle=float(i)*2.39996323;
        vec2 p=clamp(uv+vec2(cos(angle),sin(angle))*r/frameSize,
                     .5/frameSize,vec2(1)-.5/frameSize);
        float nz=viewDepth(p), nr=coc(nz);
        // Keep focused foreground silhouettes out of a blurred background,
        // and prevent a near object gathering the hidden background behind it.
        float w=1.0;
        if(nz<z*.99 && abs(nr)<r) w=0.0;
        if(nz>z*1.01 && signedRadius<0.0) w=0.0;
        sum+=decode(texture(colorMap,p).rgb)*w; weight+=w;
    }
    vec3 blurred=encode(sum/weight);
    fragColor=vec4(mix(centre.rgb,blurred,smoothstep(.5,1.5,radius)),centre.a);
}'''


class DepthOfField:
    def __init__(self):
        self.program = compileProgram(compileShader(VERTEX, gl.GL_VERTEX_SHADER),
                                      compileShader(FRAGMENT, gl.GL_FRAGMENT_SHADER))
        self.vao = int(gl.glGenVertexArrays(1))
        self.depth_texture = int(gl.glGenTextures(1))
        self.output = RenderTarget()
        self.size = None

    def apply(self, target, camera):
        """Filter a resolved FBO, preserving all touched caller GL state."""
        state = save_state()
        read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
        draw = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        viewport = np.array(gl.glGetIntegerv(gl.GL_VIEWPORT))
        try:
            width, height = target.width, target.height
            self.output.resize(width, height, samples=1)
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
            gl.glActiveTexture(gl.GL_TEXTURE1)
            gl.glBindSampler(1, 0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.depth_texture)
            if self.size != (width, height):
                gl.glCopyTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_DEPTH_COMPONENT24,
                                    0, 0, width, height, 0)
                for name in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
                    gl.glTexParameteri(gl.GL_TEXTURE_2D, name, gl.GL_NEAREST)
                for name in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
                    gl.glTexParameteri(gl.GL_TEXTURE_2D, name, gl.GL_CLAMP_TO_EDGE)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_COMPARE_MODE, gl.GL_NONE)
                self.size = (width, height)
            else:
                gl.glCopyTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, 0, 0, width, height)
            self.output.bind()
            for cap in (gl.GL_DEPTH_TEST, gl.GL_CULL_FACE, gl.GL_BLEND, gl.GL_SCISSOR_TEST,
                        gl.GL_STENCIL_TEST, gl.GL_FRAMEBUFFER_SRGB, gl.GL_RASTERIZER_DISCARD):
                gl.glDisable(cap)
            gl.glDepthMask(False)
            gl.glColorMask(True, True, True, True)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glUseProgram(self.program)
            loc = lambda name: gl.glGetUniformLocation(self.program, name)
            gl.glUniform1i(loc('colorMap'), 0)
            gl.glUniform1i(loc('depthMap'), 1)
            gl.glUniform2f(loc('frameSize'), width, height)
            gl.glUniform1f(loc('nearPlane'), camera.near)
            gl.glUniform1f(loc('farPlane'), camera.far)
            gl.glUniform1f(loc('focusDistance'), camera.focus_distance)
            focal = camera.focal_mm / 1000
            scale = .5 * width * focal**2 / (camera.f_number * .036 * (camera.focus_distance - focal))
            gl.glUniform1f(loc('cocScale'), scale)
            gl.glUniform1f(loc('radiusLimit'), 32.0 * width / 1920)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindSampler(0, 0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, target.texture)
            gl.glBindVertexArray(self.vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self.output.framebuffer)
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, target.framebuffer)
            gl.glBlitFramebuffer(0, 0, width, height, 0, 0, width, height,
                                 gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        finally:
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read)
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, draw)
            gl.glViewport(*viewport)
            restore_state(state)

    def close(self):
        self.output.close()
        if self.program:
            gl.glDeleteProgram(self.program)
        if self.vao:
            gl.glDeleteVertexArrays(1, [self.vao])
        if self.depth_texture:
            gl.glDeleteTextures([self.depth_texture])
        self.program = self.vao = self.depth_texture = 0
        self.size = None
