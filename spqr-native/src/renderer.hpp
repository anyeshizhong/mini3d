#pragma once

#include "bundle.hpp"
#include "gl_api.hpp"

#include <array>
#include <cstdint>
#ifdef SPQR_TERRAIN_LAB
#include <deque>
#endif
#include <filesystem>
#include <memory>
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

#ifdef SPQR_TERRAIN_LAB
struct TerrainGpuTimingSample {
    std::uint32_t frame = 0;
    std::uint64_t sampleId = 0;
    double gpuMs = 0.0;
    bool dropped = false;
};
#endif

// Shader source is captured once per initialization so cache keys and compiled
// programs always use the same complete source bytes.
struct RendererShaderSources {
    std::string materialVertex, materialFragment;
    std::string groundVertex, groundFragment;
    std::string skyVertex, skyFragment;
    std::string shadowVertex, shadowFragment;
    bool hasGroundVertex = false;
    bool hasGroundFragment = false;
};

struct ProgramSet;

class Renderer {
public:
    Renderer(GLApi& gl, Bundle& bundle, const std::filesystem::path& bundleDirectory,
             int width, int height, bool stabilizeDepth = true, int msaaSamples = 1,
             bool stableShadows = true, bool deferred = false);
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
    void updateTransforms(const std::uint32_t* indices, const double* worlds,
                          const float* normals, const std::uint32_t* mirrored, std::size_t count);
    void captureColor(const std::filesystem::path& path, bool presented = false);
    std::string rendererName() const;
    void close();
#ifdef SPQR_TERRAIN_LAB
    void setTerrainGpuTimingEnabled(bool enabled);
    void beginTerrainGpuTimingSample(std::uint32_t frameIndex);
    void endTerrainGpuTimingSample(bool successful = true);
    std::vector<TerrainGpuTimingSample> pollTerrainGpuTiming(std::size_t capacity);
#endif
    // Compile and upload a bounded portion of the renderer on the current GL
    // context. Returns true once all resources and targets are ready.
    bool initializeStep();
    bool ready() const { return ready_; }
    std::uint32_t programCompileCount() const { return programCompileCount_; }

private:
    friend struct ShadowAudit;  // Opt-in GPU regression executable; no runtime API.
#ifdef SPQR_TERRAIN_LAB
    friend struct TerrainLab;   // Isolated dynamic-mesh experiment bridge.
#endif
    struct MeshGpu { GLuint vao = 0, vbo = 0, ebo = 0; };
    struct InstanceGpu { GLuint vao = 0, buffer = 0; std::vector<float> lastPayload; };
    struct Batch { std::uint32_t mesh = 0; bool mirrored = false, ground = false; std::vector<std::uint32_t> entities; };
    struct DrawEntry { std::uint32_t entity = 0; float depth = 0; };

    GLuint compileProgram(const std::string& vertexSource, const std::string& fragmentSource,
                          const std::filesystem::path& vertex,
                          const std::filesystem::path& fragment);
    GLuint compileShader(const std::string& source, const std::filesystem::path& path, GLenum type);
    void uploadTextures();
    void uploadMesh(std::size_t index);
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
    void applyGlobalUniforms();
    void requireReady() const;

#ifdef SPQR_TERRAIN_LAB
    using GenQueriesProc = void (APIENTRY*)(GLsizei, GLuint*);
    using DeleteQueriesProc = void (APIENTRY*)(GLsizei, const GLuint*);
    using QueryCounterProc = void (APIENTRY*)(GLuint, GLenum);
    using GetQueryivProc = void (APIENTRY*)(GLenum, GLenum, GLint*);
    using GetQueryObjectivProc = void (APIENTRY*)(GLuint, GLenum, GLint*);
    using GetQueryObjectui64vProc = void (APIENTRY*)(GLuint, GLenum, GLuint64*);
    struct TerrainGpuQueryPair {
        GLuint begin = 0, end = 0;
        std::uint64_t sampleId = 0;
        bool inFlight = false;
    };
    struct PendingTerrainGpuSample {
        std::uint32_t frame = 0;
        std::uint64_t sampleId = 0, gpuNanoseconds = 0;
        std::size_t pendingSegments = 0;
        bool sealed = false, dropped = false;
    };
    static constexpr std::size_t terrainGpuQueryPairCapacity_ = 32;
    void loadTerrainGpuTimingApi();
    void destroyTerrainGpuTiming();
    std::size_t acquireTerrainGpuQueryPair();
    void beginTerrainGpuTimingInterval();
    void endTerrainGpuTimingInterval();
    void finalizeTerrainGpuSamples();
    PendingTerrainGpuSample& currentTerrainGpuSample();
    PendingTerrainGpuSample* findTerrainGpuSample(std::uint64_t sampleId);
#endif

    enum class InitStage { Material, Ground, Sky, Shadow, Textures, Meshes, Finalize, Ready };

    GLApi& gl_;
    Bundle& bundle_;
    std::filesystem::path shaderDirectory_;
    RendererShaderSources shaderSources_;
    std::shared_ptr<ProgramSet> programSet_;
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
    std::array<double, 16> shadowDrawMatrix_{}, nearShadowDrawMatrix_{};
    // Preserve the previous far grid while a scale/depth refit fades in.
    std::array<double, 16> shadowPreviousMatrix_{}, shadowPose_{}, shadowLens_{};
    int shadowLayer_ = 0, shadowPreviousLayer_ = 1, shadowBlendStep_ = 8;
    bool shadowTransition_ = false, shadowPoseValid_ = false;
    bool shadowTransitionsEnabled_ = true; // Audit can isolate fit from blending.
    bool shadowActive_ = false;
    bool farFitValid_ = false;
    bool shadowDepthValid_ = false, nearShadowDepthValid_ = false;
    std::uint64_t transformRevision_ = 0;
    bool closed_ = false;
    bool ready_ = false;
    std::uint32_t programCompileCount_ = 0;
    InitStage initStage_ = InitStage::Material;
    std::size_t nextMesh_ = 0;
    bool stabilizeDepth_ = true;
    bool stableShadows_ = true, nearShadowActive_ = false;
#ifdef SPQR_TERRAIN_LAB
    bool terrainGpuTimingEnabled_ = false;
    bool terrainGpuTimingSampleActive_ = false;
    bool terrainGpuTimingIntervalActive_ = false;
    std::uint32_t terrainGpuTimingFrame_ = 0;
    std::uint64_t terrainGpuTimingNextSampleId_ = 1;
    std::uint64_t terrainGpuTimingCurrentSampleId_ = 0;
    std::size_t terrainGpuTimingActivePair_ = static_cast<std::size_t>(-1);
    bool terrainGpuTimingSampleDropped_ = false;
    std::vector<TerrainGpuQueryPair> terrainGpuQueryPairs_;
    std::deque<PendingTerrainGpuSample> terrainGpuPendingSamples_;
    std::deque<TerrainGpuTimingSample> terrainGpuReadySamples_;
    GenQueriesProc terrainGpuGenQueries_ = nullptr;
    DeleteQueriesProc terrainGpuDeleteQueries_ = nullptr;
    QueryCounterProc terrainGpuQueryCounter_ = nullptr;
    GetQueryivProc terrainGpuGetQueryiv_ = nullptr;
    GetQueryObjectivProc terrainGpuGetQueryObjectiv_ = nullptr;
    GetQueryObjectui64vProc terrainGpuGetQueryObjectui64v_ = nullptr;
#endif
};

} // namespace spqr
