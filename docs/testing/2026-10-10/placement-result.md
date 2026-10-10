# Placement / composition audit — 2026-10-10

Revision under test: `7cb7719`. No production code changed.

## Result

59 existing tests and 4 new composition checks passed. These checks run actual
Editor/Commands, STL import, surface ray queries and scene persistence, without
an OpenGL window. This result does not claim visual or interactive UI acceptance.

Existing suites: placement_v2_commands (13), formation (9), surface_drag (8),
placement (10), multi_gizmo (9), placement_v2_editor (10).

New script: `tests/audit_placement_20261010.py`.

- Build a locked plinth and a 2x5 block-column portico from the tracked STL cube.
- Undo formation in one operation, preserving its source; redo preserves IDs.
- Duplicate all 10 columns, explicitly group the copies, translate and rotate.
- Save all 21 instances and both groups; reopen with matching IDs, transforms,
  names, visibility, locks, selection and group membership.
- Delete the second group selection after reopening; undo restores every member
  and selection; redo removes it again.
- Drag a prop onto a locked support using actual triangle ray queries, including
  repeated updates, cancel, one-step undo, and redo.
- Delete a shared member of overlapping groups, then restore both memberships.
- Hidden selected members transform; locked selected members remain fixed.

No user-facing functional defect was reproduced in this scope.

## Primitive geometry

| Generator | Faces | Outward nondegenerate | Inward | Degenerate |
| --- | ---: | ---: | ---: | ---: |
| Box | 12 | 12 | 0 | 0 |
| Cylinder | 64 | 64 | 0 | 0 |
| Sphere | 330 | 300 | 0 | 30 |

Sphere pole degeneracies are recorded as a geometry cleanup opportunity. They
have not been established as a visible defect. The cylinder is generated along
Y; for a Z-up architectural column, rotate it around X by 90 degrees before
placing. This is a coordinate convention, not an inverted-winding defect.

One initial audit failure was caused by this script directly moving the camera
without refreshing its clipping range (far remained 14). Calling the existing
Viewer.update_clipping method fixed the test fixture; no product fix was needed.

## Reproduction

Run from repository root:

```sh
python tests/audit_placement_20261010.py
```

Generated artifacts: `unit_cube.stl`, `portico_scene.json`, `workflow_state.json`,
and `primitive_winding.json` in this directory. The JSON scene references the
generated STL within this repository's captures directory.
