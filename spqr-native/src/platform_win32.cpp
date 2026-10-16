#include "platform_win32.hpp"

#include <stdexcept>
#include <string>
#include <bit>

namespace spqr {
namespace {
constexpr wchar_t kWindowClass[] = L"SPQRNativeViewerWindow";
using CreateContextAttribs = HGLRC(WINAPI*)(HDC, HGLRC, const int*);
using SwapInterval = BOOL(WINAPI*)(int);
constexpr int WGL_CONTEXT_MAJOR_VERSION_ARB = 0x2091;
constexpr int WGL_CONTEXT_MINOR_VERSION_ARB = 0x2092;
constexpr int WGL_CONTEXT_PROFILE_MASK_ARB = 0x9126;
constexpr int WGL_CONTEXT_CORE_PROFILE_BIT_ARB = 0x00000001;

LRESULT CALLBACK windowProcedure(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam) {
    if (message == WM_ERASEBKGND) return 1;
    if (message == WM_PAINT) {
        ValidateRect(hwnd, nullptr);
        return 0;
    }
    if (message == WM_CLOSE) {
        DestroyWindow(hwnd);
        return 0;
    }
    if (message == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}

void require(bool ok, const char* action) {
    if (!ok) throw std::runtime_error(std::string(action) + " failed (Win32 error " +
                                      std::to_string(GetLastError()) + ")");
}

} // namespace

Win32Window::Win32Window(int clientWidth, int clientHeight, bool hidden, bool vsync) {
    HGLRC bootstrap = nullptr;
    HGLRC core = nullptr;
    try {
    if (clientWidth <= 0 || clientHeight <= 0) throw std::runtime_error("invalid window dimensions");
    HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.style = CS_OWNDC;
    wc.lpfnWndProc = windowProcedure;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
    wc.lpszClassName = kWindowClass;
    if (!RegisterClassExW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
        require(false, "RegisterClassExW");

    constexpr DWORD windowStyle = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX |
                                  WS_CLIPSIBLINGS | WS_CLIPCHILDREN;
    RECT rect{0, 0, clientWidth, clientHeight};
    require(AdjustWindowRect(&rect, windowStyle, FALSE) != 0, "AdjustWindowRect");
    hwnd_ = CreateWindowExW(0, kWindowClass, L"SPQR Native Viewer", windowStyle,
                            CW_USEDEFAULT, CW_USEDEFAULT, rect.right - rect.left,
                            rect.bottom - rect.top, nullptr, nullptr, instance, nullptr);
    require(hwnd_ != nullptr, "CreateWindowExW");
    dc_ = GetDC(hwnd_);
    require(dc_ != nullptr, "GetDC");

    PIXELFORMATDESCRIPTOR pfd{};
    pfd.nSize = sizeof(pfd);
    pfd.nVersion = 1;
    pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    pfd.iPixelType = PFD_TYPE_RGBA;
    pfd.cColorBits = 32;
    pfd.cAlphaBits = 8;
    pfd.cDepthBits = 24;
    pfd.cStencilBits = 8;
    pfd.iLayerType = PFD_MAIN_PLANE;
    const int format = ChoosePixelFormat(dc_, &pfd);
    require(format != 0, "ChoosePixelFormat");
    require(SetPixelFormat(dc_, format, &pfd) != 0, "SetPixelFormat");

    bootstrap = wglCreateContext(dc_);
    require(bootstrap != nullptr, "wglCreateContext (bootstrap)");
    require(wglMakeCurrent(dc_, bootstrap) != 0, "wglMakeCurrent (bootstrap)");
    auto createCore = std::bit_cast<CreateContextAttribs>(wglGetProcAddress("wglCreateContextAttribsARB"));
    if (!createCore)
        throw std::runtime_error("driver does not expose WGL_ARB_create_context");
    const int attributes[]{WGL_CONTEXT_MAJOR_VERSION_ARB, 3,
                           WGL_CONTEXT_MINOR_VERSION_ARB, 3,
                           WGL_CONTEXT_PROFILE_MASK_ARB, WGL_CONTEXT_CORE_PROFILE_BIT_ARB,
                           0};
    core = createCore(dc_, nullptr, attributes);
    if (!core)
        throw std::runtime_error("driver could not create an OpenGL 3.3 core context");
    context_ = core;
    require(wglMakeCurrent(dc_, core) != 0, "wglMakeCurrent (OpenGL 3.3)");
    wglDeleteContext(bootstrap);
    bootstrap = nullptr;

    auto swapInterval = std::bit_cast<SwapInterval>(wglGetProcAddress("wglSwapIntervalEXT"));
    const int requestedInterval = vsync ? 1 : 0;
    if (!swapInterval || !swapInterval(requestedInterval))
        throw std::runtime_error(std::string("could not set WGL swap interval to ") +
                                 std::to_string(requestedInterval));
    (void)hidden; // The window stays hidden until show() after the first rendered frame.
    } catch (...) {
        if (wglGetCurrentContext()) wglMakeCurrent(nullptr, nullptr);
        if (core) wglDeleteContext(core);
        if (bootstrap) wglDeleteContext(bootstrap);
        context_ = nullptr;
        if (dc_ && hwnd_) ReleaseDC(hwnd_, dc_);
        dc_ = nullptr;
        if (hwnd_ && IsWindow(hwnd_)) DestroyWindow(hwnd_);
        hwnd_ = nullptr;
        throw;
    }
}

Win32Window::~Win32Window() {
    if (wglGetCurrentContext() == context_) wglMakeCurrent(nullptr, nullptr);
    if (context_) wglDeleteContext(context_);
    if (dc_ && hwnd_) ReleaseDC(hwnd_, dc_);
    if (hwnd_ && IsWindow(hwnd_)) DestroyWindow(hwnd_);
}

bool Win32Window::pumpEvents() {
    MSG msg{};
    while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
        if (msg.message == WM_QUIT) return false;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return IsWindow(hwnd_) != 0;
}

bool Win32Window::swapBuffers() { return SwapBuffers(dc_) != 0; }

void Win32Window::show() {
    if (!hwnd_ || !IsWindow(hwnd_)) return;
    ShowWindow(hwnd_, SW_SHOW);
    UpdateWindow(hwnd_);
}

} // namespace spqr
