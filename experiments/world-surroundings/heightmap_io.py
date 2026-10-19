"""Lossless 8/16-bit grayscale PNG input for the World Surroundings lab."""

import hashlib
import math
import operator
import struct
import warnings
from io import BytesIO

import numpy as np
from PIL import Image

from heightfield import Heightfield


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_HEADER_SIZE = 8 + 4 + 4 + 13 + 4
_MAX_PNG_DIMENSION = (1 << 31) - 1


def _positive_integer(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("%s must be a positive integer" % name)
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError("%s must be a positive integer" % name) from exc
    if result <= 0:
        raise ValueError("%s must be a positive integer" % name)
    return result


def _finite_number(value, name):
    if isinstance(value, (str, bytes, bytearray, bool, np.bool_)):
        raise ValueError("%s must be finite" % name)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be finite" % name) from exc
    if not math.isfinite(result):
        raise ValueError("%s must be finite" % name)
    return result


def _finite_pair(value, name):
    if isinstance(value, (str, bytes, bytearray)):
        raise ValueError("%s must contain two finite numbers" % name)
    try:
        pair = tuple(value)
    except TypeError as exc:
        raise ValueError("%s must contain two finite numbers" % name) from exc
    if len(pair) != 2:
        raise ValueError("%s must contain two finite numbers" % name)
    return (_finite_number(pair[0], name), _finite_number(pair[1], name))


def _validate_png_header(header, max_samples):
    if len(header) != _PNG_HEADER_SIZE or header[:8] != _PNG_SIGNATURE:
        raise ValueError("input is not a complete PNG file")
    ihdr_length = struct.unpack_from(">I", header, 8)[0]
    if ihdr_length != 13 or header[12:16] != b"IHDR":
        raise ValueError("PNG must start with a legal IHDR chunk")

    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack_from(">IIBBBBB", header, 16))
    if not (2 <= width <= _MAX_PNG_DIMENSION and
            2 <= height <= _MAX_PNG_DIMENSION):
        raise ValueError("PNG dimensions must each be at least 2 and legal")
    if color_type != 0:
        raise ValueError("heightmap PNG must be single-channel grayscale")
    if bit_depth not in (8, 16):
        raise ValueError("heightmap PNG must use 8-bit or 16-bit samples")
    if compression != 0 or filtering != 0 or interlace not in (0, 1):
        raise ValueError("PNG IHDR contains unsupported or illegal methods")
    if width * height > max_samples:
        raise ValueError("heightmap exceeds max_samples before decoding")
    return width, height, bit_depth


def _hash_stream(stream):
    digest = hashlib.sha256()
    while True:
        block = stream.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def read_heightmap(path, *, max_samples=1048576):
    """Read raw PNG samples without color conversion or per-image scaling.

    The returned ``samples`` array is uint8 or uint16 with shape ``(rows,
    columns)``.  PNG row zero remains array row zero.  The SHA-256 covers the
    exact input file bytes, including PNG metadata and trailing bytes.
    """
    max_samples = _positive_integer(max_samples, "max_samples")

    # Parse and budget from IHDR before asking Pillow to inspect or decode any
    # image data.  Hashing is streamed so the compressed source is not copied
    # into memory as a second full-file buffer.
    with open(path, "rb") as stream:
        header = stream.read(_PNG_HEADER_SIZE)
        width, height, bit_depth = _validate_png_header(header, max_samples)
        stream.seek(0)
        input_sha256 = _hash_stream(stream)

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                stream.seek(0)
                with Image.open(stream, formats=("PNG",)) as image:
                    if image.format != "PNG" or image.size != (width, height):
                        raise ValueError("decoded image disagrees with PNG IHDR")
                    image.verify()

                stream.seek(0)
                with Image.open(stream, formats=("PNG",)) as image:
                    if image.format != "PNG" or image.size != (width, height):
                        raise ValueError("decoded image disagrees with PNG IHDR")
                    if "transparency" in image.info:
                        raise ValueError("PNG transparency (tRNS alpha) is not supported")
                    if bit_depth == 8 and image.mode != "L":
                        raise ValueError("8-bit grayscale PNG decoded in an invalid mode")
                    if bit_depth == 16 and image.mode not in (
                            "I", "I;16", "I;16B", "I;16L"):
                        raise ValueError("16-bit grayscale PNG decoded in an invalid mode")
                    image.load()
                    decoded = np.asarray(image)
                    if decoded.shape != (height, width):
                        raise ValueError("decoded samples disagree with PNG dimensions")
                    if bit_depth == 8:
                        if decoded.dtype != np.uint8:
                            raise ValueError("8-bit grayscale PNG did not decode as uint8")
                        samples = np.array(decoded, dtype=np.uint8, copy=True)
                    else:
                        # Pillow 9.5 decodes PNG grayscale16 as mode I / int32.
                        # Check the numeric range before the exact integer cast.
                        numeric = np.asarray(decoded)
                        if not np.issubdtype(numeric.dtype, np.integer):
                            raise ValueError("16-bit grayscale PNG did not decode as integers")
                        if (np.any(numeric < 0) or np.any(numeric > 65535)):
                            raise ValueError("16-bit grayscale PNG samples are out of range")
                        samples = np.array(numeric, dtype=np.uint16, copy=True)
        except FileNotFoundError:
            raise
        except (OSError, SyntaxError, ValueError, Warning, OverflowError) as exc:
            raise ValueError("invalid or corrupted heightmap PNG: %s" % exc) from exc

    return {
        "samples": samples,
        "bit_depth": bit_depth,
        "shape": (height, width),
        "input_sha256": input_sha256,
    }


def load_heightmap(path, *, size=(36.0, 26.0), origin=(-18.0, -13.0),
                   base_z=0.0, height_range=6.0, flip_y=False,
                   max_samples=1048576):
    """Load a grayscale heightmap into a ``Heightfield``.

    Columns retain their order along +X and PNG rows retain their order along
    +Y, so row zero maps to ``origin[1]``.  ``flip_y=True`` explicitly reverses
    the rows.  Heights use the PNG's full integer range; metadata such as
    sRGB/gamma is never applied as a color transform.
    """
    size = _finite_pair(size, "size")
    if size[0] <= 0.0 or size[1] <= 0.0:
        raise ValueError("size dimensions must be positive")
    origin = _finite_pair(origin, "origin")
    base_z = _finite_number(base_z, "base_z")
    height_range = _finite_number(height_range, "height_range")
    if height_range < 0.0:
        raise ValueError("height_range must be non-negative")
    if not isinstance(flip_y, (bool, np.bool_)):
        raise ValueError("flip_y must be a boolean")
    max_samples = _positive_integer(max_samples, "max_samples")

    decoded = read_heightmap(path, max_samples=max_samples)
    samples = decoded["samples"]
    if flip_y:
        samples = samples[::-1, :]

    maximum = 255.0 if decoded["bit_depth"] == 8 else 65535.0
    with np.errstate(over="ignore", invalid="ignore"):
        heights = base_z + (samples.astype(np.float64) / maximum) * height_range
    if not np.isfinite(heights).all():
        raise ValueError("height parameters produce non-finite elevations")
    return Heightfield(heights, origin=origin, size=size)


def save_heightmap(path, samples, bit_depth):
    """Write a deterministic single-channel fixture PNG with raw samples."""
    bit_depth = _positive_integer(bit_depth, "bit_depth")
    if bit_depth not in (8, 16):
        raise ValueError("bit_depth must be 8 or 16")
    try:
        values = np.asarray(samples)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("samples must be a 2D integer array") from exc
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
        raise ValueError("samples must have at least 2 rows and 2 columns")
    if not np.issubdtype(values.dtype, np.integer) or np.issubdtype(values.dtype, np.bool_):
        raise ValueError("samples must contain integers")
    maximum = 255 if bit_depth == 8 else 65535
    if np.any(values < 0) or np.any(values > maximum):
        raise ValueError("samples are outside the selected bit depth")

    dtype = np.uint8 if bit_depth == 8 else np.uint16
    encoded_samples = np.array(values, dtype=dtype, copy=True)
    image = Image.fromarray(encoded_samples)
    buffer = BytesIO()
    try:
        image.save(buffer, format="PNG", optimize=False, compress_level=9)
    finally:
        image.close()
    with open(path, "wb") as stream:
        stream.write(buffer.getvalue())
