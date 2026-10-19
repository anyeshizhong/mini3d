"""CPU material atlas construction and endpoint-preserving texture baking.

This module is experiment-local. It deliberately does not change Mini3D's
production material shader or exporter; :func:`shader_source` patches only a
copied Bundle fragment shader for the LAB-02B fixture.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
from pathlib import Path

import numpy as np
from PIL import Image


_LAYERS = ("soil", "rock", "grass")
_MAPS = ("diff.png", "nor_gl.png", "rough.png")
_SLOTS = ("baseColor", "normal", "metallicRoughness")
_DEFAULT_ORIGIN = (-18.0, -13.0)
_DEFAULT_SIZE = (36.0, 26.0)
_ASSET_ROOT = Path(__file__).resolve().parent / "assets" / "materials"


def _finite_pair(value, name):
    try:
        if len(value) != 2:
            raise ValueError
        pair = tuple(float(component) for component in value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must contain two finite numbers" % name) from exc
    if not all(math.isfinite(component) for component in pair):
        raise ValueError("%s must contain two finite numbers" % name)
    return pair


def _weights_array(values, *, normalized=False):
    try:
        weights = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("weights must be numeric") from exc
    if weights.ndim != 3 or weights.shape[2] != 3:
        raise ValueError("weights must have shape (rows, cols, 3)")
    if weights.shape[0] < 1 or weights.shape[1] < 1:
        raise ValueError("weights must have at least one row and column")
    if not np.isfinite(weights).all() or np.any(weights < 0.0):
        raise ValueError("weights must be finite and non-negative")
    if np.any(weights > 1.0 + 1.0e-7):
        raise ValueError("weights must be in the range [0, 1]")
    if normalized:
        totals = weights.sum(axis=2)
        if (not np.isfinite(totals).all() or np.any(totals <= 0.0) or
                np.any(np.abs(totals - 1.0) > 1.0e-5)):
            raise ValueError("each weight triple must sum to 1")
    return weights


def _quantized_weights(weights):
    """Round to the same RGBA8 values used by the layered GL texture."""
    quantized = np.rint(np.clip(weights, 0.0, 1.0) * 255.0).astype(np.uint8)
    totals = quantized.astype(np.uint16).sum(axis=2)
    empty = totals == 0
    if np.any(empty):
        quantized[empty] = (255, 0, 0)
        totals[empty] = 255
    normalized = quantized.astype(np.float64) / totals[..., None]
    return quantized, normalized


def weight_rgba(weights):
    """Return the three blend weights packed into mutable RGBA8 pixels.

    The alpha channel is always opaque. A triple that rounds entirely to zero
    falls back to soil, matching the shader's zero-total fallback.
    """
    source = _weights_array(weights)
    quantized, _ = _quantized_weights(source)
    result = np.empty(source.shape[:2] + (4,), dtype=np.uint8)
    result[..., :3] = quantized
    result[..., 3] = 255
    return result


def _integer(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("%s must be an integer" % name)
    try:
        return operator.index(value)
    except TypeError as exc:
        raise ValueError("%s must be an integer" % name) from exc


class MaterialMaps:
    """Load hash-checked soil, rock and grass maps and bake their blend.

    ``asset_dir`` is optional and primarily useful for isolated tests. The
    default resolves to the checked-in ``assets/materials`` directory.
    """

    def __init__(self, asset_dir=None, *, origin=_DEFAULT_ORIGIN,
                 size=_DEFAULT_SIZE):
        self.origin = _finite_pair(origin, "origin")
        self.size = _finite_pair(size, "size")
        if self.size[0] <= 0.0 or self.size[1] <= 0.0:
            raise ValueError("size components must be positive")
        if not all(math.isfinite(self.origin[i] + self.size[i]) for i in range(2)):
            raise ValueError("world-space endpoints must be finite")

        self.asset_dir = Path(asset_dir) if asset_dir is not None else _ASSET_ROOT
        manifest_path = self.asset_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("cannot read material manifest: %s" % manifest_path) from exc
        if manifest.get("license") != "CC0-1.0":
            raise ValueError("material manifest must identify CC0-1.0 assets")
        records = manifest.get("maps")
        if not isinstance(records, dict):
            raise ValueError("material manifest has no maps table")

        self.tile_metres = []
        self._source_maps = {name: [] for name in _MAPS}
        for layer in _LAYERS:
            layer_widths = []
            for map_name in _MAPS:
                relative = "%s/%s" % (layer, map_name)
                record = records.get(relative)
                if not isinstance(record, dict):
                    raise ValueError("material manifest is missing %s" % relative)
                try:
                    tile_width = float(record["tile_metres"])
                    expected_hash = str(record["bundled_sha256"]).lower()
                    expected_size = tuple(record["size"])
                    channels = record["channels"]
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("invalid manifest record for %s" % relative) from exc
                if not math.isfinite(tile_width) or tile_width <= 0.0:
                    raise ValueError("invalid tile_metres for %s" % relative)
                if expected_size != (256, 256) or channels != "RGB8":
                    raise ValueError("%s must be a 256x256 RGB8 map" % relative)
                if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
                    raise ValueError("invalid bundled SHA256 for %s" % relative)

                path = self.asset_dir / relative
                try:
                    payload = path.read_bytes()
                except OSError as exc:
                    raise ValueError("cannot read material map: %s" % path) from exc
                digest = hashlib.sha256(payload).hexdigest()
                if digest != expected_hash:
                    raise ValueError("bundled SHA256 mismatch for %s" % relative)
                try:
                    with Image.open(path) as image:
                        image.load()
                        if image.mode != "RGB" or image.size != (256, 256):
                            raise ValueError("%s must decode as 256x256 RGB" % relative)
                        pixels = np.asarray(image, dtype=np.uint8).copy()
                except (OSError, Image.DecompressionBombError) as exc:
                    raise ValueError("cannot decode material map: %s" % path) from exc
                self._source_maps[map_name].append(pixels)
                layer_widths.append(tile_width)
            if max(layer_widths) - min(layer_widths) > 1.0e-9:
                raise ValueError("tile_metres differs among %s maps" % layer)
            self.tile_metres.append(layer_widths[0])
        self.tile_metres = tuple(self.tile_metres)
        self._mip_maps = {name: [] for name in _MAPS}
        for name in _MAPS:
            for image in self._source_maps[name]:
                levels = [image]
                for _ in range(8):
                    pixels = levels[-1].astype(np.float64) / 255.0
                    if name == "diff.png":
                        pixels = self._linearize(pixels)
                    elif name == "nor_gl.png":
                        pixels = pixels * 2.0 - 1.0
                    dimension = pixels.shape[0] // 2
                    pixels = pixels.reshape(dimension, 2, dimension, 2, 3).mean(axis=(1, 3))
                    if name == "diff.png":
                        reduced = self._encode_srgb(pixels)
                    else:
                        if name == "nor_gl.png":
                            pixels /= np.maximum(np.linalg.norm(pixels, axis=2, keepdims=True), 1e-12)
                            pixels = pixels * 0.5 + 0.5
                        reduced = np.rint(pixels * 255.0).clip(0, 255).astype(np.uint8)
                    levels.append(reduced)
                self._mip_maps[name].append(levels)

    def atlas_maps(self):
        """Pack nine isolated prefiltered levels into one RGBA8 GL level.

        Each layer owns a 256px-wide column. Level sizes are 256..1 and
        their row offsets are 0,256,384,..510; shader sampling never enters
        the padding or a neighboring material. GL mip generation is unused.
        """
        result = {slot: np.zeros((511, 768, 4), dtype=np.uint8)
                  for slot in _SLOTS}
        for layer in range(3):
            x0 = layer * 256
            for level in range(9):
                dimension = 256 >> level
                row = 512 - 2 * dimension
                region = (slice(row, row + dimension), slice(x0, x0 + dimension))
                result["baseColor"][region + (slice(0, 3),)] = self._mip_maps["diff.png"][layer][level]
                result["normal"][region + (slice(0, 3),)] = self._mip_maps["nor_gl.png"][layer][level]
                result["metallicRoughness"][region + (0,)] = 255
                result["metallicRoughness"][region + (1,)] = self._mip_maps["rough.png"][layer][level][..., 0]
        for pixels in result.values():
            pixels[..., 3] = 255
        return result

    @staticmethod
    def _rect(rect, rows, cols):
        if rect is None:
            return (0, 0, rows, cols)
        try:
            if len(rect) != 4:
                raise ValueError
            r0, c0, r1, c1 = (_integer(value, "rect component") for value in rect)
        except (TypeError, ValueError) as exc:
            raise ValueError("rect must be four integer half-open bounds") from exc
        if r0 < 0 or c0 < 0 or r1 > rows or c1 > cols or r0 >= r1 or c0 >= c1:
            raise ValueError("rect must be a non-empty in-bounds half-open region")
        return r0, c0, r1, c1

    def _world_grid(self, rows, cols, rect):
        r0, c0, r1, c1 = rect
        if cols == 1:
            x = np.array([self.origin[0] + self.size[0] * 0.5])
        else:
            x = self.origin[0] + np.arange(c0, c1, dtype=np.float64) * (self.size[0] / (cols - 1))
        if rows == 1:
            y = np.array([self.origin[1] + self.size[1] * 0.5])
        else:
            y = self.origin[1] + np.arange(r0, r1, dtype=np.float64) * (self.size[1] / (rows - 1))
        return np.broadcast_arrays(x[None, :], y[:, None])

    @staticmethod
    def _sample_tile(image, world_x, world_y, tile_width):
        """Bilinearly sample a periodic tile without touching adjacent tiles."""
        maximum = image.shape[0] - 1
        x = np.mod(world_x / tile_width, 1.0) * maximum
        y = np.mod(world_y / tile_width, 1.0) * maximum
        x0 = np.floor(x).astype(np.intp)
        y0 = np.floor(y).astype(np.intp)
        x1 = np.minimum(x0 + 1, maximum)
        y1 = np.minimum(y0 + 1, maximum)
        tx = (x - x0)[..., None]
        ty = (y - y0)[..., None]
        p00 = image[y0, x0].astype(np.float64) / 255.0
        p10 = image[y0, x1].astype(np.float64) / 255.0
        p01 = image[y1, x0].astype(np.float64) / 255.0
        p11 = image[y1, x1].astype(np.float64) / 255.0
        top = p00 * (1.0 - tx) + p10 * tx
        bottom = p01 * (1.0 - tx) + p11 * tx
        return top * (1.0 - ty) + bottom * ty

    def _filtered_sample(self, name, layer, world_x, world_y, footprint):
        lod = np.clip(np.log2(max(footprint * 256.0 / self.tile_metres[layer], 1.0)), 0.0, 8.0)
        first, second = int(np.floor(lod)), int(np.ceil(lod))
        values = []
        for level in (first, second):
            value = self._sample_tile(self._mip_maps[name][layer][level], world_x, world_y,
                                      self.tile_metres[layer])
            if name == "diff.png":
                value = self._linearize(value)
            elif name == "nor_gl.png":
                value = value * 2.0 - 1.0
            values.append(value)
        return values[0] * (1.0 - (lod - first)) + values[1] * (lod - first)

    @staticmethod
    def _linearize(rgb):
        return np.where(rgb <= 0.04045, rgb / 12.92,
                        ((rgb + 0.055) / 1.055) ** 2.4)

    @staticmethod
    def _encode_srgb(rgb):
        rgb = np.clip(rgb, 0.0, 1.0)
        encoded = np.where(rgb <= 0.0031308, rgb * 12.92,
                           1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
        return np.rint(np.clip(encoded, 0.0, 1.0) * 255.0).astype(np.uint8)

    def bake(self, weights, rect=None):
        """Bake normalized NxMx3 weights into three RGBA8 texture maps.

        ``rect`` uses global ``(row0, col0, row1, col1)`` half-open sample
        coordinates. For a partial bake, the returned arrays contain only that
        crop, ready to splice into a cached full bake.
        """
        weights = _weights_array(weights, normalized=True)
        rows, cols = weights.shape[:2]
        bounds = self._rect(rect, rows, cols)
        r0, c0, r1, c1 = bounds
        quantized, normalized = _quantized_weights(weights[r0:r1, c0:c1])
        world_x, world_y = self._world_grid(rows, cols, bounds)
        shape = world_x.shape

        linear_color = np.zeros(shape + (3,), dtype=np.float64)
        normal_sum = np.zeros(shape + (3,), dtype=np.float64)
        roughness = np.zeros(shape, dtype=np.float64)
        footprint = max(self.size[0] / max(1, cols - 1), self.size[1] / max(1, rows - 1))
        for layer, tile_width in enumerate(self.tile_metres):
            layer_weight = normalized[..., layer, None]
            color = self._filtered_sample("diff.png", layer, world_x, world_y, footprint)
            normal = self._filtered_sample("nor_gl.png", layer, world_x, world_y, footprint)
            rough = self._filtered_sample("rough.png", layer, world_x, world_y, footprint)[..., 0]
            linear_color += color * layer_weight
            normal_sum += normal * layer_weight
            roughness += rough * normalized[..., layer]

        normal_length = np.linalg.norm(normal_sum, axis=2, keepdims=True)
        flat_normal = np.zeros_like(normal_sum)
        flat_normal[..., 2] = 1.0
        normal_value = np.where(normal_length > 1.0e-12,
                                normal_sum / np.maximum(normal_length, 1.0e-12),
                                flat_normal)

        base = np.empty(shape + (4,), dtype=np.uint8)
        base[..., :3] = self._encode_srgb(linear_color)
        base[..., 3] = 255
        normal_map = np.empty(shape + (4,), dtype=np.uint8)
        normal_map[..., :3] = np.rint(np.clip(normal_value * 0.5 + 0.5,
                                              0.0, 1.0) * 255.0).astype(np.uint8)
        normal_map[..., 3] = 255
        mr = np.empty(shape + (4,), dtype=np.uint8)
        mr[..., 0] = 255
        mr[..., 1] = np.rint(np.clip(roughness, 0.0, 1.0) * 255.0).astype(np.uint8)
        mr[..., 2] = 0
        mr[..., 3] = 255
        return {"baseColor": base, "normal": normal_map,
                "metallicRoughness": mr}


def _glsl_float(value):
    result = "%.9g" % float(value)
    if "." not in result and "e" not in result.lower():
        result += ".0"
    return result


def _shader_helpers(scheme, origin, size, tile_metres):
    origin_text = ", ".join(_glsl_float(value) for value in origin)
    size_text = ", ".join(_glsl_float(value) for value in size)
    if scheme == "layered":
        tile_constants = ", ".join(_glsl_float(value) for value in tile_metres)
        return """
const vec2 LAB_MATERIAL_ORIGIN = vec2(%s);
const vec2 LAB_MATERIAL_SIZE = vec2(%s);
const float LAB_TILE_METRES[3] = float[3](%s);
vec2 labWeightUV() {
    ivec2 dimensions = textureSize(aoMap, 0);
    vec2 coordinate = clamp((worldPosition.xy - LAB_MATERIAL_ORIGIN) /
                            LAB_MATERIAL_SIZE, vec2(0.0), vec2(1.0));
    return (coordinate * vec2(dimensions - ivec2(1)) + vec2(0.5)) /
           vec2(dimensions);
}
vec3 labWeights() {
    vec3 weights = texture(aoMap, labWeightUV()).rgb;
    float total = dot(weights, vec3(1.0));
    return total > 1e-8 ? weights / total : vec3(1.0, 0.0, 0.0);
}
float labLayerLOD(float tileMetres) {
    vec2 coordinate = worldPosition.xy / tileMetres;
    float footprint = max(length(dFdx(coordinate)), length(dFdy(coordinate))) * 256.0;
    return clamp(log2(max(footprint, 1.0)), 0.0, 8.0);
}
vec2 labAtlasUV(float tileMetres, int layer, float level) {
    float dimension = exp2(8.0 - level);
    return (fract(worldPosition.xy / tileMetres) * (dimension - 1.0) + vec2(0.5) +
            vec2(float(layer * 256), 512.0 - 2.0 * dimension)) / vec2(768.0, 511.0);
}
vec3 labSample(sampler2D image, float tileMetres, int layer, bool colorData) {
    float lod = labLayerLOD(tileMetres);
    vec3 first = texture(image, labAtlasUV(tileMetres, layer, floor(lod))).rgb;
    vec3 second = texture(image, labAtlasUV(tileMetres, layer, ceil(lod))).rgb;
    if (colorData) {
        first = linearize(first);
        second = linearize(second);
    }
    return mix(first, second, fract(lod));
}
vec3 labBaseColor() {
    vec3 weights = labWeights();
    vec3 color = vec3(0.0);
    for (int layer = 0; layer < 3; ++layer) {
        color += labSample(baseMap, LAB_TILE_METRES[layer], layer, true) * weights[layer];
    }
    return color;
}
vec3 labNormal() {
    vec3 weights = labWeights();
    vec3 value = vec3(0.0);
    for (int layer = 0; layer < 3; ++layer) {
        value += (labSample(normalMap, LAB_TILE_METRES[layer], layer, false) * 2.0 - 1.0) *
            weights[layer];
    }
    float magnitude = length(value);
    return magnitude > 1e-8 ? value / magnitude : vec3(0.0, 0.0, 1.0);
}
float labRoughness() {
    vec3 weights = labWeights();
    float rough = 0.0;
    for (int layer = 0; layer < 3; ++layer) {
        rough += labSample(mrMap, LAB_TILE_METRES[layer], layer, false).g * weights[layer];
    }
    return rough;
}
""" % (origin_text, size_text, tile_constants)

    return """
const vec2 LAB_MATERIAL_ORIGIN = vec2(%s);
const vec2 LAB_MATERIAL_SIZE = vec2(%s);
vec2 labBaseUV() {
    ivec2 dimensions = textureSize(baseMap, 0);
    vec2 coordinate = clamp((worldPosition.xy - LAB_MATERIAL_ORIGIN) /
                            LAB_MATERIAL_SIZE, vec2(0.0), vec2(1.0));
    return (coordinate * vec2(dimensions - ivec2(1)) + vec2(0.5)) /
           vec2(dimensions);
}
vec2 labNormalUV() {
    ivec2 dimensions = textureSize(normalMap, 0);
    vec2 coordinate = clamp((worldPosition.xy - LAB_MATERIAL_ORIGIN) /
                            LAB_MATERIAL_SIZE, vec2(0.0), vec2(1.0));
    return (coordinate * vec2(dimensions - ivec2(1)) + vec2(0.5)) /
           vec2(dimensions);
}
vec2 labMRUV() {
    ivec2 dimensions = textureSize(mrMap, 0);
    vec2 coordinate = clamp((worldPosition.xy - LAB_MATERIAL_ORIGIN) /
                            LAB_MATERIAL_SIZE, vec2(0.0), vec2(1.0));
    return (coordinate * vec2(dimensions - ivec2(1)) + vec2(0.5)) /
           vec2(dimensions);
}
vec3 labBaseColor() { return linearize(texture(baseMap, labBaseUV()).rgb); }
vec3 labNormal() { return texture(normalMap, labNormalUV()).xyz * 2.0 - 1.0; }
float labRoughness() { return texture(mrMap, labMRUV()).g; }
""" % (origin_text, size_text)


def shader_source(source, scheme, origin=_DEFAULT_ORIGIN, size=_DEFAULT_SIZE):
    """Return an experiment-only shader patched for ``layered`` or ``baked``.

    Every source replacement is guarded by an exact occurrence count. If the
    upstream Bundle shader changes shape, this fails loudly instead of leaving
    a partially patched shader behind.
    """
    if not isinstance(source, str):
        raise TypeError("source must be shader text")
    if scheme not in ("layered", "baked"):
        raise ValueError("scheme must be 'layered' or 'baked'")
    origin = _finite_pair(origin, "origin")
    size = _finite_pair(size, "size")
    if size[0] <= 0.0 or size[1] <= 0.0:
        raise ValueError("size components must be positive")
    if not all(math.isfinite(origin[i] + size[i]) for i in range(2)):
        raise ValueError("world-space endpoints must be finite")
    tile_metres = MaterialMaps().tile_metres

    def replace_once(text, old, new, label):
        count = text.count(old)
        if count != 1:
            raise ValueError("expected exactly one %s source fragment; found %d" %
                             (label, count))
        return text.replace(old, new, 1)

    source = replace_once(source,
        "vec2 surfaceUV() { return photographicGround ? worldPosition.xy*groundScale : uv; }",
        "vec2 surfaceUV() {\n    return hasAO ? worldPosition.xy :\n           (photographicGround ? worldPosition.xy*groundScale : uv);\n}",
        "surfaceUV")
    anchor = "vec2 surfaceUV() {\n    return hasAO ? worldPosition.xy :\n           (photographicGround ? worldPosition.xy*groundScale : uv);\n}"
    source = replace_once(source, anchor,
                          _shader_helpers(scheme, origin, size, tile_metres) + anchor,
                          "material sampling helper insertion")
    source = replace_once(source,
        "vec3 mapNormal = texture(normalMap, surfaceUV()).xyz * 2.0 - 1.0;",
        "vec3 mapNormal = hasAO ? labNormal() :\n"
        "                     texture(normalMap, surfaceUV()).xyz * 2.0 - 1.0;",
        "normal map sample")
    source = replace_once(source,
        "        vec4 sampled = texture(baseMap, surfaceUV());\n"
        "        base *= vec4(linearize(sampled.rgb), sampled.a);",
        "        if (hasAO) {\n"
        "            base.rgb *= labBaseColor();\n"
        "        } else {\n"
        "            vec4 sampled = texture(baseMap, surfaceUV());\n"
        "            base *= vec4(linearize(sampled.rgb), sampled.a);\n"
        "        }",
        "base color sample")
    source = replace_once(source,
        "        vec4 mr = texture(mrMap,surfaceUV());\n"
        "        metal *= mr.b; rough *= mr.g;",
        "        if (hasAO) {\n"
        "            rough *= labRoughness();\n"
        "            metal = 0.0;\n"
        "        } else {\n"
        "            vec4 mr = texture(mrMap,surfaceUV());\n"
        "            metal *= mr.b; rough *= mr.g;\n"
        "        }",
        "metallic/roughness sample")
    source = replace_once(source,
        "    float ao = hasAO ? mix(1.0,texture(aoMap,surfaceUV()).r,aoStrength) : 1.0;",
        "    // In this fixture hasAO marks Terrain; aoMap stores layer weights, not AO.\n"
        "    float ao = 1.0;",
        "AO sample")
    return source
