"""Float64 reference functions for three-layer material height blending.

``blend_weights`` treats the authored layer weights as the authority and
returns a separate, normalized shader-weight candidate.  It provides two
order-independent adaptations for a three-material blend:

* ``depth`` uses a positive residual around the strongest active
  ``height + weight`` score.
* ``power`` uses a log-domain softmax of ``weight * (weight + height) **
  sharpness``.

Both candidates retain a zero authored layer at exactly zero.  ``strength``
interpolates between the normalized authored weights and the candidate.  An
all-zero authored triple uses layer zero (soil) as the explicit fallback.

Adaptation and license notes:

The mathematical ideas were checked against Zylann's Godot HeightMap Terrain
at commit ``7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3``, especially
``captures/upstream-quality-audit/godot_heightmap_plugin/addons/zylann.hterrain/shaders/simple4.gdshader`` (``get_depth_blended_weights`` and ``depth_blend2``),
and Terrain3D at commit ``59bacc5e61aede7d0fd96ae9cd263f4cc0f09858`` in
``captures/upstream-quality-audit/terrain3d-59bacc5/src/shaders/main.glsl``
(``accumulate_material``) and
``captures/upstream-quality-audit/terrain3d-59bacc5/project/addons/terrain_3d/
extras/shaders/lightweight.gdshader``.  The inspected upstream sources carry
MIT licenses; the captured notices are in
``captures/upstream-quality-audit/godot_heightmap_plugin/LICENSE.md`` (Marc
Gilleron, 2016–2020) and
``captures/upstream-quality-audit/terrain3d-59bacc5/LICENSE.txt`` (Cory
Petkovsek, Roope Palmroos, and contributors, 2023–2026).  This NumPy
implementation is independently written: it does not
copy shader code, assumes no Godot runtime, and replaces upstream layer/ID
paths with a symmetric three-weight operation, explicit zero-layer handling,
and a strength mix that leaves authored weights untouched.  It is a CPU
reference for testing the math, not a visual or performance conclusion.

The candidate formulas can be aggressive.  In particular, equal heights do
not make ``depth`` an identity: ``height + weight`` still favors larger
authored weights, and ``width`` controls how quickly lower scores disappear.
"""

import numpy as np


_SOIL_FALLBACK = np.array((1.0, 0.0, 0.0), dtype=np.float64)
_LOG_EPSILON = np.finfo(np.float64).tiny


def _float64_array(values, name):
    """Return a numeric float64 view/copy after rejecting non-real dtypes."""
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be a real numeric array" % name) from exc
    if raw.dtype.kind not in "fiu":
        raise ValueError("%s must be a real numeric array (not bool)" % name)
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.asarray(raw, dtype=np.float64)
    if not np.all(np.isfinite(result)):
        raise ValueError("%s must contain only finite values representable as float64" % name)
    return result


def _scalar_parameter(value, name, lower, upper=None, *, lower_open=False):
    """Validate a finite real scalar, rejecting booleans explicitly."""
    try:
        raw = np.asarray(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be a finite real scalar" % name) from exc
    if raw.ndim != 0 or raw.dtype.kind not in "fiu":
        raise ValueError("%s must be a finite real scalar (not bool)" % name)
    with np.errstate(over="ignore", invalid="ignore"):
        result = float(raw)
    if not np.isfinite(result):
        raise ValueError("%s must be finite" % name)
    if (result <= lower if lower_open else result < lower):
        operator = "greater than" if lower_open else "at least"
        raise ValueError("%s must be %s %s" % (name, operator, lower))
    if upper is not None and result > upper:
        raise ValueError("%s must be at most %s" % (name, upper))
    return result


def _normalized_weights(weights):
    """Normalize each triple without overflowing its sum; soil fills zeros."""
    largest = np.max(weights, axis=-1, keepdims=True)
    nonzero = largest > 0.0
    scaled = np.divide(weights, largest, out=np.zeros_like(weights), where=nonzero)
    total = np.sum(scaled, axis=-1, keepdims=True)
    normalized = np.divide(scaled, total, out=np.zeros_like(scaled), where=nonzero)
    return np.where(nonzero, normalized, _SOIL_FALLBACK)


def _depth_candidate(weights, heights, width):
    """Compute the scaled positive-residual three-layer depth candidate."""
    active = weights > 0.0
    scores = weights + heights
    max_active_score = np.max(np.where(active, scores, -np.inf), axis=-1, keepdims=True)

    # Divide residuals by width before normalization.  The common scale
    # cancels, while the strongest active layer keeps a positive residual even
    # for subnormal widths.
    score_delta = np.where(active, scores - max_active_score, -width)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        residual_factor = np.maximum(score_delta / width + 1.0, 0.0)
    residual = residual_factor * weights
    total = np.sum(residual, axis=-1, keepdims=True)
    return residual / total


def _power_candidate(weights, heights, sharpness):
    """Compute power-law reweighting with a stable log-domain softmax."""
    if sharpness == 0.0:
        return weights

    active = weights > 0.0
    log_base = np.log(np.maximum(weights + heights, _LOG_EPSILON))
    max_active_log_base = np.max(np.where(active, log_base, -np.inf),
                                 axis=-1, keepdims=True)

    # Subtract the largest active base log before multiplying by sharpness.
    # This removes a common softmax offset and avoids positive overflow.
    centered_log_base = np.where(active, log_base - max_active_log_base, 0.0)
    safe_weights = np.where(active, weights, 1.0)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        log_scores = sharpness * centered_log_base + np.log(safe_weights)
    log_scores = np.where(active, log_scores, -np.inf)
    log_scores -= np.max(log_scores, axis=-1, keepdims=True)
    exponentials = np.exp(log_scores)
    return exponentials / np.sum(exponentials, axis=-1, keepdims=True)


def blend_weights(weights, heights, *, method="depth", strength=1.0,
                  width=0.2, sharpness=8.0):
    """Return normalized shader weights for three authored material layers.

    Args:
        weights: Real finite non-negative values with shape ``(..., 3)``.
            Each triple is normalized internally.  An all-zero triple falls
            back to soil, layer zero.
        heights: Real finite values in ``[0, 1]`` with a broadcast-compatible
            shape ending in ``3``.  Heights are linear, relative material
            heights, not terrain elevation or metric displacement.
        method: ``"depth"`` or ``"power"``.
        strength: Blend from normalized authored weights (0) to the selected
            candidate (1), constrained to ``[0, 1]``.
        width: Positive finite residual width for ``depth``.  The score
            ``weight + height`` is in ``[0, 2]``; larger widths progressively
            approach the authored blend.
        sharpness: Non-negative exponent for ``power``.  Finite values are
            accepted; zero makes the candidate equal to normalized weights.

    Returns:
        A float64 array with the broadcast shape of ``weights`` and
        ``heights``.  The input arrays are only read and are never modified.

    ``depth`` computes ``score = normalized_weight + height`` over active
    layers, then ``q_i = p_i * max((score_i - max_active_score) / width + 1,
    0)`` and normalizes ``q``.  Dividing each residual by the common width
    before normalization is algebraically equivalent to the unscaled positive
    residual and improves subnormal-width stability.

    ``power`` computes a stable softmax equivalent to
    ``sharpness * log(max(p + height, eps)) + log(p)``.  Scores are centered
    before exponentiation.  Both methods multiply by ``p`` (or add ``log(p)``)
    so an authored zero-weight layer cannot appear from height alone.
    """
    if not isinstance(method, str) or method not in ("depth", "power"):
        raise ValueError("method must be 'depth' or 'power'")

    strength = _scalar_parameter(strength, "strength", 0.0, 1.0)
    width = _scalar_parameter(width, "width", 0.0, lower_open=True)
    sharpness = _scalar_parameter(sharpness, "sharpness", 0.0)

    weight_array = _float64_array(weights, "weights")
    height_array = _float64_array(heights, "heights")
    if weight_array.ndim == 0 or weight_array.shape[-1] != 3:
        raise ValueError("weights must have shape (..., 3)")
    if height_array.ndim == 0 or height_array.shape[-1] != 3:
        raise ValueError("heights must have shape (..., 3)")
    if np.any(weight_array < 0.0):
        raise ValueError("weights must be non-negative")
    if np.any((height_array < 0.0) | (height_array > 1.0)):
        raise ValueError("heights must be in [0, 1]")
    try:
        weight_array, height_array = np.broadcast_arrays(weight_array, height_array)
    except ValueError as exc:
        raise ValueError("weights and heights must have broadcast-compatible shapes") from exc

    authored = _normalized_weights(weight_array)
    if strength == 0.0:
        return authored

    if method == "depth":
        candidate = _depth_candidate(authored, height_array, width)
    else:
        candidate = _power_candidate(authored, height_array, sharpness)

    if strength == 1.0:
        return candidate
    return authored * (1.0 - strength) + candidate * strength
