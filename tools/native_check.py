"""Run a local validation script using the dedicated Windows GPU interpreter."""
import os
from pathlib import Path
import runpy
import sys

handles = []
if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
    for directory in (Path(sys.prefix), Path(sys.prefix) / 'Library/bin', Path(sys.prefix) / 'DLLs'):
        if directory.is_dir():
            handles.append(os.add_dll_directory(str(directory)))
if len(sys.argv) < 2:
    raise SystemExit('Provide a local Python validation script')
script = Path(sys.argv[1]).resolve(strict=True)
sys.argv = [str(script), *sys.argv[2:]]
sys.path.insert(0, str(script.parent))
runpy.run_path(str(script), run_name='__main__')
