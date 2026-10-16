"""Refittable AABB hierarchy; derived render data, never saved scene state."""
import numpy as np


class SpatialIndex:
    def __init__(self, leaf_size=16):
        self.leaf_size = leaf_size
        self.keys = None
        self.nodes = []
        self.leaves = {}
        self.refitted_leaves = 0

    def update(self, boxes):
        boxes = np.asarray(boxes, dtype=float).reshape(-1, 2, 3)
        keys = tuple(b.tobytes() for b in boxes)
        self.refitted_leaves = 0
        if keys == self.keys:
            return
        if self.keys is None or len(keys) != len(self.keys):
            self.nodes, self.leaves = [], {}
            def build(ids, parent=-1):
                index = len(self.nodes)
                lo, hi = boxes[ids, 0].min(0), boxes[ids, 1].max(0)
                self.nodes.append([lo, hi, parent, None, None])
                if len(ids) <= self.leaf_size:
                    self.nodes[index][3] = ids
                    for i in ids: self.leaves[int(i)] = index
                else:
                    centers = boxes[ids].mean(1)
                    axis = np.argmax(np.ptp(centers, axis=0))
                    ids = ids[np.argsort(centers[:, axis], kind='stable')]
                    middle = len(ids)//2
                    self.nodes[index][4] = (build(ids[:middle], index), build(ids[middle:], index))
                return index
            if len(boxes): build(np.arange(len(boxes)))
        else:
            changed = {self.leaves[i] for i, key in enumerate(keys) if key != self.keys[i]}
            parents = set()
            self.refitted_leaves = len(changed)
            for i in changed:
                node = self.nodes[i]; ids = node[3]
                node[0], node[1] = boxes[ids, 0].min(0), boxes[ids, 1].max(0)
                parent = node[2]
                while parent >= 0:
                    parents.add(parent); parent = self.nodes[parent][2]
            for i in sorted(parents, reverse=True):
                a, b = (self.nodes[j] for j in self.nodes[i][4])
                self.nodes[i][0] = np.minimum(a[0], b[0])
                self.nodes[i][1] = np.maximum(a[1], b[1])
        self.keys = keys

    def query(self, planes):
        from .render_plan import aabb_visible
        pending, result = ([0] if self.nodes else []), []
        self.tested_nodes = 0
        while pending:
            self.tested_nodes += len(pending)
            keep = aabb_visible([[self.nodes[i][0], self.nodes[i][1]] for i in pending], planes)
            next_level = []
            for i, visible in zip(pending, keep):
                if not visible: continue
                node = self.nodes[i]
                if node[3] is not None: result.extend(node[3])
                else: next_level.extend(node[4])
            pending = next_level
        return np.asarray(sorted(result), dtype=int)
