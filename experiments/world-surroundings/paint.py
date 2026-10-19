"""CPU-only, replayable three-layer material paint strokes.

The experiment stores soil, rock and grass weights on a regular world-space
grid. Preview edits replace one immutable float32 weight snapshot; history
stores only the rectangular before/after weight diff for each committed stroke.
No heightfield, mesh, renderer or GPU resource is rebuilt here.
"""

from dataclasses import dataclass
import operator
from typing import Optional, Tuple

import numpy as np


Rect = Tuple[int, int, int, int]
_LAYER_NAMES = ("soil", "rock", "grass")
_LAYER_INDEX = {name: index for index, name in enumerate(_LAYER_NAMES)}
_DEFAULT_HISTORY_BUDGET = 64 * 1024 * 1024


def _finite_float(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be finite" % name) from exc
    if not np.isfinite(result):
        raise ValueError("%s must be finite" % name)
    return result


def _integer_at_least(value, name, minimum):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("%s must be an integer >= %d" % (name, minimum))
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError("%s must be an integer >= %d" % (name, minimum)) from exc
    if result < minimum:
        raise ValueError("%s must be an integer >= %d" % (name, minimum))
    return result


def _nonnegative_int(value, name):
    return _integer_at_least(value, name, 0)


def _pair_of_finite_floats(value, name):
    try:
        if len(value) != 2:
            raise ValueError
        return (_finite_float(value[0], name),
                _finite_float(value[1], name))
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("%s must contain two finite numbers" % name) from exc


def _immutable_copy(array):
    """Return a contiguous bytes-backed immutable array copy."""
    contiguous = np.ascontiguousarray(array)
    return np.frombuffer(contiguous.tobytes(), dtype=contiguous.dtype).reshape(
        contiguous.shape)


def _canonical_weights(values):
    """Normalize valid non-negative triples and round them to float32."""
    try:
        result = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("weights must be numeric") from exc
    if result.ndim != 3 or result.shape[-1] != 3:
        raise ValueError("weights must have shape (rows, cols, 3)")
    if not np.isfinite(result).all() or np.any(result < 0.0):
        raise ValueError("weights must be finite and non-negative")

    totals = result.sum(axis=2)
    if not np.isfinite(totals).all() or np.any(totals <= 0.0):
        raise ValueError("each weight triple must have a positive finite sum")
    normalized = result / totals[..., None]
    rounded = normalized.astype(np.float32)

    # Keep the float32 triples on the simplex after conversion. Correct the
    # largest channel by the tiny rounding residual to avoid negative values.
    largest = np.argmax(rounded, axis=2)
    for layer in range(3):
        mask = largest == layer
        other_layers = [index for index in range(3) if index != layer]
        residual = 1.0 - rounded[..., other_layers].astype(np.float64).sum(axis=2)
        if np.any(residual[mask] < 0.0):
            raise ValueError("weights cannot be represented as normalized float32")
        rounded[..., layer][mask] = residual[mask].astype(np.float32)
    return rounded


def _mask_rect(mask, row_offset=0, col_offset=0):
    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        return None
    return (int(row_offset + rows.min()), int(col_offset + cols.min()),
            int(row_offset + rows.max() + 1),
            int(col_offset + cols.max() + 1))


def _merge_rect(first, second):
    if first is None:
        return second
    if second is None:
        return first
    return (min(first[0], second[0]), min(first[1], second[1]),
            max(first[2], second[2]), max(first[3], second[3]))


def _difference_rect(first, second, within=None):
    if within is None:
        within = (0, 0, first.shape[0], first.shape[1])
    row_start, col_start, row_end, col_end = within
    changed = np.any(
        first[row_start:row_end, col_start:col_end] !=
        second[row_start:row_end, col_start:col_end], axis=2)
    return _mask_rect(changed, row_start, col_start)


@dataclass(frozen=True)
class PaintPatch:
    """One committed gesture's rectangular weight diff.

    ``dirty_rect`` is ``(row_start, col_start, row_end, col_end)`` in sample
    indices, with half-open ends. ``layer`` is soil=0, rock=1, or grass=2;
    ``mode`` is ``paint`` or ``erase``. The arrays have shape
    ``(rect_rows, rect_cols, 3)`` and are immutable float32 snapshots.
    """

    mode: str
    layer: int
    dirty_rect: Rect
    before: np.ndarray
    after: np.ndarray

    @property
    def byte_size(self):
        """Bytes used by the two stored float32 region arrays."""
        return int(self.before.nbytes + self.after.nbytes)

    @property
    def rect(self):
        """Short alias for :attr:`dirty_rect`."""
        return self.dirty_rect

    @property
    def layer_name(self):
        return _LAYER_NAMES[self.layer]


class HistoryBudgetExceeded(RuntimeError):
    """A gesture was rolled back because its region diff exceeds the budget."""

    def __init__(self, required_bytes, budget_bytes, dirty_rect,
                 patch_bytes=None):
        self.required_bytes = int(required_bytes)
        self.budget_bytes = int(budget_bytes)
        self.dirty_rect = dirty_rect
        self.patch_bytes = int(required_bytes if patch_bytes is None else patch_bytes)
        super().__init__(
            "paint history would use %d bytes, exceeding the %d-byte budget" %
            (self.required_bytes, self.budget_bytes))


PaintHistoryBudgetExceeded = HistoryBudgetExceeded


@dataclass
class _Stroke:
    layer: int
    radius: float
    strength: float
    erase: bool
    start_weights: np.ndarray
    dirty_rect: Optional[Rect] = None


class PaintSession:
    """Manage CPU previews and region-diff history for material paint.

    Sample axes include both world-space endpoints. The circular brush uses a
    smoothstep falloff that reaches zero at ``radius``. ``dab``'s ``amount``
    is elapsed time in seconds, and applies ``1 - exp(-strength * amount *
    falloff)`` to each covered sample.
    """

    def __init__(self, rows=257, cols=257, origin=(-18, -13), size=(36, 26),
                 history_budget_bytes=_DEFAULT_HISTORY_BUDGET, *, weights=None):
        self._rows = _integer_at_least(rows, "rows", 2)
        self._cols = _integer_at_least(cols, "cols", 2)
        self._origin = _pair_of_finite_floats(origin, "origin")
        self._size = _pair_of_finite_floats(size, "size")
        if self._size[0] <= 0.0 or self._size[1] <= 0.0:
            raise ValueError("size components must be positive")
        endpoints = (self._origin[0] + self._size[0],
                     self._origin[1] + self._size[1])
        if not all(np.isfinite(value) for value in endpoints):
            raise ValueError("world-space endpoints must be finite")

        self._history_budget_bytes = _nonnegative_int(
            history_budget_bytes, "history_budget_bytes")
        self._x_axis = np.linspace(self._origin[0], endpoints[0], self._cols,
                                   dtype=np.float64)
        self._y_axis = np.linspace(self._origin[1], endpoints[1], self._rows,
                                   dtype=np.float64)

        if weights is None:
            initial = np.zeros((self._rows, self._cols, 3), dtype=np.float32)
            initial[..., 0] = 1.0
        else:
            try:
                initial = np.asarray(weights, dtype=np.float64)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("weights must be numeric") from exc
            if initial.shape != (self._rows, self._cols, 3):
                raise ValueError("weights must have shape (rows, cols, 3)")
            if not np.isfinite(initial).all() or np.any(initial < 0.0):
                raise ValueError("weights must be finite and non-negative")
            totals = initial.sum(axis=2)
            # Accept only float conversion noise; reject visibly unnormalized
            # input instead of silently changing user-supplied data.
            if (not np.isfinite(totals).all() or np.any(totals <= 0.0) or
                    np.any(np.abs(totals - 1.0) > 1.0e-5)):
                raise ValueError("each initial weight triple must sum to 1")
            initial = _canonical_weights(initial)

        self._weights = _immutable_copy(initial)
        self._revision = 0
        self._stroke = None
        self._undo = []
        self._redo = []

    @property
    def weights(self):
        """The current immutable preview or committed float32 weight grid."""
        return self._weights

    @property
    def rows(self):
        return self._rows

    @property
    def cols(self):
        return self._cols

    @property
    def origin(self):
        return self._origin

    @property
    def size(self):
        return self._size

    @property
    def x_axis(self):
        return _immutable_copy(self._x_axis)

    @property
    def y_axis(self):
        return _immutable_copy(self._y_axis)

    @property
    def revision(self):
        """Monotonic revision, incremented whenever the weight grid changes."""
        return self._revision

    @property
    def current_revision(self):
        return self._revision

    @property
    def active(self):
        return self._stroke is not None

    @property
    def history_budget_bytes(self):
        return self._history_budget_bytes

    @property
    def history_bytes(self):
        """Region-array bytes held by both undo and redo entries."""
        return int(sum(patch.byte_size for patch in self._undo + self._redo))

    @property
    def undo_count(self):
        return len(self._undo)

    @property
    def redo_count(self):
        return len(self._redo)

    @property
    def can_undo(self):
        return bool(self._undo) and not self.active

    @property
    def can_redo(self):
        return bool(self._redo) and not self.active

    @staticmethod
    def _layer_index(layer):
        if isinstance(layer, str):
            normalized = layer.strip().lower()
            if normalized in _LAYER_INDEX:
                return _LAYER_INDEX[normalized]
            raise ValueError("layer must be soil, rock, grass, 0, 1 or 2")
        if isinstance(layer, (bool, np.bool_)):
            raise ValueError("layer must be soil, rock, grass, 0, 1 or 2")
        try:
            result = operator.index(layer)
        except TypeError as exc:
            raise ValueError("layer must be soil, rock, grass, 0, 1 or 2") from exc
        if result not in (0, 1, 2):
            raise ValueError("layer must be soil, rock, grass, 0, 1 or 2")
        return result

    def begin_stroke(self, layer, radius, strength, erase=False):
        """Start one paint or erase gesture; invalid input is atomic."""
        if self.active:
            raise RuntimeError("a paint stroke is already active")
        layer_index = self._layer_index(layer)
        radius = _finite_float(radius, "radius")
        strength = _finite_float(strength, "strength")
        if radius <= 0.0:
            raise ValueError("radius must be positive")
        if strength < 0.0:
            raise ValueError("strength must be non-negative")
        if not isinstance(erase, (bool, np.bool_)):
            raise ValueError("erase must be a boolean")

        self._stroke = _Stroke(layer_index, radius, strength, bool(erase),
                               self._weights)

    def _candidate_window(self, x, y, radius):
        """Return sample window and smoothstep circle weights for a dab."""
        if (x < self._x_axis[0] or x > self._x_axis[-1] or
                y < self._y_axis[0] or y > self._y_axis[-1]):
            return None

        with np.errstate(over="ignore", invalid="ignore"):
            col_start = int(np.searchsorted(self._x_axis, x - radius,
                                            side="left"))
            col_end = int(np.searchsorted(self._x_axis, x + radius,
                                          side="right"))
            row_start = int(np.searchsorted(self._y_axis, y - radius,
                                            side="left"))
            row_end = int(np.searchsorted(self._y_axis, y + radius,
                                          side="right"))
        col_start = max(0, min(self._cols, col_start))
        col_end = max(0, min(self._cols, col_end))
        row_start = max(0, min(self._rows, row_start))
        row_end = max(0, min(self._rows, row_end))
        if row_start >= row_end or col_start >= col_end:
            return None

        dx = self._x_axis[col_start:col_end] - x
        dy = self._y_axis[row_start:row_end] - y
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            distance = np.hypot(dy[:, None], dx[None, :])
            t = np.clip(1.0 - distance / radius, 0.0, 1.0)
            falloff = t * t * (3.0 - 2.0 * t)
        if not np.any(falloff > 0.0):
            return None
        return (row_start, col_start, row_end, col_end, falloff)

    @staticmethod
    def _apply_weights(old_region, layer, alpha, erase):
        source = old_region.astype(np.float64)
        result = source.copy()
        old_target = source[..., layer]
        if not erase:
            result[..., layer] = old_target + alpha * (1.0 - old_target)
            for other in range(3):
                if other != layer:
                    result[..., other] = source[..., other] * (1.0 - alpha)
            return result

        target_after = old_target * (1.0 - alpha)
        released = old_target - target_after
        other_layers = [index for index in range(3) if index != layer]
        old_others = source[..., other_layers]
        other_total = old_others.sum(axis=2)
        denominator = np.where(other_total > 0.0, other_total, 1.0)
        shares = old_others / denominator[..., None]
        shares = np.where((other_total > 0.0)[..., None], shares, 0.5)
        new_others = old_others + released[..., None] * shares
        result[..., layer] = target_after
        result[..., other_layers] = new_others
        return result

    def dab(self, x, y, amount=1.0):
        """Apply one timed dab and return its changed half-open sample rect."""
        if not self.active:
            raise RuntimeError("begin_stroke must be called before dab")
        x = _finite_float(x, "x")
        y = _finite_float(y, "y")
        amount = _finite_float(amount, "amount")
        if amount < 0.0:
            raise ValueError("amount must be non-negative")
        if amount == 0.0:
            return None

        stroke = self._stroke
        if stroke.strength == 0.0:
            return None
        window = self._candidate_window(x, y, stroke.radius)
        if window is None:
            return None
        row_start, col_start, row_end, col_end, falloff = window
        old_region = self._weights[row_start:row_end, col_start:col_end]
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            dose = stroke.strength * amount * falloff
            alpha = -np.expm1(-dose)
        updated = self._apply_weights(old_region, stroke.layer, alpha,
                                      stroke.erase)
        if not np.isfinite(updated).all() or np.any(updated < 0.0):
            raise ValueError("dab would produce invalid material weights")
        updated = _canonical_weights(updated)

        changed_mask = np.any(updated != old_region, axis=2)
        changed_rect = _mask_rect(changed_mask, row_start, col_start)
        if changed_rect is None:
            return None

        candidate = self._weights.copy()
        candidate[row_start:row_end, col_start:col_end] = updated
        self._weights = _immutable_copy(candidate)
        self._revision += 1
        stroke.dirty_rect = _merge_rect(stroke.dirty_rect, changed_rect)
        return changed_rect

    def _make_patch(self, stroke):
        if stroke.dirty_rect is None:
            return None
        rect = _difference_rect(stroke.start_weights, self._weights,
                                stroke.dirty_rect)
        if rect is None:
            return None
        row_start, col_start, row_end, col_end = rect
        before = _immutable_copy(
            stroke.start_weights[row_start:row_end, col_start:col_end])
        after = _immutable_copy(
            self._weights[row_start:row_end, col_start:col_end])
        return PaintPatch("erase" if stroke.erase else "paint", stroke.layer,
                          rect, before, after)

    def _rollback_stroke(self, stroke):
        dirty_rect = _difference_rect(stroke.start_weights, self._weights,
                                      stroke.dirty_rect)
        had_preview = self._weights is not stroke.start_weights
        self._weights = stroke.start_weights
        self._stroke = None
        if had_preview:
            self._revision += 1
        return dirty_rect

    def end_stroke(self):
        """Commit a gesture as one region patch, or return ``None`` on no-op."""
        if not self.active:
            raise RuntimeError("there is no active paint stroke")
        stroke = self._stroke
        patch = self._make_patch(stroke)
        if patch is None:
            self._stroke = None
            return None

        undo_bytes = sum(item.byte_size for item in self._undo)
        projected_bytes = undo_bytes + patch.byte_size
        if projected_bytes > self._history_budget_bytes:
            dirty_rect = self._rollback_stroke(stroke)
            raise HistoryBudgetExceeded(projected_bytes,
                                        self._history_budget_bytes,
                                        dirty_rect,
                                        patch_bytes=patch.byte_size)

        self._redo.clear()
        self._undo.append(patch)
        self._stroke = None
        return patch

    def cancel_stroke(self):
        """Discard a gesture and return samples changed by the rollback."""
        if not self.active:
            raise RuntimeError("there is no active paint stroke")
        return self._rollback_stroke(self._stroke)

    def _apply_patch(self, patch, values):
        row_start, col_start, row_end, col_end = patch.dirty_rect
        candidate = self._weights.copy()
        candidate[row_start:row_end, col_start:col_end] = values
        return _immutable_copy(candidate)

    def undo(self):
        """Undo one committed gesture and return its dirty sample rectangle."""
        if self.active:
            raise RuntimeError("end or cancel the active stroke before undo")
        if not self._undo:
            return None
        patch = self._undo[-1]
        candidate = self._apply_patch(patch, patch.before)
        self._undo.pop()
        self._redo.append(patch)
        self._weights = candidate
        self._revision += 1
        return patch.dirty_rect

    def redo(self):
        """Redo one committed gesture and return its dirty sample rectangle."""
        if self.active:
            raise RuntimeError("end or cancel the active stroke before redo")
        if not self._redo:
            return None
        patch = self._redo[-1]
        candidate = self._apply_patch(patch, patch.after)
        self._redo.pop()
        self._undo.append(patch)
        self._weights = candidate
        self._revision += 1
        return patch.dirty_rect
