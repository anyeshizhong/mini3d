#pragma once
#include <array>
#include <vector>
#include <cstdint>
namespace spqr {
// Row-major double matrices. Ground footprint is conservatively projected from all
// ordinary boxes. Precise receiver/caster clipping follows existing Python.
struct ShadowBox { std::array<double,6> bounds{}; std::array<double,16> world{}; bool ground=false; };
// On false, emptyReceivers distinguishes ordinary empty receiver regions
// from invalid input. Previous is optional temporal state; stabilize=false
// replays the original tight far fit for the opt-in audit.
bool fit_shadow(const std::vector<ShadowBox>& boxes, const double* direction,
                const double* view, const double* projection, unsigned resolution,
                double* output, const double* previous = nullptr, bool* emptyReceivers = nullptr,
                bool stabilize = true);
// Stabilize local receiver XY without replacing it with scene-wide bounds.
// Previous may be null; matrix is updated only on success.
bool stabilize_shadow_matrix(double* matrix, const double* previous, unsigned resolution);
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
extern "C" __declspec(dllexport) int spqr_stabilize_shadow(double* matrix,
 const double* previous, uint32_t resolution);
extern "C" __declspec(dllexport) int spqr_fit_shadow_temporal(const double* bounds, const double* worlds,
 const uint32_t* flags, uint32_t count, const double* direction, const double* view,
 const double* projection, uint32_t resolution, const double* previous, double* output);
