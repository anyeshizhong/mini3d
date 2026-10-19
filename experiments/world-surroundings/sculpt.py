"""CPU-only, replayable sculpt strokes for the World Surroundings experiment.

Each dab builds a new immutable :class:`Heightfield`, including its full CPU
mesh and normals. History keeps only rectangular float64 before/after diffs;
this module does not perform local normal recomputation or GPU updates.
"""

from dataclasses import dataclass
import operator
from typing import Optional, Tuple

import numpy as np

try:  # Support both direct experiment imports and package-style imports.
    from .heightfield import Heightfield
except ImportError:  # pragma: no cover - exercised by the experiment test loader
    from heightfield import Heightfield


Rect = Tuple[int, int, int, int]


def _finite_float(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must be finite" % name) from exc
    if not np.isfinite(result):
        raise ValueError("%s must be finite" % name)
    return result


def _nonnegative_int(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("%s must be a non-negative integer" % name)
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError("%s must be a non-negative integer" % name) from exc
    if result < 0:
        raise ValueError("%s must be a non-negative integer" % name)
    return result


def _immutable_copy(array):
    """Return a contiguous, bytes-backed immutable array copy."""
    contiguous = np.ascontiguousarray(array)
    return np.frombuffer(contiguous.tobytes(), dtype=contiguous.dtype).reshape(
        contiguous.shape)


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
    changed = np.not_equal(first[row_start:row_end, col_start:col_end],
                           second[row_start:row_end, col_start:col_end])
    return _mask_rect(changed, row_start, col_start)


@dataclass(frozen=True)
class SculptPatch:
    """One committed gesture's rectangular height diff.

    ``dirty_rect`` is ``(row_start, col_start, row_end, col_end)`` in sample
    indices, with half-open ends. Rows run toward +Y and columns toward +X.
    The arrays have the same shape as that rectangle and are immutable.
    """

    mode: str
    dirty_rect: Rect
    before: np.ndarray
    after: np.ndarray

    @property
    def byte_size(self):
        """Bytes used by the two stored float64 region arrays."""
        return int(self.before.nbytes + self.after.nbytes)

    @property
    def rect(self):
        """Short alias for :attr:`dirty_rect`."""
        return self.dirty_rect


class HistoryBudgetExceeded(RuntimeError):
    """A gesture was rolled back because its region diff exceeds the budget."""

    def __init__(self, required_bytes, budget_bytes, dirty_rect,
                 patch_bytes=None):
        self.required_bytes = int(required_bytes)
        self.budget_bytes = int(budget_bytes)
        self.dirty_rect = dirty_rect
        self.patch_bytes = int(required_bytes if patch_bytes is None else patch_bytes)
        super().__init__(
            "sculpt history would use %d bytes, exceeding the %d-byte budget" %
            (self.required_bytes, self.budget_bytes))


@dataclass
class _Stroke:
    mode: str
    radius: float
    strength: float
    start_terrain: Heightfield
    target_height: Optional[float]
    dirty_rect: Optional[Rect] = None


class SculptSession:
    """Manage one active sculpt gesture and its undo/redo history.

    Modes are ``raise``, ``lower``, ``flatten`` and ``smooth``. ``dab``'s
    ``amount`` is elapsed time in seconds. Raise/lower strength is metres per
    second; flatten/smooth strength is inverse seconds. The circular brush uses
    a smoothstep falloff that reaches zero at its world-space radius.

    Flatten without an explicit target freezes the piecewise-planar surface
    height at its first effective dab. Smooth uses a 3×3 sample mean from the
    stroke-start heightfield, clamping neighbor indices at the outer edge; a
    fixed target field makes repeated dabs at one point independent of event
    frequency and avoids scan-order writes.
    """

    def __init__(self, terrain, history_budget_bytes=64 * 1024 * 1024):
        if not isinstance(terrain, Heightfield):
            raise TypeError("terrain must be a Heightfield")
        self._terrain = terrain
        self._history_budget_bytes = _nonnegative_int(
            history_budget_bytes, "history_budget_bytes")
        self._revision = 0
        self._stroke = None
        self._undo = []
        self._redo = []

    @property
    def terrain(self):
        """The current immutable preview or committed heightfield."""
        return self._terrain

    @property
    def revision(self):
        """Monotonic terrain revision, incremented whenever terrain is replaced."""
        return self._revision

    @property
    def active(self):
        """Whether a gesture is currently open."""
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

    def begin_stroke(self, mode, radius, strength, target_height=None):
        """Start one gesture; invalid input leaves the session untouched."""
        if self.active:
            raise RuntimeError("a sculpt stroke is already active")
        if not isinstance(mode, str):
            raise ValueError("mode must be raise, lower, flatten or smooth")
        normalized_mode = mode.strip().lower()
        if normalized_mode not in ("raise", "lower", "flatten", "smooth"):
            raise ValueError("mode must be raise, lower, flatten or smooth")

        radius = _finite_float(radius, "radius")
        strength = _finite_float(strength, "strength")
        if radius <= 0.0:
            raise ValueError("radius must be positive")
        if strength < 0.0:
            raise ValueError("strength must be non-negative")
        if target_height is not None:
            if normalized_mode != "flatten":
                raise ValueError("target_height is only valid for flatten mode")
            target_height = _finite_float(target_height, "target_height")

        self._stroke = _Stroke(normalized_mode, radius, strength,
                               self._terrain, target_height)

    def _candidate_window(self, x, y, radius):
        """Return the sample window and smoothstep circle weights for a dab."""
        bounds = self._terrain.bounds
        if (x < bounds[0][0] or x > bounds[0][1] or
                y < bounds[1][0] or y > bounds[1][1]):
            return None

        x_axis = self._terrain._x_axis64
        y_axis = self._terrain._y_axis64
        with np.errstate(over="ignore", invalid="ignore"):
            col_start = int(np.searchsorted(x_axis, x - radius, side="left"))
            col_end = int(np.searchsorted(x_axis, x + radius, side="right"))
            row_start = int(np.searchsorted(y_axis, y - radius, side="left"))
            row_end = int(np.searchsorted(y_axis, y + radius, side="right"))
        col_start = max(0, min(self._terrain.cols, col_start))
        col_end = max(0, min(self._terrain.cols, col_end))
        row_start = max(0, min(self._terrain.rows, row_start))
        row_end = max(0, min(self._terrain.rows, row_end))
        if row_start >= row_end or col_start >= col_end:
            return None

        dx = x_axis[col_start:col_end] - x
        dy = y_axis[row_start:row_end] - y
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            distance = np.hypot(dy[:, None], dx[None, :])
            t = np.clip(1.0 - distance / radius, 0.0, 1.0)
            weights = t * t * (3.0 - 2.0 * t)
        if not np.any(weights > 0.0):
            return None
        return (row_start, col_start, row_end, col_end, weights)

    @staticmethod
    def _smooth_targets(source, row_start, col_start, row_end, col_end):
        rows = np.arange(row_start, row_end, dtype=np.intp)
        cols = np.arange(col_start, col_end, dtype=np.intp)
        targets = np.zeros((len(rows), len(cols)), dtype=np.float64)
        max_row, max_col = source.shape[0] - 1, source.shape[1] - 1
        # Each target reads the immutable stroke-start window. Clamping repeats
        # edge samples, matching an edge-replicated 3×3 filter.
        for row_delta in (-1, 0, 1):
            neighbor_rows = np.clip(rows + row_delta, 0, max_row)
            for col_delta in (-1, 0, 1):
                neighbor_cols = np.clip(cols + col_delta, 0, max_col)
                targets += source[neighbor_rows[:, None], neighbor_cols[None, :]]
        targets /= 9.0
        return targets

    def dab(self, x, y, amount=1.0):
        """Apply one timed dab and return its changed half-open sample rect.

        ``amount`` is non-negative elapsed time in seconds. A center outside
        the canonical Heightfield bounds is a miss and changes nothing.
        Invalid inputs and an unrepresentable candidate fail before replacing
        the current preview.
        """
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
        row_start, col_start, row_end, col_end, weights = window
        active_samples = weights > 0.0
        old_region = self._terrain.heights[
            row_start:row_end, col_start:col_end]
        new_region = np.array(old_region, copy=True)
        frozen_target = stroke.target_height

        if stroke.mode in ("raise", "lower"):
            direction = 1.0 if stroke.mode == "raise" else -1.0
            with np.errstate(over="ignore", invalid="ignore"):
                delta = direction * stroke.strength * amount * weights
                new_region[active_samples] = (
                    old_region[active_samples] + delta[active_samples])
        else:
            if stroke.mode == "flatten":
                if frozen_target is None:
                    # The first effective dab freezes the visible surface at
                    # its center, using Heightfield's triangle convention.
                    sample = stroke.start_terrain.query_surface(x, y)
                    if not sample["hit"]:  # Bounds were checked above.
                        return None
                    frozen_target = sample["height"]
                targets = np.full(old_region.shape, frozen_target,
                                  dtype=np.float64)
            else:
                targets = self._smooth_targets(
                    stroke.start_terrain.heights, row_start, col_start,
                    row_end, col_end)
            with np.errstate(over="ignore", invalid="ignore", under="ignore"):
                dose = stroke.strength * amount
                alpha = -np.expm1(-dose * weights)
                new_region[active_samples] = (
                    old_region[active_samples] +
                    alpha[active_samples] *
                    (targets[active_samples] - old_region[active_samples]))

        if not np.isfinite(new_region).all():
            raise ValueError("dab would produce non-finite height samples")

        changed_mask = np.not_equal(new_region, old_region)
        changed_rect = _mask_rect(changed_mask, row_start, col_start)
        if changed_rect is None:
            if stroke.mode == "flatten" and stroke.target_height is None:
                # A valid first effective dab freezes even when it leaves the
                # samples unchanged (for example, its center is already flat).
                stroke.target_height = frozen_target
            return None

        candidate_heights = self._terrain.heights.copy()
        candidate_heights[row_start:row_end, col_start:col_end] = new_region
        candidate_terrain = Heightfield(
            candidate_heights, origin=self._terrain.origin,
            size=self._terrain.size)

        if stroke.mode == "flatten" and stroke.target_height is None:
            # Do not mutate stroke state until the full candidate validates.
            stroke.target_height = frozen_target
        self._terrain = candidate_terrain
        self._revision += 1
        stroke.dirty_rect = _merge_rect(stroke.dirty_rect, changed_rect)
        return changed_rect

    def _make_patch(self, stroke):
        if stroke.dirty_rect is None:
            return None
        rect = _difference_rect(stroke.start_terrain.heights,
                                self._terrain.heights, stroke.dirty_rect)
        if rect is None:
            return None
        row_start, col_start, row_end, col_end = rect
        before = _immutable_copy(
            stroke.start_terrain.heights[row_start:row_end, col_start:col_end])
        after = _immutable_copy(
            self._terrain.heights[row_start:row_end, col_start:col_end])
        return SculptPatch(stroke.mode, rect, before, after)

    def _rollback_stroke(self, stroke):
        dirty_rect = _difference_rect(stroke.start_terrain.heights,
                                      self._terrain.heights,
                                      stroke.dirty_rect)
        had_preview = self._terrain is not stroke.start_terrain
        self._terrain = stroke.start_terrain
        self._stroke = None
        if had_preview:
            self._revision += 1
        return dirty_rect

    def end_stroke(self):
        """Commit a gesture as one patch, or return ``None`` for no change."""
        if not self.active:
            raise RuntimeError("there is no active sculpt stroke")
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
            raise RuntimeError("there is no active sculpt stroke")
        return self._rollback_stroke(self._stroke)

    def _apply_patch(self, patch, values):
        row_start, col_start, row_end, col_end = patch.dirty_rect
        candidate_heights = self._terrain.heights.copy()
        candidate_heights[row_start:row_end, col_start:col_end] = values
        return Heightfield(candidate_heights, origin=self._terrain.origin,
                           size=self._terrain.size)

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
        self._terrain = candidate
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
        self._terrain = candidate
        self._revision += 1
        return patch.dirty_rect
