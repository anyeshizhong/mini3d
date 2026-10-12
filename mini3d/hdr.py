"""Bounded Radiance RGBE reader. Returns linear RGB, top-first rows."""
from pathlib import Path
import numpy as np

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
        if not (8 <= w <= 8192 and 2 <= h <= 4096) or w*h > 8388608:
            raise ValueError("HDR exceeds the 8 megapixel import limit")
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
