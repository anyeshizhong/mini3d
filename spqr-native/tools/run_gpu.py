"""Run a prototype process on the preferred GPU and restore its exact preference.

For Python tooling, use --python to create a dedicated interpreter under --runtime.
Never changes the normal Python interpreter's preference or the system GPU default.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import winreg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('A command is required after --')
    env = os.environ.copy()
    if args.python:
        if not args.runtime:
            parser.error('--python requires --runtime')
        runtime = args.runtime.resolve()
        runtime.mkdir(parents=True, exist_ok=True)
        source = args.python.resolve()
        executable = runtime / 'spqr_export.exe'
        shutil.copyfile(source, executable)
        for pattern in ('python*.dll', 'vcruntime*.dll'):
            for library in source.parent.glob(pattern):
                shutil.copyfile(library, runtime / library.name)
        env['PYTHONHOME'] = str(source.parent)
        env['PATH'] = str(source.parent / 'Library/bin') + ';' + str(source.parent / 'DLLs') + ';' + env.get('PATH', '')
        command = [str(executable), '-B'] + command
    else:
        executable = Path(command[0]).resolve(strict=True)
        command[0] = str(executable)
    registry = r'Software\Microsoft\DirectX\UserGpuPreferences'
    prior = None
    created = False
    report = dict(command=command, executable=str(executable), started=time.time())
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE)
    except FileNotFoundError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry)
        created = True
    try:
        try:
            prior = winreg.QueryValueEx(key, str(executable))
        except FileNotFoundError:
            pass
        report['previous_preference'] = prior
        winreg.SetValueEx(key, str(executable), 0, winreg.REG_SZ, 'GpuPreference=2;')
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=args.timeout)
        report.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
    except BaseException as exc:
        report.update(returncode=-1, error=repr(exc))
        raise
    finally:
        if prior is None:
            try:
                winreg.DeleteValue(key, str(executable))
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, str(executable), 0, prior[1], prior[0])
        try:
            restored = winreg.QueryValueEx(key, str(executable)) == prior
        except FileNotFoundError:
            restored = prior is None
        winreg.CloseKey(key)
        if created:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry) as check:
                empty = winreg.QueryInfoKey(check)[:2] == (0, 0)
            if empty:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry)
        report.update(preference_restored=restored, finished=time.time())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf8')
        print('GPU preference restored:', restored)
    return report['returncode']


if __name__ == '__main__':
    raise SystemExit(main())
