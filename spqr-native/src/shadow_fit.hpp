#pragma once
#include <array>
#include <vector>
#include <cstdint>
namespace spqr {
// Row-major double matrices. Ground footprint is conservatively projected from all
// ordinary boxes. Precise receiver/caster clipping follows existing Python.
struct ShadowBox { std::array<double,6> bounds{}; std::array<double,16> world{}; bool ground=false; };
// On false, emptyReceivers distinguishes an ordinary empty camera region from
// invalid input. Existing non-empty fits and the exported batch ABI are unchanged.
bool fit_shadow(const std::vector<ShadowBox>& boxes, const double* direction,
                const double* view, const double* projection, unsigned resolution,
                double* output, bool* emptyReceivers = nullptr);
// Stable near-cascade fit: fixed-radius split volume, texel-snapped XY, and
// conservative depth bounds over every non-ground caster.
bool fit_stable_shadow(const std::vector<ShadowBox>& boxes, const double* direction,
                       const double* view, const double* projection, unsigned resolution,
                       double nearDistance, double farDistance, double* output);
// Tighten the camera near plane without clipping any input OBB intersecting
// the original view frustum. On failure, result remains originalNear.
bool conservative_camera_near(const std::vector<ShadowBox>& boxes,
                              const double* view, const double* projection,
                              double originalNear, double* result);
}
// Batch ABI for numeric regression, never used per-object from Python.
extern "C" __declspec(dllexport) int spqr_fit_shadow(const double* bounds, const double* worlds,
 const uint32_t* flags, uint32_t count, const double* direction, const double* view,
 const double* projection, uint32_t resolution, double* output);
extern "C" __declspec(dllexport) int spqr_fit_stable_shadow(const double* bounds, const double* worlds,
 const uint32_t* flags, uint32_t count, const double* direction, const double* view,
 const double* projection, uint32_t resolution, double nearDistance, double farDistance,
 double* output);
extern "C" __declspec(dllexport) int spqr_camera_near(const double* bounds, const double* worlds,
 const uint32_t* flags, uint32_t count, const double* view, const double* projection,
 double originalNear, double* result);
