#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#define GL_GLEXT_PROTOTYPES 1
#include <GL/glcorearb.h>
#include <GL/glext.h>

#include <string>

namespace spqr {

#define SPQR_GL_FUNCTIONS(X) \
    X(GetString) X(GetError) X(GetIntegerv) \
    X(CreateShader) X(ShaderSource) X(CompileShader) X(GetShaderiv) X(GetShaderInfoLog) X(DeleteShader) \
    X(CreateProgram) X(AttachShader) X(LinkProgram) X(GetProgramiv) X(GetProgramInfoLog) X(DeleteProgram) \
    X(UseProgram) X(GetUniformLocation) \
    X(Uniform1i) X(Uniform1f) X(Uniform2f) X(Uniform3f) X(Uniform4f) \
    X(Uniform1fv) X(Uniform2fv) X(Uniform3fv) X(Uniform4fv) \
    X(Uniform1iv) X(Uniform2iv) X(Uniform3iv) X(Uniform4iv) \
    X(UniformMatrix2fv) X(UniformMatrix3fv) X(UniformMatrix4fv) \
    X(GenVertexArrays) X(BindVertexArray) X(DeleteVertexArrays) \
    X(GenBuffers) X(BindBuffer) X(BufferData) X(DeleteBuffers) \
    X(EnableVertexAttribArray) X(VertexAttribPointer) X(VertexAttribDivisor) \
    X(GenTextures) X(DeleteTextures) X(ActiveTexture) X(BindTexture) X(TexImage2D) X(TexImage3D) \
    X(TexParameteri) X(TexParameterfv) X(PixelStorei) \
    X(GenSamplers) X(DeleteSamplers) X(SamplerParameteri) X(SamplerParameterfv) X(BindSampler) \
    X(GenFramebuffers) X(DeleteFramebuffers) X(BindFramebuffer) X(FramebufferTexture2D) X(FramebufferTextureLayer) \
    X(CheckFramebufferStatus) X(DrawBuffer) X(ReadBuffer) \
    X(GenRenderbuffers) X(BindRenderbuffer) X(RenderbufferStorage) X(RenderbufferStorageMultisample) \
    X(FramebufferRenderbuffer) X(DeleteRenderbuffers) X(BlitFramebuffer) \
    X(Viewport) X(Enable) X(Disable) X(DepthFunc) X(DepthMask) X(DepthRange) \
    X(CullFace) X(FrontFace) X(PolygonMode) X(PolygonOffset) X(ColorMask) \
    X(BlendEquation) X(BlendFuncSeparate) X(ClearColor) X(ClearDepth) X(Clear) \
    X(DrawElements) X(DrawElementsInstanced) X(DrawArrays) X(Finish) X(ReadPixels)

class GLApi {
public:
#define SPQR_DECLARE_GL(name) decltype(&::gl##name) name = nullptr;
    SPQR_GL_FUNCTIONS(SPQR_DECLARE_GL)
#undef SPQR_DECLARE_GL
    bool load(std::string& error);
};

} // namespace spqr
