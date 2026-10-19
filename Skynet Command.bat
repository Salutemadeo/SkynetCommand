@echo off
if not exist "%~dp0runtime\python\pythonw.exe" (
  echo Run "1 - SETUP (run once).bat" first.
  pause
  exit /b 1
)
start "" "%~dp0runtime\python\pythonw.exe" "%~dp0app\skynet_command.py"
