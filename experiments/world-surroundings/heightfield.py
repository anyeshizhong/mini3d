"""Finite CPU heightfields for the independent World Surroundings experiment.

The samples are owned as immutable float64 data. Geometry is quantized to
float32 before any query or mesh is produced, matching ``mini3d.scene.Mesh``.
This module does not decode images or touch a graphics context.
"""

import operator

import numpy as np


def _immutable_array(array):
    """Return a contiguous array backed by immutable bytes."""
    contiguous = np.ascontiguousarray(array)
    return np.frombuffer(contiguous.tobytes(), dtype=contiguous.dtype).reshape(contiguous.shape)


def _finite_pair(value, name):
    try:
        pair = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("%s must contain two finite numbers" % name) from exc
    if pair.shape != (2,) or not np.isfinite(pair).all():
        raise ValueError("%s must contain two finite numbers" % name)
    return float(pair[0]), float(pair[1])


def _positive_int(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("%s must be a positive integer" % name)
    try:
        result = operator.index(value)
    except TypeError as exc:
        raise ValueError("%s must be a positive integer" % name) from exc
    if result <= 0:
        raise ValueError("%s must be a positive integer" % name)
    return result


def _make_axis(start, stop, count, name):
    with np.errstate(over="ignore", invalid="ignore"):
        axis = np.linspace(start, stop, count, dtype=np.float64).astype(np.float32)
    if not np.isfinite(axis).all():
        raise ValueError("%s coordinates must fit in float32" % name)
    # A repeated float32 coordinate would collapse a cell in the Mesh that the
    # source configuration still considers nonzero.
    if np.any(np.diff(axis.astype(np.float64)) <= 0.0):
        raise ValueError("%s grid coordinates collapse in float32" % name)
    return axis


def _grid_indices(rows, cols):
    grid = np.arange(rows * cols, dtype=np.uint32).reshape(rows, cols)
    a = grid[:-1, :-1]
    b = grid[:-1, 1:]
    c = grid[1:, 1:]
    d = grid[1:, :-1]
    return np.stack((np.stack((a, b, c), axis=-1),
                     np.stack((a, c, d), axis=-1)), axis=-2).reshape(-1, 3)


def _area_weighted_normals(vertices, indices):
    points = np.asarray(vertices, dtype=np.float64)
    triangles = points[indices]
    faces = np.cross(triangles[:, 1] - triangles[:, 0],
                     triangles[:, 2] - triangles[:, 0])
    accumulated = np.zeros((len(points), 3), dtype=np.float64)
    for corner in range(3):
        # Reduce each corner/component in compiled NumPy code with float64
        # weights. Grouping changes floating-point association; regressions
        # compare final float32 normals against the previous add.at algorithm.
        for component in range(3):
            accumulated[:, component] += np.bincount(
                indices[:, corner], weights=faces[:, component],
                minlength=len(points))
    lengths = np.linalg.norm(accumulated, axis=1)
    if not np.isfinite(lengths).all() or np.any(lengths <= 0.0):
        raise ValueError("heightfield geometry produced invalid vertex normals")
    normals = (accumulated / lengths[:, None]).astype(np.float32)
    if not np.isfinite(normals).all():
        raise ValueError("heightfield geometry produced invalid vertex normals")
    return normals


class Heightfield:
    """A finite, regular height grid with deterministic triangle geometry.

    ``heights`` is indexed as ``[row_y, col_x]``. ``origin`` and ``size``
    retain their float64 input values, while mesh coordinates are sampled and
    quantized to float32. :attr:`bounds` exposes those actual float32 endpoints;
    surface queries use that same canonical domain and each cell's actual
    quantized coordinates.
    """

    def __init__(self, heights, origin=(-18.0, -13.0), size=(36.0, 26.0)):
        try:
            samples = np.asarray(heights, dtype=np.float64)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("heights must be a finite 2D numeric array") from exc
        if samples.ndim != 2 or samples.shape[0] < 2 or samples.shape[1] < 2:
            raise ValueError("heights must have at least 2 rows and 2 columns")
        if not np.isfinite(samples).all():
            raise ValueError("heights must contain only finite values")

        self._origin = _finite_pair(origin, "origin")
        self._size = _finite_pair(size, "size")
        if self._size[0] <= 0.0 or self._size[1] <= 0.0:
            raise ValueError("size dimensions must be positive")

        with np.errstate(over="ignore", invalid="ignore"):
            end_x = self._origin[0] + self._size[0]
            end_y = self._origin[1] + self._size[1]
        if not np.isfinite([end_x, end_y]).all():
            raise ValueError("heightfield bounds must be finite")

        self._rows, self._cols = map(int, samples.shape)
        if self._rows * self._cols > np.iinfo(np.uint32).max + 1:
            raise ValueError("heightfield has too many vertices for uint32 indices")
        self._heights = _immutable_array(samples.astype(np.float64, copy=False))

        with np.errstate(over="ignore", invalid="ignore"):
            heights32 = samples.astype(np.float32)
        if not np.isfinite(heights32).all():
            raise ValueError("height samples must fit in float32 geometry")

        self._x_axis = _immutable_array(_make_axis(
            self._origin[0], end_x, self._cols, "x"))
        self._y_axis = _immutable_array(_make_axis(
            self._origin[1], end_y, self._rows, "y"))
        self._x_axis64 = self._x_axis.astype(np.float64)
        self._y_axis64 = self._y_axis.astype(np.float64)

        vertices = np.empty((self._rows, self._cols, 3), dtype=np.float32)
        vertices[..., 0] = self._x_axis[None, :]
        vertices[..., 1] = self._y_axis[:, None]
        vertices[..., 2] = heights32
        flat_vertices = vertices.reshape(-1, 3)
        indices = _grid_indices(self._rows, self._cols)
        normals = _area_weighted_normals(flat_vertices, indices)
        uvs = np.empty((self._rows, self._cols, 2), dtype=np.float32)
        uvs[..., 0] = np.linspace(0.0, 1.0, self._cols, dtype=np.float32)[None, :]
        uvs[..., 1] = np.linspace(0.0, 1.0, self._rows, dtype=np.float32)[:, None]

        self._vertices_grid = _immutable_array(vertices)
        self._vertices = _immutable_array(flat_vertices)
        self._indices = _immutable_array(indices)
        self._normals = _immutable_array(normals)
        self._uvs_grid = _immutable_array(uvs)

    @classmethod
    def flat(cls, rows=65, cols=65, height=0.0,
             origin=(-18.0, -13.0), size=(36.0, 26.0)):
        """Create a deterministic flat grid with ``rows × cols`` samples."""
        rows = _positive_int(rows, "rows")
        cols = _positive_int(cols, "cols")
        if rows < 2 or cols < 2:
            raise ValueError("flat heightfields need at least 2 rows and 2 columns")
        try:
            level = float(height)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("height must be finite") from exc
        if not np.isfinite(level):
            raise ValueError("height must be finite")
        return cls(np.full((rows, cols), level, dtype=np.float64),
                   origin=origin, size=size)

    @property
    def heights(self):
        """The owned float64 samples, backed by immutable memory."""
        return self._heights

    @property
    def origin(self):
        return self._origin

    @property
    def size(self):
        return self._size

    @property
    def bounds(self):
        """Actual float32 mesh bounds as ``((xmin, xmax), (ymin, ymax))``."""
        return ((float(self._x_axis[0]), float(self._x_axis[-1])),
                (float(self._y_axis[0]), float(self._y_axis[-1])))

    @property
    def rows(self):
        return self._rows

    @property
    def cols(self):
        return self._cols

    @property
    def vertex_count(self):
        return self._rows * self._cols

    @property
    def cell_count(self):
        return (self._rows - 1) * (self._cols - 1)

    @property
    def triangle_count(self):
        return 2 * self.cell_count

    def stats(self):
        """Return JSON-friendly grid and geometry counts."""
        return {"rows": self._rows, "cols": self._cols,
                "vertices": self.vertex_count, "cells": self.cell_count,
                "triangles": self.triangle_count}

    def mesh_arrays(self):
        """Return independent float32/uint32 arrays for the canonical mesh."""
        return {"vertices": self._vertices.copy(),
                "indices": self._indices.copy(),
                "normals": self._normals.copy(),
                "uvs": self._uvs_grid.reshape(-1, 2).copy()}

    def to_mesh(self, material=None):
        """Build a ``mini3d.scene.Mesh`` using canonical float32 geometry."""
        from mini3d.scene import Mesh

        return Mesh(self._vertices, self._indices, normals=self._normals,
                    texcoords=self._uvs_grid.reshape(-1, 2), material=material)

    @staticmethod
    def _query_scalar(value, name):
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("%s must be finite" % name) from exc
        if not np.isfinite(result):
            raise ValueError("%s must be finite" % name)
        return result

    @staticmethod
    def _miss():
        return {"hit": False, "height": None, "normal": None,
                "cell": None, "triangle": None}

    def query_surface(self, x, y):
        """Query the piecewise-planar surface, returning JSON-friendly data.

        Interior grid lines belong to the cell on their positive side; maximum
        bounds belong to the final cell. On a cell diagonal ``v <= u`` selects
        triangle 0, matching the first emitted triangle ``(a,b,c)``.
        """
        x = self._query_scalar(x, "x")
        y = self._query_scalar(y, "y")
        if (x < self._x_axis64[0] or x > self._x_axis64[-1] or
                y < self._y_axis64[0] or y > self._y_axis64[-1]):
            return self._miss()

        col = int(np.searchsorted(self._x_axis64, x, side="right") - 1)
        row = int(np.searchsorted(self._y_axis64, y, side="right") - 1)
        col = min(max(col, 0), self._cols - 2)
        row = min(max(row, 0), self._rows - 2)
        x0, x1 = self._x_axis64[col:col + 2]
        y0, y1 = self._y_axis64[row:row + 2]
        u = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        v = min(1.0, max(0.0, (y - y0) / (y1 - y0)))

        a, b, c, d = (self._vertices_grid[row, col],
                      self._vertices_grid[row, col + 1],
                      self._vertices_grid[row + 1, col + 1],
                      self._vertices_grid[row + 1, col])
        if v <= u:
            triangle = 0
            height = (1.0 - u) * float(a[2]) + (u - v) * float(b[2]) + v * float(c[2])
            face = np.cross(b.astype(np.float64) - a,
                            c.astype(np.float64) - a)
        else:
            triangle = 1
            height = ((1.0 - v) * float(a[2]) + u * float(c[2]) +
                      (v - u) * float(d[2]))
            face = np.cross(c.astype(np.float64) - a,
                            d.astype(np.float64) - a)
        face /= np.linalg.norm(face)
        return {"hit": True, "height": float(height),
                "normal": [float(face[0]), float(face[1]), float(face[2])],
                "cell": [row, col], "triangle": triangle}

    def iter_mesh_chunks(self, material=None, chunk_cells=32):
        """Return row-major mesh chunks, sharing globally computed normals.

        ``row_end`` and ``col_end`` are inclusive vertex-grid indices. The
        covered cells use the half-open ranges ``[start, end)``.
        """
        from mini3d.scene import Mesh

        chunk_cells = _positive_int(chunk_cells, "chunk_cells")
        chunks = []
        for row_start in range(0, self._rows - 1, chunk_cells):
            row_end = min(row_start + chunk_cells, self._rows - 1)
            for col_start in range(0, self._cols - 1, chunk_cells):
                col_end = min(col_start + chunk_cells, self._cols - 1)
                vertices = self._vertices_grid[row_start:row_end + 1,
                                               col_start:col_end + 1].reshape(-1, 3).copy()
                normals = self._normals.reshape(self._rows, self._cols, 3)[
                    row_start:row_end + 1, col_start:col_end + 1].reshape(-1, 3).copy()
                uvs = self._uvs_grid[row_start:row_end + 1,
                                     col_start:col_end + 1].reshape(-1, 2).copy()
                local_indices = _grid_indices(row_end - row_start + 1,
                                              col_end - col_start + 1)
                mesh = Mesh(vertices, local_indices, normals=normals,
                            texcoords=uvs, material=material)
                chunks.append({
                    "mesh": mesh,
                    "row_start": row_start,
                    "col_start": col_start,
                    "row_end": row_end,
                    "col_end": col_end,
                    "cell_rows": [row_start, row_end],
                    "cell_cols": [col_start, col_end],
                    "vertex_count": len(vertices),
                    "triangle_count": len(local_indices),
                })
        return chunks
