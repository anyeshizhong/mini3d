#!/usr/bin/env python3
"""CPU regression for the native local temporal fit and Python parity."""
import argparse
import ctypes
from pathlib import Path
import sys

import numpy as np

from test_shadow_fit import Camera, add_following_ground, invoke, load_library, street_entities


class TemporalLibrary:
    def __init__(self, library):
        self.library = library
        self.previous = None
        dp = ctypes.POINTER(ctypes.c_double)
        self.native = library.spqr_fit_shadow_temporal
        self.native.argtypes = library.spqr_fit_shadow.argtypes[:-1] + [dp, dp]
        self.native.restype = ctypes.c_int

    def spqr_fit_shadow(self, *args):
        previous = None if self.previous is None else self.previous.ctypes.data_as(
            ctypes.POINTER(ctypes.c_double))
        return self.native(*args[:-1], previous, args[-1])


def verify_motion(lib, direction, receiver_matrix):
    native = TemporalLibrary(lib)
    state = {}
    matrices = []
    maximum_error = 0.0
    for offset in np.linspace(0.0, .2, 121):
        camera = Camera([offset, -19.0, 9.0], [offset, 14.0, 1.5], far=320.0)
        entities = street_entities(rotated=True)
        add_following_ground(entities, camera)
        expected = receiver_matrix(entities, np.asarray(direction), camera, 2048, stability=state)
        ok, actual = invoke(native, entities, direction, camera, 2048)
        if not ok or expected is None:
            raise AssertionError("temporal local fit unexpectedly failed")
        np.testing.assert_allclose(actual, expected, rtol=3e-8, atol=3e-9)
        maximum_error = max(maximum_error, float(np.abs(actual - expected).max()))
        matrices.append(actual.copy())
        native.previous = np.ascontiguousarray(actual)
    matrices = np.asarray(matrices)
    pitch_drift = float(np.ptp(np.linalg.norm(matrices[:, :2, :3], axis=2), axis=0).max())
    depth_drift = float(np.ptp(matrices[:, 2], axis=0).max())
    phase_steps = np.diff(matrices[:, :2, 3], axis=0) * 1024
    phase_error = float(np.abs(phase_steps - np.rint(phase_steps)).max())
    if pitch_drift > 1e-12 or depth_drift > 1e-12 or phase_error > 1e-9:
        raise AssertionError((pitch_drift, depth_drift, phase_error))
    return dict(frames=121, parity_error=maximum_error, pitch_drift=pitch_drift,
                depth_drift=depth_drift, texel_step_error=phase_error)


def verify_snap_guard(lib):
    dp = ctypes.POINTER(ctypes.c_double)
    native = lib.spqr_stabilize_shadow
    native.argtypes = [dp, dp, ctypes.c_uint32]
    native.restype = ctypes.c_int
    matrix = np.array([[.2, 0, 0, -.13], [0, .1, 0, .17], [0, 0, -.05, .3], [0, 0, 0, 1.]])
    original = matrix.copy()
    ptr = matrix.ctypes.data_as(dp)
    if native(ptr, None, 2048) != 1:
        raise AssertionError("valid XY fit rejected")
    # All original XY box corners remain covered after a half-texel snap.
    xy = np.array([[x, y] for x in (-1., 1.) for y in (-1., 1.)])
    world = (xy - original[:2, 3]) / np.diag(original)[:2]
    if np.abs(world * np.diag(matrix)[:2] + matrix[:2, 3]).max() > 1.:
        raise AssertionError("snap clipped an original receiver")
    np.testing.assert_array_equal(matrix[2:], original[2:])
    saved = matrix.copy()
    if native(ptr, None, 0) != 0:
        raise AssertionError("invalid resolution accepted")
    np.testing.assert_array_equal(matrix, saved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.project.resolve()))
    from mini3d.shadow_fit import receiver_matrix
    lib = load_library(args.library.resolve())
    verify_snap_guard(lib)
    print("PASS snap guard preserves receiver coverage, depth, and invalid-input output")
    for name, direction in (("ordinary-sun", [.4, -.5, .8]), ("low-sun", [.985, -.06, .14])):
        print("PASS", name, verify_motion(lib, direction, receiver_matrix))


if __name__ == "__main__":
    main()
