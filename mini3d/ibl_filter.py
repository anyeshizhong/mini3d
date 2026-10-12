"""One-time GGX/Lambert filtering using the repository's pinned Khronos shaders.

Import prepares radiance once; ordinary frames only sample GPU textures.
"""
from pathlib import Path
import numpy as np


def filter_panorama(rgb, samples=128):
    from OpenGL import GL as gl
    from OpenGL.GL.shaders import compileProgram, compileShader
    from .gl_state import save_state, restore_state, preserved_pixel_pack
    upstream = Path(__file__).resolve().parents[1] / 'tools/ibl/upstream'
    vertex = '''#version 330 core
out vec2 texCoord;
void main() {
 vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);
 texCoord=p; gl_Position=vec4(p*2.0-1.0,0.0,1.0);
}'''
    state = save_state()
    gl.glActiveTexture(gl.GL_TEXTURE0)
    cube0=int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_CUBE_MAP))
    draw = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
    read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
    unpack_names = (gl.GL_UNPACK_ALIGNMENT, gl.GL_UNPACK_ROW_LENGTH,
                    gl.GL_UNPACK_SKIP_ROWS, gl.GL_UNPACK_SKIP_PIXELS)
    unpack = [int(gl.glGetIntegerv(p)) for p in unpack_names]
    unpack_buffer = int(gl.glGetIntegerv(gl.GL_PIXEL_UNPACK_BUFFER_BINDING))
    handles, programs = [], []
    vao = int(gl.glGenVertexArrays(1)); fbo = int(gl.glGenFramebuffers(1))

    def texture(target, size, levels=1):
        handle=int(gl.glGenTextures(1)); handles.append(handle)
        gl.glBindTexture(target,handle)
        for level in range(levels):
            for face in range(6 if target==gl.GL_TEXTURE_CUBE_MAP else 1):
                face_target=gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X+face if target==gl.GL_TEXTURE_CUBE_MAP else target
                gl.glTexImage2D(face_target,level,gl.GL_RGBA32F,size>>level,size>>level,
                                0,gl.GL_RGBA,gl.GL_FLOAT,None)
        gl.glTexParameteri(target,gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR_MIPMAP_LINEAR if levels>1 else gl.GL_LINEAR)
        gl.glTexParameteri(target,gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR)
        gl.glTexParameteri(target,gl.GL_TEXTURE_MAX_LEVEL,levels-1)
        for axis in (gl.GL_TEXTURE_WRAP_S,gl.GL_TEXTURE_WRAP_T):
            gl.glTexParameteri(target,axis,gl.GL_CLAMP_TO_EDGE)
        return handle

    def uniform(p,name,value):
        loc=gl.glGetUniformLocation(p,name)
        (gl.glUniform1i if isinstance(value,int) else gl.glUniform1f)(loc,value)

    def program(filename):
        source=(upstream/filename).read_text().replace('precision highp float;','')
        p=compileProgram(compileShader(vertex,gl.GL_VERTEX_SHADER),
                         compileShader('#version 330 core\n'+source,gl.GL_FRAGMENT_SHADER))
        programs.append(p); return p

    def faces(p,target,level,size):
        arrays=[]
        for face in range(6):
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,gl.GL_COLOR_ATTACHMENT0,
                                     gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X+face,target,level)
            if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)!=gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('Floating-point IBL framebuffer unsupported')
            gl.glViewport(0,0,size,size); uniform(p,'u_currentFace',face)
            gl.glDrawArrays(gl.GL_TRIANGLES,0,3)
            data=gl.glReadPixels(0,0,size,size,gl.GL_RGB,gl.GL_FLOAT)
            arrays.append(np.frombuffer(data,np.float32).reshape(size,size,3).copy())
        return np.asarray(arrays,dtype=np.float16)

    try:
        with preserved_pixel_pack(reset=True):
            gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER,0)
            for p,v in zip(unpack_names,(1,0,0,0)): gl.glPixelStorei(p,v)
            gl.glBindVertexArray(vao); gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,fbo)
            gl.glDrawBuffer(gl.GL_COLOR_ATTACHMENT0); gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
            for cap in (gl.GL_DEPTH_TEST,gl.GL_CULL_FACE,gl.GL_BLEND,gl.GL_FRAMEBUFFER_SRGB,
                        gl.GL_STENCIL_TEST,gl.GL_SCISSOR_TEST,gl.GL_RASTERIZER_DISCARD): gl.glDisable(cap)
            gl.glColorMask(True,True,True,True); gl.glPolygonMode(gl.GL_FRONT_AND_BACK,gl.GL_FILL)
            gl.glActiveTexture(gl.GL_TEXTURE0); gl.glBindSampler(0,0)
            panorama=texture(gl.GL_TEXTURE_2D,1)
            # Khronos shader uses V=1 at the north pole; Radiance rows are top-first.
            pixels=np.ascontiguousarray(rgb[::-1],dtype=np.float32)
            gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGB32F,pixels.shape[1],pixels.shape[0],
                            0,gl.GL_RGB,gl.GL_FLOAT,pixels)
            gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_WRAP_S,gl.GL_REPEAT)
            source=texture(gl.GL_TEXTURE_CUBE_MAP,256,9)
            specular=texture(gl.GL_TEXTURE_CUBE_MAP,256,9)
            diffuse=texture(gl.GL_TEXTURE_CUBE_MAP,32)
            lut=texture(gl.GL_TEXTURE_2D,256)
            p=program('panorama_to_cubemap.frag'); gl.glUseProgram(p)
            gl.glBindTexture(gl.GL_TEXTURE_2D,panorama); uniform(p,'u_panorama',0)
            faces(p,source,0,256)
            gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP,source); gl.glGenerateMipmap(gl.GL_TEXTURE_CUBE_MAP)
            gl.glEnable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)
            p=program('ibl_filtering.frag'); gl.glUseProgram(p)
            for name,value in dict(u_cubemapTexture=0,u_sampleCount=samples,u_width=256,
                    u_lodBias=0.0,u_isGeneratingLUT=0,u_floatTexture=1,u_intensityScale=1.0,
                    u_roughness=0.0,u_distribution=0).items(): uniform(p,name,value)
            arrays={'diffuse':faces(p,diffuse,0,32)}
            uniform(p,'u_distribution',1)
            for level in range(9):
                uniform(p,'u_roughness',level/8.0)
                arrays['specular_'+str(level)]=faces(p,specular,level,256>>level)
            uniform(p,'u_isGeneratingLUT',1)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER,gl.GL_COLOR_ATTACHMENT0,gl.GL_TEXTURE_2D,lut,0)
            gl.glViewport(0,0,256,256); gl.glDrawArrays(gl.GL_TRIANGLES,0,3)
            data=gl.glReadPixels(0,0,256,256,gl.GL_RGB,gl.GL_FLOAT)
            arrays['brdf']=np.frombuffer(data,np.float32).reshape(256,256,3)[...,:2].astype(np.float16)
            if any(not np.isfinite(a).all() or a.min()<0 for a in arrays.values()):
                raise ValueError('Invalid filtered HDR environment')
            return arrays
    finally:
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER,draw)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,read); gl.glViewport(*viewport)
        for p,v in zip(unpack_names,unpack): gl.glPixelStorei(p,v)
        gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER,unpack_buffer)
        gl.glDeleteTextures(handles)
        for p in programs: gl.glDeleteProgram(p)
        gl.glDeleteFramebuffers(1,[fbo]); gl.glDeleteVertexArrays(1,[vao])
        gl.glActiveTexture(gl.GL_TEXTURE0);gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP,cube0)
        restore_state(state)
