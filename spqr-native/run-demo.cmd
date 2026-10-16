@echo off
cd /d "%~dp0"
bin\spqr-native.exe --bundle assets --output demo-output --route walk --seconds 3600 --smooth-camera --vsync --samples 4
if errorlevel 1 pause
