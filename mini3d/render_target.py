"""Resizable RGBA8/depth24-stencil8 target with optional resolved Shot MSAA."""
from numbers import Integral
from OpenGL.GL import *


class RenderTarget:
    def __init__(self, samples=1):
        self.width = self.height = 0
        self.samples = 1
        self.multisample_framebuffer = self.multisample_color = self.multisample_depth = 0
        self.framebuffer = glGenFramebuffers(1)
        self.texture = glGenTextures(1)
        self.depth = glGenRenderbuffers(1)
        try:
            self.resize(1, 1, samples)
        except Exception:
            self.close()
            raise

    @staticmethod
    def validate_samples(samples):
        if isinstance(samples, bool) or not isinstance(samples, Integral) or samples not in (1, 4):
            raise ValueError('Shot samples must be 1 (off) or 4 (MSAA)')
        return int(samples)

    def resize(self, width, height, samples=None):
        if not self.framebuffer:
            raise RuntimeError('RenderTarget is closed')
        samples = self.validate_samples(self.samples if samples is None else samples)
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height, samples) == (self.width, self.height, self.samples):
            return
        if samples > 1 and samples > int(glGetIntegerv(GL_MAX_SAMPLES)):
            raise RuntimeError('4x MSAA is unsupported by this OpenGL context')
        read = int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING))
        draw = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
        texture = int(glGetIntegerv(GL_TEXTURE_BINDING_2D))
        renderbuffer = int(glGetIntegerv(GL_RENDERBUFFER_BINDING))
        try:
            # Public texture/FBO stay single-sample for ImGui, picking and readback.
            glBindTexture(GL_TEXTURE_2D, self.texture)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, width, height)
            glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.texture, 0)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, self.depth)
            self._check_complete()
            if samples > 1:
                if not self.multisample_framebuffer:
                    self.multisample_framebuffer = glGenFramebuffers(1)
                    self.multisample_color = glGenRenderbuffers(1)
                    self.multisample_depth = glGenRenderbuffers(1)
                glBindFramebuffer(GL_FRAMEBUFFER, self.multisample_framebuffer)
                for buffer, fmt, attachment in (
                        (self.multisample_color, GL_RGBA8, GL_COLOR_ATTACHMENT0),
                        (self.multisample_depth, GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL_ATTACHMENT)):
                    glBindRenderbuffer(GL_RENDERBUFFER, buffer)
                    glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples, fmt, width, height)
                    actual = int(glGetRenderbufferParameteriv(GL_RENDERBUFFER, GL_RENDERBUFFER_SAMPLES))
                    if actual != samples:
                        raise RuntimeError('Requested {} samples, driver allocated {}'.format(samples, actual))
                    glFramebufferRenderbuffer(GL_FRAMEBUFFER, attachment, GL_RENDERBUFFER, buffer)
                self._check_complete()
            else:
                # Release the extra storage when returning to normal Editor View.
                self._close_multisample()
            self.width, self.height, self.samples = width, height, samples
        except Exception:
            # Force reallocation on retry after a partial storage/attachment failure.
            self.width = self.height = 0
            self._close_multisample()
            raise
        finally:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, read if glIsFramebuffer(read) else 0)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw if glIsFramebuffer(draw) else 0)
            glBindTexture(GL_TEXTURE_2D, texture)
            glBindRenderbuffer(GL_RENDERBUFFER, renderbuffer if glIsRenderbuffer(renderbuffer) else 0)

    @staticmethod
    def _check_complete():
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError('RenderTarget framebuffer is incomplete: 0x{:x}'.format(status))

    def bind(self):
        if not self.framebuffer or not self.width:
            raise RuntimeError('RenderTarget is closed or incomplete')
        glBindFramebuffer(GL_FRAMEBUFFER, self.multisample_framebuffer or self.framebuffer)
        glViewport(0, 0, self.width, self.height)

    def resolve(self):
        """Leave the single-sample FBO bound for color/depth/stencil readback."""
        if not self.framebuffer or not self.width:
            raise RuntimeError('RenderTarget is closed or incomplete')
        if self.samples > 1:
            scissor = bool(glIsEnabled(GL_SCISSOR_TEST))
            try:
                glDisable(GL_SCISSOR_TEST)
                glBindFramebuffer(GL_READ_FRAMEBUFFER, self.multisample_framebuffer)
                glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.framebuffer)
                glBlitFramebuffer(0, 0, self.width, self.height, 0, 0, self.width, self.height,
                                  GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT,
                                  GL_NEAREST)
            finally:
                if scissor:
                    glEnable(GL_SCISSOR_TEST)
        glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)

    def _close_multisample(self):
        if self.multisample_color:
            glDeleteRenderbuffers(2, [self.multisample_color, self.multisample_depth])
        if self.multisample_framebuffer:
            glDeleteFramebuffers(1, [self.multisample_framebuffer])
        self.multisample_framebuffer = self.multisample_color = self.multisample_depth = 0

    def close(self):
        self._close_multisample()
        if self.texture:
            glDeleteTextures([self.texture])
        if self.depth:
            glDeleteRenderbuffers(1, [self.depth])
        if self.framebuffer:
            glDeleteFramebuffers(1, [self.framebuffer])
        self.texture = self.depth = self.framebuffer = self.width = self.height = 0
