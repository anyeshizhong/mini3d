#include "gl_api.hpp"

#include <cstdint>
#include <bit>

namespace spqr {
namespace {
PROC resolveGL(const char* name) {
    PROC proc = wglGetProcAddress(name);
    const auto value = reinterpret_cast<std::uintptr_t>(proc);
    if (!proc || value == 1 || value == 2 || value == 3 || value == static_cast<std::uintptr_t>(-1)) {
        static HMODULE module = GetModuleHandleW(L"opengl32.dll");
        proc = module ? GetProcAddress(module, name) : nullptr;
    }
    return proc;
}
}

bool GLApi::load(std::string& error) {
#define SPQR_LOAD_GL(name) do { \
    name = std::bit_cast<decltype(name)>(resolveGL("gl" #name)); \
    if (!name) { error = "OpenGL entry point unavailable: gl" #name; return false; } \
} while (0);
    SPQR_GL_FUNCTIONS(SPQR_LOAD_GL)
#undef SPQR_LOAD_GL
    return true;
}

} // namespace spqr
