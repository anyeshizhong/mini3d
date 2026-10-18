#pragma once

#include "bundle.hpp"
#include "gl_api.hpp"

#include <array>
#include <cstdint>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <vector>

namespace spqr {

struct FrameStats {
    std::uint32_t colorDraws = 0, shadowDraws = 0;
    std::uint64_t colorTriangles = 0, shadowTriangles = 0;
    std::uint32_t colorVisible = 0, shadowCasters = 0;
    double inputNear = 0, colorNear = 0;
};

class Renderer {
public:
    Renderer(GLApi& gl, Bundle& bundle, const std::filesystem::path& bundleDirectory,
             int width, int height, bool stabilizeDepth = true, int msaaSamples = 1,
             bool stableShadows = true);
    ~Renderer();
    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;

    // targetSingleSampleFbo==0 keeps the standalone viewer path. When nonzero,
    // render into the private target, resolve all attachments, then copy RGBA,
    // depth and stencil into the caller's single-sample target without present/swap.
    FrameStats render(const CameraFrame& frame, GLuint targetSingleSampleFbo = 0);
    void resize(int width, int height, int samples);
    void updateGlobals(UniformBlock materialGlobals, UniformBlock skyGlobals,
                       const std::array<double, 3>& lightDirection,
                       std::uint32_t shadowResolution, float shadowBias,
                       bool shadowEnabled, double groundZ);
    void capture(const CameraFrame& frame, const std::filesystem::path& basePath,
                 std::size_t frameIndex, const FrameStats& stats);
    bool setTransform(const std::string& stableEntityId, const std::array<double, 16>& world);
    void captureColor(const std::filesystem::path& path, bool presented = false);
    std::string rendererName() const;
    void close();

private:
    struct MeshGpu { GLuint vao = 0, vbo = 0, ebo = 0; };
    struct InstanceGpu { GLuint vao = 0, buffer = 0; std::vector<float> lastPayload; };
    struct Batch { std::uint32_t mesh = 0; bool mirrored = false, ground = false; std::vector<std::uint32_t> entities; };
    struct DrawEntry { std::uint32_t entity = 0; float depth = 0; };

    GLuint compileProgram(const std::filesystem::path& vertex, const std::filesystem::path& fragment);
    GLuint compileShader(const std::filesystem::path& path, GLenum type);
    void uploadTextures();
    void uploadMeshes();
    void createShadowTarget(bool nearLayer);
    void destroyShadowTarget();
    void drawShadow(const CameraFrame& frame, FrameStats& stats);
    void drawShadowLayer(const CameraFrame& frame, FrameStats& stats,
                         const std::vector<struct ShadowBox>& boxes, bool nearLayer);
    void drawSky(const CameraFrame& frame);
    void drawColor(const CameraFrame& frame, const std::vector<bool>& visible, FrameStats& stats);
    void bindMaterial(std::uint32_t materialIndex, bool ground, bool mirrored);
    void bindMaterialTextures(std::uint32_t materialIndex);
    void applyUniformBlock(GLuint program, const UniformBlock& block);
    void setUniform1i(GLuint program, const char* name, GLint value);
    void setUniform1f(GLuint program, const char* name, GLfloat value);
    void setUniform3f(GLuint program, const char* name, GLfloat x, GLfloat y, GLfloat z);
    void setUniformMatrix4(GLuint program, const char* name, const float* value);
    void setUniformMatrix3(GLuint program, const char* name, const float* value);
    GLint uniformLocation(GLuint program, const std::string& name);
    InstanceGpu& instanceResource(std::uint32_t meshIndex, bool shadowPass,
                                  std::size_t batchOrdinal);
    std::vector<Batch> makeBatches(const std::vector<std::uint32_t>& indices) const;
    std::array<double, 16> effectiveWorld(const Entity& entity, const CameraFrame& frame) const;
    std::array<float, 9> effectiveNormal(const Entity& entity, const CameraFrame& frame) const;
    std::array<double, 6> worldBounds(const Entity& entity, const CameraFrame& frame,
                                      bool& valid) const;
    std::vector<bool> visibleInFrustum(const CameraFrame& frame, bool colorPass) const;
    bool boundsVisible(const std::array<double, 6>& bounds,
                       const std::array<double, 24>& planes) const;
    std::array<double, 24> frustumPlanes(const std::array<double, 16>& view,
                                         const std::array<double, 16>& projection) const;
    void checkError(const char* stage);
    void updateGround(const CameraFrame& frame);
    void createColorTarget();
    void destroyColorTarget();

    GLApi& gl_;
    Bundle& bundle_;
    std::filesystem::path shaderDirectory_;
    int width_, height_;
    int msaaSamples_ = 1;
    GLuint materialProgram_ = 0, groundProgram_ = 0, activeColorProgram_ = 0;
    GLuint skyProgram_ = 0, shadowProgram_ = 0, skyVao_ = 0;
    std::vector<GLuint> textures_;
    std::vector<MeshGpu> meshes_;
    std::unordered_map<std::string, InstanceGpu> instances_;
    std::unordered_map<std::uint64_t, std::unordered_map<std::string, GLint>> locations_;
    GLuint shadowFbo_ = 0, shadowTexture_ = 0, rawSampler_ = 0;
    GLuint nearShadowFbo_ = 0, nearShadowTexture_ = 0;
    static constexpr unsigned nearShadowResolution_ = 4096;
    GLuint colorFbo_ = 0, colorTexture_ = 0, colorDepth_ = 0;
    GLuint msaaFbo_ = 0, msaaColor_ = 0, msaaDepth_ = 0;
    std::array<double, 16> shadowMatrix_{};
    std::array<double, 16> nearShadowMatrix_{};
    bool shadowActive_ = false;
    std::uint64_t transformRevision_ = 0;
    bool closed_ = false;
    bool stabilizeDepth_ = true;
    bool stableShadows_ = true, nearShadowActive_ = false;
};

} // namespace spqr
