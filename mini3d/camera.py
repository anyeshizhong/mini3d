"""Camera pose and perspective projection, independent of input and rendering.

World space is right handed and Z-up. ``rotation`` maps camera coordinates to
world coordinates; its columns are right, up and backward. OpenGL camera space
looks along -Z. Matrices act on column vectors and use NumPy's normal layout.
"""

import numpy as np


def _vector3(value, name):
    vector = np.asarray(value, dtype=np.float64)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError("{} must contain three finite values".format(name))
    return vector.copy()


class Camera:
    """A pose plus lens parameters; no mouse, keyboard or orbit state."""

    def __init__(self, position=(10, 0, 0), rotation=None,
                 fov_y=60.0, near=0.01, far=1000.0):
        self.position = position
        self.rotation = np.eye(3) if rotation is None else rotation
        self.fov_y = float(fov_y)  # degrees
        self.near = float(near)
        self.far = float(far)
        self.projection_matrix(1.0)  # Validate the initial lens.

    @property
    def position(self):
        return self._position.copy()

    @position.setter
    def position(self, value):
        self._position = _vector3(value, "position")

    @property
    def rotation(self):
        return self._rotation.copy()

    @rotation.setter
    def rotation(self, value):
        rotation = np.asarray(value, dtype=np.float64)
        if (rotation.shape != (3, 3) or not np.all(np.isfinite(rotation))
                or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6)
                or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6)):
            raise ValueError("rotation must be a right-handed orthonormal 3x3 matrix")
        self._rotation = rotation.copy()

    @property
    def right(self):
        return self._rotation[:, 0].copy()

    @property
    def up(self):
        return self._rotation[:, 1].copy()

    @property
    def forward(self):
        return -self._rotation[:, 2].copy()

    @property
    def view_matrix(self):
        view = np.eye(4, dtype=np.float64)
        view[:3, :3] = self._rotation.T
        view[:3, 3] = -self._rotation.T @ self._position
        return view

    def projection_matrix(self, aspect):
        """Return an OpenGL perspective matrix for width / height."""
        if not np.isfinite(aspect) or aspect <= 0:
            raise ValueError("aspect must be positive and finite")
        if not np.isfinite(self.fov_y) or not 0 < self.fov_y < 180:
            raise ValueError("fov_y must be between 0 and 180 degrees")
        if not (np.isfinite(self.near) and np.isfinite(self.far)
                and 0 < self.near < self.far):
            raise ValueError("clipping planes must satisfy 0 < near < far")
        f = 1.0 / np.tan(np.deg2rad(self.fov_y) * 0.5)
        projection = np.zeros((4, 4), dtype=np.float64)
        projection[0, 0] = f / aspect
        projection[1, 1] = f
        projection[2, 2] = (self.far + self.near) / (self.near - self.far)
        projection[2, 3] = 2 * self.far * self.near / (self.near - self.far)
        projection[3, 2] = -1
        return projection

    def look_at(self, target, up=(0, 0, 1)):
        """Orient toward target, preserving a stable right axis at the poles."""
        backward = self._position - _vector3(target, "target")
        length = np.linalg.norm(backward)
        if length == 0:
            raise ValueError("target must differ from camera position")
        backward /= length
        up = _vector3(up, "up")
        up_length = np.linalg.norm(up)
        if up_length == 0:
            raise ValueError("up must be nonzero")
        right = np.cross(up / up_length, backward)
        if np.linalg.norm(right) < 1e-8:
            right = self.right - np.dot(self.right, backward) * backward
            if np.linalg.norm(right) < 1e-8:
                axis = np.eye(3)[np.argmin(np.abs(backward))]
                right = np.cross(axis, backward)
        right /= np.linalg.norm(right)
        self.rotation = np.column_stack((right, np.cross(backward, right), backward))

    @property
    def cam_pos_(self):
        """Legacy renderer alias, derived from the pose rather than cached."""
        return self.position

    @property
    def T_w_to_c(self):
        """Legacy CPU coordinates: right, down, forward (+Z)."""
        return np.diag([1.0, -1.0, -1.0, 1.0]) @ self.view_matrix
