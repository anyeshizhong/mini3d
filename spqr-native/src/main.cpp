#include "bundle.hpp"
#include "gl_api.hpp"
#include "platform_win32.hpp"
#include "renderer.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" {
__declspec(dllexport) DWORD NvOptimusEnablement = 0x00000001;
__declspec(dllexport) DWORD AmdPowerXpressRequestHighPerformance = 0x00000001;
}

namespace {
using Clock = std::chrono::steady_clock;
struct Options {
    std::filesystem::path bundle, output;
    std::filesystem::path recordDir;
    std::string route = "walk";
    std::uint32_t frames = 120, warmup = 24;
    std::uint32_t recordEvery = 6, recordCount = 60;
    std::uint32_t samples = 1;
    double seconds = 0;
    bool hidden = false, capture = false, validateOnly = false, help = false;
    bool vsync = false, smoothCamera = false, freezeCamera = false;
    bool legacyDepth = false;
    bool legacyShadows = false;
};
struct Sample {
    std::size_t frameIndex = 0;
    double t = 0, workMs = 0, swapIntervalMs = 0, swapCallMs = 0;
    spqr::FrameStats stats;
};

[[noreturn]] void usageError(const std::string& message) {
    throw std::runtime_error(message + "\nUse --help to see the command options.");
}
std::uint32_t parseCount(const std::string& text, const char* option) {
    try {
        std::size_t consumed = 0;
        const unsigned long value = std::stoul(text, &consumed, 10);
        if (consumed != text.size() || value > 1'000'000ul) usageError(std::string("invalid ") + option);
        return static_cast<std::uint32_t>(value);
    } catch (const std::exception&) { usageError(std::string("invalid ") + option + ": " + text); }
}
Options parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&](const char* name) -> std::string {
            if (i + 1 >= argc) usageError(std::string("missing value after ") + name);
            return argv[++i];
        };
        if (arg == "--bundle") options.bundle = value("--bundle");
        else if (arg == "--output") options.output = value("--output");
        else if (arg == "--route") options.route = value("--route");
        else if (arg == "--frames") options.frames = parseCount(value("--frames"), "--frames");
        else if (arg == "--warmup") options.warmup = parseCount(value("--warmup"), "--warmup");
        else if (arg == "--samples") options.samples = parseCount(value("--samples"), "--samples");
        else if (arg == "--record-dir") options.recordDir = value("--record-dir");
        else if (arg == "--record-every") options.recordEvery = parseCount(value("--record-every"), "--record-every");
        else if (arg == "--record-count") options.recordCount = parseCount(value("--record-count"), "--record-count");
        else if (arg == "--seconds") {
            const std::string raw = value("--seconds");
            try {
                std::size_t consumed = 0;
                options.seconds = std::stod(raw, &consumed);
                if (consumed != raw.size() || !std::isfinite(options.seconds) || options.seconds <= 0 || options.seconds > 3600)
                    usageError("--seconds must be between 0 and 3600");
            } catch (const std::exception&) { usageError("invalid --seconds: " + raw); }
        }
        else if (arg == "--hidden") options.hidden = true;
        else if (arg == "--capture") options.capture = true;
        else if (arg == "--vsync") options.vsync = true;
        else if (arg == "--smooth-camera") options.smoothCamera = true;
        else if (arg == "--freeze-camera") options.freezeCamera = true;
        else if (arg == "--legacy-depth") options.legacyDepth = true;
        else if (arg == "--legacy-shadows") options.legacyShadows = true;
        else if (arg == "--validate-only") options.validateOnly = true;
        else if (arg == "--help" || arg == "-h") options.help = true;
        else usageError("unknown option: " + arg);
    }
    if (options.help) return options;
    if (options.bundle.empty()) usageError("--bundle is required");
    if (options.route != "walk" && options.route != "orbit") usageError("--route must be walk or orbit");
    if (options.samples != 1 && options.samples != 4) usageError("--samples must be 1 or 4");
    if (options.output.empty()) options.output = options.bundle / "native-output";
    if (!options.frames && !options.validateOnly) usageError("--frames must be greater than zero");
    if (options.smoothCamera && options.seconds <= 0)
        usageError("--smooth-camera requires --seconds");
    if (options.smoothCamera && options.freezeCamera)
        usageError("--smooth-camera and --freeze-camera cannot be used together");
    if (!options.recordEvery || !options.recordCount)
        usageError("--record-every and --record-count must be greater than zero");
    return options;
}
void printHelp() {
    std::cout << "SPQR native OpenGL viewer/benchmark\n"
                 "  --bundle DIR       SPQR offline export bundle\n"
                 "  --output DIR       benchmark and capture output directory\n"
                 "  --route walk|orbit camera fixture route (default walk)\n"
                 "  --frames N         measured frames (default 120)\n"
                 "  --warmup N         warmup frames (default 24)\n"
                 "  --samples 1|4      color-pass sample count (default 1)\n"
                 "  --seconds N        measure for wall-clock seconds\n"
                 "  --vsync            enable WGL vertical synchronization (default off)\n"
                 "  --smooth-camera    in --seconds mode, interpolate the route at elapsed-time pace\n"
                 "  --freeze-camera    hold the first measured fixture camera during measurement\n"
                 "  --legacy-depth     reproduce original camera near/depth precision for regression\n"
                 "  --legacy-shadows   reproduce original single shadow map for regression\n"
                 "  --hidden           create a hidden benchmark window\n"
                 "  --capture          write fixed first-measured and +60-fixture captures\n"
                 "  --record-dir DIR   save bounded FBO/front-buffer diagnostic frame pairs\n"
                 "  --record-every N   diagnostic capture cadence (default 6 measurement frames)\n"
                 "  --record-count N   maximum diagnostic capture pairs (default 60)\n"
                 "  --validate-only    validate scene.bin, frames.bin and required shaders without GL\n";
}
std::vector<spqr::CameraFrame> chooseRoute(const std::vector<spqr::CameraFrame>& all, const std::string& route) {
    std::vector<spqr::CameraFrame> frames;
    for (const auto& frame : all) if (frame.route == route) frames.push_back(frame);
    if (frames.empty()) throw std::runtime_error("frames.bin contains no frames for route " + route);
    return frames;
}
using V3 = std::array<double, 3>;
V3 subtract3(const V3& a, const V3& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}
V3 cross3(const V3& a, const V3& b) {
    return {a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]};
}
double dot3(const V3& a, const V3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
V3 normalize3(V3 value, const char* label) {
    const double length = std::sqrt(dot3(value, value));
    if (!(length > 1e-12) || !std::isfinite(length))
        throw std::runtime_error(std::string("cannot build smooth camera: degenerate ") + label);
    for (double& component : value) component /= length;
    return value;
}
spqr::CameraFrame smoothCameraAt(const std::vector<spqr::CameraFrame>& routeFrames,
                                 std::size_t firstMeasured, double elapsedSeconds,
                                 int width, int height, std::size_t* sourceFrameIndex = nullptr) {
    constexpr double kLegSeconds = 8.0;
    if (firstMeasured >= routeFrames.size() || routeFrames.size() - firstMeasured < 2)
        throw std::runtime_error("--smooth-camera needs at least two measured route fixtures");
    const double phase = std::fmod(std::max(0.0, elapsedSeconds), 2.0 * kLegSeconds);
    const double progress = phase <= kLegSeconds
        ? phase / kLegSeconds : (2.0 * kLegSeconds - phase) / kLegSeconds;
    const std::size_t sampleCount = routeFrames.size() - firstMeasured;
    const double samplePosition = progress * static_cast<double>(sampleCount - 1);
    const std::size_t leftIndex = std::min(static_cast<std::size_t>(std::floor(samplePosition)), sampleCount - 1);
    const std::size_t rightIndex = std::min(leftIndex + 1, sampleCount - 1);
    const double blend = samplePosition - static_cast<double>(leftIndex);
    const auto& a = routeFrames[firstMeasured + leftIndex];
    const auto& b = routeFrames[firstMeasured + rightIndex];
    if (sourceFrameIndex) *sourceFrameIndex = firstMeasured + leftIndex;

    spqr::CameraFrame frame;
    frame.route = a.route;
    frame.t = a.t + (b.t - a.t) * blend;
    for (int axis = 0; axis < 3; ++axis)
        frame.position[axis] = a.position[axis] + (b.position[axis] - a.position[axis]) * blend;
    frame.nearPlane = std::min(a.nearPlane, b.nearPlane);
    frame.farPlane = std::max(a.farPlane, b.farPlane);
    if (!(frame.nearPlane > 0 && frame.nearPlane < frame.farPlane))
        throw std::runtime_error("cannot build smooth camera: invalid conservative clipping range");

    const V3 target = frame.route == "walk" ? V3{0.0, 20.0, 3.0} : V3{0.0, 8.0, 2.0};
    const V3 backward = normalize3(subtract3(frame.position, target), "look-at direction");
    const V3 zUp{0.0, 0.0, 1.0};
    V3 right = cross3(zUp, backward);
    const double rightLength = std::sqrt(dot3(right, right));
    if (rightLength < 1e-8) {
        const V3 fallbackAxes[3]{{1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 0.0, 1.0}};
        int axis = 0;
        if (std::abs(backward[1]) < std::abs(backward[axis])) axis = 1;
        if (std::abs(backward[2]) < std::abs(backward[axis])) axis = 2;
        right = cross3(fallbackAxes[axis], backward);
    }
    right = normalize3(right, "camera right axis");
    const V3 up = normalize3(cross3(backward, right), "camera up axis");
    const V3 basisColumns[3]{right, up, backward};
    for (int row = 0; row < 3; ++row)
        for (int column = 0; column < 3; ++column)
            frame.rotation[row * 3 + column] = basisColumns[column][row];

    frame.view = {right[0], right[1], right[2], -dot3(right, frame.position),
                  up[0], up[1], up[2], -dot3(up, frame.position),
                  backward[0], backward[1], backward[2], -dot3(backward, frame.position),
                  0.0, 0.0, 0.0, 1.0};
    const double focal = a.projection[5];
    if (!(focal > 0) || !std::isfinite(focal))
        throw std::runtime_error("cannot build smooth camera: fixture projection has invalid FOV scale");
    const double aspect = static_cast<double>(width) / static_cast<double>(height);
    frame.projection = {};
    frame.projection[0] = focal / aspect;
    frame.projection[5] = focal;
    frame.projection[10] = (frame.farPlane + frame.nearPlane) / (frame.nearPlane - frame.farPlane);
    frame.projection[11] = (2.0 * frame.farPlane * frame.nearPlane) /
                           (frame.nearPlane - frame.farPlane);
    frame.projection[14] = -1.0;
    return frame;
}
struct Summary { double mean = 0, p50 = 0, p95 = 0, p99 = 0; };
Summary summarize(std::vector<double> values) {
    if (values.empty()) return {};
    const double sum = std::accumulate(values.begin(), values.end(), 0.0);
    std::sort(values.begin(), values.end());
    auto percentile = [&](double q) {
        const double pos = q * static_cast<double>(values.size() - 1);
        const auto lo = static_cast<std::size_t>(std::floor(pos));
        const auto hi = static_cast<std::size_t>(std::ceil(pos));
        const double mix = pos - static_cast<double>(lo);
        return values[lo] * (1.0 - mix) + values[hi] * mix;
    };
    return {sum / values.size(), percentile(.50), percentile(.95), percentile(.99)};
}
void writeSummary(std::ostream& out, const Summary& summary) {
    out << "{\"mean\":" << summary.mean << ",\"p50\":" << summary.p50
        << ",\"p95\":" << summary.p95 << ",\"p99\":" << summary.p99 << '}';
}
void writeBenchmark(const std::filesystem::path& path, const Options& options,
                    const std::string& rendererName, int width, int height,
                    const std::vector<Sample>& samples, double measuredSeconds,
                    std::size_t recordedPairs) {
    std::filesystem::create_directories(path.parent_path());
    std::vector<double> work, interval, swapCall;
    std::uint64_t colorDraws = 0, shadowDraws = 0, colorTriangles = 0, shadowTriangles = 0;
    for (const auto& sample : samples) {
        work.push_back(sample.workMs); interval.push_back(sample.swapIntervalMs); swapCall.push_back(sample.swapCallMs);
        colorDraws += sample.stats.colorDraws; shadowDraws += sample.stats.shadowDraws;
        colorTriangles += sample.stats.colorTriangles; shadowTriangles += sample.stats.shadowTriangles;
    }
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("cannot create benchmark output: " + path.string());
    out << std::setprecision(9)
        << "{\n  \"route\": \"" << options.route << "\",\n  \"renderer\": \"" << rendererName
        << "\",\n  \"width\": " << width << ",\n  \"height\": " << height
        << ",\n  \"vsync\": " << (options.vsync ? "true" : "false")
        << ",\n  \"depth_precision\": \"" << (options.legacyDepth ? "legacy camera near" : "conservative visible bounds near") << "\""
        << ",\n  \"shadow_mode\": \"" << (options.legacyShadows ? "legacy single map" : "stable near 4096 plus original far map, blend 12-16m") << "\""
        << ",\n  \"requested_seconds\": " << options.seconds
        << ",\n  \"measured_wall_seconds\": " << measuredSeconds
        << ",\n  \"camera_sampling\": \""
        << (options.smoothCamera ? "elapsed-time smooth fixture interpolation, 8-second forward leg and ping-pong return"
            : options.freezeCamera ? "fixed first measured fixture camera"
            : options.seconds > 0 ? "discrete fixture frames, wrapping at route end" : "fixture frames")
        << "\",\n  \"frames\": " << samples.size() << ",\n  \"warmup\": " << options.warmup
        << ",\n  \"msaa_samples\": " << options.samples
        << ",\n  \"recording\": " << (!options.recordDir.empty() ? "true" : "false")
        << ",\n  \"recorded_pairs\": " << recordedPairs
        << ",\n  \"record_every\": " << options.recordEvery
        << ",\n  \"record_count_limit\": " << options.recordCount
        << ",\n  \"recording_note\": \""
        << (!options.recordDir.empty()
            ? "diagnostic readback runs after SwapBuffers and delays later frames; do not use this run's frame intervals for performance acceptance"
            : "diagnostic readback disabled")
        << "\",\n  \"timing_scope\": \"render submission plus glFinish; swap interval measured separately; no editor UI\",\n"
        << "  \"render_work_ms\": "; writeSummary(out, summarize(work));
    out << ",\n  \"swap_interval_ms\": "; writeSummary(out, summarize(interval));
    out << ",\n  \"swap_call_ms\": "; writeSummary(out, summarize(swapCall));
    out << ",\n  \"totals\": {\"color_draws\":" << colorDraws << ",\"shadow_draws\":" << shadowDraws
        << ",\"color_triangles\":" << colorTriangles << ",\"shadow_triangles\":" << shadowTriangles << "},\n"
        << "  \"samples\": [\n";
    for (std::size_t i = 0; i < samples.size(); ++i) {
        const auto& s = samples[i];
        out << "    {\"frame_index\":" << s.frameIndex << ",\"t\":" << s.t
            << ",\"render_work_ms\":" << s.workMs << ",\"swap_interval_ms\":" << s.swapIntervalMs
            << ",\"swap_call_ms\":" << s.swapCallMs << ",\"color_draws\":" << s.stats.colorDraws
            << ",\"shadow_draws\":" << s.stats.shadowDraws << ",\"color_triangles\":" << s.stats.colorTriangles
            << ",\"input_near\":" << s.stats.inputNear << ",\"color_near\":" << s.stats.colorNear
            << ",\"shadow_triangles\":" << s.stats.shadowTriangles << "}"
            << (i + 1 == samples.size() ? "\n" : ",\n");
    }
    out << "  ]\n}\n";
    if (!out) throw std::runtime_error("failed writing benchmark output: " + path.string());
}
void validateOnly(const Options& options) {
    const auto bundle = spqr::loadBundle(options.bundle);
    const auto frames = spqr::loadFrames(options.bundle / "frames.bin");
    for (const char* shader : {"material.vert", "material.frag", "sky.vert", "sky.frag", "shadow.vert", "shadow.frag"})
        if (spqr::readTextFile(options.bundle / "shaders" / shader).empty())
            throw std::runtime_error(std::string("empty required shader: ") + shader);
    if (!options.legacyShadows && spqr::readTextFile(options.bundle / "shaders/shadow_cascade.glsl").empty())
        throw std::runtime_error("empty native shadow cascade shader");
    const auto routeFrames = chooseRoute(frames, options.route);
    std::cout << "{\"valid\":true,\"textures\":" << bundle.textures.size()
              << ",\"materials\":" << bundle.materials.size() << ",\"meshes\":" << bundle.meshes.size()
              << ",\"entities\":" << bundle.entities.size() << ",\"opaque_order\":" << bundle.opaqueOrder.size()
              << ",\"frames\":" << frames.size() << ",\"route\":\"" << options.route
              << "\",\"route_frames\":" << routeFrames.size() << ",\"shadow_resolution\":"
              << bundle.shadowResolution << "}\n";
}

} // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parseOptions(argc, argv);
        if (options.help) { printHelp(); return 0; }
        if (options.validateOnly) { validateOnly(options); return 0; }

        spqr::Bundle bundle = spqr::loadBundle(options.bundle);
        const auto allFrames = spqr::loadFrames(options.bundle / "frames.bin");
        const auto routeFrames = chooseRoute(allFrames, options.route);
        const std::uint64_t required = static_cast<std::uint64_t>(options.warmup) +
            (options.seconds > 0 ? 1u : options.frames);
        if (required > routeFrames.size())
            throw std::runtime_error("route " + options.route + " has " + std::to_string(routeFrames.size()) +
                " frames, but --warmup + --frames requires " + std::to_string(required));
        const std::size_t availableMeasured = routeFrames.size() - options.warmup;
        if (options.smoothCamera && availableMeasured < 2)
            throw std::runtime_error("--smooth-camera needs at least two measured route fixtures after warmup");
        const std::size_t captureFirst = options.warmup;
        const std::size_t captureMiddle = static_cast<std::size_t>(options.warmup) + 60;
        if (options.capture && captureMiddle >= routeFrames.size())
            throw std::runtime_error("--capture needs fixed fixture frames at warmup and warmup+60");

        constexpr int width = 1081, height = 662;
        spqr::Win32Window window(width, height, options.hidden, options.vsync);
        spqr::GLApi gl;
        std::string glLoadError;
        if (!gl.load(glLoadError)) throw std::runtime_error(glLoadError);
        spqr::Renderer renderer(gl, bundle, options.bundle, width, height,
                                !options.legacyDepth, static_cast<int>(options.samples), !options.legacyShadows);

        bool firstFramePresented = false;
        auto showAfterFirstFrame = [&] {
            if (!options.hidden && !firstFramePresented) {
                window.show();
                firstFramePresented = true;
            }
        };
        for (std::uint32_t i = 0; i < options.warmup; ++i) {
            if (!window.pumpEvents()) throw std::runtime_error("window closed during warmup");
            renderer.render(routeFrames[i]);
            if (!window.swapBuffers()) throw std::runtime_error("SwapBuffers failed during warmup");
            showAfterFirstFrame();
        }
        auto lastSwap = Clock::now();
        std::vector<Sample> samples;
        samples.reserve(options.seconds > 0 ? 1024 : options.frames);
        if (!options.recordDir.empty()) std::filesystem::create_directories(options.recordDir);
        const auto measurementStart = Clock::now();
        std::uint64_t i = 0;
        std::size_t recordedPairs = 0;
        while (options.seconds > 0
                ? std::chrono::duration<double>(Clock::now() - measurementStart).count() < options.seconds
                : i < options.frames) {
            if (!window.pumpEvents()) throw std::runtime_error("window closed during benchmark");
            const double elapsedSeconds = std::chrono::duration<double>(Clock::now() - measurementStart).count();
            std::size_t frameIndex = static_cast<std::size_t>(options.warmup) +
                (options.seconds > 0 ? (i % availableMeasured) : i);
            spqr::CameraFrame smoothFrame;
            const spqr::CameraFrame* activeCamera = nullptr;
            if (options.freezeCamera) {
                frameIndex = options.warmup;
                activeCamera = &routeFrames[frameIndex];
            } else if (options.smoothCamera) {
                smoothFrame = smoothCameraAt(routeFrames, options.warmup, elapsedSeconds,
                                             width, height, &frameIndex);
                activeCamera = &smoothFrame;
            } else {
                activeCamera = &routeFrames[frameIndex];
            }
            const auto workStart = Clock::now();
            const spqr::FrameStats stats = renderer.render(*activeCamera);
            const auto workEnd = Clock::now();
            const auto swapStart = Clock::now();
            if (!window.swapBuffers()) throw std::runtime_error("SwapBuffers failed during benchmark");
            const auto swapEnd = Clock::now();
            showAfterFirstFrame();
            Sample sample;
            sample.frameIndex = frameIndex;
            sample.t = activeCamera->t;
            sample.workMs = std::chrono::duration<double, std::milli>(workEnd - workStart).count();
            sample.swapIntervalMs = std::chrono::duration<double, std::milli>(swapEnd - lastSwap).count();
            sample.swapCallMs = std::chrono::duration<double, std::milli>(swapEnd - swapStart).count();
            sample.stats = stats;
            samples.push_back(sample);
            lastSwap = swapEnd;
            if (!options.recordDir.empty() && recordedPairs < options.recordCount &&
                (i + 1) % options.recordEvery == 0) {
                std::ostringstream stem;
                stem << "frame-" << std::setw(6) << std::setfill('0') << recordedPairs;
                renderer.captureColor(options.recordDir / (stem.str() + "-fbo.ppm"), false);
                renderer.captureColor(options.recordDir / (stem.str() + "-front.ppm"), true);
                ++recordedPairs;
            }
            ++i;
        }
        const double measuredSeconds = std::chrono::duration<double>(Clock::now() - measurementStart).count();

        if (options.capture) {
            const auto captureDir = options.output / "captures";
            auto captureAt = [&](std::size_t index, const std::string& suffix) {
                const auto stats = renderer.render(routeFrames[index]);
                renderer.capture(routeFrames[index], captureDir / (options.route + "-" + suffix), index, stats);
                if (!window.swapBuffers()) throw std::runtime_error("SwapBuffers failed after capture");
            };
            captureAt(captureFirst, "0");
            if (captureMiddle != captureFirst) captureAt(captureMiddle, "mid");
        }
        const std::string rendererName = renderer.rendererName();
        const auto report = options.output / ("benchmark-" + options.route + ".json");
        writeBenchmark(report, options, rendererName, width, height, samples, measuredSeconds, recordedPairs);
        std::cout << "GL_RENDERER: " << rendererName << "\n"
                  << "MSAA samples: " << options.samples << "\n"
                  << "Vsync: " << (options.vsync ? "enabled" : "disabled") << "\n"
                  << "Render work ms: "; writeSummary(std::cout, summarize([&] {
                      std::vector<double> v; for (const auto& s : samples) v.push_back(s.workMs); return v;
                  }()));
        std::cout << "\nSwap interval ms: "; writeSummary(std::cout, summarize([&] {
            std::vector<double> v; for (const auto& s : samples) v.push_back(s.swapIntervalMs); return v;
        }()));
        std::cout << "\nBenchmark JSON: " << report.string() << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "SPQR native error: " << error.what() << "\n";
        return 1;
    }
}
