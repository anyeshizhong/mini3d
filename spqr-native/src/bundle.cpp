#include "bundle.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>
#include <span>
#include <stdexcept>
#include <type_traits>

namespace spqr {
namespace {

constexpr std::uint32_t kMaxItems = 20'000'000;
constexpr std::uint32_t kNone = 0xffffffffu;

class Reader {
public:
    explicit Reader(const std::filesystem::path& path) : path_(path) {
        std::ifstream in(path, std::ios::binary | std::ios::ate);
        if (!in) throw std::runtime_error("cannot open bundle file: " + path.string());
        const auto end = in.tellg();
        if (end < 0 || static_cast<std::uint64_t>(end) > (std::uint64_t{1} << 34))
            throw std::runtime_error("invalid or oversized bundle file: " + path.string());
        bytes_.resize(static_cast<std::size_t>(end));
        in.seekg(0);
        if (!bytes_.empty() && !in.read(reinterpret_cast<char*>(bytes_.data()), end))
            throw std::runtime_error("short read from bundle file: " + path.string());
    }

    template<class T> T scalar() {
        static_assert(std::is_trivially_copyable_v<T>);
        require(sizeof(T));
        T value{};
        std::memcpy(&value, bytes_.data() + cursor_, sizeof(T));
        cursor_ += sizeof(T);
        return value;
    }
    std::string string() {
        const auto length = scalar<std::uint32_t>();
        if (length > 16u * 1024u * 1024u) fail("string exceeds 16 MiB");
        require(length);
        std::string value(reinterpret_cast<const char*>(bytes_.data() + cursor_), length);
        cursor_ += length;
        if (value.find('\0') != std::string::npos) fail("string contains NUL");
        return value;
    }
    template<class T> std::vector<T> array(std::size_t count) {
        if (count > kMaxItems) fail("array count exceeds safety limit");
        if (count > std::numeric_limits<std::size_t>::max() / sizeof(T)) fail("array size overflow");
        const auto byteCount = count * sizeof(T);
        require(byteCount);
        std::vector<T> result(count);
        if (byteCount) std::memcpy(result.data(), bytes_.data() + cursor_, byteCount);
        cursor_ += byteCount;
        return result;
    }
    void magic(const char (&expected)[9]) {
        require(8);
        if (std::memcmp(bytes_.data() + cursor_, expected, 8) != 0) fail("bad file signature");
        cursor_ += 8;
    }
    void finish() {
        if (cursor_ != bytes_.size()) fail("unexpected trailing bytes");
    }
    [[noreturn]] void fail(const std::string& message) const {
        throw std::runtime_error(path_.string() + ": " + message + " at byte " + std::to_string(cursor_));
    }
private:
    void require(std::size_t count) const {
        if (count > bytes_.size() - std::min(cursor_, bytes_.size())) fail("truncated file");
    }
    std::filesystem::path path_;
    std::vector<std::byte> bytes_;
    std::size_t cursor_ = 0;
};

void requireFinite(std::span<const double> values, Reader& reader, const char* what) {
    if (!std::all_of(values.begin(), values.end(), [](double x) { return std::isfinite(x); }))
        reader.fail(std::string("non-finite ") + what);
}
void requireFinite(std::span<const float> values, Reader& reader, const char* what) {
    if (!std::all_of(values.begin(), values.end(), [](float x) { return std::isfinite(x); }))
        reader.fail(std::string("non-finite ") + what);
}
std::uint32_t count(Reader& r, const char* what) {
    const auto n = r.scalar<std::uint32_t>();
    if (n > kMaxItems) r.fail(std::string(what) + " count exceeds safety limit");
    return n;
}
UniformBlock readUniformBlock(Reader& r) {
    UniformBlock block;
    const auto n = count(r, "uniform");
    block.reserve(n);
    for (std::uint32_t i = 0; i < n; ++i) {
        UniformValue value;
        value.name = r.string();
        value.type = r.scalar<std::uint32_t>();
        value.components = r.scalar<std::uint32_t>();
        if (value.name.empty()) r.fail("empty uniform name");
        if (value.components == 0 || value.components > 65536) r.fail("invalid uniform component count");
        value.bytes.resize(static_cast<std::size_t>(value.components) * sizeof(std::uint32_t));
        auto raw = r.array<std::uint32_t>(value.components);
        std::memcpy(value.bytes.data(), raw.data(), value.bytes.size());
        block.push_back(std::move(value));
    }
    return block;
}
bool affine(const std::array<double, 16>& m) {
    return m[12] == 0.0 && m[13] == 0.0 && m[14] == 0.0 && m[15] == 1.0;
}

} // namespace

Bundle loadBundle(const std::filesystem::path& directory) {
    if (std::endian::native != std::endian::little)
        throw std::runtime_error("SPQR native loader requires a little-endian host");
    Reader r(directory / "scene.bin");
    r.magic("SPQRN001");
    if (r.scalar<std::uint32_t>() != 1) r.fail("unsupported scene bundle version");
    Bundle bundle;

    const auto textureCount = count(r, "texture");
    bundle.textures.reserve(textureCount);
    for (std::uint32_t ti = 0; ti < textureCount; ++ti) {
        Texture texture;
        texture.target = r.scalar<std::uint32_t>();
        texture.internalFormat = r.scalar<std::uint32_t>();
        texture.minFilter = r.scalar<std::uint32_t>();
        texture.magFilter = r.scalar<std::uint32_t>();
        texture.wrapS = r.scalar<std::uint32_t>();
        texture.wrapT = r.scalar<std::uint32_t>();
        texture.wrapR = r.scalar<std::uint32_t>();
        if (texture.target != 0x0de1u && texture.target != 0x8513u)
            r.fail("unsupported texture target; only 2D and cube maps are supported");
        const auto mipCount = count(r, "texture mip");
        if (mipCount == 0) r.fail("texture has no mip levels");
        texture.mips.reserve(mipCount);
        for (std::uint32_t level = 0; level < mipCount; ++level) {
            TextureMip mip;
            mip.width = r.scalar<std::uint32_t>();
            mip.height = r.scalar<std::uint32_t>();
            if (mip.width == 0 || mip.height == 0 || mip.width > 32768 || mip.height > 32768)
                r.fail("invalid texture mip dimensions");
            if (texture.target == 0x8513u && mip.width != mip.height)
                r.fail("cube map faces must be square");
            if (level && (mip.width != std::max(1u, texture.mips.back().width / 2) ||
                          mip.height != std::max(1u, texture.mips.back().height / 2)))
                r.fail("texture mip dimensions are not a complete halving chain");
            const std::uint64_t texels = std::uint64_t(mip.width) * mip.height * 4u *
                                         (texture.target == 0x8513u ? 6u : 1u);
            if (texels > (std::uint64_t{1} << 31)) r.fail("texture mip exceeds safety limit");
            mip.faces = r.array<float>(static_cast<std::size_t>(texels));
            requireFinite(mip.faces, r, "texture data");
            texture.mips.push_back(std::move(mip));
        }
        bundle.textures.push_back(std::move(texture));
    }

    bundle.materialGlobals = readUniformBlock(r);
    bundle.skyGlobals = readUniformBlock(r);
    const auto materialCount = count(r, "material");
    if (!materialCount) r.fail("scene has no materials");
    bundle.materials.reserve(materialCount);
    for (std::uint32_t i = 0; i < materialCount; ++i) {
        Material material;
        material.parameters = readUniformBlock(r);
        material.flags = r.scalar<std::uint32_t>();
        if (material.flags & ~1u) r.fail("unsupported material flag bits");
        for (auto& index : material.textureIndices) {
            index = r.scalar<std::uint32_t>();
            if (index != kNone && index >= textureCount) r.fail("material texture index is out of range");
        }
        if (material.textureIndices[7] != kNone || material.textureIndices[12] != kNone)
            r.fail("texture units 7 and 12 are reserved for runtime shadow samplers");
        bundle.materials.push_back(std::move(material));
    }

    const auto meshCount = count(r, "mesh");
    if (!meshCount) r.fail("scene has no meshes");
    bundle.meshes.reserve(meshCount);
    for (std::uint32_t i = 0; i < meshCount; ++i) {
        Mesh mesh;
        mesh.material = r.scalar<std::uint32_t>();
        mesh.vertexCount = r.scalar<std::uint32_t>();
        mesh.indexCount = r.scalar<std::uint32_t>();
        if (mesh.material >= materialCount) r.fail("mesh material index is out of range");
        if (!mesh.vertexCount || !mesh.indexCount || mesh.indexCount % 3)
            r.fail("mesh must have vertices and a triangle index list");
        for (double& value : mesh.bounds) value = r.scalar<double>();
        requireFinite(mesh.bounds, r, "mesh bounds");
        for (int axis = 0; axis < 3; ++axis)
            if (mesh.bounds[axis] > mesh.bounds[axis + 3]) r.fail("inverted mesh bounds");
        mesh.vertices = r.array<float>(static_cast<std::size_t>(mesh.vertexCount) * 12u);
        requireFinite(mesh.vertices, r, "mesh vertex data");
        mesh.indices = r.array<std::uint32_t>(mesh.indexCount);
        if (std::any_of(mesh.indices.begin(), mesh.indices.end(), [&](std::uint32_t index) {
                return index >= mesh.vertexCount;
            })) r.fail("mesh index exceeds vertex count");
        bundle.meshes.push_back(std::move(mesh));
    }

    const auto entityCount = count(r, "entity");
    if (!entityCount) r.fail("scene has no entities");
    bundle.entities.reserve(entityCount);
    for (std::uint32_t i = 0; i < entityCount; ++i) {
        Entity entity;
        entity.id = r.string();
        entity.mesh = r.scalar<std::uint32_t>();
        entity.flags = r.scalar<std::uint32_t>();
        if (entity.id.empty()) r.fail("entity stable ID is empty");
        if (entity.mesh >= meshCount) r.fail("entity mesh index is out of range");
        if (entity.flags & ~3u) r.fail("unsupported entity flag bits");
        for (double& value : entity.world) value = r.scalar<double>();
        for (float& value : entity.normal) value = r.scalar<float>();
        requireFinite(entity.world, r, "entity world matrix");
        requireFinite(entity.normal, r, "entity normal matrix");
        if (!affine(entity.world)) r.fail("projective entity transform is unsupported");
        bundle.entities.push_back(std::move(entity));
    }

    const auto orderCount = count(r, "opaque order");
    bundle.opaqueOrder = r.array<std::uint32_t>(orderCount);
    std::vector<bool> seen(entityCount, false);
    for (const auto index : bundle.opaqueOrder) {
        if (index >= entityCount) r.fail("opaque-order entity index is out of range");
        if (seen[index]) r.fail("opaque order contains duplicate entity indices");
        seen[index] = true;
    }
    for (double& value : bundle.lightDirection) value = r.scalar<double>();
    requireFinite(bundle.lightDirection, r, "light direction");
    if (std::hypot(bundle.lightDirection[0], bundle.lightDirection[1], bundle.lightDirection[2]) < 1e-15)
        r.fail("light direction has zero length");
    bundle.shadowResolution = r.scalar<std::uint32_t>();
    bundle.shadowBias = r.scalar<float>();
    bundle.normalBias = r.scalar<float>();
    bundle.shadowStrength = r.scalar<float>();
    bundle.shadowEnabled = r.scalar<std::uint32_t>() != 0;
    bundle.groundZ = r.scalar<double>();
    if (bundle.shadowResolution == 0 || bundle.shadowResolution > 32768)
        r.fail("invalid shadow-map resolution");
    if (!std::isfinite(bundle.shadowBias) || !std::isfinite(bundle.normalBias) ||
        !std::isfinite(bundle.shadowStrength) || !std::isfinite(bundle.groundZ))
        r.fail("non-finite shadow or ground setting");
    r.finish();
    return bundle;
}

std::vector<CameraFrame> loadFrames(const std::filesystem::path& path) {
    Reader r(path);
    r.magic("SPQRF001");
    const auto n = count(r, "camera frame");
    if (!n) r.fail("frames file is empty");
    std::vector<CameraFrame> frames;
    frames.reserve(n);
    for (std::uint32_t i = 0; i < n; ++i) {
        CameraFrame frame;
        frame.route = r.string();
        frame.t = r.scalar<double>();
        for (double& value : frame.position) value = r.scalar<double>();
        for (double& value : frame.rotation) value = r.scalar<double>();
        for (double& value : frame.view) value = r.scalar<double>();
        for (double& value : frame.projection) value = r.scalar<double>();
        frame.nearPlane = r.scalar<double>();
        frame.farPlane = r.scalar<double>();
        if (frame.route != "walk" && frame.route != "orbit") r.fail("unsupported camera route name");
        if (!std::isfinite(frame.t) || !std::isfinite(frame.nearPlane) ||
            !std::isfinite(frame.farPlane) || frame.nearPlane <= 0 || frame.farPlane <= frame.nearPlane)
            r.fail("invalid camera frame scalar");
        requireFinite(frame.position, r, "camera position");
        requireFinite(frame.rotation, r, "camera rotation");
        requireFinite(frame.view, r, "camera view matrix");
        requireFinite(frame.projection, r, "camera projection matrix");
        frames.push_back(std::move(frame));
    }
    r.finish();
    return frames;
}

std::string readTextFile(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open shader: " + path.string());
    std::ostringstream output;
    output << in.rdbuf();
    if (!in.good() && !in.eof()) throw std::runtime_error("failed reading shader: " + path.string());
    return output.str();
}

} // namespace spqr
