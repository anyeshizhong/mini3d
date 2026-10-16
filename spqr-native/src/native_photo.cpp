#include "native_photo.h"

#include "renderer.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

thread_local std::string lastError;

struct PhotoRenderer {
    HGLRC context = nullptr;
    DWORD threadId = 0;
    spqr::GLApi gl;
    spqr::Bundle bundle;
    std::unique_ptr<spqr::Renderer> renderer;
};

void clearError() { lastError.clear(); }
void saveError(const char* message) noexcept {
    try { lastError = message ? message : "unknown native photo error"; }
    catch (...) { }
}
void saveError(const std::exception& error) noexcept { saveError(error.what()); }

PhotoRenderer& checked(void* opaque) {
    if (!opaque) throw std::runtime_error("photo renderer handle is null");
    auto& state = *static_cast<PhotoRenderer*>(opaque);
    if (GetCurrentThreadId() != state.threadId)
        throw std::runtime_error("photo renderer must be called on its creating thread");
    if (wglGetCurrentContext() != state.context)
        throw std::runtime_error("photo renderer requires its creating OpenGL context to be current");
    return state;
}

std::uint32_t readU32(const std::byte* bytes, std::size_t length, std::size_t& cursor) {
    if (cursor > length || length - cursor < sizeof(std::uint32_t))
        throw std::runtime_error("truncated photo globals UniformBlock header");
    std::uint32_t value = 0;
    std::memcpy(&value, bytes + cursor, sizeof(value));
    cursor += sizeof(value);
    return value;
}

bool isSamplerType(std::uint32_t type) {
    switch (type) {
    case GL_SAMPLER_1D: case GL_SAMPLER_2D: case GL_SAMPLER_3D: case GL_SAMPLER_CUBE:
    case GL_SAMPLER_1D_SHADOW: case GL_SAMPLER_2D_SHADOW: case GL_SAMPLER_1D_ARRAY:
    case GL_SAMPLER_2D_ARRAY: case GL_SAMPLER_1D_ARRAY_SHADOW: case GL_SAMPLER_2D_ARRAY_SHADOW:
    case GL_SAMPLER_2D_MULTISAMPLE: case GL_SAMPLER_2D_MULTISAMPLE_ARRAY:
    case GL_SAMPLER_CUBE_SHADOW: case GL_SAMPLER_BUFFER: case GL_SAMPLER_2D_RECT:
    case GL_SAMPLER_2D_RECT_SHADOW: case GL_INT_SAMPLER_1D: case GL_INT_SAMPLER_2D:
    case GL_INT_SAMPLER_3D: case GL_INT_SAMPLER_CUBE: case GL_INT_SAMPLER_1D_ARRAY:
    case GL_INT_SAMPLER_2D_ARRAY: case GL_INT_SAMPLER_2D_MULTISAMPLE:
    case GL_INT_SAMPLER_2D_MULTISAMPLE_ARRAY: case GL_INT_SAMPLER_BUFFER:
    case GL_INT_SAMPLER_2D_RECT: case GL_UNSIGNED_INT_SAMPLER_1D:
    case GL_UNSIGNED_INT_SAMPLER_2D: case GL_UNSIGNED_INT_SAMPLER_3D:
    case GL_UNSIGNED_INT_SAMPLER_CUBE: case GL_UNSIGNED_INT_SAMPLER_1D_ARRAY:
    case GL_UNSIGNED_INT_SAMPLER_2D_ARRAY: case GL_UNSIGNED_INT_SAMPLER_2D_MULTISAMPLE:
    case GL_UNSIGNED_INT_SAMPLER_2D_MULTISAMPLE_ARRAY: case GL_UNSIGNED_INT_SAMPLER_BUFFER:
    case GL_UNSIGNED_INT_SAMPLER_2D_RECT:
        return true;
    default:
        return false;
    }
}

int vectorWidth(std::uint32_t type) {
    switch (type) {
    case GL_INT_VEC2: case GL_BOOL_VEC2: case GL_FLOAT_VEC2: return 2;
    case GL_INT_VEC3: case GL_BOOL_VEC3: case GL_FLOAT_VEC3: return 3;
    case GL_INT_VEC4: case GL_BOOL_VEC4: case GL_FLOAT_VEC4: return 4;
    default: return 1;
    }
}

int matrixDimension(std::uint32_t type) {
    switch (type) {
    case GL_FLOAT_MAT2: return 2;
    case GL_FLOAT_MAT3: return 3;
    case GL_FLOAT_MAT4: return 4;
    default: return 0;
    }
}

void validateUniform(const spqr::UniformValue& value) {
    const auto type = value.type;
    const int matrix = matrixDimension(type);
    if (matrix) {
        if (value.components % static_cast<std::uint32_t>(matrix * matrix))
            throw std::runtime_error("photo globals matrix component count is invalid: " + value.name);
        return;
    }
    const int width = vectorWidth(type);
    const bool integerType = type == GL_INT || type == GL_BOOL || isSamplerType(type) ||
        type == GL_INT_VEC2 || type == GL_INT_VEC3 || type == GL_INT_VEC4 ||
        type == GL_BOOL_VEC2 || type == GL_BOOL_VEC3 || type == GL_BOOL_VEC4;
    const bool floatType = type == GL_FLOAT || type == GL_FLOAT_VEC2 ||
        type == GL_FLOAT_VEC3 || type == GL_FLOAT_VEC4;
    if (!integerType && !floatType)
        throw std::runtime_error("unsupported photo globals uniform type " + std::to_string(type) +
                                 " for " + value.name);
    if (value.components % static_cast<std::uint32_t>(width))
        throw std::runtime_error("photo globals vector component count is invalid: " + value.name);
}

spqr::UniformBlock readUniformBlock(const std::byte* bytes, std::size_t length,
                                    std::size_t& cursor) {
    const std::uint32_t count = readU32(bytes, length, cursor);
    if (count > 65536u) throw std::runtime_error("photo globals uniform count exceeds safety limit");
    spqr::UniformBlock block;
    block.reserve(count);
    for (std::uint32_t i = 0; i < count; ++i) {
        const std::uint32_t nameLength = readU32(bytes, length, cursor);
        if (nameLength == 0 || nameLength > 4096u)
            throw std::runtime_error("photo globals uniform name length is invalid");
        if (cursor > length || nameLength > length - cursor)
            throw std::runtime_error("truncated photo globals uniform name");
        spqr::UniformValue value;
        value.name.assign(reinterpret_cast<const char*>(bytes + cursor), nameLength);
        cursor += nameLength;
        if (value.name.find('\0') != std::string::npos)
            throw std::runtime_error("photo globals uniform name contains NUL");
        value.type = readU32(bytes, length, cursor);
        value.components = readU32(bytes, length, cursor);
        if (value.components == 0 || value.components > 65536u)
            throw std::runtime_error("photo globals component count is invalid: " + value.name);
        const std::size_t byteCount = static_cast<std::size_t>(value.components) * sizeof(std::uint32_t);
        if (cursor > length || byteCount > length - cursor)
            throw std::runtime_error("truncated photo globals uniform data: " + value.name);
        value.bytes.resize(byteCount);
        std::memcpy(value.bytes.data(), bytes + cursor, byteCount);
        cursor += byteCount;
        validateUniform(value);
        block.push_back(std::move(value));
    }
    return block;
}

std::pair<spqr::UniformBlock, spqr::UniformBlock> parseGlobals(const void* data,
                                                              std::size_t length) {
    if (!data) throw std::runtime_error("photo globals byte buffer is null");
    if (length == 0 || length > 32u * 1024u * 1024u)
        throw std::runtime_error("photo globals byte length must be between 1 and 32 MiB");
    if (std::endian::native != std::endian::little)
        throw std::runtime_error("photo globals parser requires a little-endian host");
    const auto* bytes = static_cast<const std::byte*>(data);
    std::size_t cursor = 0;
    auto material = readUniformBlock(bytes, length, cursor);
    auto sky = readUniformBlock(bytes, length, cursor);
    if (cursor != length) throw std::runtime_error("photo globals contain trailing bytes");
    return {std::move(material), std::move(sky)};
}

spqr::CameraFrame parseCamera(const double* values) {
    if (!values) throw std::runtime_error("photo camera46 pointer is null");
    for (std::size_t i = 0; i < 46; ++i)
        if (!std::isfinite(values[i])) throw std::runtime_error("photo camera46 contains a non-finite value");
    spqr::CameraFrame frame;
    frame.route = "photo";
    std::copy_n(values, 3, frame.position.begin());
    std::copy_n(values + 3, 9, frame.rotation.begin());
    std::copy_n(values + 12, 16, frame.view.begin());
    std::copy_n(values + 28, 16, frame.projection.begin());
    frame.nearPlane = values[44];
    frame.farPlane = values[45];
    if (!(frame.nearPlane > 0.0) || !(frame.farPlane > frame.nearPlane))
        throw std::runtime_error("photo camera near/far planes are invalid");
    return frame;
}

template<class Function>
int runGuarded(void* opaque, Function&& function) noexcept {
    clearError();
    try {
        auto& state = checked(opaque);
        function(state);
        return 1;
    } catch (const std::exception& error) {
        saveError(error);
    } catch (...) {
        saveError("unknown C++ exception in native photo API");
    }
    return 0;
}

} // namespace

extern "C" __declspec(dllexport) std::uint32_t spqr_photo_abi_version(void) {
    return 1;
}

extern "C" __declspec(dllexport) void* spqr_photo_create(const wchar_t* bundleDir,
                                                           int width, int height, int samples) {
    clearError();
    try {
        if (!bundleDir || !*bundleDir) throw std::runtime_error("bundleDir must be a non-empty path");
        if (width <= 0 || height <= 0) throw std::runtime_error("photo dimensions must be positive");
        if (samples != 1 && samples != 4) throw std::runtime_error("photo samples must be 1 or 4");
        auto state = std::make_unique<PhotoRenderer>();
        state->context = wglGetCurrentContext();
        state->threadId = GetCurrentThreadId();
        if (!state->context)
            throw std::runtime_error("spqr_photo_create requires a current OpenGL context");
        std::string loadError;
        if (!state->gl.load(loadError)) throw std::runtime_error(loadError);
        const std::filesystem::path directory(bundleDir);
        state->bundle = spqr::loadBundle(directory);
        state->renderer = std::make_unique<spqr::Renderer>(state->gl, state->bundle, directory,
                                                           width, height, true, samples, true);
        return state.release();
    } catch (const std::exception& error) {
        saveError(error);
    } catch (...) {
        saveError("unknown C++ exception creating native photo renderer");
    }
    return nullptr;
}

extern "C" __declspec(dllexport) int spqr_photo_resize(void* instance,
                                                        int width, int height, int samples) {
    return runGuarded(instance, [&](PhotoRenderer& state) {
        state.renderer->resize(width, height, samples);
    });
}

extern "C" __declspec(dllexport) int spqr_photo_globals(void* instance,
                                                         const void* bytes, size_t length,
                                                         const double* lightDirection,
                                                         uint32_t farShadowResolution,
                                                         float shadowBias, int shadowEnabled,
                                                         double groundZ) {
    return runGuarded(instance, [&](PhotoRenderer& state) {
        if (!lightDirection) throw std::runtime_error("photo globals lightDirection pointer is null");
        auto blocks = parseGlobals(bytes, length);
        const std::array<double, 3> direction{
            lightDirection[0], lightDirection[1], lightDirection[2]};
        state.renderer->updateGlobals(std::move(blocks.first), std::move(blocks.second), direction,
                                      farShadowResolution, shadowBias, shadowEnabled != 0, groundZ);
    });
}

extern "C" __declspec(dllexport) int spqr_photo_render(void* instance,
                                                        const double* camera46,
                                                        uint32_t targetSingleSampleFbo,
                                                        double* stats8) {
    if (stats8) std::fill_n(stats8, 8, 0.0);
    return runGuarded(instance, [&](PhotoRenderer& state) {
        if (!targetSingleSampleFbo)
            throw std::runtime_error("photo render requires a caller-owned nonzero single-sample FBO");
        if (!stats8) throw std::runtime_error("photo stats8 pointer is null");
        const spqr::CameraFrame frame = parseCamera(camera46);
        const spqr::FrameStats stats = state.renderer->render(frame, targetSingleSampleFbo);
        stats8[0] = stats.colorNear;
        stats8[1] = frame.farPlane;
        stats8[2] = static_cast<double>(stats.colorDraws);
        stats8[3] = static_cast<double>(stats.shadowDraws);
        stats8[4] = static_cast<double>(stats.colorTriangles);
        stats8[5] = static_cast<double>(stats.shadowTriangles);
        stats8[6] = 0.0;
        stats8[7] = 0.0;
    });
}

extern "C" __declspec(dllexport) int spqr_photo_destroy(void* instance) {
    clearError();
    try {
        auto& state = checked(instance);
        delete &state;
        return 1;
    } catch (const std::exception& error) {
        saveError(error);
    } catch (...) {
        saveError("unknown C++ exception destroying native photo renderer");
    }
    return 0;
}

extern "C" __declspec(dllexport) const char* spqr_photo_last_error(void) {
    return lastError.c_str();
}
