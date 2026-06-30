@echo off
setlocal
cd /d "%~dp0"

set "MARKER=%~dp0.e2dm2-admin-tools"

echo.
echo E2DM2 Admin Tools
echo =================
if exist "%MARKER%" (
  echo Current status: ENABLED
) else (
  echo Current status: DISABLED
)
echo.

choice /C ED /N /M "Press E to enable or D to disable: "
if errorlevel 2 goto :disable

:enable
> "%MARKER%" echo enabled
echo.
echo Admin Tools are now ENABLED for local development.
echo Restart E2DM2, then open View ^> Admin Tools.
goto :done

:disable
if exist "%MARKER%" del /q "%MARKER%"
echo.
echo Admin Tools are now DISABLED.
echo Restart E2DM2 before packaging or testing the distribution.

:done
echo.
pause
