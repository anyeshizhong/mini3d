"""Real HDR sky shared by the backdrop, reflections, diffuse light and haze."""
from functools import lru_cache
from pathlib import Path
import math
import numpy as np

RESOURCES=Path(__file__).parent/'resources/photography'


def sky_path(source):
    if source=='sunset': return RESOURCES/'sunset.hdr'
    return Path(source).expanduser().resolve()


@lru_cache(maxsize=2)
def _load_sky(path,stamp,size):
    from .hdr import read_hdr
    rgb=read_hdr(path)
    if not np.isfinite(rgb).all() or rgb.max()<=0:
        raise ValueError('HDR sky must contain finite, positive radiance')
    h,w=rgb.shape[:2]
    luminance=rgb[:h//2]@np.array([.2126,.7152,.0722])
    y,x=np.unravel_index(luminance.argmax(),luminance.shape)
    # Radiance panorama -> Mini3D Z-up; matches the IBL cube conversion.
    azimuth=-((x+.5)/w-.5)*2*math.pi
    elevation=math.pi/2-(y+.5)/h*math.pi
    sun=np.array([math.cos(elevation)*math.cos(azimuth),
                  math.cos(elevation)*math.sin(azimuth),math.sin(elevation)])
    # Remove the small solar disc from ambient IBL. The shadowed directional
    # light supplies this energy, avoiding an unshadowed second sun in diffuse.
    ambient=rgb.copy()
    radius=max(3,int(w*.005))
    yy,xx=np.ogrid[:h,:w]; dx=(xx-x+w//2)%w-w//2
    distance=(yy-y)**2+dx**2
    ring=ambient[(distance>radius**2)&(distance<(radius*2)**2)]
    ambient[distance<=radius**2]=np.median(ring,axis=0)
    rgb.setflags(write=False); ambient.setflags(write=False)
    return rgb,ambient,sun


def load_sky(source):
    path=sky_path(source)
    if path.suffix.lower()!='.hdr': raise ValueError('Sky import requires a Radiance .hdr file')
    stat=path.stat()
    return _load_sky(str(path),stat.st_mtime_ns,stat.st_size)


def sky_rotation(source,direction):
    """World -> original dome, rotating the recorded solar direction to the lamp."""
    sun=load_sky(source)[2]
    def basis(v):
        v=np.asarray(v,dtype=float);v=v/np.linalg.norm(v)
        right=np.cross([0,0,1],v);right/=np.linalg.norm(right)
        return np.column_stack((v,right,np.cross(v,right)))
    return basis(sun)@basis(direction).T


class PhotoEnvironment:
    """One currently selected sky; textures are reused across ordinary frames."""
    def __init__(self):
        self.key=None;self.panorama=0;self.environment=None

    def prepare(self,source,lighting=False):
        from OpenGL import GL as gl
        path=sky_path(source);stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
        if self.key!=key:
            rgb,ambient,sun=load_sky(source)
            handle=int(gl.glGenTextures(1))
            names=(gl.GL_UNPACK_ALIGNMENT,gl.GL_UNPACK_ROW_LENGTH,gl.GL_UNPACK_SKIP_ROWS,gl.GL_UNPACK_SKIP_PIXELS)
            previous=[int(gl.glGetIntegerv(p)) for p in names]
            buffer=int(gl.glGetIntegerv(gl.GL_PIXEL_UNPACK_BUFFER_BINDING))
            try:
                gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER,0)
                for p,v in zip(names,(1,0,0,0)):gl.glPixelStorei(p,v)
                gl.glActiveTexture(gl.GL_TEXTURE11);gl.glBindSampler(11,0)
                gl.glBindTexture(gl.GL_TEXTURE_2D,handle)
                # Top-first rows are intentional; shader uses V=0 at the north pole.
                pixels=np.ascontiguousarray(rgb,dtype=np.float32)
                gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGB32F,rgb.shape[1],rgb.shape[0],
                                0,gl.GL_RGB,gl.GL_FLOAT,pixels)
                for p,v in ((gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR_MIPMAP_LINEAR),
                        (gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR),(gl.GL_TEXTURE_WRAP_S,gl.GL_REPEAT),
                        (gl.GL_TEXTURE_WRAP_T,gl.GL_CLAMP_TO_EDGE)):gl.glTexParameteri(gl.GL_TEXTURE_2D,p,v)
                gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            except Exception:
                gl.glDeleteTextures([handle]);raise
            finally:
                for p,v in zip(names,previous):gl.glPixelStorei(p,v)
                gl.glBindBuffer(gl.GL_PIXEL_UNPACK_BUFFER,buffer)
            self.close();self.panorama=handle;self.key=key
        if lighting and self.environment is None:
            from .environment import EnvironmentMap,load_environment
            if source=='sunset':arrays=load_environment(RESOURCES/'sunset_ibl.npz')
            else:
                from .ibl_filter import filter_panorama
                arrays=filter_panorama(load_sky(source)[1])
            self.environment=EnvironmentMap(arrays=arrays)
        if lighting:
            from OpenGL import GL as gl
            for unit in (8,9,10):gl.glBindSampler(unit,0)
        gl.glActiveTexture(gl.GL_TEXTURE11);gl.glBindTexture(gl.GL_TEXTURE_2D,self.panorama)
        gl.glBindSampler(11,0)
        if lighting:self.environment.bind()

    def close(self):
        from OpenGL import GL as gl
        if self.panorama:gl.glDeleteTextures([self.panorama]);self.panorama=0
        if self.environment:self.environment.close();self.environment=None
        self.key=None
