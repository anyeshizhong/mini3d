"""Z-up orbit navigation. Mouse displacements are pixels, never rates."""

import numpy as np

from .camera import _vector3


class OrbitController:
    """Own target/distance/yaw/pitch and derive the camera pose from them.

    Angles are radians. Yaw zero places the camera on the +X side of target;
    positive yaw moves toward +Y, and positive pitch moves toward +Z.
    """

    def __init__(self, camera, target=(0, 0, 0), distance=10.0,
                 yaw=0.0, pitch=0.35):
        self.camera = camera
        self.target = _vector3(target, "target")
        self.distance = float(distance)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.orbit_sensitivity = 0.005
        self.zoom_sensitivity = 0.12
        self.pitch_limit = np.deg2rad(89.5)
        self.min_distance = 1e-4
        self.max_distance = 1e8
        self._bounds_center = self.target.copy()
        self._bounds_radius = 1.0
        self.update()

    def update(self):
        """Synchronize camera pose and clipping after changing orbit state."""
        self.target = _vector3(self.target, "target")
        if not (np.isfinite(self.distance) and self.distance > 0
                and np.isfinite(self.yaw) and np.isfinite(self.pitch)):
            raise ValueError("distance must be positive; orbit state must be finite")
        self.distance = float(np.clip(self.distance, self.min_distance, self.max_distance))
        cy, sy = np.cos(self.yaw), np.sin(self.yaw)
        cp, sp = np.cos(self.pitch), np.sin(self.pitch)
        backward = np.array([cp * cy, cp * sy, sp])
        # Analytic right is well-defined even at an exact top/bottom view.
        right = np.array([-sy, cy, 0.0])
        up = np.cross(backward, right)
        self.camera.position = self.target + self.distance * backward
        self.camera.rotation = np.column_stack((right, up, backward))
        self._update_clipping()

    def _update_clipping(self):
        depth = np.dot(self._bounds_center - self.camera.position, self.camera.forward)
        radius = self._bounds_radius
        # Preserve depth precision outside the framing sphere while leaving
        # room for foreground objects elsewhere in the scene. Inside the sphere
        # (or after navigating past it), retain a small scale-aware near plane.
        near = max(self.distance * 1e-4, radius * 1e-5, 1e-12)
        if depth > radius:
            near = min((depth - radius) * 0.5, self.distance * 0.01)
        self.camera.near = max(near, 1e-12)
        self.camera.far = max(self.distance + 4 * radius, depth + 2 * radius,
                              self.camera.near * 2)

    def orbit(self, dx, dy):
        """Drag the scene: rightward drag decreases yaw; down increases pitch."""
        self.yaw -= float(dx) * self.orbit_sensitivity
        self.pitch = float(np.clip(self.pitch + float(dy) * self.orbit_sensitivity,
                                   -self.pitch_limit, self.pitch_limit))
        self.update()

    def pan(self, dx, dy, viewport_height):
        """Translate parallel to the image, making the scene follow the drag."""
        if not np.isfinite(viewport_height) or viewport_height <= 0:
            raise ValueError("viewport_height must be positive and finite")
        units_per_pixel = (2 * self.distance * np.tan(np.deg2rad(self.camera.fov_y) / 2)
                           / viewport_height)
        self.target += (-self.camera.right * float(dx) + self.camera.up * float(dy)) * units_per_pixel
        self.update()

    def zoom(self, wheel_delta):
        """Positive wheel motion dollies toward target by a constant ratio."""
        if not np.isfinite(wheel_delta):
            raise ValueError("wheel_delta must be finite")
        # Work in log space so very large wheel deltas cannot overflow.
        log_distance = np.log(self.distance) - float(wheel_delta) * self.zoom_sensitivity
        self.distance = float(np.exp(np.clip(log_distance, np.log(self.min_distance),
                                             np.log(self.max_distance))))
        self.update()

    def set_view(self, name):
        """Look from a named world-axis side while retaining target/distance."""
        presets = {
            "front": (0, 0), "back": (np.pi, 0),
            "right": (np.pi / 2, 0), "left": (-np.pi / 2, 0),
            "top": (0, np.pi / 2), "bottom": (0, -np.pi / 2),
        }
        if name not in presets:
            raise ValueError("unknown view: {}".format(name))
        self.yaw, self.pitch = presets[name]
        self.update()

    def focus_bounds(self, minimum, maximum, aspect, padding=1.1):
        """Frame a world AABB, including its depth, at any viewport aspect."""
        minimum = _vector3(minimum, "minimum")
        maximum = _vector3(maximum, "maximum")
        if np.any(maximum < minimum):
            raise ValueError("maximum must not be below minimum")
        if not np.isfinite(padding) or padding < 1:
            raise ValueError("padding must be finite and at least 1")
        self.camera.projection_matrix(aspect)  # Validate aspect and lens.
        center = minimum + (maximum - minimum) * 0.5
        radius = float(np.linalg.norm((maximum - minimum) * 0.5))
        if radius == 0:
            radius = 1.0  # A point still needs a useful viewing distance.
        self._bounds_center = center.copy()
        self._bounds_radius = radius
        half_vertical = np.deg2rad(self.camera.fov_y) * 0.5
        half_horizontal = np.arctan(np.tan(half_vertical) * aspect)
        self.target = center
        fit_distance = radius * padding / np.sin(min(half_vertical, half_horizontal))
        self.min_distance = max(radius * 1e-4, 1e-12)
        self.max_distance = max(radius * 1e6, fit_distance * 10)
        self.distance = fit_distance
        self.update()

    def snapshot(self):
        """Capture navigation and framing data for an explicit reset action."""
        return {
            "target": self.target.copy(), "distance": self.distance,
            "yaw": self.yaw, "pitch": self.pitch,
            "fov_y": self.camera.fov_y,
            "bounds_center": self._bounds_center.copy(),
            "bounds_radius": self._bounds_radius,
            "min_distance": self.min_distance, "max_distance": self.max_distance,
        }

    def restore(self, state):
        """Restore a snapshot made by this controller."""
        self.target = _vector3(state["target"], "target")
        self.distance = float(state["distance"])
        self.yaw = float(state["yaw"])
        self.pitch = float(state["pitch"])
        self.camera.fov_y = float(state.get("fov_y", self.camera.fov_y))
        self._bounds_center = _vector3(state["bounds_center"], "bounds_center")
        self._bounds_radius = float(state["bounds_radius"])
        self.min_distance = float(state["min_distance"])
        self.max_distance = float(state["max_distance"])
        self.update()
