@echo off
rem Double-click launcher for start.ps1 (all parameters are passed through, e.g. start.bat -SkipTests -Port 8080).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "RC=%ERRORLEVEL%"
rem Keep the window open on failure so the message can be read (double-click case).
if not "%RC%"=="0" pause
exit /b %RC%
