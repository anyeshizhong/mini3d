#include "renderer.hpp"

#include "shadow_fit.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <mutex>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <unordered_map>

namespace spqr {

struct ProgramSet {
    decltype(&::glDeleteProgram) deleteProgram = nullptr;
    GLuint material = 0;
    GLuint ground = 0;
    GLuint sky = 0;
    GLuint shadow = 0;

    ~ProgramSet() {
        if (!deleteProgram) return;
        for (GLuint program : {material, ground, sky, shadow})
            if (program) deleteProgram(program);
    }
};

namespace {
constexpr std::uint32_t kNone = 0xffffffffu;
constexpr GLenum GL_TEXTURE_COMPARE_MODE_VALUE = 0x884c;
constexpr GLenum GL_TEXTURE_COMPARE_FUNC_VALUE = 0x884d;
constexpr GLenum GL_COMPARE_REF_TO_TEXTURE_VALUE = 0x884e;
constexpr GLenum GL_CLAMP_TO_BORDER_VALUE = 0x812d;
constexpr GLenum GL_TEXTURE_MAX_LEVEL_VALUE = 0x813d;
constexpr GLenum GL_TEXTURE_BORDER_COLOR_VALUE = 0x1004;
constexpr GLenum GL_DEPTH_COMPONENT24_VALUE = 0x81a6;
constexpr GLenum GL_FRAMEBUFFER_SRGB_VALUE = 0x8db9;
constexpr GLenum GL_POLYGON_OFFSET_FILL_VALUE = 0x8037;

using M4 = std::array<double, 16>;
using M3 = std::array<double, 9>;

std::string loadRendererShader(const std::filesystem::path& path, bool stableShadows,
                               const std::filesystem::path& shaderDirectory) {
    std::string source = readTextFile(path);
    if (stableShadows && (path.filename() == "material.frag" || path.filename() == "ground.frag")) {
        const auto begin = source.find("float shadowVisibility(");
        const auto end = source.find("uniform bool photoColorEnabled;", begin);
        if (begin == std::string::npos || end == std::string::npos)
            throw std::runtime_error("material shader lacks native shadow replacement markers");
        source.replace(begin, end - begin, readTextFile(shaderDirectory / "shadow_cascade.glsl") + "\n");
    }
    return source;
}

RendererShaderSources loadRendererShaderSources(const std::filesystem::path& shaderDirectory,
                                                 bool stableShadows) {
    RendererShaderSources sources;
    sources.materialVertex = loadRendererShader(shaderDirectory / "material.vert", stableShadows,
                                                shaderDirectory);
    sources.materialFragment = loadRendererShader(shaderDirectory / "material.frag", stableShadows,
                                                  shaderDirectory);
    const auto groundVertex = shaderDirectory / "ground.vert";
    const auto groundFragment = shaderDirectory / "ground.frag";
    sources.hasGroundVertex = std::filesystem::exists(groundVertex);
    sources.hasGroundFragment = std::filesystem::exists(groundFragment);
    if (sources.hasGroundVertex)
        sources.groundVertex = loadRendererShader(groundVertex, stableShadows, shaderDirectory);
    if (sources.hasGroundFragment)
        sources.groundFragment = loadRendererShader(groundFragment, stableShadows, shaderDirectory);
    sources.skyVertex = loadRendererShader(shaderDirectory / "sky.vert", stableShadows, shaderDirectory);
    sources.skyFragment = loadRendererShader(shaderDirectory / "sky.frag", stableShadows, shaderDirectory);
    sources.shadowVertex = loadRendererShader(shaderDirectory / "shadow.vert", stableShadows, shaderDirectory);
    sources.shadowFragment = loadRendererShader(shaderDirectory / "shadow.frag", stableShadows, shaderDirectory);
    return sources;
}

void appendCacheField(std::string& key, std::string_view name, const std::string& source) {
    const auto nameSize = static_cast<std::uint64_t>(name.size());
    const auto sourceSize = static_cast<std::uint64_t>(source.size());
    key.append(reinterpret_cast<const char*>(&nameSize), sizeof(nameSize));
    key.append(name.data(), name.size());
    key.append(reinterpret_cast<const char*>(&sourceSize), sizeof(sourceSize));
    key.append(source.data(), source.size());
}

std::string programCacheKey(HGLRC context, bool stableShadows,
                            const RendererShaderSources& sources) {
    std::string key;
    key.reserve(256 + sources.materialVertex.size() + sources.materialFragment.size() +
                sources.groundVertex.size() + sources.groundFragment.size() +
                sources.skyVertex.size() + sources.skyFragment.size() +
                sources.shadowVertex.size() + sources.shadowFragment.size());
    const auto contextValue = reinterpret_cast<std::uintptr_t>(context);
    key.append(reinterpret_cast<const char*>(&contextValue), sizeof(contextValue));
    key.push_back(stableShadows ? '\1' : '\0');
    key.push_back(sources.hasGroundVertex ? '\1' : '\0');
    key.push_back(sources.hasGroundFragment ? '\1' : '\0');
    appendCacheField(key, "material.vert", sources.materialVertex);
    appendCacheField(key, "material.frag", sources.materialFragment);
    appendCacheField(key, "ground.vert", sources.groundVertex);
    appendCacheField(key, "ground.frag", sources.groundFragment);
    appendCacheField(key, "sky.vert", sources.skyVertex);
    appendCacheField(key, "sky.frag", sources.skyFragment);
    appendCacheField(key, "shadow.vert", sources.shadowVertex);
    appendCacheField(key, "shadow.frag", sources.shadowFragment);
    return key;
}

std::shared_ptr<ProgramSet> acquireProgramSet(GLApi& gl, HGLRC context,
                                              bool stableShadows,
                                              const RendererShaderSources& sources) {
    static std::mutex cacheMutex;
    static std::unordered_map<std::string, std::weak_ptr<ProgramSet>> cache;
    std::string key = programCacheKey(context, stableShadows, sources);
    std::lock_guard lock(cacheMutex);
    for (auto it = cache.begin(); it != cache.end();) {
        if (it->second.expired()) it = cache.erase(it);
        else ++it;
    }
    const auto found = cache.find(key);
    if (found != cache.end()) {
        if (auto existing = found->second.lock()) return existing;
        cache.erase(found);
    }
    auto programs = std::make_shared<ProgramSet>();
    programs->deleteProgram = gl.DeleteProgram;
    cache.emplace(std::move(key), programs);
    return programs;
}

float f32(double value) { return static_cast<float>(value); }
std::array<float, 16> floatMatrix(const M4& value) {
    std::array<float, 16> out{};
    for (std::size_t i = 0; i < out.size(); ++i) out[i] = f32(value[i]);
    return out;
}
M4 floatRoundTrip(const M4& value) {
    M4 out{};
    for (std::size_t i = 0; i < out.size(); ++i) out[i] = static_cast<double>(f32(value[i]));
    return out;
}
M4 multiply4(const M4& a, const M4& b) {
    M4 out{};
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c)
            for (int k = 0; k < 4; ++k) out[r * 4 + c] += a[r * 4 + k] * b[k * 4 + c];
    return out;
}
M4 inverse4(const M4& source) {
    double a[4][8]{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) a[r][c] = source[r * 4 + c];
        a[r][4 + r] = 1.0;
    }
    for (int c = 0; c < 4; ++c) {
        int pivot = c;
        for (int r = c + 1; r < 4; ++r)
            if (std::abs(a[r][c]) > std::abs(a[pivot][c])) pivot = r;
        if (!std::isfinite(a[pivot][c]) || std::abs(a[pivot][c]) < 1e-30)
            throw std::runtime_error("camera projection matrix is singular");
        if (pivot != c) for (int j = 0; j < 8; ++j) std::swap(a[pivot][j], a[c][j]);
        const double divisor = a[c][c];
        for (double& value : a[c]) value /= divisor;
        for (int r = 0; r < 4; ++r) if (r != c) {
            const double factor = a[r][c];
            for (int j = 0; j < 8; ++j) a[r][j] -= factor * a[c][j];
        }
    }
    M4 out{};
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) out[r * 4 + c] = a[r][c + 4];
    return out;
}
std::array<float, 9> inverseTranspose3x3(const M4& matrix) {
    float a[3][6]{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) a[r][c] = f32(matrix[r * 4 + c]);
        a[r][r + 3] = 1.0f;
    }
    for (int c = 0; c < 3; ++c) {
        int pivot = c;
        for (int r = c + 1; r < 3; ++r)
            if (std::abs(a[r][c]) > std::abs(a[pivot][c])) pivot = r;
        if (!std::isfinite(a[pivot][c]) || std::abs(a[pivot][c]) < 1e-12f)
            throw std::runtime_error("singular transform is unsupported by native setTransform");
        if (pivot != c) for (int j = 0; j < 6; ++j) std::swap(a[pivot][j], a[c][j]);
        const float divisor = a[c][c];
        for (float& value : a[c]) value /= divisor;
        for (int r = 0; r < 3; ++r) if (r != c) {
            const float factor = a[r][c];
            for (int j = 0; j < 6; ++j) a[r][j] -= factor * a[c][j];
        }
    }
    std::array<float, 9> out{};
    for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) out[r * 3 + c] = a[c][r + 3];
    return out;
}
std::array<double, 3> normalize3(std::array<double, 3> v) {
    const double length = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (length <= 0 || !std::isfinite(length)) throw std::runtime_error("cannot normalize camera light direction");
    for (double& x : v) x /= length;
    return v;
}
std::array<double, 3> add3(std::array<double, 3> a, std::array<double, 3> b, double scaleB = 1) {
    for (int i = 0; i < 3; ++i) a[i] += b[i] * scaleB;
    return a;
}
std::array<double, 3> rotationColumn(const std::array<double, 9>& rotation, int column) {
    return {rotation[column], rotation[3 + column], rotation[6 + column]};
}
float det3(const float a[3][3]) {
    return a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) -
           a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) +
           a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]);
}

bool isSampler(GLenum type) {
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
    default: return false;
    }
}
bool isIntegerUniform(GLenum type) {
    return type == GL_INT || type == GL_BOOL || type == GL_INT_VEC2 || type == GL_INT_VEC3 ||
           type == GL_INT_VEC4 || type == GL_BOOL_VEC2 || type == GL_BOOL_VEC3 ||
           type == GL_BOOL_VEC4 || isSampler(type);
}
int uniformWidth(GLenum type) {
    switch (type) {
    case GL_INT_VEC2: case GL_BOOL_VEC2: case GL_FLOAT_VEC2: return 2;
    case GL_INT_VEC3: case GL_BOOL_VEC3: case GL_FLOAT_VEC3: return 3;
    case GL_INT_VEC4: case GL_BOOL_VEC4: case GL_FLOAT_VEC4: return 4;
    default: return 1;
    }
}
int matrixWidth(GLenum type) {
    switch (type) {
    case GL_FLOAT_MAT2: return 2;
    case GL_FLOAT_MAT3: return 3;
    case GL_FLOAT_MAT4: return 4;
    default: return 0;
    }
}
const std::int32_t* intData(const UniformValue& value) {
    return reinterpret_cast<const std::int32_t*>(value.bytes.data());
}
const float* floatData(const UniformValue& value) {
    return reinterpret_cast<const float*>(value.bytes.data());
}
} // namespace

Renderer::Renderer(GLApi& gl, Bundle& bundle, const std::filesystem::path& bundleDirectory,
                   int width, int height, bool stabilizeDepth, int msaaSamples, bool stableShadows,
                   bool deferred)
    : gl_(gl), bundle_(bundle), shaderDirectory_(bundleDirectory / "shaders"),
      width_(width), height_(height), msaaSamples_(msaaSamples), stabilizeDepth_(stabilizeDepth),
      stableShadows_(stableShadows) {
    if (width <= 0 || height <= 0) throw std::runtime_error("invalid render dimensions");
    if (msaaSamples_ != 1 && msaaSamples_ != 4)
        throw std::runtime_error("renderer samples must be 1 or 4");
    try {
        if (!deferred)
            while (!initializeStep()) { }
    } catch (...) {
        close();
        throw;
    }
}

Renderer::~Renderer() { close(); }

bool Renderer::initializeStep() {
    if (closed_) throw std::runtime_error("renderer is closed");
    if (ready_) return true;
    try {
        if (!programSet_) {
            const HGLRC context = wglGetCurrentContext();
            if (!context) throw std::runtime_error("renderer initialization requires a current OpenGL context");
            shaderSources_ = loadRendererShaderSources(shaderDirectory_, stableShadows_);
            programSet_ = acquireProgramSet(gl_, context, stableShadows_, shaderSources_);
        }
        switch (initStage_) {
        case InitStage::Material:
            if (!programSet_->material) {
                programSet_->material = compileProgram(shaderSources_.materialVertex,
                    shaderSources_.materialFragment, shaderDirectory_ / "material.vert",
                    shaderDirectory_ / "material.frag");
                ++programCompileCount_;
            }
            materialProgram_ = programSet_->material;
            initStage_ = InitStage::Ground;
            break;
        case InitStage::Ground:
            if (std::any_of(bundle_.entities.begin(), bundle_.entities.end(),
                            [](const Entity& entity) { return (entity.flags & 1u) != 0; }) &&
                shaderSources_.hasGroundVertex) {
                if (!shaderSources_.hasGroundFragment)
                    throw std::runtime_error("cannot open shader: " +
                                             (shaderDirectory_ / "ground.frag").string());
                if (!programSet_->ground) {
                    programSet_->ground = compileProgram(shaderSources_.groundVertex,
                        shaderSources_.groundFragment, shaderDirectory_ / "ground.vert",
                        shaderDirectory_ / "ground.frag");
                    ++programCompileCount_;
                }
                groundProgram_ = programSet_->ground;
            }
            initStage_ = InitStage::Sky;
            break;
        case InitStage::Sky:
            if (!programSet_->sky) {
                programSet_->sky = compileProgram(shaderSources_.skyVertex, shaderSources_.skyFragment,
                    shaderDirectory_ / "sky.vert", shaderDirectory_ / "sky.frag");
                ++programCompileCount_;
            }
            skyProgram_ = programSet_->sky;
            initStage_ = InitStage::Shadow;
            break;
        case InitStage::Shadow:
            if (!programSet_->shadow) {
                programSet_->shadow = compileProgram(shaderSources_.shadowVertex,
                    shaderSources_.shadowFragment, shaderDirectory_ / "shadow.vert",
                    shaderDirectory_ / "shadow.frag");
                ++programCompileCount_;
            }
            shadowProgram_ = programSet_->shadow;
            initStage_ = InitStage::Textures;
            break;
        case InitStage::Textures:
            uploadTextures();
            meshes_.resize(bundle_.meshes.size());
            initStage_ = InitStage::Meshes;
            break;
        case InitStage::Meshes:
            if (nextMesh_ < bundle_.meshes.size()) uploadMesh(nextMesh_++);
            if (nextMesh_ == bundle_.meshes.size()) initStage_ = InitStage::Finalize;
            break;
        case InitStage::Finalize: {
            gl_.GenVertexArrays(1, &skyVao_);
            createColorTarget();

            const std::array<std::pair<const char*, GLint>, 13> samplers{{
                {"baseMap",0},{"mrMap",1},{"normalMap",2},{"aoMap",3},{"emissiveMap",4},
                {"specularMap",5},{"specularColorMap",6},{"shadowDepth",7},{"diffuseEnv",8},
                {"specularEnv",9},{"brdfLut",10},{"photoSky",11},{"shadowRaw",12}}};
            for (GLuint program : {materialProgram_, groundProgram_}) {
                if (!program) continue;
                gl_.UseProgram(program);
                for (const auto& [name, unit] : samplers) setUniform1i(program, name, unit);
                setUniform1i(program, "shadowNearDepth", 13);
                setUniform1i(program, "shadowNearRaw", 14);
            }
            gl_.UseProgram(skyProgram_);
            setUniform1i(skyProgram_, "photoSky", 11);
            gl_.UseProgram(shadowProgram_);
            setUniform1i(shadowProgram_, "baseMap", 0);
            applyGlobalUniforms();
            gl_.UseProgram(0);
            checkError("renderer initialization");
            ready_ = true;
            initStage_ = InitStage::Ready;
            break;
        }
        case InitStage::Ready:
            ready_ = true;
            break;
        }
        return ready_;
    } catch (...) {
        close();
        throw;
    }
}

GLuint Renderer::compileShader(const std::string& source, const std::filesystem::path& path, GLenum type) {
    if (source.empty()) throw std::runtime_error("empty shader source: " + path.string());
    const GLuint shader = gl_.CreateShader(type);
    const GLchar* sourcePointer = source.c_str();
    const GLint sourceLength = static_cast<GLint>(source.size());
    gl_.ShaderSource(shader, 1, &sourcePointer, &sourceLength);
    gl_.CompileShader(shader);
    GLint ok = GL_FALSE;
    gl_.GetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (ok != GL_TRUE) {
        GLint size = 0;
        gl_.GetShaderiv(shader, GL_INFO_LOG_LENGTH, &size);
        std::string log(std::max(1, size), '\0');
        GLsizei written = 0;
        gl_.GetShaderInfoLog(shader, static_cast<GLsizei>(log.size()), &written, log.data());
        log.resize(std::max<GLsizei>(0, written));
        gl_.DeleteShader(shader);
        throw std::runtime_error("shader compile failed at " + path.string() + ":\n" + log);
    }
    return shader;
}

GLuint Renderer::compileProgram(const std::string& vertexSource, const std::string& fragmentSource,
                                const std::filesystem::path& vertex,
                                const std::filesystem::path& fragment) {
    GLuint vs = compileShader(vertexSource, vertex, GL_VERTEX_SHADER);
    GLuint fs = 0;
    GLuint program = 0;
    try {
        fs = compileShader(fragmentSource, fragment, GL_FRAGMENT_SHADER);
        program = gl_.CreateProgram();
        gl_.AttachShader(program, vs);
        gl_.AttachShader(program, fs);
        gl_.LinkProgram(program);
        GLint ok = GL_FALSE;
        gl_.GetProgramiv(program, GL_LINK_STATUS, &ok);
        if (ok != GL_TRUE) {
            GLint size = 0;
            gl_.GetProgramiv(program, GL_INFO_LOG_LENGTH, &size);
            std::string log(std::max(1, size), '\0');
            GLsizei written = 0;
            gl_.GetProgramInfoLog(program, static_cast<GLsizei>(log.size()), &written, log.data());
            log.resize(std::max<GLsizei>(0, written));
            throw std::runtime_error("program link failed for " + vertex.string() + " + " +
                                     fragment.string() + ":\n" + log);
        }
    } catch (...) {
        if (program) gl_.DeleteProgram(program);
        if (fs) gl_.DeleteShader(fs);
        gl_.DeleteShader(vs);
        throw;
    }
    gl_.DeleteShader(vs);
    gl_.DeleteShader(fs);
    return program;
}

GLint Renderer::uniformLocation(GLuint program, const std::string& name) {
    auto& cache = locations_[program];
    const auto found = cache.find(name);
    if (found != cache.end()) return found->second;
    const GLint location = gl_.GetUniformLocation(program, name.c_str());
    cache.emplace(name, location);
    return location;
}

void Renderer::setUniform1i(GLuint program, const char* name, GLint value) {
    const GLint loc = uniformLocation(program, name);
    if (loc >= 0) gl_.Uniform1i(loc, value);
}
void Renderer::setUniform1f(GLuint program, const char* name, GLfloat value) {
    const GLint loc = uniformLocation(program, name);
    if (loc >= 0) gl_.Uniform1f(loc, value);
}
void Renderer::setUniform3f(GLuint program, const char* name, GLfloat x, GLfloat y, GLfloat z) {
    const GLint loc = uniformLocation(program, name);
    if (loc >= 0) gl_.Uniform3f(loc, x, y, z);
}
void Renderer::setUniformMatrix4(GLuint program, const char* name, const float* value) {
    const GLint loc = uniformLocation(program, name);
    if (loc >= 0) gl_.UniformMatrix4fv(loc, 1, GL_TRUE, value);
}
void Renderer::setUniformMatrix3(GLuint program, const char* name, const float* value) {
    const GLint loc = uniformLocation(program, name);
    if (loc >= 0) gl_.UniformMatrix3fv(loc, 1, GL_TRUE, value);
}

void Renderer::applyUniformBlock(GLuint program, const UniformBlock& block) {
    for (const UniformValue& value : block) {
        const GLenum type = value.type;
        const GLint location = uniformLocation(program, value.name);
        const int width = uniformWidth(type);
        const int matrix = matrixWidth(type);
        if (matrix) {
            const int per = matrix * matrix;
            if (value.components % per) throw std::runtime_error("uniform matrix data length mismatch: " + value.name);
            const GLsizei count = static_cast<GLsizei>(value.components / per);
            if (type == GL_FLOAT_MAT2) gl_.UniformMatrix2fv(location, count, GL_TRUE, floatData(value));
            else if (type == GL_FLOAT_MAT3) gl_.UniformMatrix3fv(location, count, GL_TRUE, floatData(value));
            else gl_.UniformMatrix4fv(location, count, GL_TRUE, floatData(value));
        } else if (isIntegerUniform(type)) {
            if (value.components % width) throw std::runtime_error("integer uniform data length mismatch: " + value.name);
            if (location < 0) continue;
            const GLsizei count = static_cast<GLsizei>(value.components / width);
            const auto* data = intData(value);
            if (width == 1) gl_.Uniform1iv(location, count, data);
            else if (width == 2) gl_.Uniform2iv(location, count, data);
            else if (width == 3) gl_.Uniform3iv(location, count, data);
            else gl_.Uniform4iv(location, count, data);
        } else if (type == GL_FLOAT || type == GL_FLOAT_VEC2 || type == GL_FLOAT_VEC3 || type == GL_FLOAT_VEC4) {
            if (value.components % width) throw std::runtime_error("float uniform data length mismatch: " + value.name);
            if (location < 0) continue;
            const GLsizei count = static_cast<GLsizei>(value.components / width);
            const auto* data = floatData(value);
            if (width == 1) gl_.Uniform1fv(location, count, data);
            else if (width == 2) gl_.Uniform2fv(location, count, data);
            else if (width == 3) gl_.Uniform3fv(location, count, data);
            else gl_.Uniform4fv(location, count, data);
        } else {
            throw std::runtime_error("unsupported exported uniform type " + std::to_string(type) +
                                     " for " + value.name);
        }
    }
}

void Renderer::uploadTextures() {
    textures_.assign(bundle_.textures.size(), 0);
    gl_.PixelStorei(GL_UNPACK_ALIGNMENT, 1);
    GLint maxTextureSize = 0;
    gl_.GetIntegerv(GL_MAX_TEXTURE_SIZE, &maxTextureSize);
    for (std::size_t i = 0; i < bundle_.textures.size(); ++i) {
        const Texture& texture = bundle_.textures[i];
        const GLenum target = texture.target;
        if (texture.borrowedHandle) {
            if (!glIsTexture(texture.borrowedHandle))
                throw std::runtime_error("borrowed texture does not exist in the current context");
            // Bind to validate its target, but retain all caller sampling/storage.
            gl_.BindTexture(target, texture.borrowedHandle);
            checkError("validate borrowed texture target");
            textures_[i] = texture.borrowedHandle;
            continue;
        }
        if (texture.mips.front().width > static_cast<std::uint32_t>(maxTextureSize) ||
            texture.mips.front().height > static_cast<std::uint32_t>(maxTextureSize))
            throw std::runtime_error("texture " + std::to_string(i) + " exceeds GL_MAX_TEXTURE_SIZE");
        GLuint handle = 0;
        gl_.GenTextures(1, &handle);
        textures_[i] = handle;
        gl_.BindTexture(target, handle);
        for (std::size_t level = 0; level < texture.mips.size(); ++level) {
            const TextureMip& mip = texture.mips[level];
            const std::size_t faceTexels = static_cast<std::size_t>(mip.width) * mip.height * 4u;
            const int faceCount = target == GL_TEXTURE_CUBE_MAP ? 6 : 1;
            for (int face = 0; face < faceCount; ++face) {
                const GLenum imageTarget = target == GL_TEXTURE_CUBE_MAP
                    ? GL_TEXTURE_CUBE_MAP_POSITIVE_X + face : GL_TEXTURE_2D;
                gl_.TexImage2D(imageTarget, static_cast<GLint>(level),
                    static_cast<GLint>(texture.internalFormat), static_cast<GLsizei>(mip.width),
                    static_cast<GLsizei>(mip.height), 0, GL_RGBA, GL_FLOAT,
                    mip.faces.data() + faceTexels * static_cast<std::size_t>(face));
            }
        }
        gl_.TexParameteri(target, GL_TEXTURE_MIN_FILTER, static_cast<GLint>(texture.minFilter));
        gl_.TexParameteri(target, GL_TEXTURE_MAG_FILTER, static_cast<GLint>(texture.magFilter));
        gl_.TexParameteri(target, GL_TEXTURE_WRAP_S, static_cast<GLint>(texture.wrapS));
        gl_.TexParameteri(target, GL_TEXTURE_WRAP_T, static_cast<GLint>(texture.wrapT));
        if (target == GL_TEXTURE_CUBE_MAP)
            gl_.TexParameteri(target, GL_TEXTURE_WRAP_R, static_cast<GLint>(texture.wrapR));
        gl_.TexParameteri(target, GL_TEXTURE_MAX_LEVEL_VALUE, static_cast<GLint>(texture.mips.size() - 1));
        checkError(("upload texture " + std::to_string(i)).c_str());
    }
}

void Renderer::uploadMesh(std::size_t index) {
    if (index >= bundle_.meshes.size() || index >= meshes_.size())
        throw std::runtime_error("native mesh upload index is out of range");
    const Mesh& mesh = bundle_.meshes[index];
    MeshGpu& gpu = meshes_[index];
    gl_.GenVertexArrays(1, &gpu.vao);
    gl_.GenBuffers(1, &gpu.vbo);
    gl_.GenBuffers(1, &gpu.ebo);
    gl_.BindVertexArray(gpu.vao);
    gl_.BindBuffer(GL_ARRAY_BUFFER, gpu.vbo);
    gl_.BufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(mesh.vertices.size() * sizeof(float)),
                   mesh.vertices.data(), GL_STATIC_DRAW);
    gl_.BindBuffer(GL_ELEMENT_ARRAY_BUFFER, gpu.ebo);
    gl_.BufferData(GL_ELEMENT_ARRAY_BUFFER, static_cast<GLsizeiptr>(mesh.indices.size() * sizeof(std::uint32_t)),
                   mesh.indices.data(), GL_STATIC_DRAW);
    constexpr GLsizei stride = 12 * sizeof(float);
    for (GLuint location = 0; location < 4; ++location) gl_.EnableVertexAttribArray(location);
    gl_.VertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, nullptr);
    gl_.VertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<const void*>(3 * sizeof(float)));
    gl_.VertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<const void*>(6 * sizeof(float)));
    gl_.VertexAttribPointer(3, 4, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<const void*>(8 * sizeof(float)));
    gl_.BindVertexArray(0);
    gl_.BindBuffer(GL_ARRAY_BUFFER, 0);
    checkError("upload native mesh");
}

std::array<double, 16> Renderer::effectiveWorld(const Entity& entity, const CameraFrame& frame) const {
    if (!(entity.flags & 1u)) return entity.world;
    const double size = 2.0 * frame.farPlane;
    return {size,0,0,frame.position[0], 0,size,0,frame.position[1],
            0,0,1,bundle_.groundZ, 0,0,0,1};
}
std::array<float, 9> Renderer::effectiveNormal(const Entity& entity, const CameraFrame& frame) const {
    if (!(entity.flags & 1u)) return entity.normal;
    const float scale = f32(2.0 * frame.farPlane);
    if (!(scale > 0) || !std::isfinite(scale)) throw std::runtime_error("invalid ground scale for camera far plane");
    return {1.0f / scale,0,0,0,1.0f / scale,0,0,0,1};
}
void Renderer::updateGround(const CameraFrame&) {
    // Ground transform is derived from the active camera in effectiveWorld();
    // the persistent entity and mesh resources remain shared.
}

std::array<double, 6> Renderer::worldBounds(const Entity& entity, const CameraFrame& frame,
                                           bool& valid) const {
    valid = false;
    const Mesh& mesh = bundle_.meshes[entity.mesh];
    const M4 world = effectiveWorld(entity, frame);
    const std::array<double, 3> lo{mesh.bounds[0], mesh.bounds[1], mesh.bounds[2]};
    const std::array<double, 3> hi{mesh.bounds[3], mesh.bounds[4], mesh.bounds[5]};
    std::array<double, 3> center{}, radius{};
    for (int r = 0; r < 3; ++r) {
        center[r] = world[r * 4 + 3];
        for (int c = 0; c < 3; ++c) {
            const double localCenter = lo[c] * .5 + hi[c] * .5;
            const double localRadius = hi[c] * .5 - lo[c] * .5;
            center[r] += world[r * 4 + c] * localCenter;
            radius[r] += std::abs(world[r * 4 + c]) * localRadius;
        }
    }
    std::array<double, 6> result{};
    for (int axis = 0; axis < 3; ++axis) {
        result[axis] = center[axis] - radius[axis];
        result[axis + 3] = center[axis] + radius[axis];
    }
    valid = std::all_of(result.begin(), result.end(), [](double x) { return std::isfinite(x); });
    return result;
}

std::array<double, 24> Renderer::frustumPlanes(const M4& view, const M4& projection) const {
    const M4 clip = multiply4(projection, view);
    std::array<double, 24> planes{};
    int p = 0;
    for (int axis = 0; axis < 3; ++axis) for (int sign : {1, -1}) {
        for (int c = 0; c < 4; ++c)
            planes[p++] = clip[12 + c] + sign * clip[axis * 4 + c];
    }
    return planes;
}

bool Renderer::boundsVisible(const std::array<double, 6>& b, const std::array<double, 24>& planes) const {
    for (int axis = 0; axis < 3; ++axis)
        if (!std::isfinite(b[axis]) || !std::isfinite(b[axis + 3]) || b[axis] > b[axis + 3]) return true;
    for (int p = 0; p < 6; ++p) {
        const double* plane = planes.data() + p * 4;
        double support = plane[3], tolerance = std::abs(plane[3]) + 1.0;
        for (int axis = 0; axis < 3; ++axis) {
            const double center = b[axis] * .5 + b[axis + 3] * .5;
            const double radius = b[axis + 3] * .5 - b[axis] * .5;
            support += plane[axis] * center + std::abs(plane[axis]) * radius;
            tolerance += std::max(std::abs(b[axis]), std::abs(b[axis + 3])) * std::abs(plane[axis]);
        }
        tolerance *= 1e-5;
        if (support < -tolerance) return false;
    }
    return true;
}

std::vector<bool> Renderer::visibleInFrustum(const CameraFrame& frame, bool colorPass) const {
    M4 view = frame.view, projection = frame.projection;
    if (colorPass) {
        view = floatRoundTrip(view);
        projection = floatRoundTrip(projection);
    }
    const auto planes = frustumPlanes(view, projection);
    std::vector<bool> visible(bundle_.entities.size(), true);
    for (std::size_t i = 0; i < bundle_.entities.size(); ++i) {
        // The analytic photographic plane covers screen rays beyond camera.far.
        if (colorPass && groundProgram_ && (bundle_.entities[i].flags & 1u)) continue;
        bool valid = false;
        const auto bounds = worldBounds(bundle_.entities[i], frame, valid);
        if (valid) visible[i] = boundsVisible(bounds, planes);
    }
    return visible;
}

std::vector<Renderer::Batch> Renderer::makeBatches(const std::vector<std::uint32_t>& indices) const {
    std::vector<Batch> batches;
    for (const std::uint32_t index : indices) {
        const Entity& entity = bundle_.entities[index];
        const Material& material = bundle_.materials[bundle_.meshes[entity.mesh].material];
        const std::int32_t alpha = [&]() {
            for (const auto& value : material.parameters)
                if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                    return intData(value)[0];
            return 0;
        }();
        if (alpha < 0 || alpha > 2) throw std::runtime_error("material alphaMode must be OPAQUE, MASK or BLEND");
        const bool ground = (entity.flags & 1u) != 0;
        const bool mirrored = (entity.flags & 2u) != 0;
        const bool canInstance = alpha == 0;
        if (canInstance && !batches.empty() && batches.back().mesh == entity.mesh &&
            batches.back().mirrored == mirrored && batches.back().ground == ground &&
            [&]() {
                const Entity& previous = bundle_.entities[batches.back().entities.front()];
                const Material& previousMat = bundle_.materials[bundle_.meshes[previous.mesh].material];
                for (const auto& value : previousMat.parameters)
                    if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                        return intData(value)[0] == 0;
                return true;
            }()) {
            batches.back().entities.push_back(index);
        } else {
            batches.push_back(Batch{entity.mesh, mirrored, ground, {index}});
        }
    }
    return batches;
}

Renderer::InstanceGpu& Renderer::instanceResource(std::uint32_t meshIndex, bool shadowPass,
                                                  std::size_t batchOrdinal) {
    std::string key = std::to_string(meshIndex) + (shadowPass ? ":s" : ":c");
    key += ":" + std::to_string(batchOrdinal);
    auto [it, inserted] = instances_.try_emplace(key);
    InstanceGpu& resource = it->second;
    if (inserted) {
        const MeshGpu& mesh = meshes_[meshIndex];
        gl_.GenVertexArrays(1, &resource.vao);
        gl_.GenBuffers(1, &resource.buffer);
        gl_.BindVertexArray(resource.vao);
        gl_.BindBuffer(GL_ARRAY_BUFFER, mesh.vbo);
        gl_.BindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.ebo);
        constexpr GLsizei baseStride = 12 * sizeof(float);
        for (GLuint location = 0; location < 4; ++location) gl_.EnableVertexAttribArray(location);
        gl_.VertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, baseStride, nullptr);
        gl_.VertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, baseStride, reinterpret_cast<const void*>(3 * sizeof(float)));
        gl_.VertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, baseStride, reinterpret_cast<const void*>(6 * sizeof(float)));
        gl_.VertexAttribPointer(3, 4, GL_FLOAT, GL_FALSE, baseStride, reinterpret_cast<const void*>(8 * sizeof(float)));
        gl_.BindBuffer(GL_ARRAY_BUFFER, resource.buffer);
        const GLsizei instanceStride = static_cast<GLsizei>((shadowPass ? 16u : 25u) * sizeof(float));
        for (GLuint column = 0; column < 4; ++column) {
            const GLuint location = 4 + column;
            gl_.EnableVertexAttribArray(location);
            gl_.VertexAttribPointer(location, 4, GL_FLOAT, GL_FALSE, instanceStride,
                                    reinterpret_cast<const void*>(column * 4u * sizeof(float)));
            gl_.VertexAttribDivisor(location, 1);
        }
        if (!shadowPass) for (GLuint column = 0; column < 3; ++column) {
            const GLuint location = 8 + column;
            gl_.EnableVertexAttribArray(location);
            gl_.VertexAttribPointer(location, 3, GL_FLOAT, GL_FALSE, instanceStride,
                reinterpret_cast<const void*>((16u + column * 3u) * sizeof(float)));
            gl_.VertexAttribDivisor(location, 1);
        }
    }
    return resource;
}

void Renderer::createShadowTarget(bool nearLayer) {
    auto& targetFbo = nearLayer ? nearShadowFbo_ : shadowFbo_;
    auto& targetTexture = nearLayer ? nearShadowTexture_ : shadowTexture_;
    const auto resolution = nearLayer ? nearShadowResolution_ : bundle_.shadowResolution;
    if (targetFbo) return;
    GLint maxTextureSize = 0;
    gl_.GetIntegerv(GL_MAX_TEXTURE_SIZE, &maxTextureSize);
    if (resolution > static_cast<std::uint32_t>(maxTextureSize))
        throw std::runtime_error("shadow resolution exceeds GL_MAX_TEXTURE_SIZE");
    gl_.GenTextures(1, &targetTexture);
    const GLenum target = nearLayer ? GL_TEXTURE_2D : GL_TEXTURE_2D_ARRAY;
    gl_.BindTexture(target, targetTexture);
    if (nearLayer)
        gl_.TexImage2D(target, 0, GL_DEPTH_COMPONENT24_VALUE, resolution, resolution,
                       0, GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
    else
        gl_.TexImage3D(target, 0, GL_DEPTH_COMPONENT24_VALUE, resolution, resolution, 2,
                       0, GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
    gl_.TexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    gl_.TexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    gl_.TexParameteri(target, GL_TEXTURE_COMPARE_MODE_VALUE, GL_COMPARE_REF_TO_TEXTURE_VALUE);
    gl_.TexParameteri(target, GL_TEXTURE_COMPARE_FUNC_VALUE, GL_LEQUAL);
    gl_.TexParameteri(target, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER_VALUE);
    gl_.TexParameteri(target, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER_VALUE);
    const GLfloat border[]{1,1,1,1};
    gl_.TexParameterfv(target, GL_TEXTURE_BORDER_COLOR_VALUE, border);

    if (!rawSampler_) gl_.GenSamplers(1, &rawSampler_);
    gl_.SamplerParameteri(rawSampler_, GL_TEXTURE_COMPARE_MODE_VALUE, GL_NONE);
    gl_.SamplerParameteri(rawSampler_, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    gl_.SamplerParameteri(rawSampler_, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    gl_.SamplerParameteri(rawSampler_, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER_VALUE);
    gl_.SamplerParameteri(rawSampler_, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER_VALUE);
    gl_.SamplerParameterfv(rawSampler_, GL_TEXTURE_BORDER_COLOR_VALUE, border);

    gl_.GenFramebuffers(1, &targetFbo);
    gl_.BindFramebuffer(GL_FRAMEBUFFER, targetFbo);
    if (nearLayer)
        gl_.FramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, targetTexture, 0);
    else
        gl_.FramebufferTextureLayer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, targetTexture, 0, shadowLayer_);
    gl_.DrawBuffer(GL_NONE);
    gl_.ReadBuffer(GL_NONE);
    const GLenum status = gl_.CheckFramebufferStatus(GL_FRAMEBUFFER);
    gl_.BindFramebuffer(GL_FRAMEBUFFER, 0);
    if (status != GL_FRAMEBUFFER_COMPLETE)
        throw std::runtime_error("shadow depth framebuffer is incomplete (status " + std::to_string(status) + ")");
    checkError("create shadow target");
}

void Renderer::destroyShadowTarget() {
    shadowDepthValid_ = nearShadowDepthValid_ = false;
    shadowTransition_ = false;
    shadowPoseValid_ = false;
    if (nearShadowFbo_) gl_.DeleteFramebuffers(1, &nearShadowFbo_);
    if (nearShadowTexture_) gl_.DeleteTextures(1, &nearShadowTexture_);
    nearShadowFbo_ = nearShadowTexture_ = 0;
    if (shadowFbo_) gl_.DeleteFramebuffers(1, &shadowFbo_);
    if (shadowTexture_) gl_.DeleteTextures(1, &shadowTexture_);
    if (rawSampler_) gl_.DeleteSamplers(1, &rawSampler_);
    shadowFbo_ = shadowTexture_ = rawSampler_ = 0;
}

void Renderer::drawShadow(const CameraFrame& frame, FrameStats& stats) {
    shadowActive_ = false;
    nearShadowActive_ = false;
    if (!bundle_.shadowEnabled || bundle_.entities.empty()) return;
    const auto pose = floatRoundTrip(frame.view);
    const auto lens = floatRoundTrip(frame.projection);
    if (shadowPoseValid_ && lens != shadowLens_) {
        farFitValid_ = shadowDepthValid_ = nearShadowDepthValid_ = false;
        shadowTransition_ = false;
    }
    if (shadowPoseValid_ && pose != shadowPose_ && shadowTransition_) {
        if (++shadowBlendStep_ >= 8) shadowTransition_ = false;
    }
    shadowPose_ = pose;
    shadowLens_ = lens;
    shadowPoseValid_ = true;
    std::vector<ShadowBox> boxes;
    boxes.reserve(bundle_.entities.size());
    for (const Entity& entity : bundle_.entities) {
        ShadowBox box;
        box.bounds = bundle_.meshes[entity.mesh].bounds;
        box.world = effectiveWorld(entity, frame);
        box.ground = (entity.flags & 1u) != 0;
        boxes.push_back(box);
    }
    drawShadowLayer(frame, stats, boxes, false);
    if (stableShadows_ && shadowActive_) drawShadowLayer(frame, stats, boxes, true);
}

void Renderer::drawShadowLayer(const CameraFrame& frame, FrameStats& stats,
                                const std::vector<ShadowBox>& boxes, bool nearLayer) {
    auto& matrix = nearLayer ? nearShadowMatrix_ : shadowMatrix_;
    const auto previousMatrix = matrix;
    const auto resolution = nearLayer ? nearShadowResolution_ : bundle_.shadowResolution;
    bool emptyReceivers = false;
    const bool fitted = nearLayer
        ? fit_stable_shadow(boxes, bundle_.lightDirection.data(), frame.view.data(), frame.projection.data(),
                            resolution, .02, 18.0, matrix.data())
        : fit_shadow(boxes, bundle_.lightDirection.data(), frame.view.data(), frame.projection.data(),
                      resolution, matrix.data(), stableShadows_ && farFitValid_ ? previousMatrix.data() : nullptr,
                      &emptyReceivers, stableShadows_);
    if (!fitted && emptyReceivers) {
        // Empty finite receiver/caster regions are normal for aerial/sky shots.
        // The analytic plane remains visible, but has no relevant local shadows.
        farFitValid_ = shadowDepthValid_ = false;
        shadowTransition_ = false;
        return;
    }
    if (!fitted)
        throw std::runtime_error("fit_shadow could not fit this camera/scene; native viewer has no silent shadow fallback");
    if (!nearLayer && stableShadows_) {
        farFitValid_ = true;
    }
    auto& depthValid = nearLayer ? nearShadowDepthValid_ : shadowDepthValid_;
    auto& drawnMatrix = nearLayer ? nearShadowDrawMatrix_ : shadowDrawMatrix_;
    // The shader consumes float32, so compare exactly that uploaded transform.
    // Use the same transform for caster culling and cache identity.
    const auto drawMatrix = floatRoundTrip(matrix);
    if (!nearLayer && depthValid && stableShadows_ && shadowTransitionsEnabled_ && !shadowTransition_) {
        bool refit = false;
        for (int index : {0,1,2,4,5,6,8,9,10,11})
            refit = refit || drawMatrix[index] != drawnMatrix[index];
        if (refit) {
            shadowPreviousMatrix_ = drawnMatrix;
            shadowPreviousLayer_ = shadowLayer_;
            shadowLayer_ = 1 - shadowLayer_;
            shadowBlendStep_ = 1;
            shadowTransition_ = true;
        }
    }
    const auto fbo = nearLayer ? nearShadowFbo_ : shadowFbo_;
    if (depthValid && fbo && drawMatrix == drawnMatrix) {
        if (nearLayer) nearShadowActive_ = true;
        else shadowActive_ = true;
        return;
    }
    createShadowTarget(nearLayer);
    const auto planes = frustumPlanes(M4{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1}, drawMatrix);
    std::vector<std::uint32_t> casters;
    std::vector<bool> visible(bundle_.entities.size(), true);
    for (std::size_t i = 0; i < bundle_.entities.size(); ++i) {
        const Entity& entity = bundle_.entities[i];
        const Material& material = bundle_.materials[bundle_.meshes[entity.mesh].material];
        std::int32_t alpha = 0;
        for (const auto& value : material.parameters)
            if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                alpha = intData(value)[0];
        if ((entity.flags & 1u) || alpha == 2) continue;
        bool valid = false;
        const auto bounds = worldBounds(entity, frame, valid);
        if (valid) visible[i] = boundsVisible(bounds, planes);
        if (visible[i]) casters.push_back(static_cast<std::uint32_t>(i));
    }
    stats.shadowCasters += static_cast<std::uint32_t>(casters.size());

    gl_.BindFramebuffer(GL_FRAMEBUFFER, nearLayer ? nearShadowFbo_ : shadowFbo_);
    if (!nearLayer)
        gl_.FramebufferTextureLayer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, shadowTexture_, 0, shadowLayer_);
    gl_.Disable(GL_MULTISAMPLE);
    gl_.Viewport(0, 0, static_cast<GLsizei>(resolution), static_cast<GLsizei>(resolution));
    gl_.Disable(GL_BLEND);
    gl_.Disable(GL_CULL_FACE);
    gl_.Disable(GL_SCISSOR_TEST);
    gl_.Disable(GL_STENCIL_TEST);
    gl_.Disable(GL_RASTERIZER_DISCARD);
    gl_.Enable(GL_POLYGON_OFFSET_FILL_VALUE);
    gl_.PolygonOffset(2.0f, 4.0f);
    gl_.Enable(GL_DEPTH_TEST);
    gl_.DepthFunc(GL_LESS);
    gl_.DepthMask(GL_TRUE);
    gl_.DepthRange(0.0, 1.0);
    gl_.PolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    gl_.ClearDepth(1.0);
    gl_.Clear(GL_DEPTH_BUFFER_BIT);
    gl_.UseProgram(shadowProgram_);
    const auto lightF = floatMatrix(matrix);
    setUniformMatrix4(shadowProgram_, "lightMatrix", lightF.data());
    setUniform1i(shadowProgram_, "baseMap", 0);
    std::vector<Batch> batches;
    std::vector<Batch> maskedBatches;
    std::unordered_map<std::uint32_t, std::size_t> opaqueMeshSlots;
    for (const std::uint32_t index : casters) {
        const Entity& entity = bundle_.entities[index];
        const Material& material = bundle_.materials[bundle_.meshes[entity.mesh].material];
        std::int32_t alpha = 0;
        for (const auto& value : material.parameters)
            if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                alpha = intData(value)[0];
        if (alpha == 0) {
            auto [slot, inserted] = opaqueMeshSlots.emplace(entity.mesh, batches.size());
            if (inserted) batches.push_back(Batch{entity.mesh, false, false, {}});
            batches[slot->second].entities.push_back(index);
        } else if (alpha == 1) {
            maskedBatches.push_back(Batch{entity.mesh, (entity.flags & 2u) != 0, false, {index}});
        } else if (alpha != 2) {
            throw std::runtime_error("material alphaMode must be OPAQUE, MASK or BLEND");
        }
    }
    batches.insert(batches.end(), maskedBatches.begin(), maskedBatches.end());
    std::unordered_map<std::uint32_t, std::size_t> instanceOrdinals;
    for (const Batch& batch : batches) {
        const Mesh& mesh = bundle_.meshes[batch.mesh];
        const Material& material = bundle_.materials[mesh.material];
        std::int32_t alpha = 0;
        float baseAlpha = 1.0f, cutoff = 0.5f;
        for (const auto& value : material.parameters) {
            if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                alpha = intData(value)[0];
            if (value.name == "baseFactor" && value.components >= 4 && !isIntegerUniform(value.type))
                baseAlpha = floatData(value)[3];
            if (value.name == "alphaCutoff" && value.components == 1 && !isIntegerUniform(value.type))
                cutoff = floatData(value)[0];
        }
        const bool masked = alpha == 1;
        setUniform1i(shadowProgram_, "alphaMask", masked ? GL_TRUE : GL_FALSE);
        setUniform1i(shadowProgram_, "hasBase", material.textureIndices[0] != kNone ? GL_TRUE : GL_FALSE);
        setUniform1f(shadowProgram_, "baseAlpha", baseAlpha);
        setUniform1f(shadowProgram_, "cutoff", cutoff);
        gl_.ActiveTexture(GL_TEXTURE0);
        const std::uint32_t baseTexture = material.textureIndices[0];
        gl_.BindTexture(GL_TEXTURE_2D, baseTexture == kNone ? 0 : textures_[baseTexture]);
        gl_.BindTexture(GL_TEXTURE_CUBE_MAP, 0);
        const bool instanced = !masked && batch.entities.size() > 1;
        setUniform1i(shadowProgram_, "useInstances", instanced ? GL_TRUE : GL_FALSE);
        if (instanced) {
            InstanceGpu& instance = instanceResource(batch.mesh, true, instanceOrdinals[batch.mesh]++);
            std::vector<float> payload(batch.entities.size() * 16u);
            for (std::size_t i = 0; i < batch.entities.size(); ++i) {
                const M4 world = effectiveWorld(bundle_.entities[batch.entities[i]], frame);
                for (int column = 0; column < 4; ++column)
                    for (int row = 0; row < 4; ++row)
                        payload[i * 16u + column * 4u + row] = f32(world[row * 4 + column]);
            }
            gl_.BindVertexArray(instance.vao);
            if (instance.lastPayload != payload) {
                gl_.BindBuffer(GL_ARRAY_BUFFER, instance.buffer);
                gl_.BufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(payload.size() * sizeof(float)),
                               payload.data(), GL_STREAM_DRAW);
                instance.lastPayload = std::move(payload);
            }
            gl_.DrawElementsInstanced(GL_TRIANGLES, mesh.indexCount, GL_UNSIGNED_INT, nullptr,
                                      static_cast<GLsizei>(batch.entities.size()));
        } else {
            const std::uint32_t entityIndex = batch.entities.front();
            const auto world = floatMatrix(effectiveWorld(bundle_.entities[entityIndex], frame));
            setUniformMatrix4(shadowProgram_, "model", world.data());
            gl_.BindVertexArray(meshes_[batch.mesh].vao);
            gl_.DrawElements(GL_TRIANGLES, mesh.indexCount, GL_UNSIGNED_INT, nullptr);
        }
        ++stats.shadowDraws;
        stats.shadowTriangles += (mesh.indexCount / 3u) * batch.entities.size();
    }
    gl_.Disable(GL_POLYGON_OFFSET_FILL_VALUE);
    gl_.BindFramebuffer(GL_FRAMEBUFFER, 0);
    if (nearLayer) nearShadowActive_ = true;
    else shadowActive_ = true;
    checkError("shadow pass");
    drawnMatrix = drawMatrix;
    depthValid = true;
}

void Renderer::drawSky(const CameraFrame& frame) {
    const auto projectionInverse = floatMatrix(inverse4(frame.projection));
    std::array<float, 9> rotation{};
    for (std::size_t i = 0; i < rotation.size(); ++i) rotation[i] = f32(frame.rotation[i]);
    gl_.UseProgram(skyProgram_);
    setUniformMatrix4(skyProgram_, "inverseProjection", projectionInverse.data());
    setUniformMatrix3(skyProgram_, "cameraRotation", rotation.data());
    setUniform1f(skyProgram_, "photoFar", f32(frame.farPlane));
    for (std::size_t unit = 8; unit <= 11; ++unit) {
        gl_.BindSampler(static_cast<GLuint>(unit), 0);
        std::uint32_t textureIndex = kNone;
        for (const Material& material : bundle_.materials)
            if (material.textureIndices[unit] != kNone) { textureIndex = material.textureIndices[unit]; break; }
        const GLuint handle = textureIndex == kNone ? 0 : textures_[textureIndex];
        const GLenum target = textureIndex == kNone ? GL_TEXTURE_2D : bundle_.textures[textureIndex].target;
        gl_.ActiveTexture(GL_TEXTURE0 + static_cast<GLenum>(unit));
        gl_.BindTexture(GL_TEXTURE_2D, target == GL_TEXTURE_2D ? handle : 0);
        gl_.BindTexture(GL_TEXTURE_CUBE_MAP, target == GL_TEXTURE_CUBE_MAP ? handle : 0);
    }
    gl_.Viewport(0, 0, width_, height_);
    gl_.Disable(GL_DEPTH_TEST);
    gl_.DepthMask(GL_FALSE);
    gl_.Disable(GL_CULL_FACE);
    gl_.Disable(GL_BLEND);
    gl_.Disable(GL_FRAMEBUFFER_SRGB_VALUE);
    gl_.PolygonMode(GL_FRONT_AND_BACK, GL_FILL);
    gl_.BindVertexArray(skyVao_);
    gl_.DrawArrays(GL_TRIANGLES, 0, 3);
}

void Renderer::bindMaterialTextures(std::uint32_t materialIndex) {
    const Material& material = bundle_.materials[materialIndex];
    for (std::size_t unit = 0; unit < material.textureIndices.size(); ++unit) {
        if (unit == 7 || unit == 12) continue;
        gl_.BindSampler(static_cast<GLuint>(unit), 0);
        gl_.ActiveTexture(GL_TEXTURE0 + static_cast<GLenum>(unit));
        const std::uint32_t index = material.textureIndices[unit];
        const GLuint texture = index == kNone ? 0 : textures_[index];
        const GLenum target = index == kNone ? GL_TEXTURE_2D : bundle_.textures[index].target;
        gl_.BindTexture(GL_TEXTURE_2D, target == GL_TEXTURE_2D ? texture : 0);
        gl_.BindTexture(GL_TEXTURE_CUBE_MAP, target == GL_TEXTURE_CUBE_MAP ? texture : 0);
    }
}

void Renderer::bindMaterial(std::uint32_t materialIndex, bool ground, bool mirrored) {
    const Material& material = bundle_.materials[materialIndex];
    applyUniformBlock(activeColorProgram_, material.parameters);
    bindMaterialTextures(materialIndex);
    setUniform1i(activeColorProgram_, "photographicGround", ground ? GL_TRUE : GL_FALSE);
    setUniform1i(activeColorProgram_, "shadowEnabled", shadowActive_ ? GL_TRUE : GL_FALSE);
    setUniform1i(activeColorProgram_, "shadowDepth", 7);
    setUniform1i(activeColorProgram_, "shadowRaw", 12);
    setUniform1i(activeColorProgram_, "shadowNearEnabled", nearShadowActive_ ? GL_TRUE : GL_FALSE);
    if (nearShadowActive_) {
        gl_.ActiveTexture(GL_TEXTURE0 + 13);
        gl_.BindTexture(GL_TEXTURE_2D, nearShadowTexture_);
        gl_.BindSampler(13, 0);
        gl_.ActiveTexture(GL_TEXTURE0 + 14);
        gl_.BindTexture(GL_TEXTURE_2D, nearShadowTexture_);
        gl_.BindSampler(14, rawSampler_);
        const auto nearMatrix = floatMatrix(nearShadowMatrix_);
        setUniformMatrix4(activeColorProgram_, "shadowNearMatrix", nearMatrix.data());
        const double row0 = std::hypot(nearShadowDrawMatrix_[0], nearShadowDrawMatrix_[1], nearShadowDrawMatrix_[2]);
        const double row1 = std::hypot(nearShadowDrawMatrix_[4], nearShadowDrawMatrix_[5], nearShadowDrawMatrix_[6]);
        const double row2 = std::hypot(nearShadowDrawMatrix_[8], nearShadowDrawMatrix_[9], nearShadowDrawMatrix_[10]);
        setUniform3f(activeColorProgram_, "shadowNearWorldScale", f32(row0 * .5), f32(row1 * .5), f32(2.0 / row2));
        setUniform1f(activeColorProgram_, "shadowNearBias", bundle_.shadowBias);
    }
    setUniform1f(activeColorProgram_, "shadowBias", bundle_.shadowBias);
    setUniform1i(activeColorProgram_, "shadowLayer", shadowLayer_);
    setUniform1i(activeColorProgram_, "shadowPreviousLayer", shadowPreviousLayer_);
    setUniform1i(activeColorProgram_, "shadowTransition", shadowTransition_ ? GL_TRUE : GL_FALSE);
    setUniform1f(activeColorProgram_, "shadowBlend", (shadowBlendStep_ - 1) / 7.0f);
    if (shadowTransition_) {
        const auto previous = floatMatrix(shadowPreviousMatrix_);
        setUniformMatrix4(activeColorProgram_, "shadowPreviousMatrix", previous.data());
        const auto& m = shadowPreviousMatrix_;
        setUniform3f(activeColorProgram_, "shadowPreviousWorldScale",
            f32(std::hypot(m[0],m[1],m[2]) * .5),
            f32(std::hypot(m[4],m[5],m[6]) * .5),
            f32(2.0 / std::hypot(m[8],m[9],m[10])));
    }
    if (shadowActive_) {
        gl_.ActiveTexture(GL_TEXTURE0 + 7);
        gl_.BindTexture(GL_TEXTURE_2D_ARRAY, shadowTexture_);
        gl_.BindSampler(7, 0);
        gl_.ActiveTexture(GL_TEXTURE0 + 12);
        gl_.BindTexture(GL_TEXTURE_2D_ARRAY, shadowTexture_);
        gl_.BindSampler(12, rawSampler_);
        const double row0 = std::hypot(shadowDrawMatrix_[0], shadowDrawMatrix_[1], shadowDrawMatrix_[2]);
        const double row1 = std::hypot(shadowDrawMatrix_[4], shadowDrawMatrix_[5], shadowDrawMatrix_[6]);
        const double row2 = std::hypot(shadowDrawMatrix_[8], shadowDrawMatrix_[9], shadowDrawMatrix_[10]);
        setUniform3f(activeColorProgram_, "shadowWorldScale", f32(row0 * .5), f32(row1 * .5), f32(2.0 / row2));
        const auto matrix = floatMatrix(shadowMatrix_);
        setUniformMatrix4(activeColorProgram_, "shadowMatrix", matrix.data());
    } else {
        gl_.ActiveTexture(GL_TEXTURE0 + 7); gl_.BindTexture(GL_TEXTURE_2D_ARRAY, 0); gl_.BindSampler(7, 0);
        gl_.ActiveTexture(GL_TEXTURE0 + 12); gl_.BindTexture(GL_TEXTURE_2D_ARRAY, 0); gl_.BindSampler(12, 0);
    }
    gl_.FrontFace(mirrored ? GL_CW : GL_CCW);
    if (material.flags & 1u) gl_.Disable(GL_CULL_FACE);
    else { gl_.Enable(GL_CULL_FACE); gl_.CullFace(GL_BACK); }
}

void Renderer::drawColor(const CameraFrame& frame, const std::vector<bool>& visible, FrameStats& stats) {
    M4 view = floatRoundTrip(frame.view);
    M4 projection = floatRoundTrip(frame.projection);
    const auto viewF = floatMatrix(view), projectionF = floatMatrix(projection);
    for (GLuint program : {materialProgram_, groundProgram_}) {
        if (!program) continue;
        activeColorProgram_ = program;
        gl_.UseProgram(program);
        if (program == groundProgram_) {
            const auto inverseVP = floatMatrix(inverse4(multiply4(projection, view)));
            setUniformMatrix4(program, "groundInverseViewProjection", inverseVP.data());
        }
        setUniformMatrix4(activeColorProgram_, "view", viewF.data());
        setUniformMatrix4(activeColorProgram_, "projection", projectionF.data());
        setUniform3f(activeColorProgram_, "eye", f32(frame.position[0]), f32(frame.position[1]), f32(frame.position[2]));
        setUniform1f(activeColorProgram_, "photoFar", f32(frame.farPlane));

        // The Studio light rig follows camera rotation in the Python renderer.
        // Scene mode keeps the bundle's world-space directional light.
        bool sceneLighting = true;
        for (const auto& value : bundle_.materialGlobals)
            if (value.name == "sceneLighting" && value.components == 1 && isIntegerUniform(value.type))
                sceneLighting = intData(value)[0] != 0;
        if (sceneLighting) {
            auto light = normalize3(bundle_.lightDirection);
            setUniform3f(activeColorProgram_, "light0", f32(light[0]), f32(light[1]), f32(light[2]));
        } else {
            const auto right = rotationColumn(frame.rotation, 0);
            const auto up = rotationColumn(frame.rotation, 1);
            const auto back = rotationColumn(frame.rotation, 2);
            auto l0 = normalize3(add3(add3(back, up, 1.1), right, -.8));
            auto l1 = normalize3(add3(add3(back, right), up, .2));
            auto l2 = normalize3(add3(add3(back, up), right, .2));
            setUniform3f(activeColorProgram_, "light0", f32(l0[0]), f32(l0[1]), f32(l0[2]));
            setUniform3f(activeColorProgram_, "light1", f32(l1[0]), f32(l1[1]), f32(l1[2]));
            setUniform3f(activeColorProgram_, "light2", f32(l2[0]), f32(l2[1]), f32(l2[2]));
        }
    }
    activeColorProgram_ = materialProgram_;
    gl_.UseProgram(activeColorProgram_);
    if (shadowActive_) {
        gl_.ActiveTexture(GL_TEXTURE0 + 7);
        gl_.BindTexture(GL_TEXTURE_2D_ARRAY, shadowTexture_);
        gl_.BindSampler(7, 0);
        gl_.ActiveTexture(GL_TEXTURE0 + 12);
        gl_.BindTexture(GL_TEXTURE_2D_ARRAY, shadowTexture_);
        gl_.BindSampler(12, rawSampler_);
    }

    gl_.Viewport(0, 0, width_, height_);
    gl_.Enable(GL_DEPTH_TEST);
    gl_.DepthFunc(GL_LESS);
    gl_.DepthMask(GL_TRUE);
    gl_.Disable(GL_BLEND);
    gl_.Disable(GL_FRAMEBUFFER_SRGB_VALUE);
    gl_.PolygonMode(GL_FRONT_AND_BACK, GL_FILL);

    std::vector<std::uint32_t> opaque;
    std::vector<bool> inOrder(bundle_.entities.size(), false);
    auto consider = [&](std::uint32_t i) {
        if (inOrder[i]) return;
        inOrder[i] = true;
        const Material& material = bundle_.materials[bundle_.meshes[bundle_.entities[i].mesh].material];
        std::int32_t alpha = 0;
        for (const auto& value : material.parameters)
            if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                alpha = intData(value)[0];
        if (alpha != 2 && visible[i]) opaque.push_back(i);
    };
    for (auto index : bundle_.opaqueOrder) consider(index);
    for (std::uint32_t i = 0; i < bundle_.entities.size(); ++i) consider(i);
    stats.colorVisible = static_cast<std::uint32_t>(std::count(visible.begin(), visible.end(), true));

    const auto opaqueBatches = makeBatches(opaque);
    std::unordered_map<std::uint32_t, std::size_t> instanceOrdinals;
    for (const Batch& batch : opaqueBatches) {
        const Mesh& mesh = bundle_.meshes[batch.mesh];
        const std::uint32_t materialIndex = mesh.material;
        const Material& material = bundle_.materials[materialIndex];
        std::int32_t alpha = 0;
        for (const auto& value : material.parameters)
            if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                alpha = intData(value)[0];
        gl_.DepthMask(GL_TRUE);
        gl_.Disable(GL_BLEND);
        const GLuint program = batch.ground && groundProgram_ ? groundProgram_ : materialProgram_;
        if (activeColorProgram_ != program) {
            activeColorProgram_ = program;
            gl_.UseProgram(program);
        }
        bindMaterial(materialIndex, batch.ground, batch.mirrored);
        const bool instanced = alpha == 0 && batch.entities.size() > 1;
        setUniform1i(activeColorProgram_, "useInstances", instanced ? GL_TRUE : GL_FALSE);
        if (instanced) {
            InstanceGpu& instance = instanceResource(batch.mesh, false, instanceOrdinals[batch.mesh]++);
            const std::size_t n = batch.entities.size();
            std::vector<float> payload(n * 25u);
            for (std::size_t i = 0; i < n; ++i) {
                const Entity& entity = bundle_.entities[batch.entities[i]];
                const M4 world = effectiveWorld(entity, frame);
                const auto normal = effectiveNormal(entity, frame);
                for (int column = 0; column < 4; ++column)
                    for (int row = 0; row < 4; ++row)
                        payload[i * 25u + column * 4u + row] = f32(world[row * 4 + column]);
                for (int column = 0; column < 3; ++column)
                    for (int row = 0; row < 3; ++row)
                        payload[i * 25u + 16u + column * 3u + row] = normal[row * 3 + column];
            }
            gl_.BindVertexArray(instance.vao);
            if (instance.lastPayload != payload) {
                gl_.BindBuffer(GL_ARRAY_BUFFER, instance.buffer);
                gl_.BufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(payload.size() * sizeof(float)),
                               payload.data(), GL_STREAM_DRAW);
                instance.lastPayload = std::move(payload);
            }
            gl_.DrawElementsInstanced(GL_TRIANGLES, mesh.indexCount, GL_UNSIGNED_INT, nullptr,
                                      static_cast<GLsizei>(batch.entities.size()));
        } else {
            const std::uint32_t entityIndex = batch.entities.front();
            const Entity& entity = bundle_.entities[entityIndex];
            const auto world = floatMatrix(effectiveWorld(entity, frame));
            const auto normal = effectiveNormal(entity, frame);
            setUniformMatrix4(activeColorProgram_, "model", world.data());
            setUniformMatrix3(activeColorProgram_, "normalMatrix", normal.data());
            gl_.BindVertexArray(meshes_[batch.mesh].vao);
            gl_.DrawElements(GL_TRIANGLES, mesh.indexCount, GL_UNSIGNED_INT, nullptr);
        }
        ++stats.colorDraws;
        stats.colorTriangles += (mesh.indexCount / 3u) * batch.entities.size();
    }

    std::vector<DrawEntry> transparent;
    for (std::uint32_t i = 0; i < bundle_.entities.size(); ++i) {
        if (!visible[i]) continue;
        const Entity& entity = bundle_.entities[i];
        const Material& material = bundle_.materials[bundle_.meshes[entity.mesh].material];
        std::int32_t alpha = 0;
        for (const auto& value : material.parameters)
            if (value.name == "alphaMode" && value.components == 1 && isIntegerUniform(value.type))
                alpha = intData(value)[0];
        if (alpha != 2) continue;
        const Mesh& mesh = bundle_.meshes[entity.mesh];
        std::array<double, 3> localCenter{};
        for (int a = 0; a < 3; ++a) localCenter[a] = mesh.bounds[a] * .5 + mesh.bounds[a + 3] * .5;
        const M4 world = effectiveWorld(entity, frame);
        std::array<double, 4> center{world[0]*localCenter[0] + world[1]*localCenter[1] + world[2]*localCenter[2] + world[3],
                                     world[4]*localCenter[0] + world[5]*localCenter[1] + world[6]*localCenter[2] + world[7],
                                     world[8]*localCenter[0] + world[9]*localCenter[1] + world[10]*localCenter[2] + world[11], 1};
        double depth = 0;
        for (int c = 0; c < 4; ++c) depth += frame.view[8 + c] * center[c];
        transparent.push_back({i, f32(depth)});
    }
    std::stable_sort(transparent.begin(), transparent.end(), [](const DrawEntry& a, const DrawEntry& b) {
        return a.depth < b.depth;
    });
    if (!transparent.empty()) {
        gl_.Enable(GL_BLEND);
        gl_.BlendEquation(GL_FUNC_ADD);
        gl_.BlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        gl_.DepthMask(GL_FALSE);
        for (const DrawEntry& entry : transparent) {
            const Entity& entity = bundle_.entities[entry.entity];
            const Mesh& mesh = bundle_.meshes[entity.mesh];
            const GLuint program = (entity.flags & 1u) && groundProgram_ ? groundProgram_ : materialProgram_;
            if (activeColorProgram_ != program) {
                activeColorProgram_ = program;
                gl_.UseProgram(program);
            }
            bindMaterial(mesh.material, (entity.flags & 1u) != 0, (entity.flags & 2u) != 0);
            setUniform1i(activeColorProgram_, "useInstances", GL_FALSE);
            const auto world = floatMatrix(effectiveWorld(entity, frame));
            const auto normal = effectiveNormal(entity, frame);
            setUniformMatrix4(activeColorProgram_, "model", world.data());
            setUniformMatrix3(activeColorProgram_, "normalMatrix", normal.data());
            gl_.BindVertexArray(meshes_[entity.mesh].vao);
            gl_.DrawElements(GL_TRIANGLES, mesh.indexCount, GL_UNSIGNED_INT, nullptr);
            ++stats.colorDraws;
            stats.colorTriangles += mesh.indexCount / 3u;
        }
    }
    gl_.Disable(GL_BLEND);
    gl_.DepthMask(GL_TRUE);
    gl_.BindVertexArray(0);
}

void Renderer::createColorTarget() {
    // Match Python RenderTarget exactly instead of inheriting the window's
    // driver-selected depth format or sample layout.
    if (msaaSamples_ == 4) {
        GLint maximumSamples = 0;
        gl_.GetIntegerv(GL_MAX_SAMPLES, &maximumSamples);
        if (maximumSamples < 4)
            throw std::runtime_error("4x MSAA requested, but GL_MAX_SAMPLES is " +
                                     std::to_string(maximumSamples));
    }
    gl_.GenFramebuffers(1, &colorFbo_);
    gl_.GenTextures(1, &colorTexture_);
    gl_.BindTexture(GL_TEXTURE_2D, colorTexture_);
    gl_.TexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width_, height_, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    gl_.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    gl_.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    gl_.GenRenderbuffers(1, &colorDepth_);
    gl_.BindRenderbuffer(GL_RENDERBUFFER, colorDepth_);
    gl_.RenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, width_, height_);
    gl_.BindFramebuffer(GL_FRAMEBUFFER, colorFbo_);
    gl_.FramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, colorTexture_, 0);
    gl_.FramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, colorDepth_);
    gl_.DrawBuffer(GL_COLOR_ATTACHMENT0);
    gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
    if (gl_.CheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        throw std::runtime_error("native RGBA8/depth24-stencil8 target is incomplete");

    if (msaaSamples_ == 4) {
        gl_.GenFramebuffers(1, &msaaFbo_);
        gl_.GenRenderbuffers(1, &msaaColor_);
        gl_.BindRenderbuffer(GL_RENDERBUFFER, msaaColor_);
        gl_.RenderbufferStorageMultisample(GL_RENDERBUFFER, msaaSamples_, GL_RGBA8, width_, height_);
        gl_.GenRenderbuffers(1, &msaaDepth_);
        gl_.BindRenderbuffer(GL_RENDERBUFFER, msaaDepth_);
        gl_.RenderbufferStorageMultisample(GL_RENDERBUFFER, msaaSamples_, GL_DEPTH24_STENCIL8, width_, height_);
        gl_.BindFramebuffer(GL_FRAMEBUFFER, msaaFbo_);
        gl_.FramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, msaaColor_);
        gl_.FramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, msaaDepth_);
        gl_.DrawBuffer(GL_COLOR_ATTACHMENT0);
        gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
        if (gl_.CheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
            throw std::runtime_error("requested 4x RGBA8/depth24-stencil8 MSAA target is incomplete");
    }
    gl_.BindFramebuffer(GL_FRAMEBUFFER, 0);
    checkError("create color target");
}

void Renderer::destroyColorTarget() {
    if (colorFbo_) gl_.DeleteFramebuffers(1, &colorFbo_);
    if (colorTexture_) gl_.DeleteTextures(1, &colorTexture_);
    if (colorDepth_) gl_.DeleteRenderbuffers(1, &colorDepth_);
    if (msaaFbo_) gl_.DeleteFramebuffers(1, &msaaFbo_);
    if (msaaColor_) gl_.DeleteRenderbuffers(1, &msaaColor_);
    if (msaaDepth_) gl_.DeleteRenderbuffers(1, &msaaDepth_);
    colorFbo_ = colorTexture_ = colorDepth_ = 0;
    msaaFbo_ = msaaColor_ = msaaDepth_ = 0;
}

void Renderer::resize(int width, int height, int samples) {
    requireReady();
    if (width <= 0 || height <= 0) throw std::runtime_error("photo target dimensions must be positive");
    if (samples != 1 && samples != 4) throw std::runtime_error("photo target samples must be 1 or 4");
    if (width == width_ && height == height_ && samples == msaaSamples_) return;
    destroyColorTarget();
    width_ = width;
    height_ = height;
    msaaSamples_ = samples;
    try {
        createColorTarget();
    } catch (...) {
        destroyColorTarget();
        throw;
    }
}

void Renderer::updateGlobals(UniformBlock materialGlobals, UniformBlock skyGlobals,
                             const std::array<double, 3>& lightDirection,
                             std::uint32_t shadowResolution, float shadowBias,
                             bool shadowEnabled, double groundZ) {
    requireReady();
    if (!std::all_of(lightDirection.begin(), lightDirection.end(),
                     [](double value) { return std::isfinite(value); }) ||
        std::hypot(lightDirection[0], lightDirection[1], lightDirection[2]) < 1e-15)
        throw std::runtime_error("photo globals light direction must be finite and nonzero");
    if (shadowResolution == 0 || shadowResolution > 32768)
        throw std::runtime_error("photo globals shadow resolution must be between 1 and 32768");
    if (!std::isfinite(shadowBias) || !std::isfinite(groundZ))
        throw std::runtime_error("photo globals bias and ground Z must be finite");

    if (bundle_.shadowResolution != shadowResolution || bundle_.lightDirection != lightDirection ||
        bundle_.groundZ != groundZ) {
        farFitValid_ = false;
        shadowDepthValid_ = nearShadowDepthValid_ = false;
        shadowTransition_ = false;
        shadowPoseValid_ = false;
    }
    if (bundle_.shadowResolution != shadowResolution) destroyShadowTarget();
    bundle_.materialGlobals = std::move(materialGlobals);
    bundle_.skyGlobals = std::move(skyGlobals);
    bundle_.lightDirection = lightDirection;
    bundle_.shadowResolution = shadowResolution;
    bundle_.shadowBias = shadowBias;
    bundle_.shadowEnabled = shadowEnabled;
    bundle_.groundZ = groundZ;
    shadowActive_ = false;
    nearShadowActive_ = false;

    applyGlobalUniforms();
    checkError("update photo globals");
}

void Renderer::applyGlobalUniforms() {
    for (GLuint program : {materialProgram_, groundProgram_}) {
        if (!program) continue;
        gl_.UseProgram(program);
        applyUniformBlock(program, bundle_.materialGlobals);
    }
    if (skyProgram_) {
        gl_.UseProgram(skyProgram_);
        applyUniformBlock(skyProgram_, bundle_.skyGlobals);
    }
}

FrameStats Renderer::render(const CameraFrame& frame, GLuint targetSingleSampleFbo) {
    requireReady();
    // Program objects are shared between renderers with identical shader
    // sources. Their ordinary uniforms are shared too, so restore this
    // renderer's globals before the next renderer can draw with its own data.
    applyGlobalUniforms();
    // The photo renderer borrows a context whose previous pass may have
    // disabled seamless cube sampling. Set the environment contract per frame,
    // including frames without a low-frequency Python lighting update.
    gl_.Enable(GL_TEXTURE_CUBE_MAP_SEAMLESS);
    gl_.DepthRange(0.0, 1.0);
    gl_.Disable(GL_POLYGON_OFFSET_FILL_VALUE);
    updateGround(frame);
    FrameStats stats;
    CameraFrame colorFrame = frame;
    if (stabilizeDepth_) {
        std::vector<ShadowBox> boxes;
        boxes.reserve(bundle_.entities.size());
        for (const Entity& entity : bundle_.entities) {
            ShadowBox box;
            box.bounds = bundle_.meshes[entity.mesh].bounds;
            box.world = effectiveWorld(entity, frame);
            box.ground = (entity.flags & 1u) != 0;
            boxes.push_back(box);
        }
        double candidateNear = frame.nearPlane;
        if (conservative_camera_near(boxes, frame.view.data(), frame.projection.data(),
                                    frame.nearPlane, &candidateNear) && candidateNear > frame.nearPlane && candidateNear < frame.farPlane) {
            colorFrame.nearPlane = candidateNear;
            colorFrame.projection[10] = (frame.farPlane + candidateNear) / (candidateNear - frame.farPlane);
            colorFrame.projection[11] = 2.0 * frame.farPlane * candidateNear / (candidateNear - frame.farPlane);
        }
    }
    stats.inputNear = frame.nearPlane;
    stats.colorNear = colorFrame.nearPlane;
    const auto visible = visibleInFrustum(colorFrame, true);
    drawShadow(frame, stats);
    const GLuint colorDrawFbo = msaaSamples_ == 4 ? msaaFbo_ : colorFbo_;
    gl_.BindFramebuffer(GL_FRAMEBUFFER, colorDrawFbo);
    gl_.Viewport(0, 0, width_, height_);
    gl_.Disable(GL_SCISSOR_TEST);
    gl_.Disable(GL_STENCIL_TEST);
    gl_.Disable(GL_RASTERIZER_DISCARD);
    if (msaaSamples_ == 4) gl_.Enable(GL_MULTISAMPLE);
    else gl_.Disable(GL_MULTISAMPLE);
    gl_.ColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    bool atmosphereEnabled = true;
    bool hasAtmosphereSetting = false;
    for (const UniformValue& value : bundle_.materialGlobals)
        if (value.name == "atmosphereEnabled" && value.components == 1 &&
            isIntegerUniform(value.type)) {
            atmosphereEnabled = intData(value)[0] != 0;
            hasAtmosphereSetting = true;
            break;
        }
    if (!hasAtmosphereSetting)
        for (const UniformValue& value : bundle_.skyGlobals)
            if (value.name == "atmosphereEnabled" && value.components == 1 &&
                isIntegerUniform(value.type)) {
                atmosphereEnabled = intData(value)[0] != 0;
                break;
            }
    if (atmosphereEnabled) gl_.ClearColor(0, 0, 0, 1);
    else gl_.ClearColor(30.0f / 255.0f, 30.0f / 255.0f, 35.0f / 255.0f, 1);
    gl_.ClearDepth(1.0);
    glStencilMask(0xffffffffu);
    glClearStencil(0);
    gl_.DepthMask(GL_TRUE);
    gl_.Clear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
    if (atmosphereEnabled) drawSky(frame);
    gl_.Enable(GL_DEPTH_TEST);
    gl_.DepthFunc(GL_LESS);
    gl_.DepthMask(GL_TRUE);
    drawColor(colorFrame, visible, stats);
    checkError("color pass");
    if (msaaSamples_ == 4) {
        gl_.BindFramebuffer(GL_READ_FRAMEBUFFER, msaaFbo_);
        gl_.BindFramebuffer(GL_DRAW_FRAMEBUFFER, colorFbo_);
        gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
        gl_.DrawBuffer(GL_COLOR_ATTACHMENT0);
        gl_.BlitFramebuffer(0, 0, width_, height_, 0, 0, width_, height_,
                            GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT,
                            GL_NEAREST);
        checkError("resolve 4x MSAA color/depth/stencil target");
    }
    if (targetSingleSampleFbo) {
        gl_.BindFramebuffer(GL_READ_FRAMEBUFFER, colorFbo_);
        gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
        gl_.BindFramebuffer(GL_DRAW_FRAMEBUFFER, targetSingleSampleFbo);
        gl_.DrawBuffer(GL_COLOR_ATTACHMENT0);
        if (gl_.CheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
            throw std::runtime_error("caller photo framebuffer is incomplete");
        GLint targetSampleBuffers = 0, targetSamples = 0;
        gl_.GetIntegerv(GL_SAMPLE_BUFFERS, &targetSampleBuffers);
        gl_.GetIntegerv(GL_SAMPLES, &targetSamples);
        if (targetSampleBuffers != 0 || targetSamples != 0)
            throw std::runtime_error("caller photo framebuffer must be single-sample");
        gl_.BlitFramebuffer(0, 0, width_, height_, 0, 0, width_, height_,
                            GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT,
                            GL_NEAREST);
        checkError("copy color/depth/stencil to caller photo framebuffer");
        gl_.BindFramebuffer(GL_FRAMEBUFFER, targetSingleSampleFbo);
    } else {
        gl_.BindFramebuffer(GL_READ_FRAMEBUFFER, colorFbo_);
        gl_.BindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
        gl_.DrawBuffer(GL_BACK);
        gl_.BlitFramebuffer(0, 0, width_, height_, 0, 0, width_, height_, GL_COLOR_BUFFER_BIT, GL_NEAREST);
        gl_.Finish();
    }
    return stats;
}

void Renderer::capture(const CameraFrame& frame, const std::filesystem::path& basePath,
                       std::size_t frameIndex, const FrameStats& stats) {
    requireReady();
    std::filesystem::create_directories(basePath.parent_path());
    const std::size_t pixelCount = static_cast<std::size_t>(width_) * height_;
    std::vector<std::uint8_t> rgba(pixelCount * 4u);
    gl_.BindFramebuffer(GL_FRAMEBUFFER, colorFbo_);
    gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
    gl_.PixelStorei(GL_PACK_ALIGNMENT, 1);
    gl_.ReadPixels(0, 0, width_, height_, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
    {
        std::ofstream out(basePath.string() + ".rgba", std::ios::binary);
        if (!out || !out.write(reinterpret_cast<const char*>(rgba.data()),
                                static_cast<std::streamsize>(rgba.size())))
            throw std::runtime_error("failed writing RGBA capture: " + basePath.string());
    }
    {
        std::ofstream out(basePath.string() + ".ppm", std::ios::binary);
        if (!out) throw std::runtime_error("failed opening PPM capture: " + basePath.string());
        out << "P6\n" << width_ << " " << height_ << "\n255\n";
        for (int y = height_ - 1; y >= 0; --y) {
            const auto offset = static_cast<std::size_t>(y) * width_ * 4u;
            for (int x = 0; x < width_; ++x) {
                out.put(static_cast<char>(rgba[offset + x * 4u + 0]));
                out.put(static_cast<char>(rgba[offset + x * 4u + 1]));
                out.put(static_cast<char>(rgba[offset + x * 4u + 2]));
            }
        }
        if (!out) throw std::runtime_error("failed writing PPM capture: " + basePath.string());
    }
    if (shadowFbo_) {
        std::vector<float> depth(static_cast<std::size_t>(bundle_.shadowResolution) * bundle_.shadowResolution);
        gl_.BindFramebuffer(GL_READ_FRAMEBUFFER, shadowFbo_);
        gl_.ReadPixels(0, 0, static_cast<GLsizei>(bundle_.shadowResolution),
                       static_cast<GLsizei>(bundle_.shadowResolution), GL_DEPTH_COMPONENT,
                       GL_FLOAT, depth.data());
        std::ofstream out(basePath.string() + ".depth.f32", std::ios::binary);
        if (!out || !out.write(reinterpret_cast<const char*>(depth.data()),
                               static_cast<std::streamsize>(depth.size() * sizeof(float))))
            throw std::runtime_error("failed writing raw shadow depth: " + basePath.string());
    }
    gl_.BindFramebuffer(GL_FRAMEBUFFER, 0);
    gl_.ReadBuffer(GL_BACK);
    std::ofstream json(basePath.string() + ".json", std::ios::binary);
    if (!json) throw std::runtime_error("failed opening capture metadata: " + basePath.string());
    json << std::setprecision(17)
         << "{\n  \"route\": \"" << frame.route << "\",\n  \"frame_index\": " << frameIndex
         << ",\n  \"t\": " << frame.t << ",\n  \"width\": " << width_
         << ",\n  \"height\": " << height_ << ",\n  \"color_draws\": " << stats.colorDraws
         << ",\n  \"msaa_samples\": " << msaaSamples_
         << ",\n  \"input_near\": " << stats.inputNear << ",\n  \"color_near\": " << stats.colorNear
         << ",\n  \"shadow_draws\": " << stats.shadowDraws
         << ",\n  \"color_triangles\": " << stats.colorTriangles
         << ",\n  \"shadow_triangles\": " << stats.shadowTriangles
         << ",\n  \"shadow_active\": " << (shadowActive_ ? "true" : "false")
         << ",\n  \"near_shadow_active\": " << (nearShadowActive_ ? "true" : "false")
         << ",\n  \"near_shadow_resolution\": " << (stableShadows_ ? nearShadowResolution_ : 0)
         << ",\n  \"near_shadow_matrix_row_major\": [";
    for (std::size_t i = 0; i < nearShadowMatrix_.size(); ++i) {
        if (i) json << ',';
        json << nearShadowMatrix_[i];
    }
    json << "\n  ],\n  \"shadow_matrix_row_major\": [";
    for (std::size_t i = 0; i < shadowMatrix_.size(); ++i) {
        if (i) json << ',';
        if (i % 4 == 0) json << "\n    ";
        json << shadowMatrix_[i];
    }
    json << "\n  ],\n  \"rgba_orientation\": \"GL bottom-up\",\n  \"ppm_orientation\": \"top-down\",\n"
         << "  \"depth_orientation\": \"GL bottom-up\"\n}\n";
    if (!json) throw std::runtime_error("failed writing capture metadata: " + basePath.string());
    checkError("capture readback");
}

void Renderer::captureColor(const std::filesystem::path& path, bool presented) {
    requireReady();
    // Diagnostics only: compare our finished render target with the window's
    // front buffer after SwapBuffers. Readback/encoding must not be benchmarked.
    std::filesystem::create_directories(path.parent_path());
    gl_.BindFramebuffer(GL_READ_FRAMEBUFFER, presented ? 0 : colorFbo_);
    gl_.ReadBuffer(presented ? GL_FRONT : GL_COLOR_ATTACHMENT0);
    gl_.PixelStorei(GL_PACK_ALIGNMENT, 1);
    std::vector<std::uint8_t> rgb(static_cast<std::size_t>(width_) * height_ * 3u);
    gl_.ReadPixels(0, 0, width_, height_, GL_RGB, GL_UNSIGNED_BYTE, rgb.data());
    checkError(presented ? "front buffer diagnostic" : "offscreen diagnostic");
    std::ofstream out(path, std::ios::binary);
    out << "P6\n" << width_ << ' ' << height_ << "\n255\n";
    for (int row = height_ - 1; row >= 0; --row)
        out.write(reinterpret_cast<const char*>(rgb.data() + static_cast<std::size_t>(row) * width_ * 3u),
                  static_cast<std::streamsize>(width_) * 3);
    if (!out) throw std::runtime_error("failed writing diagnostic image: " + path.string());
    gl_.BindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    gl_.ReadBuffer(GL_BACK);
}

void Renderer::updateTransforms(const std::uint32_t* indices, const double* worlds,
                                const float* normals, const std::uint32_t* mirrored,
                                std::size_t count) {
    requireReady();
    if (count > bundle_.entities.size()) throw std::runtime_error("transform update count exceeds entity count");
    if (count && (!indices || !worlds || !normals || !mirrored))
        throw std::runtime_error("transform update pointer is null");
    // Validate the entire batch before changing any entity or shadow cache.
    for (std::size_t i = 0; i < count; ++i) {
        const double* world = worlds + i * 16;
        if (indices[i] >= bundle_.entities.size() || mirrored[i] > 1)
            throw std::runtime_error("invalid transform update entity index or winding flag");
        if (world[12] != 0 || world[13] != 0 || world[14] != 0 || world[15] != 1 ||
            !std::all_of(world, world + 16, [](double v) { return std::isfinite(v); }) ||
            !std::all_of(normals + i * 9, normals + (i + 1) * 9,
                         [](float v) { return std::isfinite(v); }))
            throw std::runtime_error("transform update requires finite affine matrices and normals");
    }
    for (std::size_t i = 0; i < count; ++i) {
        Entity& entity = bundle_.entities[indices[i]];
        std::copy_n(worlds + i * 16, 16, entity.world.begin());
        std::copy_n(normals + i * 9, 9, entity.normal.begin());
        entity.flags = (entity.flags & ~2u) | (mirrored[i] ? 2u : 0u);
    }
    if (count) {
        ++transformRevision_;
        farFitValid_ = false;
        shadowDepthValid_ = nearShadowDepthValid_ = false;
        shadowTransition_ = false;
        shadowPoseValid_ = false;
    }
}

bool Renderer::setTransform(const std::string& stableEntityId, const std::array<double, 16>& world) {
    requireReady();
    if (world[12] != 0.0 || world[13] != 0.0 || world[14] != 0.0 || world[15] != 1.0 ||
        !std::all_of(world.begin(), world.end(), [](double x) { return std::isfinite(x); }))
        throw std::runtime_error("setTransform requires a finite affine matrix");
    const auto normal = inverseTranspose3x3(world); // Float32 arithmetic matches the renderer's normal input precision.
    float linear[3][3]{};
    for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) linear[r][c] = f32(world[r * 4 + c]);
    const bool mirrored = det3(linear) < 0;
    bool found = false;
    for (Entity& entity : bundle_.entities) if (entity.id == stableEntityId) {
        entity.world = world;
        entity.normal = normal;
        if (mirrored) entity.flags |= 2u;
        else entity.flags &= ~2u;
        found = true;
    }
    if (found) {
        ++transformRevision_;
        farFitValid_ = false;
        shadowDepthValid_ = nearShadowDepthValid_ = false;
        shadowTransition_ = false;
        shadowPoseValid_ = false;
    }
    return found;
}

std::string Renderer::rendererName() const {
    const auto* renderer = gl_.GetString(GL_RENDERER);
    return renderer ? reinterpret_cast<const char*>(renderer) : "(unknown OpenGL renderer)";
}

void Renderer::checkError(const char* stage) {
    const GLenum error = gl_.GetError();
    if (error != GL_NO_ERROR)
        throw std::runtime_error(std::string("OpenGL error 0x") + [&]() {
            std::ostringstream out; out << std::hex << error; return out.str();
        }() + " after " + stage);
}

void Renderer::requireReady() const {
    if (closed_) throw std::runtime_error("renderer is closed");
    if (!ready_) throw std::runtime_error("renderer initialization is incomplete");
}

void Renderer::close() {
    if (closed_) return;
    closed_ = true;
    ready_ = false;
    destroyShadowTarget();
    destroyColorTarget();
    for (auto& [key, instance] : instances_) {
        if (instance.vao) gl_.DeleteVertexArrays(1, &instance.vao);
        if (instance.buffer) gl_.DeleteBuffers(1, &instance.buffer);
    }
    instances_.clear();
    for (auto& mesh : meshes_) {
        if (mesh.vao) gl_.DeleteVertexArrays(1, &mesh.vao);
        if (mesh.vbo) gl_.DeleteBuffers(1, &mesh.vbo);
        if (mesh.ebo) gl_.DeleteBuffers(1, &mesh.ebo);
    }
    meshes_.clear();
    for (std::size_t i = 0; i < textures_.size(); ++i)
        if (textures_[i] && (i >= bundle_.textures.size() || !bundle_.textures[i].borrowedHandle))
            gl_.DeleteTextures(1, &textures_[i]);
    textures_.clear();
    if (skyVao_) gl_.DeleteVertexArrays(1, &skyVao_);
    skyVao_ = 0;
    materialProgram_ = groundProgram_ = activeColorProgram_ = skyProgram_ = shadowProgram_ = 0;
    locations_.clear();
    programSet_.reset();
}

} // namespace spqr
