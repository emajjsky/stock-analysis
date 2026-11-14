@echo off
setlocal
cd /d "%~dp0desktop"
if not exist "node_modules\electron\dist\electron.exe" (
  echo Please run npm ci in the desktop folder first.
  pause
  exit /b 1
)
start "" "node_modules\electron\dist\electron.exe" "."
