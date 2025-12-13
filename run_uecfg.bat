@echo off
setlocal enableextensions

rem Change to repo root (location of this script)
cd /d "%~dp0"

set "PY_CMD="

rem Prefer the Windows Python launcher
py -3 -c "import sys" >nul 2>&1
if "%errorlevel%"=="0" (
    set "PY_CMD=py -3"
) else (
    rem Fall back to python on PATH
    python -c "import sys" >nul 2>&1
    if "%errorlevel%"=="0" (
        set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo [uecfg] Python 3.9+ is required but not found.>&2
    exit /b 1
)

%PY_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [uecfg] Python 3.9+ is required. Current interpreter is %PY_CMD%.>&2
    exit /b 1
)

%PY_CMD% -m ue_configurator.cli scan %*
