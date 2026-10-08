"""Compatibility entry for the Ground separation regression.

The earlier culling/offset diagnostic is retained in commit bd41b2b; the
current regression includes its legacy Ground behavior as a test-only baseline.
"""
from pathlib import Path
import sys
from ground_separation_smoke import ROOT, run, run_editor

if __name__ == '__main__':
    output = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'captures/ground-separation'
    scale = float(sys.argv[2]) if len(sys.argv)>2 else 1.
    run(output,scale)
    run_editor(output,scale)
