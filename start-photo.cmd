@echo off
cd /d "%~dp0"
set "PHOTO_PYTHON=F:\gymenv\python.exe"
if not exist "%PHOTO_PYTHON%" set "PHOTO_PYTHON=python"
"%PHOTO_PYTHON%" -B tools\run_editor.py --scene examples\pompeii\native-photo.json
if errorlevel 1 pause
