#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace spqr {

struct UniformValue {
    std::string name;
    std::uint32_t type = 0;
    std::uint32_t components = 0;
    std::vector<std::byte> bytes;
};
using UniformBlock = std::vector<UniformValue>;

struct TextureMip {
    std::uint32_t width = 0, height = 0;
    std::vector<float> faces; // Face-major RGBA float pixels.
};
struct Texture {
    std::uint32_t target = 0, internalFormat = 0;
    std::uint32_t minFilter = 0, magFilter = 0;
    std::uint32_t wrapS = 0, wrapT = 0, wrapR = 0;
    std::vector<TextureMip> mips;
};
struct Material {
    UniformBlock parameters;
    std::uint32_t flags = 0; // bit 0: double-sided.
    std::array<std::uint32_t, 13> textureIndices{};
};
struct Mesh {
    std::uint32_t material = 0, vertexCount = 0, indexCount = 0;
    std::array<double, 6> bounds{}; // lo xyz, hi xyz.
    std::vector<float> vertices;   // position3 normal3 uv2 color4.
    std::vector<std::uint32_t> indices;
};
struct Entity {
    std::string id;
    std::uint32_t mesh = 0, flags = 0;
    std::array<double, 16> world{};
    std::array<float, 9> normal{};
};
struct CameraFrame {
    std::string route;
    double t = 0;
    std::array<double, 3> position{};
    std::array<double, 9> rotation{};
    std::array<double, 16> view{}, projection{};
    double nearPlane = 0.1, farPlane = 1000;
};
struct Bundle {
    std::vector<Texture> textures;
    UniformBlock materialGlobals, skyGlobals;
    std::vector<Material> materials;
    std::vector<Mesh> meshes;
    std::vector<Entity> entities;
    std::vector<std::uint32_t> opaqueOrder;
    std::array<double, 3> lightDirection{};
    std::uint32_t shadowResolution = 2048;
    float shadowBias = 0.001f, normalBias = 0.0f, shadowStrength = 1.0f;
    bool shadowEnabled = true;
    double groundZ = 0;
};

Bundle loadBundle(const std::filesystem::path& directory);
std::vector<CameraFrame> loadFrames(const std::filesystem::path& path);
std::string readTextFile(const std::filesystem::path& path);

} // namespace spqr
