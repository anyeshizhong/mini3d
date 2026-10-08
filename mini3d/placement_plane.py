"""Mathematical fallback surface; no Mesh, Entity, GPU resource or visibility."""
import numpy as np


class PlacementPlane:
    def __init__(self, z=0.0, size=2000.0, enabled=True):
        self.z, self.size = float(z), float(size)
        if not np.isfinite([self.z, self.size]).all() or self.size <= 0:
            raise ValueError('Placement plane needs finite z and positive size')
        if not isinstance(enabled, bool):
            raise ValueError('Placement plane enabled must be boolean')
        self.enabled = enabled

    def point(self, x, y):
        x, y = float(x), float(y)
        if not np.isfinite([x, y]).all() or max(abs(x), abs(y)) > self.size / 2:
            raise ValueError('Ground position must lie inside the finite placement plane bounds')
        return np.array([x, y, self.z])

    def intersect(self, origin, direction):
        origin, direction = np.asarray(origin, float), np.asarray(direction, float)
        if not self.enabled or abs(direction[2]) < 1e-12:
            return None
        distance = (self.z - origin[2]) / direction[2]
        if distance < 0 or not np.isfinite(distance):
            return None
        point = origin + distance * direction
        try:
            return self.point(*point[:2]), float(distance)
        except ValueError:
            return None

    def to_dict(self):
        return dict(z=self.z, size=self.size, enabled=self.enabled)
