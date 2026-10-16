"""Focus from the displayed resolved depth, using top-left image coordinates."""
import numpy as np


def image_pixel(screen_pos, rect, size):
    raw = np.asarray(screen_pos, dtype=object)
    from numbers import Real
    if raw.shape != (2,) or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) for v in raw):
        raise ValueError('Screen point must contain two finite numbers')
    p = np.asarray(raw, dtype=float)
    x, y, w, h = rect
    if not np.isfinite(p).all() or not np.isfinite(rect).all() or w <= 0 or h <= 0:
        raise ValueError('Invalid screen point or image rectangle')
    if not (x <= p[0] < x+w and y <= p[1] < y+h): return None
    width, height = size
    return min(width-1, int((p[0]-x)/w*width)), height-1-min(height-1, int((p[1]-y)/h*height))


def unproject_depth(camera, pixel, size, depth):
    if not np.isfinite(depth) or depth < 0 or depth >= 1: return None
    width, height = size
    x, y = pixel
    ndc = np.array([2*(x+.5)/width-1, 2*(y+.5)/height-1, 2*depth-1, 1.])
    world = np.linalg.inv(camera.projection_matrix(width/height) @ camera.view_matrix) @ ndc
    if not np.isfinite(world).all() or abs(world[3]) < 1e-12: return None
    return world[:3]/world[3]


def read_focus_point(target, camera, screen_pos, rect):
    from OpenGL import GL as gl
    from .gl_state import preserved_pixel_pack
    pixel = image_pixel(screen_pos, rect, (target.width, target.height))
    if pixel is None: return None
    read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    try:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, target.framebuffer)
        with preserved_pixel_pack(reset=True):
            depth = float(np.asarray(gl.glReadPixels(*pixel, 1, 1, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT)).reshape(-1)[0])
        # Native color depth uses a conservative near plane. Unproject with
        # the exact projection that produced this displayed depth buffer.
        rendered_camera = getattr(target, 'render_camera', camera)
        return unproject_depth(rendered_camera, pixel, (target.width, target.height), depth)
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, read)


class PhotoPreviewQuality:
    """Use 960 during changes, promote after 180ms idle; PNG remains full size."""
    def __init__(self):
        self.key = None
        self.last_change = -float('inf')

    def size(self, key, full_size, active, now):
        if self.key is not None and key != self.key: self.last_change = now
        self.key = key
        if active: self.last_change = now
        if now-self.last_change < .18:
            width, height = full_size
            return (960, int(round(height*960/width)))
        return full_size
