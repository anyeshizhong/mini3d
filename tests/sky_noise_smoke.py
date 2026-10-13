"""GPU lattice-boundary continuity check, independent of sky composition."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from mini3d.sky_renderer import ATMOSPHERE_GLSL, VERTEX
from mini3d.render_target import RenderTarget
from tools.capture_sunset import desktop_context


def check(source):
    noise = source[source.index('float skyHash'):source.index('vec3 skyRadiance')]
    fragment = '''#version 330 core
out vec4 color;
''' + noise + '''
void main() {
    int axis=int(gl_FragCoord.x)/64;
    float cell=mod(floor(gl_FragCoord.x),64.0)-32.0;
    vec3 p=vec3(cell,gl_FragCoord.y*.37-12.0,gl_FragCoord.y*.21-6.0);
    p[axis]=cell;
    vec3 d=vec3(0.0); d[axis]=.0001;
    color=vec4(skyNoise(p-d),skyNoise(p+d),0.0,1.0);
}'''
    program=compileProgram(compileShader(VERTEX,gl.GL_VERTEX_SHADER),compileShader(fragment,gl.GL_FRAGMENT_SHADER))
    target=RenderTarget(); target.resize(192,64)
    vao=gl.glGenVertexArrays(1)
    try:
        target.bind(); gl.glUseProgram(program); gl.glBindVertexArray(vao)
        gl.glDisable(gl.GL_DEPTH_TEST); gl.glDisable(gl.GL_BLEND)
        gl.glDrawArrays(gl.GL_TRIANGLES,0,3)
        pixels=np.frombuffer(gl.glReadPixels(0,0,192,64,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE),np.uint8).reshape(-1,4).astype(int)
        delta=abs(pixels[:,0]-pixels[:,1])
        return dict(max_boundary_jump=int(delta.max()), discontinuities=int((delta>1).sum()))
    finally:
        target.close(); gl.glDeleteProgram(program); gl.glDeleteVertexArrays(1,[vao])


if __name__ == '__main__':
    with desktop_context():
        result=check(ATMOSPHERE_GLSL)
        print(result)
        assert result['max_boundary_jump'] <= 1, result
