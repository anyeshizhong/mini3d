cmake_minimum_required(VERSION 3.20)
project(spqr_native LANGUAGES CXX)

if(NOT WIN32)
  message(FATAL_ERROR "The SPQR native viewer currently requires Win32/WGL.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(SPQR_COMPILER_BIN_DIR "${CMAKE_CXX_COMPILER}" DIRECTORY)
get_filename_component(SPQR_COMPILER_ROOT "${SPQR_COMPILER_BIN_DIR}" DIRECTORY)
find_path(SPQR_GL_INCLUDE_DIR NAMES GL/glcorearb.h
  HINTS
    "${SPQR_COMPILER_ROOT}/include"
    "${SPQR_COMPILER_ROOT}/x86_64-w64-mingw32/include"
    "${SPQR_COMPILER_ROOT}/i686-w64-mingw32/include"
    "$ENV{MINGW_PREFIX}/include"
  REQUIRED)
if(NOT EXISTS "${SPQR_GL_INCLUDE_DIR}/GL/glext.h")
  message(FATAL_ERROR "MinGW OpenGL headers glcorearb.h and glext.h are required in one include directory.")
endif()

set(SPQR_CORE_SOURCES
  src/bundle.cpp
  src/gl_api.cpp
  src/renderer.cpp
  src/shadow_fit.cpp
)

add_executable(spqr-native
  src/main.cpp
  src/platform_win32.cpp
  ${SPQR_CORE_SOURCES}
)
target_include_directories(spqr-native PRIVATE src "${SPQR_GL_INCLUDE_DIR}")
target_link_libraries(spqr-native PRIVATE opengl32 gdi32 user32)

# Shared-context photo renderer. It uses the caller's current WGL context and
# has no window, event loop, Python dependency, or default-framebuffer present.
add_library(spqr_photo SHARED
  src/native_photo.cpp
  ${SPQR_CORE_SOURCES}
)
target_include_directories(spqr_photo PRIVATE src "${SPQR_GL_INCLUDE_DIR}")
target_link_libraries(spqr_photo PRIVATE opengl32)
set_target_properties(spqr_photo PROPERTIES PREFIX "" OUTPUT_NAME "spqr_photo")

# Kept separate for the Python numeric-regression harness. The executable also
# compiles the same implementation directly, so it has no runtime DLL dependency.
add_library(spqr_shadow SHARED src/shadow_fit.cpp)
target_include_directories(spqr_shadow PRIVATE src)
if(MINGW)
  target_link_options(spqr_shadow PRIVATE -static-libgcc -static-libstdc++)
endif()

set_target_properties(spqr-native spqr_shadow spqr_photo PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
  ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

# Diagnostic target is opt-in and never linked into the photo DLL.
add_executable(spqr-shadow-audit EXCLUDE_FROM_ALL
  tests/shadow_gpu_audit.cpp src/platform_win32.cpp ${SPQR_CORE_SOURCES})
target_include_directories(spqr-shadow-audit PRIVATE src "${SPQR_GL_INCLUDE_DIR}")
target_link_libraries(spqr-shadow-audit PRIVATE opengl32 gdi32 user32)
set_target_properties(spqr-shadow-audit PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
if(MINGW)
  target_link_options(spqr-shadow-audit PRIVATE -static-libgcc -static-libstdc++)
endif()

if(MSVC)
  target_compile_options(spqr-native PRIVATE /W4 /permissive-)
  target_compile_options(spqr_shadow PRIVATE /W4 /permissive-)
  target_compile_options(spqr_photo PRIVATE /W4 /permissive-)
else()
  target_compile_options(spqr-native PRIVATE -Wall -Wextra -Wpedantic)
  target_compile_options(spqr_shadow PRIVATE -Wall -Wextra -Wpedantic)
  target_compile_options(spqr_photo PRIVATE -Wall -Wextra -Wpedantic)
  target_link_options(spqr_photo PRIVATE -static-libgcc -static-libstdc++)
    target_link_options(spqr-native PRIVATE -static-libgcc -static-libstdc++)
endif()
