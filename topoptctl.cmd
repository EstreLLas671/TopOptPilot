@echo off
setlocal
chcp 65001 >nul
set "TOPPILOTCTL_ROOT=%~dp0"
if exist "%TOPPILOTCTL_ROOT%.venv\Scripts\python.exe" (
  "%TOPPILOTCTL_ROOT%.venv\Scripts\python.exe" "%TOPPILOTCTL_ROOT%topoptctl.py" %*
) else (
  py -3 "%TOPPILOTCTL_ROOT%topoptctl.py" %*
)
exit /b %ERRORLEVEL%
