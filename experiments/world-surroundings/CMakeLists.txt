cmake_minimum_required(VERSION 3.20)
project(terrain_lab LANGUAGES CXX)

if(NOT WIN32)
  message(FATAL_ERROR "terrain_lab uses the SPQR Win32/WGL renderer and requires Windows.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(TERRAIN_LAB_COMPILER_BIN_DIR "${CMAKE_CXX_COMPILER}" DIRECTORY)
get_filename_component(TERRAIN_LAB_COMPILER_ROOT "${TERRAIN_LAB_COMPILER_BIN_DIR}" DIRECTORY)
find_path(TERRAIN_LAB_GL_INCLUDE_DIR NAMES GL/glcorearb.h
  HINTS
    "${TERRAIN_LAB_COMPILER_ROOT}/include"
    "${TERRAIN_LAB_COMPILER_ROOT}/x86_64-w64-mingw32/include"
    "${TERRAIN_LAB_COMPILER_ROOT}/i686-w64-mingw32/include"
    "$ENV{MINGW_PREFIX}/include"
  REQUIRED)
if(NOT EXISTS "${TERRAIN_LAB_GL_INCLUDE_DIR}/GL/glext.h")
  message(FATAL_ERROR "MinGW OpenGL headers glcorearb.h and glext.h are required in one include directory.")
endif()

set(SPQR_NATIVE_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../spqr-native/src")
add_library(terrain_lab SHARED
  terrain_bridge.cpp
  "${SPQR_NATIVE_SOURCE_DIR}/bundle.cpp"
  "${SPQR_NATIVE_SOURCE_DIR}/gl_api.cpp"
  "${SPQR_NATIVE_SOURCE_DIR}/renderer.cpp"
  "${SPQR_NATIVE_SOURCE_DIR}/shadow_fit.cpp"
)
target_include_directories(terrain_lab PRIVATE
  "${SPQR_NATIVE_SOURCE_DIR}"
  "${TERRAIN_LAB_GL_INCLUDE_DIR}"
)
target_compile_definitions(terrain_lab PRIVATE SPQR_TERRAIN_LAB=1)
target_link_libraries(terrain_lab PRIVATE opengl32)
set_target_properties(terrain_lab PROPERTIES
  PREFIX ""
  OUTPUT_NAME "terrain_lab"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
  ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

if(MINGW)
  target_link_options(terrain_lab PRIVATE -static-libgcc -static-libstdc++)
endif()

if(MSVC)
  target_compile_options(terrain_lab PRIVATE /W4 /permissive-)
else()
  target_compile_options(terrain_lab PRIVATE -Wall -Wextra -Wpedantic)
endif()
