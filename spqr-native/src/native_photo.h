#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

__declspec(dllexport) uint32_t spqr_photo_abi_version(void);
__declspec(dllexport) void* spqr_photo_create(const wchar_t* bundleDir,
                                               int width, int height, int samples);
__declspec(dllexport) int spqr_photo_resize(void* instance,
                                             int width, int height, int samples);
// `bytes` contains exactly two serialized UniformBlocks: material globals,
// followed by sky globals. Each block uses the existing SPQR UniformBlock wire
// format described in FORMAT.md.
__declspec(dllexport) int spqr_photo_globals(void* instance,
                                              const void* bytes, size_t length,
                                              const double* lightDirection,
                                              uint32_t farShadowResolution,
                                              float shadowBias, int shadowEnabled,
                                              double groundZ);
// camera46 = position[3], rotation row-major[9], view row-major[16],
// projection row-major[16], near, far. targetSingleSampleFbo must be a
// complete single-sample RGBA8 + DEPTH24_STENCIL8 framebuffer of matching size.
// stats8 = effective near, far, color draws, shadow draws, color triangles,
// shadow triangles, 0, 0.
__declspec(dllexport) int spqr_photo_render(void* instance,
                                            const double* camera46,
                                            uint32_t targetSingleSampleFbo,
                                            double* stats8);
__declspec(dllexport) int spqr_photo_destroy(void* instance);
__declspec(dllexport) const char* spqr_photo_last_error(void);

#ifdef __cplusplus
}
#endif
