@echo off
setlocal enableextensions enabledelayedexpansion

cd /d "%~dp0"
set "REPO_DIR=%CD%"

set "FORWARD_ARGS="
set "PAUSE_FLAG="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--no-pause" (
    set "PAUSE_FLAG=OFF"
    shift
    goto parse_args
)
if /I "%~1"=="--pause" (
    set "PAUSE_FLAG=ON"
    shift
    goto parse_args
)
set "FORWARD_ARGS=!FORWARD_ARGS! "%~1""
shift
goto parse_args

:args_done
if "%PAUSE_FLAG%"=="ON" (
    set "PAUSE_MODE=ON"
) else if "%PAUSE_FLAG%"=="OFF" (
    set "PAUSE_MODE=OFF"
) else if /I "%UECFG_NO_PAUSE%"=="1" (
    set "PAUSE_MODE=OFF"
) else (
    set "PAUSE_MODE=ON"
)

for /f "usebackq delims=" %%i in (`powershell -NoLogo -NoProfile -Command "Get-Date -Format o" 2^>nul`) do set "UECFG_TIMESTAMP=%%i"
if not defined UECFG_TIMESTAMP set "UECFG_TIMESTAMP=%date% %time%"

echo [uecfg] Unreal Engine Dev Configurator launcher
echo [uecfg] Repository: %REPO_DIR%
echo [uecfg] Timestamp: %UECFG_TIMESTAMP%

set "PY_CMD="

py -3 -c "import sys" >nul 2>&1
if "%errorlevel%"=="0" (
    set "PY_CMD=py -3"
    set "PY_DESC=Windows Python launcher (py -3)"
) else (
    python -c "import sys" >nul 2>&1
    if "%errorlevel%"=="0" (
        set "PY_CMD=python"
        set "PY_DESC=python on PATH"
    )
)

if not defined PY_CMD (
    echo [uecfg] ERROR: Python 3.9+ is required but was not found.
    echo [uecfg] Install Python from https://www.python.org/downloads/windows/ or enable the 'py' launcher.
    set "EXIT_CODE=1"
    goto finalize
)

%PY_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [uecfg] ERROR: Interpreter %PY_CMD% is older than Python 3.9. Please install Python 3.9+.
    set "EXIT_CODE=1"
    goto finalize
)

echo [uecfg] Using interpreter: %PY_DESC%
echo [uecfg] Command: %PY_CMD% -m ue_configurator.cli scan!FORWARD_ARGS!

call %PY_CMD% -m ue_configurator.cli scan!FORWARD_ARGS!
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo [uecfg] Scan completed successfully.
) else (
    echo [uecfg] Scan failed with exit code %EXIT_CODE%.
)

:finalize
if "%PAUSE_MODE%"=="ON" (
    echo.
    echo Press any key to close...
    pause >nul
)

exit /b %EXIT_CODE%
