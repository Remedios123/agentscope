@echo off
setlocal

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1" %*
set "startupExitCode=%errorlevel%"
if not "%startupExitCode%"=="0" (
    echo.
    echo AgentScope startup failed. See the error message above.
    pause
)

endlocal & exit /b %startupExitCode%
