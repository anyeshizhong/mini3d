#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

__declspec(dllexport) uint32_t spqr_photo_abi_version(void);
__declspec(dllexport) void* spqr_photo_create(const wchar_t* bundleDir,
                                               int width, int height, int samples);
// Live v2 bundles reference textures owned by the caller in the same GL context.
// Their owners must remain alive until this renderer is destroyed. No readback,
// texture upload, mutation of sampling parameters or ownership transfer occurs.
__declspec(dllexport) void* spqr_photo_create_shared(const wchar_t* bundleDir,
                                                   int width, int height, int samples);
// Create a live shared-texture renderer without compiling or uploading its GL
// resources. Call prepare_step on the same thread/context until ready is nonzero.
__declspec(dllexport) void* spqr_photo_begin_shared(const wchar_t* bundleDir,
                                                    int width, int height, int samples);
// Returns success; writes 1 to ready only after the final initialization stage.
__declspec(dllexport) int spqr_photo_prepare_step(void* instance, int* ready);
// Diagnostic count of shader programs compiled by this renderer handle.
// Shared programs reused from another live renderer are not counted again.
__declspec(dllexport) int spqr_photo_program_compile_count(void* instance,
                                                            uint32_t* count);
__declspec(dllexport) int spqr_photo_resize(void* instance,
                                             int width, int height, int samples);
// Batch update of existing mesh instances in bundle order. Matrices are row-major.
// The whole batch is validated before mutation; normals match Python pseudoinverse
// semantics, including singular scale. Only mirrored winding is changed in flags.
__declspec(dllexport) int spqr_photo_transforms(void* instance, const uint32_t* indices,
    const double* worlds16, const float* normals9, const uint32_t* mirrored, size_t count);
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
