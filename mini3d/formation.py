"""Planar rectangular formations built exclusively through placement commands.

Spacing is in engine world units; facing is yaw in radians. The source is the
first row/column origin, not the formation centre. Meshes and imported child
hierarchies remain shared clones, with independent instance transforms.
"""
from numbers import Integral, Real

import numpy as np


def create_rectangular_formation(commands, source_id, rows, columns, spacing_x,
                                 spacing_y, facing=None, include_source=True):
    """Create/select one flat SceneGroup in a single undoable transaction.

    With include_source=True, rows*columns includes the existing source. Undo
    restores that original instance (including its prior transform/selection).
    Locked sources are rejected; unlock explicitly before creating a formation.
    """
    for label, value in (("rows", rows), ("columns", columns)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(label + " must be a positive integer")
    for label, value in (("spacing_x", spacing_x), ("spacing_y", spacing_y)):
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not np.isfinite(value) or value <= 0):
            raise ValueError(label + " must be finite and positive")
    if not isinstance(include_source, (bool, np.bool_)):
        raise ValueError("include_source must be a boolean")
    if facing is not None and (isinstance(facing, (bool, np.bool_))
            or not isinstance(facing, Real) or not np.isfinite(facing)):
        raise ValueError("facing must be a finite yaw in radians")
    source = commands.scene.find_by_id(source_id)
    if source is None:
        raise ValueError("Unknown formation source: {!r}".format(source_id))
    if source.locked:
        raise ValueError("Formation source is locked: " + source.entity_id)
    origin, rotation = source.pos.copy(), source.rot.copy()
    yaw = rotation[2] if facing is None else float(facing)
    rotation[2] = yaw
    cosine, sine = np.cos(yaw), np.sin(yaw)
    basis = np.array([[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]])
    # Validate the largest offset before mutation (overflow must be atomic too).
    with np.errstate(over="ignore", invalid="ignore"):
        extent = origin + basis @ np.array([(columns - 1) * float(spacing_x),
                                           (rows - 1) * float(spacing_y), 0])
    if not np.all(np.isfinite(extent)):
        raise ValueError("Formation extent must be finite")
    used_names = {group.name for group in commands.scene.groups}
    number = 1
    while "Legion_Formation_{:03d}".format(number) in used_names:
        number += 1
    name = "Legion_Formation_{:03d}".format(number)
    with commands.transaction("Rectangular Formation"):
        member_ids = []
        for row in range(rows):
            for column in range(columns):
                instance = (source if include_source and row == column == 0
                            else commands.duplicate(source_id))
                offset = basis @ np.array([column * spacing_x, row * spacing_y, 0])
                commands.set_transform(instance.entity_id, position=origin + offset,
                                       rotation=rotation)
                member_ids.append(instance.entity_id)
        group = commands.create_group(member_ids, name=name)
        commands.set_selection(member_ids, primary_id=member_ids[0], group_id=group.group_id)
    return group
