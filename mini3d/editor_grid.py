"""View-covering editor guides on the placement plane; never scene geometry."""
import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader


VERTEX = """#version 330 core
out vec2 ndc;
void main() {
    ndc = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2) * 2.0 - 1.0;
    gl_Position = vec4(ndc, 0.0, 1.0);
}
"""

FRAGMENT = """#version 330 core
in vec2 ndc;
out vec4 color;
uniform mat4 inverseProjection, projection;
uniform mat3 cameraRotation;
uniform vec3 eye;
uniform float planeZ, spacing, farClip;

void main() {
    vec3 cameraRay = normalize((inverseProjection * vec4(ndc, 1.0, 1.0)).xyz);
    vec3 ray = cameraRotation * cameraRay;
    if (abs(ray.z) < 1e-7) discard;
    float distance = (planeZ - eye.z) / ray.z;
    if (distance <= 0.0) discard;
    vec3 viewPoint = cameraRay * distance;
    vec4 clip = projection * vec4(viewPoint, 1.0);
    float depth = clip.z / clip.w * 0.5 + 0.5;
    if (depth < 0.0 || depth > 1.0) discard;
    gl_FragDepth = gl_DepthRange.near + depth * gl_DepthRange.diff;

    // Camera-relative intersection avoids subtracting large world positions
    // again to recover depth. Lines remain anchored to the world origin.
    vec2 world = eye.xy + ray.xy * distance;
    vec2 coord = world / spacing;
    vec2 footprint = max(fwidth(coord), vec2(1e-6));
    vec2 lineDistance = abs(fract(coord - 0.5) - 0.5) / footprint;
    vec2 lines = (1.0 - smoothstep(vec2(0.0), vec2(1.0), lineDistance))
               * (1.0 - smoothstep(vec2(0.35), vec2(1.0), footprint));
    float alpha = max(lines.x, lines.y);
    vec3 rgb = vec3(90.0 / 255.0);

    vec2 axisDistance = abs(world) / max(fwidth(world), vec2(1e-6));
    vec2 axes = 1.0 - smoothstep(vec2(0.0), vec2(1.0), axisDistance);
    rgb = mix(rgb, vec3(80, 180, 80) / 255.0, axes.x);  // X=0: Y axis.
    rgb = mix(rgb, vec3(180, 80, 80) / 255.0, axes.y);  // Y=0: X axis.
    alpha = max(alpha, max(axes.x, axes.y));

    // Fade unresolved lines and the far/horizon limit instead of exposing a
    // finite square or a sharp far-clip edge. Near geometry still occludes us.
    alpha *= 1.0 - smoothstep(farClip * 0.75, farClip, -viewPoint.z);
    alpha *= smoothstep(0.005, 0.03, abs(ray.z));
    if (alpha < 0.002) discard;
    color = vec4(rgb, alpha);
}
"""


class EditorGrid:
    def __init__(self):
        self.program = self.vao = 0
        self.locations = {}

    def _allocate(self):
        if self.program:
            return
        self.program = compileProgram(compileShader(VERTEX, gl.GL_VERTEX_SHADER),
                                      compileShader(FRAGMENT, gl.GL_FRAGMENT_SHADER))
        self.vao = int(gl.glGenVertexArrays(1))
        self.locations = {name: gl.glGetUniformLocation(self.program, name) for name in
                          ('inverseProjection', 'projection', 'cameraRotation', 'eye',
                           'planeZ', 'spacing', 'farClip')}

    def draw(self, scene, camera, width, height):
        if not getattr(scene, 'show_grid', True):
            return
        spacing = 20. * getattr(scene, 'grid_scale', 1.)
        if not np.isfinite(spacing) or spacing <= 0:
            return
        plane_z = getattr(getattr(scene, 'placement_plane', None), 'z', 0.)
        projection = np.asarray(camera.projection_matrix(float(width) / height), np.float32)
        # Only states changed by this pass are queried; no texture-unit walk.
        names = ('CURRENT_PROGRAM', 'VERTEX_ARRAY_BINDING', 'DEPTH_FUNC',
                 'BLEND_SRC_RGB', 'BLEND_DST_RGB', 'BLEND_SRC_ALPHA', 'BLEND_DST_ALPHA',
                 'BLEND_EQUATION_RGB', 'BLEND_EQUATION_ALPHA')
        previous = {name: int(gl.glGetIntegerv(getattr(gl, 'GL_' + name))) for name in names}
        enabled = {cap: bool(gl.glIsEnabled(cap)) for cap in
                   (gl.GL_DEPTH_TEST, gl.GL_CULL_FACE, gl.GL_BLEND)}
        depth_mask = bool(gl.glGetBooleanv(gl.GL_DEPTH_WRITEMASK))
        polygon = int(np.asarray(gl.glGetIntegerv(gl.GL_POLYGON_MODE)).reshape(-1)[0])
        try:
            self._allocate()
            gl.glDepthMask(False)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LEQUAL)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendEquationSeparate(gl.GL_FUNC_ADD, gl.GL_FUNC_ADD)
            gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA,
                                   gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glUseProgram(self.program)
            loc = self.locations.__getitem__
            gl.glUniformMatrix4fv(loc('projection'), 1, gl.GL_TRUE, projection)
            gl.glUniformMatrix4fv(loc('inverseProjection'), 1, gl.GL_TRUE,
                                 np.linalg.inv(projection.astype(float)).astype(np.float32))
            gl.glUniformMatrix3fv(loc('cameraRotation'), 1, gl.GL_TRUE,
                                 np.asarray(camera.rotation, np.float32))
            gl.glUniform3fv(loc('eye'), 1, np.asarray(camera.position, np.float32))
            gl.glUniform1f(loc('planeZ'), plane_z)
            gl.glUniform1f(loc('spacing'), spacing)
            gl.glUniform1f(loc('farClip'), camera.far)
            gl.glBindVertexArray(self.vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        finally:
            gl.glDepthMask(depth_mask)
            gl.glDepthFunc(previous['DEPTH_FUNC'])
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, polygon)
            gl.glBlendEquationSeparate(previous['BLEND_EQUATION_RGB'], previous['BLEND_EQUATION_ALPHA'])
            gl.glBlendFuncSeparate(previous['BLEND_SRC_RGB'], previous['BLEND_DST_RGB'],
                                   previous['BLEND_SRC_ALPHA'], previous['BLEND_DST_ALPHA'])
            for cap, active in enabled.items():
                (gl.glEnable if active else gl.glDisable)(cap)
            gl.glUseProgram(previous['CURRENT_PROGRAM'])
            gl.glBindVertexArray(previous['VERTEX_ARRAY_BINDING'])

    def close(self):
        if self.vao:
            gl.glDeleteVertexArrays(1, [self.vao])
        if self.program:
            gl.glDeleteProgram(self.program)
        self.program = self.vao = 0
        self.locations.clear()
