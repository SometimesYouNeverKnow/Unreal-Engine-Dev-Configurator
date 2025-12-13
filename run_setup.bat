@echo off
setlocal enableextensions enabledelayedexpansion

cd /d "%~dp0"
set "REPO_DIR=%CD%"

set "PY_CMD="
py -3 -c "import sys" >nul 2>&1
if "%errorlevel%"=="0" (
    set "PY_CMD=py -3"
) else (
    python -c "import sys" >nul 2>&1
    if "%errorlevel%"=="0" (
        set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo [setup] Python 3.9+ is required but not found.
    pause
    exit /b 1
)

set "PAUSE_MODE=ON"
set "HAS_LOG=0"
set "FORWARD_ARGS="
:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--no-pause" (
    set "PAUSE_MODE=OFF"
    shift
    goto parse_args
)
if /I "%~1"=="--pause" (
    set "PAUSE_MODE=ON"
    shift
    goto parse_args
)
if /I "%~1"=="--log" (
    set "HAS_LOG=1"
    set "LOG_VALUE=%~2"
    if "%LOG_VALUE%"=="" goto args_done
    set "FORWARD_ARGS=!FORWARD_ARGS! --log \"%LOG_VALUE%\""
    shift
    shift
    goto parse_args
)
set "FORWARD_ARGS=!FORWARD_ARGS! "%~1""
shift
goto parse_args

:args_done
if /I "%UECFG_NO_PAUSE%"=="1" set "PAUSE_MODE=OFF"

for /f "usebackq tokens=*" %%t in (`powershell -NoLogo -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set "TIMESTAMP=%%t"
if not defined TIMESTAMP set "TIMESTAMP=%date%_%time%"
if "%HAS_LOG%"=="0" (
    if not exist "%REPO_DIR%\logs" mkdir "%REPO_DIR%\logs" >nul 2>&1
    set "LOG_PATH=%REPO_DIR%\logs\uecfg_setup_%TIMESTAMP%.log"
) else (
    set "LOG_PATH=%LOG_VALUE%"
)

set "EXTRA_LOG="
if "%HAS_LOG%"=="0" set "EXTRA_LOG= --log \"%LOG_PATH%\""

call %PY_CMD% -m ue_configurator.cli setup !FORWARD_ARGS!%EXTRA_LOG%
set "EXIT_CODE=%ERRORLEVEL%"
echo [setup] Log file: %LOG_PATH%

if "%PAUSE_MODE%"=="ON" (
    echo.
    echo Press any key to close...
    pause >nul
)
exit /b %EXIT_CODE%
