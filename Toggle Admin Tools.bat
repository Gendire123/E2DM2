@echo off
setlocal
cd /d "%~dp0"

set "ADMIN_MARKER=%~dp0.e2dm2-admin-tools"
set "BUILTIN_MARKER=%~dp0.e2dm2-builtin-admin"

:menu
cls
echo ===========================================
echo E2DM2 Developer ^& Admin Tools Configurator
echo ===========================================
echo.

if exist "%ADMIN_MARKER%" (
  echo  [1] Admin Tools:             [ ENABLED ]
) else (
  echo  [1] Admin Tools:             [ DISABLED ]
)

if exist "%BUILTIN_MARKER%" (
  echo  [2] Add to Built-in Library: [ ENABLED ]
) else (
  echo  [2] Add to Built-in Library: [ DISABLED ]
)

echo  [3] Exit
echo.
echo Note: Please restart E2DM2 for changes to take effect.
echo.

choice /C 123 /N /M "Select option (1-3) to toggle or exit: "
if errorlevel 3 goto :done
if errorlevel 2 goto :toggle_builtin
if errorlevel 1 goto :toggle_admin

:toggle_admin
if exist "%ADMIN_MARKER%" (
  del /q "%ADMIN_MARKER%"
  echo.
  echo Admin Tools are now DISABLED.
) else (
  > "%ADMIN_MARKER%" echo enabled
  echo.
  echo Admin Tools are now ENABLED.
  echo (Open View ^> Admin Tools in E2DM2 after restarting)
)
echo.
pause
goto :menu

:toggle_builtin
if exist "%BUILTIN_MARKER%" (
  del /q "%BUILTIN_MARKER%"
  echo.
  echo "Add to Built-in Library" option is now HIDDEN.
) else (
  > "%BUILTIN_MARKER%" echo enabled
  echo.
  echo "Add to Built-in Library" option is now VISIBLE.
)
echo.
pause
goto :menu

:done
echo.
echo Configuration finished.
echo.
