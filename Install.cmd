@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
set "kitty_result=%errorlevel%"
echo.
pause
exit /b %kitty_result%
