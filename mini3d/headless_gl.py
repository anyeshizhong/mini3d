"""Optional EGL context for offline captures on Linux, without a display server.

Set PYOPENGL_PLATFORM=egl before importing any OpenGL module. The normal editor
continues to use Pygame's desktop context. No Blender or alternate renderer.
"""
import ctypes
from contextlib import contextmanager


@contextmanager
def egl_context():
    from OpenGL import EGL
    from OpenGL.EGL.EXT.platform_base import eglGetPlatformDisplayEXT
    display = eglGetPlatformDisplayEXT(0x31DD, EGL.EGL_DEFAULT_DISPLAY, None)
    surface = context = None
    initialized = False
    try:
        major, minor = EGL.EGLint(), EGL.EGLint()
        EGL.eglInitialize(display, major, minor); initialized = True
        EGL.eglBindAPI(EGL.EGL_OPENGL_API)
        config, count = EGL.EGLConfig(), EGL.EGLint()
        attributes = (EGL.EGLint*11)(EGL.EGL_SURFACE_TYPE,EGL.EGL_PBUFFER_BIT,
            EGL.EGL_RENDERABLE_TYPE,EGL.EGL_OPENGL_BIT,EGL.EGL_RED_SIZE,8,
            EGL.EGL_GREEN_SIZE,8,EGL.EGL_BLUE_SIZE,8,EGL.EGL_NONE)
        EGL.eglChooseConfig(display,attributes,ctypes.byref(config),1,count)
        if count.value != 1: raise RuntimeError('EGL OpenGL pbuffer config unavailable')
        surface = EGL.eglCreatePbufferSurface(display,config,(EGL.EGLint*5)(
            EGL.EGL_WIDTH,16,EGL.EGL_HEIGHT,16,EGL.EGL_NONE))
        context = EGL.eglCreateContext(display,config,EGL.EGL_NO_CONTEXT,(EGL.EGLint*7)(
            0x3098,3,0x30FB,3,0x30FD,1,EGL.EGL_NONE))
        EGL.eglMakeCurrent(display,surface,surface,context)
        yield
    finally:
        if initialized:
            EGL.eglMakeCurrent(display,EGL.EGL_NO_SURFACE,EGL.EGL_NO_SURFACE,EGL.EGL_NO_CONTEXT)
            if context: EGL.eglDestroyContext(display,context)
            if surface: EGL.eglDestroySurface(display,surface)
            EGL.eglTerminate(display)
