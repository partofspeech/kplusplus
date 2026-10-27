@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0install.py" %*
  goto finished
)
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 (
  python "%~dp0install.py" %*
  goto finished
)
echo Нужен Python 3.11 или новее: https://www.python.org/downloads/
pause
exit /b 1
:finished
set install_result=%errorlevel%
pause
exit /b %install_result%
