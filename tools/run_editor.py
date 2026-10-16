"""Launch mini3D on Windows' high-performance GPU without changing Python's profile.

Only the dedicated .runtime executable receives a temporary GPU preference.
The caller's Python environment and the previous preference are restored/kept.
Other platforms use the current interpreter directly.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if os.name != 'nt':
        return subprocess.call([sys.executable, '-B', '-m', 'mini3d', *args], cwd=str(ROOT))
    import winreg
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    executable = runtime / 'mini3d.exe'
    source = Path(sys.executable)
    python_home = Path(sys.base_prefix)
    # Don't overwrite a running executable when a second editor is opened.
    if not executable.exists() or executable.stat().st_size != source.stat().st_size:
        shutil.copy2(str(source), str(executable))
    for folder in (source.parent, python_home):
        for pattern in ('python*.dll', 'vcruntime*.dll'):
            for library in folder.glob(pattern):
                destination = runtime / library.name
                if not destination.exists() or destination.stat().st_size != library.stat().st_size:
                    shutil.copy2(str(library), str(destination))
    environment = os.environ.copy()
    environment['PYTHONHOME'] = str(python_home)
    environment['MINI3D_PYTHON_HOME'] = str(python_home)
    environment['MINI3D_PYTHON_PATH'] = json.dumps([str(ROOT), *sys.path])
    environment['PATH'] = os.pathsep.join((str(python_home / 'Library/bin'),
                                         str(python_home / 'DLLs'), environment.get('PATH', '')))
    bootstrap = """
import json, os, runpy, sys
from pathlib import Path
home = Path(os.environ['MINI3D_PYTHON_HOME'])
handles = [os.add_dll_directory(str(p)) for p in (home, home/'Library/bin', home/'DLLs')
           if p.is_dir()]
sys.path[:] = json.loads(os.environ['MINI3D_PYTHON_PATH'])
sys.argv = ['mini3d', *sys.argv[1:]]
runpy.run_module('mini3d', run_name='__main__')
"""
    registry_path = r'Software\Microsoft\DirectX\UserGpuPreferences'
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_path, 0,
                           winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            previous = winreg.QueryValueEx(key, str(executable))
        except FileNotFoundError:
            previous = None
        winreg.SetValueEx(key, str(executable), 0, winreg.REG_SZ, 'GpuPreference=2;')
        try:
            return subprocess.call([str(executable), '-B', '-c', bootstrap, *args],
                                   cwd=str(ROOT), env=environment)
        finally:
            # Don't overwrite a preference the user changed while we were open.
            try:
                current = winreg.QueryValueEx(key, str(executable))
            except FileNotFoundError:
                current = None
            if current == ('GpuPreference=2;', winreg.REG_SZ):
                if previous is None:
                    winreg.DeleteValue(key, str(executable))
                else:
                    winreg.SetValueEx(key, str(executable), 0, previous[1], previous[0])


if __name__ == '__main__':
    raise SystemExit(main())
