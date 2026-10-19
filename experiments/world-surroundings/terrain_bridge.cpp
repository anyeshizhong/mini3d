#include "renderer.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

using BufferSubDataProc = void (APIENTRY*)(GLenum target, GLintptr offset,
                                           GLsizeiptr size, const void* data);
using GetBufferSubDataProc = void (APIENTRY*)(GLenum target, GLintptr offset,
                                              GLsizeiptr size, void* data);
using TexSubImage2DProc = void (APIENTRY*)(GLenum target, GLint level, GLint xoffset,
                                           GLint yoffset, GLsizei width, GLsizei height,
                                           GLenum format, GLenum type, const void* pixels);
using GetTexImageProc = void (APIENTRY*)(GLenum target, GLint level, GLenum format,
                                         GLenum type, void* pixels);

thread_local std::string g_lastError;

void clearError() { g_lastError.clear(); }
void setError(const char* message) { g_lastError = message ? message : "unknown terrain_lab error"; }
void setCurrentException() {
    try {
        throw;
    } catch (const std::exception& error) {
        setError(error.what());
    } catch (...) {
        setError("unknown C++ exception in terrain_lab");
    }
}

std::string glErrorText(GLenum error) {
    const char* name = nullptr;
    switch (error) {
    case GL_INVALID_ENUM: name = "GL_INVALID_ENUM"; break;
    case GL_INVALID_VALUE: name = "GL_INVALID_VALUE"; break;
    case GL_INVALID_OPERATION: name = "GL_INVALID_OPERATION"; break;
    case GL_OUT_OF_MEMORY: name = "GL_OUT_OF_MEMORY"; break;
    case GL_INVALID_FRAMEBUFFER_OPERATION: name = "GL_INVALID_FRAMEBUFFER_OPERATION"; break;
    default: break;
    }
    return name ? name : ("OpenGL error 0x" + [&]() {
        char buffer[16]{};
        std::snprintf(buffer, sizeof(buffer), "%04x", static_cast<unsigned>(error));
        return std::string(buffer);
    }());
}

PROC resolveLocalGL(const char* name) {
    PROC proc = wglGetProcAddress(name);
    const auto value = reinterpret_cast<std::uintptr_t>(proc);
    if (!proc || value == 1 || value == 2 || value == 3 ||
        value == static_cast<std::uintptr_t>(-1)) {
        static HMODULE module = GetModuleHandleW(L"opengl32.dll");
        proc = module ? GetProcAddress(module, name) : nullptr;
    }
    return proc;
}

template<class Function>
Function loadLocalGL(const char* name) {
    return std::bit_cast<Function>(resolveLocalGL(name));
}

std::filesystem::path pathFromUtf8(const char* value, const char* label) {
    if (!value || !*value) throw std::runtime_error(std::string(label) + " is empty");
    const int required = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, nullptr, 0);
    if (required <= 0) throw std::runtime_error(std::string(label) + " is not valid UTF-8");
    std::wstring wide(static_cast<std::size_t>(required), L'\0');
    const int written = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1,
                                             wide.data(), required);
    if (written != required) throw std::runtime_error(std::string(label) + " could not be decoded as UTF-8");
    wide.pop_back();
    return std::filesystem::path(std::move(wide));
}

std::filesystem::path capturePathFromUtf8(const char* value, const char* label) {
    auto path = pathFromUtf8(value, label);
    // Renderer::capture and captureColor create the parent directory. Resolve a
    // bare filename first so that this also works from the experiment cwd.
    if (path.parent_path().empty()) path = std::filesystem::current_path() / path;
    return path;
}

struct PendingMeshUpdate {
    std::uint32_t meshId = 0;
    std::vector<float> vertices;
    std::array<double, 6> bounds{};
    GLsizeiptr byteCount = 0;
};

struct PendingTextureUpdate {
    std::uint32_t textureId = 0;
    std::uint32_t x = 0, y = 0, width = 0, height = 0;
    std::size_t payloadOffset = 0;
    std::uint64_t byteCount = 0;
    std::vector<float> cpuPixels;
};

class ArrayBufferBindingGuard {
public:
    ArrayBufferBindingGuard(spqr::GLApi& gl, GLint previous) : gl_(gl), previous_(previous) {}
    ArrayBufferBindingGuard(const ArrayBufferBindingGuard&) = delete;
    ArrayBufferBindingGuard& operator=(const ArrayBufferBindingGuard&) = delete;
    ~ArrayBufferBindingGuard() {
        if (active_) gl_.BindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(previous_));
    }

    bool restore() {
        if (!active_) return true;
        gl_.BindBuffer(GL_ARRAY_BUFFER, static_cast<GLuint>(previous_));
        active_ = false;
        return gl_.GetError() == GL_NO_ERROR;
    }

private:
    spqr::GLApi& gl_;
    GLint previous_ = 0;
    bool active_ = true;
};

struct PixelTransferState {
    GLint textureBinding = 0;
    GLint bufferBinding = 0;
    GLint alignment = 4;
    GLint rowLength = 0;
    GLint skipRows = 0;
    GLint skipPixels = 0;
};

class TextureTransferStateGuard {
public:
    TextureTransferStateGuard(spqr::GLApi& gl, GLenum bufferTarget, GLenum alignmentName,
                              GLenum rowLengthName, GLenum skipRowsName,
                              GLenum skipPixelsName, const PixelTransferState& previous)
        : gl_(gl), bufferTarget_(bufferTarget), previous_(previous),
          alignmentName_(alignmentName), rowLengthName_(rowLengthName),
          skipRowsName_(skipRowsName), skipPixelsName_(skipPixelsName) {}
    TextureTransferStateGuard(const TextureTransferStateGuard&) = delete;
    TextureTransferStateGuard& operator=(const TextureTransferStateGuard&) = delete;
    ~TextureTransferStateGuard() { if (active_) restore(); }

    bool restore() {
        if (!active_) return true;
        active_ = false;
        gl_.BindTexture(GL_TEXTURE_2D, static_cast<GLuint>(previous_.textureBinding));
        gl_.BindBuffer(bufferTarget_, static_cast<GLuint>(previous_.bufferBinding));
        gl_.PixelStorei(alignmentName_, previous_.alignment);
        gl_.PixelStorei(rowLengthName_, previous_.rowLength);
        gl_.PixelStorei(skipRowsName_, previous_.skipRows);
        gl_.PixelStorei(skipPixelsName_, previous_.skipPixels);
        return gl_.GetError() == GL_NO_ERROR;
    }

private:
    spqr::GLApi& gl_;
    GLenum bufferTarget_ = 0;
    PixelTransferState previous_;
    GLenum alignmentName_ = 0, rowLengthName_ = 0, skipRowsName_ = 0, skipPixelsName_ = 0;
    bool active_ = true;
};

void requireNoGlError(spqr::GLApi& gl, const std::string& stage) {
    const GLenum error = gl.GetError();
    if (error != GL_NO_ERROR)
        throw std::runtime_error(std::string(stage) + ": " + glErrorText(error));
}

void drainGlErrors(spqr::GLApi& gl) {
    // Attribute only errors generated by this bridge call. OpenGL permits more
    // than one queued error, so drain a bounded number and reject a stuck driver.
    for (unsigned i = 0; i < 32; ++i)
        if (gl.GetError() == GL_NO_ERROR) return;
    throw std::runtime_error("OpenGL error queue did not clear before texture transfer");
}

PixelTransferState queryPixelTransferState(spqr::GLApi& gl, GLenum bufferBindingName,
                                           GLenum alignmentName, GLenum rowLengthName,
                                           GLenum skipRowsName, GLenum skipPixelsName) {
    PixelTransferState state;
    gl.GetIntegerv(GL_TEXTURE_BINDING_2D, &state.textureBinding);
    gl.GetIntegerv(bufferBindingName, &state.bufferBinding);
    gl.GetIntegerv(alignmentName, &state.alignment);
    gl.GetIntegerv(rowLengthName, &state.rowLength);
    gl.GetIntegerv(skipRowsName, &state.skipRows);
    gl.GetIntegerv(skipPixelsName, &state.skipPixels);
    requireNoGlError(gl, "failed to query OpenGL texture-transfer state");
    if (state.textureBinding < 0 || state.bufferBinding < 0)
        throw std::runtime_error("OpenGL returned an invalid texture-transfer binding");
    return state;
}

} // namespace

namespace spqr {

struct TerrainLab {
    TerrainLab(const std::filesystem::path& bundleDirectory, int width, int height)
        : context_(requireCurrentContext()), ownerThread_(GetCurrentThreadId()),
          bundle_(loadBundle(bundleDirectory, false)),
          frames_(loadFrames(bundleDirectory / "frames.bin")) {
        std::string glLoadError;
        if (!gl_.load(glLoadError)) throw std::runtime_error(glLoadError);

        bufferSubData_ = loadLocalGL<BufferSubDataProc>("glBufferSubData");
        getBufferSubData_ = loadLocalGL<GetBufferSubDataProc>("glGetBufferSubData");
        texSubImage2D_ = loadLocalGL<TexSubImage2DProc>("glTexSubImage2D");
        getTexImage_ = loadLocalGL<GetTexImageProc>("glGetTexImage");
        if (!bufferSubData_) throw std::runtime_error("OpenGL entry point unavailable: glBufferSubData");
        if (!texSubImage2D_) throw std::runtime_error("OpenGL entry point unavailable: glTexSubImage2D");
        if (!getTexImage_) throw std::runtime_error("OpenGL entry point unavailable: glGetTexImage");

        renderer_ = std::make_unique<Renderer>(gl_, bundle_, bundleDirectory,
                                               width, height, true, 1, true, false);
        if (!renderer_->ready()) throw std::runtime_error("renderer initialization did not complete");

        rendererName_ = renderer_->rendererName();
        const auto* version = gl_.GetString(GL_VERSION);
        glVersion_ = version ? reinterpret_cast<const char*>(version) : "(unknown OpenGL version)";
    }

    static HGLRC requireCurrentContext() {
        const HGLRC context = wglGetCurrentContext();
        if (!context) throw std::runtime_error("lab_create requires a current OpenGL context");
        return context;
    }

    void requireOwner(bool allowFatal = false) const {
        if (GetCurrentThreadId() != ownerThread_)
            throw std::runtime_error("terrain_lab call rejected: handle belongs to another thread");
        if (wglGetCurrentContext() != context_)
            throw std::runtime_error("terrain_lab call rejected: handle belongs to another OpenGL context");
        if (!allowFatal && fatal_)
            throw std::runtime_error("terrain_lab handle is fatal after a GL update failure; destroy and recreate it: " + fatalMessage_);
        if (!renderer_ && !allowFatal)
            throw std::runtime_error("terrain_lab renderer has been destroyed");
    }

    const CameraFrame& frameAt(std::uint32_t frameIndex) const {
        if (frameIndex >= frames_.size()) throw std::runtime_error("frame index is out of range");
        return frames_[frameIndex];
    }

    int updateBatch(const std::uint32_t* meshIds, const std::uint32_t* vertexCounts,
                    const float* packedVertices, std::uint32_t batchCount) {
        requireOwner();
        if (batchCount > bundle_.meshes.size())
            throw std::runtime_error("mesh update batch count exceeds the bundle mesh count");
        if (batchCount && (!meshIds || !vertexCounts))
            throw std::runtime_error("mesh update batch contains a null ID or count pointer");
        if (!batchCount) return 1;
        if (!packedVertices) throw std::runtime_error("mesh update vertex pointer is null");

        std::unordered_set<std::uint32_t> seen;
        seen.reserve(batchCount);
        std::vector<PendingMeshUpdate> pending;
        pending.reserve(batchCount);
        std::size_t packedOffset = 0;
        std::uint64_t batchBytes = 0;
        constexpr std::size_t floatsPerVertex = 12;

        // Validate and stage the full CPU batch before issuing any GL command.
        for (std::uint32_t i = 0; i < batchCount; ++i) {
            const std::uint32_t meshId = meshIds[i];
            if (meshId >= bundle_.meshes.size() || meshId >= renderer_->meshes_.size())
                throw std::runtime_error("mesh update ID is out of range");
            if (!seen.insert(meshId).second)
                throw std::runtime_error("mesh update batch contains a duplicate mesh ID");

            const Mesh& oldMesh = bundle_.meshes[meshId];
            if (vertexCounts[i] != oldMesh.vertexCount)
                throw std::runtime_error("mesh update vertex count does not match the existing topology");
            if (oldMesh.vertices.size() != static_cast<std::size_t>(oldMesh.vertexCount) * floatsPerVertex)
                throw std::runtime_error("bundle mesh vertex storage does not match its vertex count");
            if (!renderer_->meshes_[meshId].vbo)
                throw std::runtime_error("mesh update target has no uploaded VBO");
            if (oldMesh.vertexCount > std::numeric_limits<std::size_t>::max() / floatsPerVertex)
                throw std::runtime_error("mesh update vertex span size overflows size_t");

            const std::size_t floatCount = static_cast<std::size_t>(oldMesh.vertexCount) * floatsPerVertex;
            if (packedOffset > std::numeric_limits<std::size_t>::max() - floatCount)
                throw std::runtime_error("mesh update packed span size overflows size_t");
            if (floatCount > static_cast<std::size_t>(std::numeric_limits<GLsizeiptr>::max()) / sizeof(float))
                throw std::runtime_error("mesh update VBO size exceeds GLsizeiptr");
            const auto byteCount = static_cast<std::uint64_t>(floatCount) * sizeof(float);
            if (batchBytes > std::numeric_limits<std::uint64_t>::max() - byteCount)
                throw std::runtime_error("mesh update byte count overflows uint64");
            batchBytes += byteCount;

            PendingMeshUpdate update;
            update.meshId = meshId;
            update.byteCount = static_cast<GLsizeiptr>(byteCount);
            update.vertices.assign(packedVertices + packedOffset,
                                   packedVertices + packedOffset + floatCount);
            update.bounds = {
                std::numeric_limits<double>::infinity(),
                std::numeric_limits<double>::infinity(),
                std::numeric_limits<double>::infinity(),
                -std::numeric_limits<double>::infinity(),
                -std::numeric_limits<double>::infinity(),
                -std::numeric_limits<double>::infinity()
            };

            for (std::uint32_t vertex = 0; vertex < oldMesh.vertexCount; ++vertex) {
                const std::size_t base = static_cast<std::size_t>(vertex) * floatsPerVertex;
                const float* input = update.vertices.data() + base;
                const float* old = oldMesh.vertices.data() + base;
                for (std::size_t component = 0; component < floatsPerVertex; ++component)
                    if (!std::isfinite(input[component]))
                        throw std::runtime_error("mesh update contains a non-finite vertex value");

                if (std::memcmp(input, old, 2 * sizeof(float)) != 0 ||
                    std::memcmp(input + 6, old + 6, 6 * sizeof(float)) != 0)
                    throw std::runtime_error("mesh update may change only vertex Z and normal; XY, UV, and color must remain byte-identical");

                const double nx = input[3], ny = input[4], nz = input[5];
                const double normalLength = std::hypot(nx, ny, nz);
                if (!std::isfinite(normalLength) || normalLength <= 1e-6)
                    throw std::runtime_error("mesh update contains a zero-length or invalid normal");

                update.bounds[0] = std::min(update.bounds[0], static_cast<double>(input[0]));
                update.bounds[1] = std::min(update.bounds[1], static_cast<double>(input[1]));
                update.bounds[2] = std::min(update.bounds[2], static_cast<double>(input[2]));
                update.bounds[3] = std::max(update.bounds[3], static_cast<double>(input[0]));
                update.bounds[4] = std::max(update.bounds[4], static_cast<double>(input[1]));
                update.bounds[5] = std::max(update.bounds[5], static_cast<double>(input[2]));
            }

            pending.push_back(std::move(update));
            packedOffset += floatCount;
        }

        if (updateCount_ == std::numeric_limits<std::uint64_t>::max() ||
            uploadedBytes_ > std::numeric_limits<std::uint64_t>::max() - batchBytes)
            throw std::runtime_error("mesh update statistics would overflow uint64");

        GLint previousArrayBuffer = 0;
        gl_.GetIntegerv(GL_ARRAY_BUFFER_BINDING, &previousArrayBuffer);
        if (previousArrayBuffer < 0) throw std::runtime_error("OpenGL returned an invalid array-buffer binding");
        ArrayBufferBindingGuard bindingGuard(gl_, previousArrayBuffer);
        bool uploadMayHaveChangedGpu = false;
        try {
            for (const PendingMeshUpdate& update : pending) {
                const GLuint vbo = renderer_->meshes_[update.meshId].vbo;
                gl_.BindBuffer(GL_ARRAY_BUFFER, vbo);
                GLenum error = gl_.GetError();
                if (error != GL_NO_ERROR)
                    throw std::runtime_error("failed to bind mesh VBO before update: " + glErrorText(error));

                uploadMayHaveChangedGpu = true;
                bufferSubData_(GL_ARRAY_BUFFER, 0, update.byteCount, update.vertices.data());
                error = gl_.GetError();
                if (error != GL_NO_ERROR)
                    throw std::runtime_error("glBufferSubData failed for mesh " +
                                             std::to_string(update.meshId) + ": " + glErrorText(error));
            }
            if (!bindingGuard.restore())
                throw std::runtime_error("failed to restore the previous GL_ARRAY_BUFFER binding after mesh update");
        } catch (...) {
            bindingGuard.restore();
            if (uploadMayHaveChangedGpu) {
                fatal_ = true;
                fatalMessage_ = "OpenGL mesh upload may be partial; renderer must be destroyed and recreated";
            }
            throw;
        }

        // Commit CPU mesh data and bounds only after the complete GL batch succeeds.
        for (PendingMeshUpdate& update : pending) {
            Mesh& mesh = bundle_.meshes[update.meshId];
            mesh.vertices = std::move(update.vertices);
            mesh.bounds = update.bounds;
        }
        ++renderer_->transformRevision_;
        renderer_->farFitValid_ = false;
        renderer_->shadowDepthValid_ = false;
        renderer_->nearShadowDepthValid_ = false;
        renderer_->shadowTransition_ = false;
        renderer_->shadowPoseValid_ = false;
        ++updateCount_;
        uploadedBytes_ += batchBytes;
        return 1;
    }

    int readMeshVertices(std::uint32_t meshId, float* output, std::uint32_t floatCapacity) {
        requireOwner(true);
        if (meshId >= bundle_.meshes.size() || meshId >= renderer_->meshes_.size())
            throw std::runtime_error("mesh ID is out of range");
        if (!getBufferSubData_)
            throw std::runtime_error("OpenGL entry point unavailable: glGetBufferSubData");
        const auto& mesh = bundle_.meshes[meshId];
        const std::size_t floatCount = static_cast<std::size_t>(mesh.vertexCount) * 12u;
        if (floatCapacity < floatCount)
            throw std::runtime_error("GPU vertex readback output buffer is too small");
        if (floatCount && !output) throw std::runtime_error("GPU vertex readback output pointer is null");
        if (floatCount > static_cast<std::size_t>(std::numeric_limits<GLsizeiptr>::max()) / sizeof(float))
            throw std::runtime_error("GPU vertex readback size exceeds GLsizeiptr");
        const GLuint vbo = renderer_->meshes_[meshId].vbo;
        if (!vbo) throw std::runtime_error("mesh has no uploaded VBO");

        GLint previousArrayBuffer = 0;
        gl_.GetIntegerv(GL_ARRAY_BUFFER_BINDING, &previousArrayBuffer);
        if (previousArrayBuffer < 0) throw std::runtime_error("OpenGL returned an invalid array-buffer binding");
        ArrayBufferBindingGuard bindingGuard(gl_, previousArrayBuffer);
        gl_.BindBuffer(GL_ARRAY_BUFFER, vbo);
        GLenum error = gl_.GetError();
        if (error != GL_NO_ERROR)
            throw std::runtime_error("failed to bind mesh VBO for readback: " + glErrorText(error));
        getBufferSubData_(GL_ARRAY_BUFFER, 0,
                          static_cast<GLsizeiptr>(floatCount * sizeof(float)), output);
        error = gl_.GetError();
        if (error != GL_NO_ERROR)
            throw std::runtime_error("glGetBufferSubData failed: " + glErrorText(error));
        if (!bindingGuard.restore())
            throw std::runtime_error("failed to restore GL_ARRAY_BUFFER after readback");
        return 1;
    }

    std::uint32_t entityTextureId(std::uint32_t entityIndex, std::uint32_t slot) const {
        requireOwner(true);
        if (entityIndex >= bundle_.entities.size())
            throw std::runtime_error("entity index is out of range");
        if (slot >= 13u)
            throw std::runtime_error("material texture slot is out of range");
        const Entity& entity = bundle_.entities[entityIndex];
        if (entity.mesh >= bundle_.meshes.size())
            throw std::runtime_error("entity mesh index is out of range");
        const std::uint32_t materialIndex = bundle_.meshes[entity.mesh].material;
        if (materialIndex >= bundle_.materials.size())
            throw std::runtime_error("entity mesh material index is out of range");
        const std::uint32_t textureId = bundle_.materials[materialIndex].textureIndices[slot];
        if (textureId == std::numeric_limits<std::uint32_t>::max())
            throw std::runtime_error("entity material texture slot is empty");
        if (textureId >= bundle_.textures.size())
            throw std::runtime_error("entity material texture index is out of range");
        if (textureId > static_cast<std::uint32_t>(std::numeric_limits<std::int32_t>::max()))
            throw std::runtime_error("texture ID cannot be represented by the C ABI");
        return textureId;
    }

    const TextureMip& requireEditableTexture(std::uint32_t textureId) const {
        if (!renderer_)
            throw std::runtime_error("terrain_lab renderer has been destroyed");
        if (textureId >= bundle_.textures.size() || textureId >= renderer_->textures_.size())
            throw std::runtime_error("texture ID is out of range");
        const Texture& texture = bundle_.textures[textureId];
        if (texture.borrowedHandle)
            throw std::runtime_error("borrowed textures cannot be updated by terrain_lab");
        if (texture.target != GL_TEXTURE_2D)
            throw std::runtime_error("texture update requires a 2D texture");
        if (texture.internalFormat != GL_RGBA8)
            throw std::runtime_error("texture update requires GL_RGBA8 storage");
        if (texture.minFilter != GL_LINEAR || texture.magFilter != GL_LINEAR)
            throw std::runtime_error("texture update requires linear minification and magnification filters");
        if (texture.mips.size() != 1)
            throw std::runtime_error("texture update requires exactly one mip level");
        const TextureMip& mip = texture.mips.front();
        if (!mip.width || !mip.height)
            throw std::runtime_error("texture update requires positive texture dimensions");
        if (mip.width > static_cast<std::uint32_t>(std::numeric_limits<GLsizei>::max()) ||
            mip.height > static_cast<std::uint32_t>(std::numeric_limits<GLsizei>::max()))
            throw std::runtime_error("texture dimensions exceed OpenGL limits");
        const std::uint64_t pixelCount = static_cast<std::uint64_t>(mip.width) * mip.height;
        if (pixelCount > std::numeric_limits<std::uint64_t>::max() / 4u ||
            pixelCount * 4u > std::numeric_limits<std::size_t>::max())
            throw std::runtime_error("texture pixel span overflows addressable memory");
        if (mip.faces.size() != static_cast<std::size_t>(pixelCount * 4u))
            throw std::runtime_error("texture mip CPU storage does not match its dimensions");
        if (!renderer_->textures_[textureId])
            throw std::runtime_error("texture has no uploaded OpenGL handle");
        return mip;
    }

    int textureInfo(std::uint32_t textureId, std::uint32_t* width,
                    std::uint32_t* height) const {
        requireOwner(true);
        if (!width || !height)
            throw std::runtime_error("texture info output pointer is null");
        const TextureMip& mip = requireEditableTexture(textureId);
        *width = mip.width;
        *height = mip.height;
        return 1;
    }

    int updateTextureBatch(const std::uint32_t* textureIds,
                           const std::uint32_t* rectsXYWH,
                           const std::uint8_t* packedRGBA8,
                           std::uint32_t batchCount) {
        requireOwner();
        if (batchCount > bundle_.textures.size())
            throw std::runtime_error("texture update batch count exceeds the bundle texture count");
        if (!batchCount) return 1;
        if (!textureIds || !rectsXYWH || !packedRGBA8)
            throw std::runtime_error("texture update batch contains a null input pointer");

        std::unordered_set<std::uint32_t> seen;
        seen.reserve(batchCount);
        std::vector<PendingTextureUpdate> pending;
        pending.reserve(batchCount);
        std::uint64_t batchBytes = 0;
        std::size_t payloadOffset = 0;

        // Finish every validation, and allocate/convert all CPU patches, before
        // querying or changing any GL state. This keeps rejected batches atomic.
        for (std::uint32_t i = 0; i < batchCount; ++i) {
            const std::uint32_t textureId = textureIds[i];
            if (!seen.insert(textureId).second)
                throw std::runtime_error("texture update batch contains a duplicate texture ID");
            const TextureMip& mip = requireEditableTexture(textureId);
            const std::uint32_t x = rectsXYWH[static_cast<std::size_t>(i) * 4u + 0u];
            const std::uint32_t y = rectsXYWH[static_cast<std::size_t>(i) * 4u + 1u];
            const std::uint32_t width = rectsXYWH[static_cast<std::size_t>(i) * 4u + 2u];
            const std::uint32_t height = rectsXYWH[static_cast<std::size_t>(i) * 4u + 3u];
            if (!width || !height)
                throw std::runtime_error("texture update rectangle must have positive width and height");
            if (x > mip.width || y > mip.height || width > mip.width - x || height > mip.height - y)
                throw std::runtime_error("texture update rectangle is outside the texture bounds");

            const std::uint64_t pixelCount = static_cast<std::uint64_t>(width) * height;
            if (pixelCount > std::numeric_limits<std::uint64_t>::max() / 4u)
                throw std::runtime_error("texture update byte count overflows uint64");
            const std::uint64_t byteCount = pixelCount * 4u;
            if (byteCount > std::numeric_limits<std::size_t>::max() ||
                payloadOffset > std::numeric_limits<std::size_t>::max() - static_cast<std::size_t>(byteCount))
                throw std::runtime_error("texture update payload span overflows size_t");
            if (batchBytes > std::numeric_limits<std::uint64_t>::max() - byteCount)
                throw std::runtime_error("texture update byte count overflows uint64");
            if (pixelCount > std::numeric_limits<std::size_t>::max())
                throw std::runtime_error("texture update pixel count overflows size_t");

            PendingTextureUpdate update;
            update.textureId = textureId;
            update.x = x;
            update.y = y;
            update.width = width;
            update.height = height;
            update.payloadOffset = payloadOffset;
            update.byteCount = byteCount;
            update.cpuPixels.resize(static_cast<std::size_t>(pixelCount) * 4u);
            const std::uint8_t* source = packedRGBA8 + payloadOffset;
            for (std::size_t component = 0; component < update.cpuPixels.size(); ++component)
                update.cpuPixels[component] = static_cast<float>(source[component]) / 255.0f;
            pending.push_back(std::move(update));
            payloadOffset += static_cast<std::size_t>(byteCount);
            batchBytes += byteCount;
        }

        if (textureUpdateCount_ == std::numeric_limits<std::uint64_t>::max() ||
            textureUploadedBytes_ > std::numeric_limits<std::uint64_t>::max() - batchBytes)
            throw std::runtime_error("texture update statistics would overflow uint64");

        drainGlErrors(gl_);
        const GLenum bufferTarget = GL_PIXEL_UNPACK_BUFFER;
        const GLenum bufferBindingName = GL_PIXEL_UNPACK_BUFFER_BINDING;
        PixelTransferState state = queryPixelTransferState(
            gl_, bufferBindingName, GL_UNPACK_ALIGNMENT, GL_UNPACK_ROW_LENGTH,
            GL_UNPACK_SKIP_ROWS, GL_UNPACK_SKIP_PIXELS);
        TextureTransferStateGuard stateGuard(
            gl_, bufferTarget, GL_UNPACK_ALIGNMENT,
            GL_UNPACK_ROW_LENGTH, GL_UNPACK_SKIP_ROWS, GL_UNPACK_SKIP_PIXELS, state);
        try {
            gl_.BindBuffer(bufferTarget, 0);
            gl_.PixelStorei(GL_UNPACK_ALIGNMENT, 1);
            gl_.PixelStorei(GL_UNPACK_ROW_LENGTH, 0);
            gl_.PixelStorei(GL_UNPACK_SKIP_ROWS, 0);
            gl_.PixelStorei(GL_UNPACK_SKIP_PIXELS, 0);
            requireNoGlError(gl_, "failed to prepare OpenGL texture upload state");

            for (const PendingTextureUpdate& update : pending) {
                gl_.BindTexture(GL_TEXTURE_2D, renderer_->textures_[update.textureId]);
                requireNoGlError(gl_, "failed to bind texture for subregion update");
                texSubImage2D_(GL_TEXTURE_2D, 0, static_cast<GLint>(update.x),
                               static_cast<GLint>(update.y), static_cast<GLsizei>(update.width),
                               static_cast<GLsizei>(update.height), GL_RGBA, GL_UNSIGNED_BYTE,
                               packedRGBA8 + update.payloadOffset);
                requireNoGlError(gl_, "glTexSubImage2D failed for texture " +
                                       std::to_string(update.textureId));
            }
            if (!stateGuard.restore())
                throw std::runtime_error("failed to restore OpenGL texture-upload state");
        } catch (...) {
            stateGuard.restore();
            fatal_ = true;
            fatalMessage_ = "OpenGL texture upload or state restoration may have left the batch partial";
            throw;
        }

        // All GL writes and state restoration succeeded. Commit the same pixels
        // to the authoritative Bundle mip0 without allocating or changing IDs.
        for (const PendingTextureUpdate& update : pending) {
            TextureMip& mip = bundle_.textures[update.textureId].mips.front();
            const std::size_t destinationStride = static_cast<std::size_t>(mip.width) * 4u;
            const std::size_t sourceStride = static_cast<std::size_t>(update.width) * 4u;
            for (std::uint32_t row = 0; row < update.height; ++row) {
                float* destination = mip.faces.data() +
                    static_cast<std::size_t>(update.y + row) * destinationStride +
                    static_cast<std::size_t>(update.x) * 4u;
                const float* source = update.cpuPixels.data() + static_cast<std::size_t>(row) * sourceStride;
                std::copy_n(source, sourceStride, destination);
            }
        }
        ++textureUpdateCount_;
        textureUploadedBytes_ += batchBytes;
        return 1;
    }

    int readTextureRGBA8(std::uint32_t textureId, std::uint8_t* output,
                         std::uint64_t capacityBytes) {
        requireOwner(true);
        const TextureMip& mip = requireEditableTexture(textureId);
        const std::uint64_t pixelCount = static_cast<std::uint64_t>(mip.width) * mip.height;
        if (pixelCount > std::numeric_limits<std::uint64_t>::max() / 4u)
            throw std::runtime_error("texture readback byte count overflows uint64");
        const std::uint64_t byteCount = pixelCount * 4u;
        if (capacityBytes < byteCount)
            throw std::runtime_error("GPU texture readback output buffer is too small");
        if (!output) throw std::runtime_error("GPU texture readback output pointer is null");

        drainGlErrors(gl_);
        const GLenum bufferTarget = GL_PIXEL_PACK_BUFFER;
        const GLenum bufferBindingName = GL_PIXEL_PACK_BUFFER_BINDING;
        PixelTransferState state = queryPixelTransferState(
            gl_, bufferBindingName, GL_PACK_ALIGNMENT, GL_PACK_ROW_LENGTH,
            GL_PACK_SKIP_ROWS, GL_PACK_SKIP_PIXELS);
        TextureTransferStateGuard stateGuard(
            gl_, bufferTarget, GL_PACK_ALIGNMENT,
            GL_PACK_ROW_LENGTH, GL_PACK_SKIP_ROWS, GL_PACK_SKIP_PIXELS, state);
        try {
            gl_.BindBuffer(bufferTarget, 0);
            gl_.PixelStorei(GL_PACK_ALIGNMENT, 1);
            gl_.PixelStorei(GL_PACK_ROW_LENGTH, 0);
            gl_.PixelStorei(GL_PACK_SKIP_ROWS, 0);
            gl_.PixelStorei(GL_PACK_SKIP_PIXELS, 0);
            requireNoGlError(gl_, "failed to prepare OpenGL texture readback state");
            gl_.BindTexture(GL_TEXTURE_2D, renderer_->textures_[textureId]);
            requireNoGlError(gl_, "failed to bind texture for readback");
            getTexImage_(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, output);
            requireNoGlError(gl_, "glGetTexImage failed");
            if (!stateGuard.restore())
                throw std::runtime_error("failed to restore OpenGL texture-readback state");
        } catch (...) {
            stateGuard.restore();
            throw;
        }
        return 1;
    }

    HGLRC context_ = nullptr;
    DWORD ownerThread_ = 0;
    GLApi gl_;
    Bundle bundle_;
    std::vector<CameraFrame> frames_;
    std::unique_ptr<Renderer> renderer_;
    BufferSubDataProc bufferSubData_ = nullptr;
    GetBufferSubDataProc getBufferSubData_ = nullptr;
    TexSubImage2DProc texSubImage2D_ = nullptr;
    GetTexImageProc getTexImage_ = nullptr;
    std::string rendererName_, glVersion_;
    std::uint64_t updateCount_ = 0, uploadedBytes_ = 0;
    std::uint64_t textureUpdateCount_ = 0, textureUploadedBytes_ = 0;
    bool fatal_ = false;
    std::string fatalMessage_;
};

} // namespace spqr

extern "C" __declspec(dllexport) const char* lab_error() {
    return g_lastError.c_str();
}

extern "C" __declspec(dllexport) void* lab_create(const char* bundleDirUtf8, int width, int height) {
    clearError();
    try {
        const auto directory = pathFromUtf8(bundleDirUtf8, "bundle directory");
        return new spqr::TerrainLab(directory, width, height);
    } catch (...) {
        setCurrentException();
        return nullptr;
    }
}

extern "C" __declspec(dllexport) int lab_destroy(void* handle) {
    clearError();
    if (!handle) {
        setError("terrain_lab handle is null");
        return 0;
    }
    auto* lab = static_cast<spqr::TerrainLab*>(handle);
    try {
        lab->requireOwner(true);
        lab->renderer_.reset();
        delete lab;
        return 1;
    } catch (...) {
        setCurrentException();
        return 0;
    }
}

extern "C" __declspec(dllexport) int lab_render(void* handle, std::uint32_t frameIndex) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner();
        lab.renderer_->render(lab.frameAt(frameIndex));
        return 1;
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) int lab_capture(void* handle, const char* stemUtf8,
                                                  std::uint32_t frameIndex) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner();
        const auto& frame = lab.frameAt(frameIndex);
        const auto stats = lab.renderer_->render(frame);
        lab.renderer_->capture(frame, capturePathFromUtf8(stemUtf8, "capture stem"), frameIndex, stats);
        return 1;
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) int lab_capture_color(void* handle, const char* ppmPathUtf8) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner();
        lab.renderer_->captureColor(capturePathFromUtf8(ppmPathUtf8, "PPM output path"), false);
        return 1;
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) std::uint32_t lab_compile_count(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return std::numeric_limits<std::uint32_t>::max(); }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.renderer_ ? lab.renderer_->programCompileCount() : 0;
    } catch (...) { setCurrentException(); return std::numeric_limits<std::uint32_t>::max(); }
}

extern "C" __declspec(dllexport) std::uint32_t lab_mesh_count(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return std::numeric_limits<std::uint32_t>::max(); }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return static_cast<std::uint32_t>(lab.bundle_.meshes.size());
    } catch (...) { setCurrentException(); return std::numeric_limits<std::uint32_t>::max(); }
}

extern "C" __declspec(dllexport) std::int32_t lab_entity_mesh_id(void* handle,
                                                                   std::uint32_t entityIndex) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return -1; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        if (entityIndex >= lab.bundle_.entities.size()) throw std::runtime_error("entity index is out of range");
        return static_cast<std::int32_t>(lab.bundle_.entities[entityIndex].mesh);
    } catch (...) { setCurrentException(); return -1; }
}

extern "C" __declspec(dllexport) std::int32_t lab_entity_texture_id(void* handle,
                                                                       std::uint32_t entityIndex,
                                                                       std::uint32_t slot) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return -1; }
    try {
        return static_cast<std::int32_t>(static_cast<spqr::TerrainLab*>(handle)->entityTextureId(
            entityIndex, slot));
    } catch (...) { setCurrentException(); return -1; }
}

extern "C" __declspec(dllexport) int lab_texture_info(void* handle,
                                                        std::uint32_t textureId,
                                                        std::uint32_t* width,
                                                        std::uint32_t* height) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        return static_cast<spqr::TerrainLab*>(handle)->textureInfo(textureId, width, height);
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) int lab_update_texture_batch(void* handle,
                                                                const std::uint32_t* textureIds,
                                                                const std::uint32_t* rectsXYWH,
                                                                const std::uint8_t* packedRGBA8,
                                                                std::uint32_t batchCount) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        return static_cast<spqr::TerrainLab*>(handle)->updateTextureBatch(
            textureIds, rectsXYWH, packedRGBA8, batchCount);
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) int lab_read_texture_rgba8(void* handle,
                                                              std::uint32_t textureId,
                                                              std::uint8_t* output,
                                                              std::uint64_t capacityBytes) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        return static_cast<spqr::TerrainLab*>(handle)->readTextureRGBA8(
            textureId, output, capacityBytes);
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) std::uint64_t lab_texture_update_count(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return std::numeric_limits<std::uint64_t>::max(); }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.textureUpdateCount_;
    } catch (...) { setCurrentException(); return std::numeric_limits<std::uint64_t>::max(); }
}

extern "C" __declspec(dllexport) std::uint64_t lab_texture_uploaded_bytes(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return std::numeric_limits<std::uint64_t>::max(); }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.textureUploadedBytes_;
    } catch (...) { setCurrentException(); return std::numeric_limits<std::uint64_t>::max(); }
}

extern "C" __declspec(dllexport) std::int32_t lab_mesh_vertex_count(void* handle,
                                                                      std::uint32_t meshId) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return -1; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        if (meshId >= lab.bundle_.meshes.size()) throw std::runtime_error("mesh ID is out of range");
        return static_cast<std::int32_t>(lab.bundle_.meshes[meshId].vertexCount);
    } catch (...) { setCurrentException(); return -1; }
}

extern "C" __declspec(dllexport) int lab_update_batch(void* handle,
                                                        const std::uint32_t* meshIds,
                                                        const std::uint32_t* vertexCounts,
                                                        const float* packedVertices12,
                                                        std::uint32_t batchCount) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        return static_cast<spqr::TerrainLab*>(handle)->updateBatch(
            meshIds, vertexCounts, packedVertices12, batchCount);
    } catch (...) { setCurrentException(); return 0; }
}

extern "C" __declspec(dllexport) std::uint64_t lab_update_count(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return std::numeric_limits<std::uint64_t>::max(); }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.updateCount_;
    } catch (...) { setCurrentException(); return std::numeric_limits<std::uint64_t>::max(); }
}

extern "C" __declspec(dllexport) std::uint64_t lab_uploaded_bytes(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return std::numeric_limits<std::uint64_t>::max(); }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.uploadedBytes_;
    } catch (...) { setCurrentException(); return std::numeric_limits<std::uint64_t>::max(); }
}

extern "C" __declspec(dllexport) const char* lab_renderer_name(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return nullptr; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.rendererName_.c_str();
    } catch (...) { setCurrentException(); return nullptr; }
}

extern "C" __declspec(dllexport) const char* lab_gl_version(void* handle) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return nullptr; }
    try {
        auto& lab = *static_cast<spqr::TerrainLab*>(handle);
        lab.requireOwner(true);
        return lab.glVersion_.c_str();
    } catch (...) { setCurrentException(); return nullptr; }
}

extern "C" __declspec(dllexport) int lab_read_mesh_vertices(void* handle,
                                                             std::uint32_t meshId,
                                                             float* output,
                                                             std::uint32_t floatCapacity) {
    clearError();
    if (!handle) { setError("terrain_lab handle is null"); return 0; }
    try {
        return static_cast<spqr::TerrainLab*>(handle)->readMeshVertices(meshId, output, floatCapacity);
    } catch (...) { setCurrentException(); return 0; }
}
