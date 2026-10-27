@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Сначала запустите install-windows.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m interfaces.web.app
set app_result=%errorlevel%
pause
exit /b %app_result%
