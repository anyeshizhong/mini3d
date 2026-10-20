"""LAB-02B-Q height atlases and isolated GLSL 3.30 sampling.

The original MaterialMaps, assets and LAB-02B shader stay reproducible. Height
data is linear; only RGB is sRGB-decoded. This module consumes prepared CC0
inputs offline and never changes Terrain Heightmap or authoritative weights.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from material_maps import MaterialMaps, _shader_helpers, _glsl_float

HEIGHT_ROOT = Path(__file__).resolve().parent / 'assets/material-heights'


class QualityMaps(MaterialMaps):
    def __init__(self, height_dir=None):
        super().__init__()
        folder = Path(height_dir) if height_dir is not None else HEIGHT_ROOT
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('license') != 'CC0-1.0':
            raise ValueError('height manifest must identify CC0-1.0')
        self.height_manifest = manifest
        self.height_levels = []
        # All sources are normalized by their encoding range, never image min/max.
        for index, (layer, asset) in enumerate(zip(('soil', 'rock', 'grass'),
                                                  ('brown_mud_02', 'rock_face', 'leafy_grass'))):
            path = folder / (layer + '.png')
            record = manifest['maps'][layer + '.png']
            if record.get('asset_id') != asset or record.get('tile_metres') != self.tile_metres[index]:
                raise ValueError('height asset/scale must match original PBR set: ' + layer)
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != record['bundled_sha256']:
                raise ValueError('height SHA256 mismatch: ' + layer)
            if payload[:8] != b'\x89PNG\r\n\x1a\n' or payload[24:26] != bytes((16, 0)):
                raise ValueError('height must encode grayscale PNG16')
            with Image.open(path) as image:
                if image.size != (256, 256) or image.mode not in ('I', 'I;16', 'I;16B'):
                    raise ValueError('height must be 256x256 grayscale 16-bit PNG')
                values = np.asarray(image, dtype=np.float64) / 65535.
            if not np.isfinite(values).all() or values.min() < 0. or values.max() > 1.:
                raise ValueError('invalid material height range')
            levels = [values]
            for _ in range(8):
                d = levels[-1].shape[0] // 2
                levels.append(levels[-1].reshape(d, 2, d, 2).mean(axis=(1, 3)))
            self.height_levels.append(levels)

    def atlas_maps(self):
        result = super().atlas_maps()
        for layer, levels in enumerate(self.height_levels):
            for level, height in enumerate(levels):
                d = 256 >> level
                row = 512 - 2 * d
                result['baseColor'][row:row+d, layer*256:layer*256+d, 3] = np.rint(height*255.).astype(np.uint8)
        return result


def quality_shader(layered_source, *, method='depth', strength=.8, width=.2, sharpness=8.):
    """Patch an already LAB-02B-layered Bundle copy, fail on source drift.

    Height-weight equations are the three-layer adaptations in quality_blend;
    sourcing/modification records and full MIT notices are in QUALITY-SOURCES.md.
    Samples are collected once for all PBR channels. A_control uses this exact
    sampling path with strength zero, to separate refactoring from blend cost.
    """
    from quality_blend import blend_weights
    blend_weights(np.array([1., 0., 0.]), np.array([.5, .5, .5]),
                  method=method, strength=strength, width=width, sharpness=sharpness)
    if not 1.e-4 <= float(width) <= 2. or not 0. <= float(sharpness) <= 64.:
        raise ValueError('GLSL width must be [1e-4, 2] and sharpness [0, 64]')
    maps = MaterialMaps()
    original = _shader_helpers('layered', maps.origin, maps.size, maps.tile_metres)
    if layered_source.count(original) != 1 or layered_source.count('void main() {') != 1:
        raise ValueError('LAB-02B shader source changed; quality patch refused')
    sampling = original[:original.index('vec3 labBaseColor()')]
    sampling += r'''
vec4 qSampleBase(float tileMetres, int layer, float lod) {
    vec4 a = textureLod(baseMap, labAtlasUV(tileMetres, layer, floor(lod)), 0.0);
    vec4 b = textureLod(baseMap, labAtlasUV(tileMetres, layer, ceil(lod)), 0.0);
    a.rgb = linearize(a.rgb); b.rgb = linearize(b.rgb);
    return mix(a, b, fract(lod));
}
vec3 qSampleData(sampler2D image, float tileMetres, int layer, float lod) {
    vec3 a = textureLod(image, labAtlasUV(tileMetres, layer, floor(lod)), 0.0).rgb;
    vec3 b = textureLod(image, labAtlasUV(tileMetres, layer, ceil(lod)), 0.0).rgb;
    return mix(a, b, fract(lod));
}
vec3 qBlend(vec3 p, vec3 h) {
    vec3 score = p + h;
    vec3 q;
'''
    if method == 'depth':
        sampling += '''
    // HTerrain-style near-zero suppression: a tiny high third layer must not
    // dominate max(score) and abruptly replace an existing two-layer blend.
    score *= smoothstep(vec3(0.0), vec3(0.05), p);
    vec3 activeScore = mix(vec3(-1e20), score, greaterThan(p, vec3(0.0)));
    float highest = max(activeScore.x, max(activeScore.y, activeScore.z));
    q = max(score - vec3(highest) + vec3(%s), vec3(0.0)) * p;
''' % _glsl_float(width)
    else:
        sampling += '''
    // Log-domain normalization avoids overflow at high sharpness.
    vec3 logs = %s * log(max(score, vec3(1e-30))) + log(max(p, vec3(1e-30)));
    logs = mix(vec3(-1e20), logs, greaterThan(p, vec3(0.0)));
    q = exp(logs - vec3(max(logs.x, max(logs.y, logs.z)))) * step(vec3(1e-30), p);
''' % _glsl_float(sharpness)
    sampling += '''
    float total = dot(q, vec3(1.0));
    q = total > 1e-20 ? q / total : p;
    return mix(p, q, %s);
}
''' % _glsl_float(strength)
    sampling += r'''
vec3 qColor;
vec3 qNormal;
float qRough;
vec3 qEffective;
void qPrepare() {
    vec3 p = labWeights();
    vec3 h;
    vec3 colors[3];
    vec3 normals[3];
    float roughnesses[3];
    for (int i = 0; i < 3; ++i) {
        // Derivatives must be evaluated before non-uniform layer culling.
        // Atlas GL storage has only level zero; explicit LOD avoids implicit
        // derivatives inside the branch, while manual prefilter LOD is retained.
        float lod = labLayerLOD(LAB_TILE_METRES[i]);
        colors[i] = vec3(0.0); normals[i] = vec3(0.0);
        roughnesses[i] = 0.0; h[i] = 0.0;
        if (p[i] > 0.0) {
            vec4 colorHeight = qSampleBase(LAB_TILE_METRES[i], i, lod);
            colors[i] = colorHeight.rgb;
            h[i] = colorHeight.a;
            normals[i] = qSampleData(normalMap, LAB_TILE_METRES[i], i, lod) * 2.0 - 1.0;
            roughnesses[i] = qSampleData(mrMap, LAB_TILE_METRES[i], i, lod).g;
        }
    }
    qEffective = qBlend(p, h);
    qColor = vec3(0.0); qNormal = vec3(0.0); qRough = 0.0;
    for (int i = 0; i < 3; ++i) {
        qColor += colors[i] * qEffective[i];
        qNormal += normals[i] * qEffective[i];
        qRough += roughnesses[i] * qEffective[i];
    }
    float magnitude = length(qNormal);
    qNormal = magnitude > 1e-8 ? qNormal / magnitude : vec3(0.0, 0.0, 1.0);
}
vec3 labBaseColor() { return qColor; }
vec3 labNormal() { return qNormal; }
float labRoughness() { return qRough; }
'''
    result = layered_source.replace(original, sampling, 1)
    return result.replace('void main() {', 'void main() {\n    if (hasAO) qPrepare();', 1)
