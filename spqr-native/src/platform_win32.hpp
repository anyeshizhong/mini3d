#pragma once

#include <windows.h>
#include <string>

namespace spqr {

class Win32Window {
public:
    Win32Window(int clientWidth, int clientHeight, bool hidden, bool vsync = false);
    ~Win32Window();
    Win32Window(const Win32Window&) = delete;
    Win32Window& operator=(const Win32Window&) = delete;
    bool pumpEvents();
    bool swapBuffers();
    void show();
    HWND handle() const { return hwnd_; }
private:
    HWND hwnd_ = nullptr;
    HDC dc_ = nullptr;
    HGLRC context_ = nullptr;
};

} // namespace spqr
