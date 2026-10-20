"""Prepare pinned Poly Haven displacement maps for the Q terrain experiment.

This is an offline-runtime fixture builder. It queries Poly Haven's public API,
checks downloaded source files against the API's size and MD5, then writes
256x256 16-bit grayscale maps beside the existing material fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import warnings

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DESTINATION = HERE / "assets" / "material-heights"
DEFAULT_CACHE = ROOT / "captures" / "world-surroundings" / "material-height-source"
API_BASE = "https://api.polyhaven.com"
USER_AGENT = "Mini3D-Terrain-Quality/1.0"
OUTPUT_SIZE = (256, 256)
SOURCE_SIZE = (1024, 1024)
MAX_API_BYTES = 8 * 1024 * 1024
MAX_TEXTURE_BYTES = 16 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MANAGED_OUTPUTS = {"soil.png", "rock.png", "grass.png", "manifest.json", "NOTICE.md"}

LAYERS = (
    {
        "layer": "soil",
        "asset_id": "brown_mud_02",
        "asset_name": "Brown Mud 02",
        "asset_page": "https://polyhaven.com/a/brown_mud_02",
        "tile_metres": 1.3,
    },
    {
        "layer": "rock",
        "asset_id": "rock_face",
        "asset_name": "Rock Face",
        "asset_page": "https://polyhaven.com/a/rock_face",
        "tile_metres": 2.4,
    },
    {
        "layer": "grass",
        "asset_id": "leafy_grass",
        "asset_name": "Leafy Grass",
        "asset_page": "https://polyhaven.com/a/leafy_grass",
        "tile_metres": 2.0,
    },
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _fetch_bytes(url, *, limit, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Response exceeded the allowed size: " + url)
    return data


def _fetch_json(url):
    raw = _fetch_bytes(url, limit=MAX_API_BYTES, timeout=30)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON from Poly Haven API: " + url) from exc
    if not isinstance(value, dict):
        raise ValueError("Expected an object from Poly Haven API: " + url)
    return value


def _find_casefold(mapping, key):
    if not isinstance(mapping, dict):
        return None
    wanted = key.casefold()
    for name, value in mapping.items():
        if isinstance(name, str) and name.casefold() == wanted:
            return value
    return None


def _author_metadata(info):
    authors = info.get("authors")
    if not isinstance(authors, dict) or not authors:
        raise ValueError("Poly Haven asset info does not list authors")
    return [
        {"name": str(name), "role": str(role)}
        for name, role in sorted(authors.items(), key=lambda item: item[0].casefold())
    ]


def _author_display(authors):
    values = []
    for entry in authors:
        name, role = entry["name"], entry["role"]
        values.append(name if role.casefold() == "all" else "{} ({})".format(name, role.casefold()))
    return ", ".join(values)


def _source_record(layer, cache):
    asset_id = layer["asset_id"]
    files_url = API_BASE + "/files/" + asset_id
    info_url = API_BASE + "/info/" + asset_id
    files = _fetch_json(files_url)
    info = _fetch_json(info_url)

    displacement = _find_casefold(files, "displacement")
    one_k = displacement.get("1k") if isinstance(displacement, dict) else None
    png = one_k.get("png") if isinstance(one_k, dict) else None
    if not isinstance(png, dict):
        raise ValueError("Poly Haven has no 1K displacement PNG for " + asset_id)

    url = png.get("url")
    size = png.get("size")
    expected_md5 = png.get("md5")
    if not isinstance(url, str) or not isinstance(size, int) or not isinstance(expected_md5, str):
        raise ValueError("Poly Haven API returned incomplete 1K PNG metadata for " + asset_id)
    parsed_url = urllib.parse.urlparse(url)
    expected_path = "/file/ph-assets/Textures/png/1k/{}/".format(asset_id)
    if (parsed_url.scheme != "https" or parsed_url.netloc != "dl.polyhaven.org" or
            not parsed_url.path.startswith(expected_path) or
            not parsed_url.path.endswith("_disp_1k.png")):
        raise ValueError("Poly Haven API returned an unexpected source URL for " + asset_id)
    if size <= 0 or size > MAX_TEXTURE_BYTES:
        raise ValueError("Poly Haven API returned an unexpected source size for " + asset_id)

    cache.mkdir(parents=True, exist_ok=True)
    cache_path = cache / Path(parsed_url.path).name
    if cache_path.exists():
        raw = cache_path.read_bytes()
        if len(raw) != size or hashlib.md5(raw).hexdigest() != expected_md5.lower():
            raise ValueError("Cached source does not match current Poly Haven API metadata: " + str(cache_path))
    else:
        raw = _fetch_bytes(url, limit=MAX_TEXTURE_BYTES)
        if len(raw) != size or hashlib.md5(raw).hexdigest() != expected_md5.lower():
            raise ValueError("Downloaded source does not match Poly Haven API metadata: " + url)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", prefix="." + cache_path.name + ".", suffix=".part",
                    dir=str(cache), delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(cache_path))
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    authors = _author_metadata(info)
    return {
        "api_files_endpoint": files_url,
        "api_info_endpoint": info_url,
        "asset_page": layer["asset_page"],
        "url": url,
        "api_bytes": size,
        "api_md5": expected_md5.lower(),
        "upstream_sha256": sha256(raw),
        "upstream_bytes": len(raw),
        "cache_file": cache_path.name,
        "asset_files_hash": info.get("files_hash"),
        "authors": authors,
        "author_display": _author_display(authors),
        "tile_metres": layer["tile_metres"],
        "source_dimensions_mm": info.get("dimensions"),
        "raw": raw,
    }


def _png_header(raw, expected_size=SOURCE_SIZE):
    if len(raw) < 33 or raw[:8] != PNG_SIGNATURE:
        raise ValueError("Source is not a complete PNG")
    if struct.unpack_from(">I", raw, 8)[0] != 13 or raw[12:16] != b"IHDR":
        raise ValueError("PNG does not begin with a legal IHDR")
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack_from(
        ">IIBBBBB", raw, 16)
    if (width, height) != tuple(expected_size):
        raise ValueError("Expected a {}x{} PNG, got {}x{}".format(
            expected_size[0], expected_size[1], width, height))
    if color_type != 0 or depth not in (8, 16):
        raise ValueError("Displacement source must be 8- or 16-bit grayscale PNG")
    if compression != 0 or filtering != 0 or interlace != 0:
        raise ValueError("Source PNG uses unsupported encoding methods")
    return width, height, depth, color_type


def _png_color_chunks(raw):
    names = {b"gAMA": "gAMA", b"sRGB": "sRGB", b"cHRM": "cHRM",
             b"iCCP": "iCCP", b"sBIT": "sBIT", b"tRNS": "tRNS"}
    chunks = []
    cursor = 8
    while cursor + 12 <= len(raw):
        length = struct.unpack_from(">I", raw, cursor)[0]
        kind = raw[cursor + 4:cursor + 8]
        end = cursor + 12 + length
        if end > len(raw):
            raise ValueError("Truncated PNG chunk")
        if kind in names:
            chunks.append(names[kind])
        cursor = end
        if kind == b"IEND":
            break
    return chunks


def decode_displacement_png(raw):
    """Read raw grayscale values as linear data; never apply PNG color metadata."""
    width, height, bit_depth, _ = _png_header(raw)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(__import__("io").BytesIO(raw), formats=("PNG",)) as image:
                if image.format != "PNG" or image.size != (width, height):
                    raise ValueError("Decoded source disagrees with its PNG header")
                if "transparency" in image.info:
                    raise ValueError("Displacement PNG must not contain transparency")
                image.load()
                decoded = np.asarray(image)
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Could not decode source displacement PNG") from exc

    if decoded.shape != (height, width):
        raise ValueError("Displacement PNG must decode to one grayscale channel")
    encoded_min = int(decoded.min())
    encoded_max = int(decoded.max())
    encoded_mean = float(decoded.mean(dtype=np.float64))
    encoded_full_scale = 255 if bit_depth == 8 else 65535
    if bit_depth == 8:
        if decoded.dtype != np.uint8:
            raise ValueError("8-bit PNG did not decode as uint8")
        samples = decoded.astype(np.uint16) * np.uint16(257)
        expansion = "uint8 sample multiplied by 257; exact 0..255 to 0..65535 code-space mapping"
    else:
        if decoded.dtype not in (np.uint16, np.int32, np.int64):
            raise ValueError("16-bit PNG did not decode as an integer array")
        if decoded.size and (int(decoded.min()) < 0 or int(decoded.max()) > 65535):
            raise ValueError("16-bit PNG samples are outside the uint16 range")
        samples = decoded.astype(np.uint16, copy=True)
        expansion = "none; source uint16 samples retained"

    return samples, {
        "size": [width, height],
        "bit_depth": bit_depth,
        "color_type": "grayscale",
        "sample_mode": "linear scalar data; PNG color metadata ignored",
        "ignored_color_chunks": _png_color_chunks(raw),
        "uint16_conversion": expansion,
        "source_range": {
            "minimum_code": encoded_min,
            "maximum_code": encoded_max,
            "full_scale_code": encoded_full_scale,
            "mean_code": encoded_mean,
            "normalized_minimum": encoded_min / float(encoded_full_scale),
            "normalized_maximum": encoded_max / float(encoded_full_scale),
        },
        "converted_uint16_range": {
            "minimum_code": int(samples.min()),
            "maximum_code": int(samples.max()),
            "mean_code": float(samples.mean(dtype=np.float64)),
        },
        "min": int(samples.min()),
        "max": int(samples.max()),
        "mean": float(samples.mean(dtype=np.float64)),
        "unique_sample_count": int(np.unique(samples).size),
    }


def downsample_area(samples, target_size=OUTPUT_SIZE):
    """Downsample uint16 height data with a box mean and half-up rounding."""
    values = np.asarray(samples)
    if values.ndim != 2 or values.dtype != np.uint16:
        raise ValueError("samples must be a two-dimensional uint16 array")
    target_width, target_height = target_size
    source_height, source_width = values.shape
    if (target_width <= 0 or target_height <= 0 or source_width % target_width or
            source_height % target_height):
        raise ValueError("target dimensions must evenly divide the source image")
    factor_x = source_width // target_width
    factor_y = source_height // target_height
    blocks = values.astype(np.float64).reshape(
        target_height, factor_y, target_width, factor_x)
    means = blocks.mean(axis=(1, 3), dtype=np.float64)
    rounded = np.floor(means + 0.5)
    result = rounded.astype(np.uint16)
    within_block_error = blocks - means[:, None, :, None]
    rounding_error = rounded - means
    return result, {
        "resampling": "arithmetic 4x4 area mean, rounded half-up to uint16",
        "source_to_area_mean_error_lsb": {
            "comparison": "source samples versus their exact 4x4 block mean",
            "mean_absolute": float(np.abs(within_block_error).mean()),
            "rms": float(np.sqrt(np.square(within_block_error).mean())),
            "max_absolute": float(np.abs(within_block_error).max()),
        },
        "area_mean_rounding_error_lsb": {
            "comparison": "stored uint16 result versus exact 4x4 block mean",
            "mean_absolute": float(np.abs(rounding_error).mean()),
            "max_absolute": float(np.abs(rounding_error).max()),
        },
        "min": int(result.min()),
        "max": int(result.max()),
        "mean": float(result.mean(dtype=np.float64)),
        "size": [target_width, target_height],
        "box_factor": [factor_x, factor_y],
    }


def _manifest_source(source):
    return {key: value for key, value in source.items() if key != "raw"}


def _notice(records):
    rows = []
    for layer in LAYERS:
        record = records[layer["layer"]]
        source_depth = record["source_sample_info"]["bit_depth"]
        rows.append("| {layer} | [{name}]({page}) | {author} | {tile:g} m | {depth}-bit |".format(
            layer=layer["layer"].title(), name=layer["asset_name"],
            page=layer["asset_page"], author=record["author"],
            tile=layer["tile_metres"], depth=source_depth))
    return """# Terrain material height fixtures — CC0-1.0

These are displacement maps from the same Poly Haven materials used by the
LAB-02B material experiment. Poly Haven publishes these assets under CC0.
The asset pages, creators, display tile widths, and source PNG bit depths are:

| Experiment layer | Asset | Author | Tile width | Source PNG |
| --- | --- | --- | ---: | ---: |
{rows}

[Poly Haven asset license](https://polyhaven.com/license) · CC0-1.0.
The retained CC0 legal text is [CC0.html](../../../../mini3d/resources/ibl/CC0.html).
Source URLs, API-reported sizes and MD5 values, downloaded SHA-256 values,
output hashes, dimensions, ranges, and measured resampling errors are recorded
in `manifest.json`. The 1K source PNGs stay in the ignored
`captures/world-surroundings/material-height-source` cache.

The bundled inputs are 256×256 single-channel uint16 PNGs. A source 8-bit
sample is mapped to the same 16-bit code space as `sample * 257`; 16-bit source
samples are kept unchanged. Each output pixel is the arithmetic mean of its
corresponding 4×4 source block, rounded half-up to the nearest uint16 code.
This is linear scalar processing: source PNG gAMA/sRGB/color-profile chunks are
ignored and omitted from the output, and each image keeps its original numeric
range. No per-image contrast stretch or normalization is performed. Row zero
and column zero retain the source orientation. Interpret an output sample as
`sample / 65535.0` for normalized displacement.

Reproduce from the repository root with:

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/prepare_quality_assets.py
```

The preparation script checks the live official API metadata before accepting
cached or downloaded files. Runtime rendering reads the bundled maps offline.
""".format(rows="\n".join(rows))


def _write_png16(path, samples):
    image = Image.fromarray(np.asarray(samples, dtype=np.uint16))
    if image.mode not in ("I;16", "I;16B", "I;16L"):
        raise ValueError("Pillow did not create a 16-bit grayscale image")
    image.save(str(path), format="PNG", optimize=False)
    encoded = path.read_bytes()
    width, height, depth, color_type = _png_header(encoded, OUTPUT_SIZE)
    if (width, height) != OUTPUT_SIZE or depth != 16 or color_type != 0:
        raise ValueError("Prepared PNG does not match the 256x256 uint16 grayscale contract")
    if set(_png_color_chunks(encoded)) & {"gAMA", "sRGB", "cHRM", "iCCP"}:
        raise ValueError("Prepared height data unexpectedly contains color-space metadata")
    with Image.open(path) as check:
        check.load()
        decoded = np.asarray(check)
    if decoded.shape != (OUTPUT_SIZE[1], OUTPUT_SIZE[0]):
        raise ValueError("Prepared PNG failed its decode check")
    if decoded.dtype not in (np.uint16, np.int32, np.int64):
        raise ValueError("Prepared PNG did not decode at 16-bit precision")
    if not np.array_equal(decoded.astype(np.uint16), samples):
        raise ValueError("Prepared PNG does not round-trip exact uint16 samples")
    return encoded


def _read_previous_manifest(destination):
    path = destination / "manifest.json"
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Existing height manifest is unreadable; leaving outputs untouched") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("maps"), dict):
        raise ValueError("Existing height manifest has an unexpected structure")
    return manifest


def _validate_previous_sources(previous, records, accept_source_change):
    if previous is None:
        return
    old_maps = previous["maps"]
    for layer in LAYERS:
        output_name = layer["layer"] + ".png"
        old = old_maps.get(output_name)
        new = records[layer["layer"]]
        old_source = old.get("source", {}) if isinstance(old, dict) else {}
        old_hash = old_source.get("upstream_sha256")
        new_hash = new["source"]["upstream_sha256"]
        if old_hash and old_hash != new_hash and not accept_source_change:
            raise ValueError(
                "Poly Haven source changed for {}; use --accept-source-change to prepare an explicit update".format(
                    output_name))


def _remove_owned_directory(path):
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            raise OSError("Refusing to recursively remove unexpected directory: " + str(child))
    path.rmdir()


def _check_managed_directory(destination):
    if destination.is_symlink():
        raise ValueError("Refusing to replace a symlinked height output path: " + str(destination))
    if not destination.exists():
        return
    if not destination.is_dir():
        raise ValueError("Height output path exists but is not a directory: " + str(destination))
    unexpected = sorted(child.name for child in destination.iterdir()
                        if child.name not in MANAGED_OUTPUTS)
    if unexpected:
        raise ValueError("Refusing to replace unrecognized files in height output: " + ", ".join(unexpected))


def promote_staging(staging, destination, replace=os.replace):
    """Promote a complete output directory, restoring the old directory on error."""
    _check_managed_directory(destination)
    backup = destination.with_name(destination.name + ".backup-" + uuid.uuid4().hex)
    moved_old = False
    try:
        if destination.exists():
            replace(str(destination), str(backup))
            moved_old = True
        replace(str(staging), str(destination))
    except Exception:
        if moved_old and backup.exists() and not destination.exists():
            replace(str(backup), str(destination))
        raise
    if moved_old:
        try:
            _remove_owned_directory(backup)
        except OSError as exc:
            print("Warning: prepared outputs are live; old backup remains at {} ({})".format(
                backup, exc), file=sys.stderr)


def prepare(cache=DEFAULT_CACHE, destination=DESTINATION, *, accept_source_change=False):
    cache = Path(cache)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _check_managed_directory(destination)
    previous = _read_previous_manifest(destination)

    records = {}
    for layer in LAYERS:
        source = _source_record(layer, cache)
        samples, source_info = decode_displacement_png(source["raw"])
        output, processing_info = downsample_area(samples)
        records[layer["layer"]] = {
            "asset_id": layer["asset_id"],
            "asset_name": layer["asset_name"],
            "asset_page": layer["asset_page"],
            "author": source["author_display"],
            "authors": source["authors"],
            "tile_metres": layer["tile_metres"],
            "source": _manifest_source(source),
            "source_sample_info": source_info,
            "processing": processing_info,
            "size": [OUTPUT_SIZE[0], OUTPUT_SIZE[1]],
            "bit_depth": 16,
            "channels": "grayscale uint16",
            "sample_encoding": "linear scalar; sample / 65535.0",
            "bundled_sha256": None,
            "bundled_bytes": None,
            "bundled_min": int(output.min()),
            "bundled_max": int(output.max()),
            "bundled_mean": float(output.mean(dtype=np.float64)),
        }
        records[layer["layer"]]["_output_samples"] = output

    _validate_previous_sources(previous, records, accept_source_change)

    staging = destination.with_name(destination.name + ".stage-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        for layer in LAYERS:
            record = records[layer["layer"]]
            output_name = layer["layer"] + ".png"
            encoded = _write_png16(staging / output_name, record.pop("_output_samples"))
            record["bundled_sha256"] = sha256(encoded)
            record["bundled_bytes"] = len(encoded)

        manifest = {
            "license": "CC0-1.0",
            "license_url": "https://polyhaven.com/license",
            "preparation": {
                "source_resolution": [SOURCE_SIZE[0], SOURCE_SIZE[1]],
                "output_resolution": [OUTPUT_SIZE[0], OUTPUT_SIZE[1]],
                "output_format": "single-channel grayscale uint16 PNG",
                "linear_data": True,
                "source_color_metadata": "ignored; output color metadata omitted",
                "source_8bit_mapping": "sample * 257; no precision is added",
                "resampling": "4x4 arithmetic area mean, round-half-up to uint16",
                "normalization": "none; source numeric range is preserved",
                "orientation": "source row/column order preserved; no flip",
                "runtime_decode": "sample / 65535.0",
            },
            "maps": {
                layer["layer"] + ".png": {
                    key: value for key, value in records[layer["layer"]].items()
                    if not key.startswith("_")
                }
                for layer in LAYERS
            },
        }
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        (staging / "manifest.json").write_bytes(manifest_bytes)
        with (staging / "NOTICE.md").open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(_notice(records))
        _validate_staged_outputs(staging, manifest)
        promote_staging(staging, destination)
        print("Prepared 3 verified height maps in {}".format(destination))
        return manifest
    except Exception:
        if staging.exists():
            _remove_owned_directory(staging)
        raise


def _validate_staged_outputs(staging, manifest):
    if set(path.name for path in staging.iterdir()) != MANAGED_OUTPUTS:
        raise ValueError("Staged height outputs do not match the managed file set")
    for output_name, record in manifest["maps"].items():
        path = staging / output_name
        raw = path.read_bytes()
        if sha256(raw) != record["bundled_sha256"]:
            raise ValueError("Staged bundled hash mismatch: " + output_name)
        with Image.open(path) as image:
            image.load()
            values = np.asarray(image).astype(np.uint16)
        if values.shape != (OUTPUT_SIZE[1], OUTPUT_SIZE[0]):
            raise ValueError("Staged dimensions mismatch: " + output_name)
        if int(values.min()) != record["bundled_min"] or int(values.max()) != record["bundled_max"]:
            raise ValueError("Staged numeric range mismatch: " + output_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE,
                        help="verified 1K source cache (default: captures/world-surroundings/material-height-source)")
    parser.add_argument("--destination", type=Path, default=DESTINATION,
                        help="managed output directory (default: assets/material-heights)")
    parser.add_argument("--accept-source-change", action="store_true",
                        help="explicitly accept updated upstream content after reviewing its new API metadata")
    args = parser.parse_args(argv)
    prepare(args.cache, args.destination, accept_source_change=args.accept_source_change)


if __name__ == "__main__":
    main()
