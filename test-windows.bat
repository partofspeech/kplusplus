@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if exist ".venv-windows-tests\Scripts\python.exe" goto dependencies
py -3 -m venv .venv-windows-tests
if not errorlevel 1 goto dependencies
python -m venv .venv-windows-tests
if errorlevel 1 goto failed
:dependencies
".venv-windows-tests\Scripts\python.exe" -m pip install -e ".[test]"
if errorlevel 1 goto failed
".venv-windows-tests\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto failed
set SCRAPER_GUI_TESTS=1
set SCRAPER_OFFLINE_BROWSER_TESTS=1
".venv-windows-tests\Scripts\python.exe" -m pytest tests -q --junitxml=artifacts/windows-local-tests.xml
if errorlevel 1 goto failed
echo Проверки завершены успешно.
pause
exit /b 0
:failed
echo Проверки не завершены. См. сообщение об ошибке выше.
pause
exit /b 1
