@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :error
echo.
echo E2DM2 is ready. Use Run E2DM2.cmd to launch it.
pause
exit /b 0
:error
echo.
echo E2DM2 setup failed. Review the messages above.
pause
exit /b 1

