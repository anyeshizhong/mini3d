"""Adapt ASCII/binary STL to the editor's shared scene/mesh representation."""
from pathlib import Path
import struct

import numpy as np
from stl import Mode, mesh as stl_mesh

from .gltf_loader import Asset
from .scene import Entity, Mesh


def load_stl(path):
    path = Path(path).resolve()
    try:
        with path.open('rb') as stream:
            header = stream.read(84)
            binary = (len(header) == 84 and
                      path.stat().st_size == 84 + 50 * struct.unpack('<I', header[80:84])[0])
            stream.seek(0)
            source = stl_mesh.Mesh.from_file(str(path), fh=stream,
                                            mode=Mode.BINARY if binary else Mode.AUTOMATIC)
    except OSError:
        raise
    except Exception as exc:
        raise ValueError("Cannot read STL '{}': {}".format(path.name, exc)) from exc
    triangles = np.asarray(source.vectors, dtype=np.float64)
    if not len(triangles) or not np.all(np.isfinite(triangles)):
        raise ValueError("STL contains no triangles or has non-finite coordinates")
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 0
    if not np.any(valid):
        raise ValueError("STL contains no non-degenerate triangles")
    triangles = triangles[valid]
    normals = normals[valid] / lengths[valid, None]
    # Keep corners separate: welding would round off CAD hard edges. STL has
    # no standard units/up-axis/material, so preserve coordinates and use matte gray.
    model = Mesh(triangles.reshape(-1, 3), np.arange(triangles.size // 3).reshape(-1, 3),
                 normals=np.repeat(normals, 3, axis=0), material={
                     "pbrMetallicRoughness": {"baseColorFactor": [.65, .68, .72, 1],
                                             "metallicFactor": 0, "roughnessFactor": .8},
                     "doubleSided": True,
                 })
    return Asset(path, Entity(model, path.stem))
