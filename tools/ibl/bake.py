"""Offline desktop-GL host for pinned Khronos IBL filtering shaders.

No convolution code is invented here. See upstream/NOTICE.md for provenance.
Requires the same NumPy / pygame / PyOpenGL installation as Mini3D.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pygame
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path(__file__).parent / 'upstream'
FILAMENT = '764fe6cac9bdb4ba24d3d852344dfa04a5f70f75'
HDR_SHA256 = '8dee8bd1f47b6e723284a58bd0a2db12e3cd3bc70283e17707d06b6b142065e0'
VERTEX = """#version 330 core
out vec2 texCoord;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    texCoord = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""


def read_hdr(path):
    """Decode the pinned Radiance RGBE scanline format, retaining top-first rows."""
    with Path(path).open('rb') as stream:
        if not stream.readline().startswith(b'#?'):
            raise ValueError('Not a Radiance HDR')
        header = []
        while True:
            line = stream.readline()
            if not line:
                raise ValueError('Truncated HDR header')
            if not line.strip():
                break
            header.append(line.strip())
        if b'FORMAT=32-bit_rle_rgbe' not in header:
            raise ValueError('Unsupported HDR encoding')
        axis_y, h, axis_x, w = stream.readline().split()
        h, w = int(h), int(w)
        if (axis_y, axis_x) != (b'-Y', b'+X'):
            raise ValueError('Unsupported HDR orientation')
        rgbe = np.empty((h, w, 4), np.uint8)
        for y in range(h):
            prefix = stream.read(4)
            if prefix != bytes((2, 2, w >> 8, w & 255)):
                raise ValueError('Unsupported or truncated scanline')
            for c in range(4):
                x = 0
                while x < w:
                    count = stream.read(1)
                    if not count or count[0] == 0:
                        raise ValueError('Invalid HDR run')
                    count = count[0]
                    n = count - 128 if count > 128 else count
                    data = stream.read(1 if count > 128 else n)
                    if len(data) != (1 if count > 128 else n) or x + n > w:
                        raise ValueError('Truncated HDR run')
                    rgbe[y, x:x+n, c] = data[0] if count > 128 else np.frombuffer(data, np.uint8)
                    x += n
    rgb = np.ldexp(rgbe[..., :3].astype(np.float32), rgbe[..., 3:4].astype(np.int32)-136)
    rgb[rgbe[..., 3] == 0] = 0
    return rgb


def program(filename):
    source = (UPSTREAM / filename).read_text()
    # GLSL ES -> desktop GLSL: only version/precision declarations change.
    source = source.replace('precision highp float;', '')
    return compileProgram(compileShader(VERTEX, gl.GL_VERTEX_SHADER),
                          compileShader('#version 330 core\n'+source, gl.GL_FRAGMENT_SHADER))


def bake(hdr, output, samples=1024):
    started = time.perf_counter()
    rgb = read_hdr(hdr)
    sha = hashlib.sha256(Path(hdr).read_bytes()).hexdigest()
    if HDR_SHA256 and sha != HDR_SHA256:
        raise ValueError('Input does not match pinned CC0 environment')
    pygame.init()
    pygame.display.set_mode((32, 32), pygame.OPENGL | pygame.HIDDEN)
    vao = int(gl.glGenVertexArrays(1))
    gl.glBindVertexArray(vao)
    framebuffer = int(gl.glGenFramebuffers(1))
    gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, framebuffer)
    handles, programs = [], []

    def texture(target, size, levels=1):
        handle = int(gl.glGenTextures(1)); handles.append(handle)
        gl.glBindTexture(target, handle)
        for level in range(levels):
            for face in range(6 if target == gl.GL_TEXTURE_CUBE_MAP else 1):
                face_target = gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X+face if target == gl.GL_TEXTURE_CUBE_MAP else target
                gl.glTexImage2D(face_target, level, gl.GL_RGBA32F, size >> level, size >> level,
                                0, gl.GL_RGBA, gl.GL_FLOAT, None)
        gl.glTexParameteri(target, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if levels > 1 else gl.GL_LINEAR)
        gl.glTexParameteri(target, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(target, gl.GL_TEXTURE_MAX_LEVEL, levels-1)
        for axis in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
            gl.glTexParameteri(target, axis, gl.GL_CLAMP_TO_EDGE)
        return handle

    def uniform(p, name, value):
        loc = gl.glGetUniformLocation(p, name)
        (gl.glUniform1i if isinstance(value, int) else gl.glUniform1f)(loc, value)

    def render_faces(p, target, level, size):
        faces = []
        for face in range(6):
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                     gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X+face, target, level)
            if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('Offline float framebuffer unsupported')
            gl.glViewport(0, 0, size, size)
            uniform(p, 'u_currentFace', face)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            data = gl.glReadPixels(0, 0, size, size, gl.GL_RGB, gl.GL_FLOAT)
            faces.append(np.frombuffer(data, np.float32).reshape(size, size, 3).copy())
        return np.asarray(faces, dtype=np.float16)

    try:
        panorama = texture(gl.GL_TEXTURE_2D, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB32F, rgb.shape[1], rgb.shape[0],
                        0, gl.GL_RGB, gl.GL_FLOAT, rgb)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        source = texture(gl.GL_TEXTURE_CUBE_MAP, 512, 10)
        specular = texture(gl.GL_TEXTURE_CUBE_MAP, 256, 9)
        diffuse = texture(gl.GL_TEXTURE_CUBE_MAP, 32)
        lut = texture(gl.GL_TEXTURE_2D, 256)
        p = program('panorama_to_cubemap.frag'); programs.append(p)
        gl.glUseProgram(p)
        gl.glBindTexture(gl.GL_TEXTURE_2D, panorama)
        uniform(p, 'u_panorama', 0)
        render_faces(p, source, 0, 512)
        gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, source)
        gl.glGenerateMipmap(gl.GL_TEXTURE_CUBE_MAP)
        gl.glEnable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)
        p = program('ibl_filtering.frag'); programs.append(p)
        gl.glUseProgram(p)
        for name, value in dict(u_cubemapTexture=0, u_sampleCount=samples, u_width=512,
                                u_lodBias=0.0, u_isGeneratingLUT=0, u_floatTexture=1,
                                u_intensityScale=1.0, u_roughness=0.0, u_distribution=0).items():
            uniform(p, name, value)
        arrays = {'diffuse': render_faces(p, diffuse, 0, 32)}
        uniform(p, 'u_distribution', 1)
        for level in range(9):
            uniform(p, 'u_roughness', level / 8.0)
            arrays['specular_'+str(level)] = render_faces(p, specular, level, 256 >> level)
            print('GGX mip', level, flush=True)
            pygame.event.pump()
        uniform(p, 'u_isGeneratingLUT', 1)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, lut, 0)
        gl.glViewport(0, 0, 256, 256)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        data = gl.glReadPixels(0, 0, 256, 256, gl.GL_RGB, gl.GL_FLOAT)
        arrays['brdf'] = np.frombuffer(data, np.float32).reshape(256, 256, 3)[..., :2].astype(np.float16)
        if gl.glGetError() != gl.GL_NO_ERROR or any(not np.isfinite(a).all() or a.min() < 0 for a in arrays.values()):
            raise RuntimeError('Invalid prefiltered resource')
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(output, **arrays)
        metadata = dict(source_sha256=sha, source_filament_commit=FILAMENT, samples=samples,
                        source_cube_size=512, roughness_mips=[i/8 for i in range(9)],
                        diffuse_is_irradiance_div_pi=True, exposure=1.0, rgb_scale=1.0,
                        gpu=gl.glGetString(gl.GL_RENDERER).decode(),
                        bake_seconds=time.perf_counter()-started,
                        texture_bytes=sum(a.nbytes for a in arrays.values()),
                        resource_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        output.with_suffix('.json').write_text(json.dumps(metadata, indent=2)+'\n')
        print(json.dumps(metadata, indent=2))
    finally:
        gl.glDeleteTextures(handles)
        for p in programs: gl.glDeleteProgram(p)
        gl.glDeleteFramebuffers(1, [framebuffer])
        gl.glDeleteVertexArrays(1, [vao])
        pygame.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hdr', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'mini3d/resources/ibl/neutral.npz')
    args = parser.parse_args()
    bake(args.hdr, args.output)
