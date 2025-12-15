@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: Minimal marker written before any directory changes or complex logic.
set "TS=%DATE%_%TIME%"
set "TS=%TS::=%"
set "TS=%TS:/=-%"
set "TS=%TS:\\=-%"
set "TS=%TS: =_%"
set "TS=%TS:.=_%"
set "TS=%TS:,=_%"
set "MARKER=%TEMP%\uecfg_launcher_started_%TS%.txt"
echo [marker] launcher: %~f0>>"%MARKER%"
echo [marker] start_cwd: %CD%>>"%MARKER%"
echo [marker] user: %USERNAME%>>"%MARKER%"
whoami /groups | find "S-1-5-32-544" >nul 2>&1 && set "ADMIN_STATE=admin" || set "ADMIN_STATE=standard"
echo [marker] admin: %ADMIN_STATE%>>"%MARKER%"
echo [marker] timestamp: %DATE% %TIME%>>"%MARKER%"

set "PAUSE_MODE=ON"
set "DEBUG_MODE=0"
set "HAS_LOG=0"
set "FORWARD_ARGS="
set "REPO_ROOT=%~dp0"
set "START_CWD=%CD%"
set "LAST_ERROR="
set "EXIT_CODE="
set "LAUNCH_LOG="
set "PUSHD_OK="
set "FINAL_CWD="

if not defined REPO_ROOT (
    set "LAST_ERROR=ERROR: Could not resolve launcher directory (%%~dp0 empty)."
    set "EXIT_CODE=1"
    goto fail
)

pushd "%REPO_ROOT%" >nul 2>&1
if errorlevel 1 (
    set "LAST_ERROR=ERROR: Unable to change to launcher directory: "%REPO_ROOT%"."
    set "EXIT_CODE=1"
    goto fail
)
set "PUSHD_OK=1"
set "REPO_ROOT=%CD%"
set "IMPORT_ROOT=%REPO_ROOT%\src"
echo [marker] repo_root: %REPO_ROOT%>>"%MARKER%"
echo [marker] cwd_after_pushd: %CD%>>"%MARKER%"
echo [marker] import_root: %IMPORT_ROOT%>>"%MARKER%"

:: Prepare launcher log early so every path records context.
set "TS2=%DATE%_%TIME%"
set "TS2=%TS2::=%"
set "TS2=%TS2:/=-%"
set "TS2=%TS2:\\=-%"
set "TS2=%TS2: =_%"
set "TS2=%TS2:.=_%"
set "TS2=%TS2:,=_%"
set "LOG_DIR=%REPO_ROOT%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if errorlevel 1 set "LOG_DIR=%TEMP%\uecfg_launcher"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%LOG_DIR%" set "LOG_DIR=%TEMP%"
set "LAUNCH_LOG=%LOG_DIR%\uecfg_launcher_%TS2%.log"
echo [launcher] launcher: %~f0>>"%LAUNCH_LOG%"
echo [launcher] marker: %MARKER%>>"%LAUNCH_LOG%"
echo [launcher] start_cwd: %START_CWD%>>"%LAUNCH_LOG%"
echo [launcher] repo: %REPO_ROOT%>>"%LAUNCH_LOG%"
echo [launcher] cwd_after_pushd: %CD%>>"%LAUNCH_LOG%"
echo [launcher] import_root: %IMPORT_ROOT%>>"%LAUNCH_LOG%"
echo [launcher] admin: %ADMIN_STATE%>>"%LAUNCH_LOG%"
echo [marker] launch_log: %LAUNCH_LOG%>>"%MARKER%"

:: Parse args
:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--no-pause" set "PAUSE_MODE=OFF" & shift & goto parse_args
if /I "%~1"=="--pause" set "PAUSE_MODE=ON" & shift & goto parse_args
if /I "%~1"=="--debug" set "DEBUG_MODE=1" & shift & goto parse_args
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
if "%DEBUG_MODE%"=="1" set "PAUSE_MODE=ON"

if not exist "%IMPORT_ROOT%\ue_configurator" (
    set "LAST_ERROR=ERROR: Expected package under "%IMPORT_ROOT%"."
    set "EXIT_CODE=1"
    goto fail
)

if "%DEBUG_MODE%"=="1" echo [setup] DEBUG mode enabled.

set "PY_CMD="
set "PY_DESC="
py -3 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3" && set "PY_DESC=Windows py launcher"
if not defined PY_CMD (
    python -c "import sys" >nul 2>&1 && set "PY_CMD=python" && set "PY_DESC=python on PATH"
)
if not defined PY_CMD (
    set "LAST_ERROR=ERROR: Python 3.9+ not found."
    set "EXIT_CODE=1"
    goto fail
)
set "PY_EXE="
for /f "delims=" %%p in ('%PY_CMD% -c "import sys; print(sys.executable)"') do set "PY_EXE=%%p"
if not defined PY_EXE set "PY_EXE=%PY_CMD%"
echo [launcher] python_cmd: %PY_CMD%>>"%LAUNCH_LOG%"
echo [launcher] python_exe: %PY_EXE%>>"%LAUNCH_LOG%"

:: Validate PY_EXE has no embedded quotes.
set "TMP_PY=%PY_EXE%"
if not "%TMP_PY:"=%"=="%TMP_PY%" (
    set "LAST_ERROR=ERROR: PY_EXE contains embedded quotes: [%PY_EXE%]"
    set "EXIT_CODE=1"
    goto fail
)

set "PYTHONPATH=%IMPORT_ROOT%"
set "PYTHONNOUSERSITE=1"
echo [launcher] pythonpath: %PYTHONPATH%>>"%LAUNCH_LOG%"

set "EXTRA_LOG="
if "%HAS_LOG%"=="0" (
    set "CLI_LOG=%REPO_ROOT%\logs\uecfg_setup_%TS2%.log"
) else (
    set "CLI_LOG=%LOG_VALUE%"
)
set "EXTRA_LOG= --log \"%CLI_LOG%\""
echo [launcher] cli_log: %CLI_LOG%>>"%LAUNCH_LOG%"

set "CMDLINE=%PY_EXE% -m ue_configurator.cli setup%FORWARD_ARGS%%EXTRA_LOG%"
echo [launcher] cmd: "%PY_EXE%" -m ue_configurator.cli setup%FORWARD_ARGS%%EXTRA_LOG%>>"%LAUNCH_LOG%"
echo [marker] command: "%PY_EXE%" -m ue_configurator.cli setup%FORWARD_ARGS%%EXTRA_LOG%>>"%MARKER%"

call "%PY_EXE%" -m ue_configurator.cli setup %FORWARD_ARGS%%EXTRA_LOG%
set "EXIT_CODE=%ERRORLEVEL%"
set "FINAL_CWD=%CD%"
if not "%EXIT_CODE%"=="0" (
    set "LAST_ERROR=Python setup command failed with exit %EXIT_CODE%."
    goto fail
)
echo [launcher] final_cwd: %FINAL_CWD%>>"%LAUNCH_LOG%"
echo [launcher] exit: %EXIT_CODE%>>"%LAUNCH_LOG%"
echo [marker] exit: %EXIT_CODE%>>"%MARKER%"

echo [setup] Completed. Log: %LAUNCH_LOG%
if "%DEBUG_MODE%"=="1" (
    echo [setup] DEBUG: Keeping window open.
    cmd /k
) else if "%PAUSE_MODE%"=="ON" (
    pause
)
goto end

:fail
if not defined LAUNCH_LOG (
    set "LOG_DIR=%TEMP%\uecfg_launcher"
    if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
    if not exist "%LOG_DIR%" set "LOG_DIR=%TEMP%"
    set "LAUNCH_LOG=%LOG_DIR%\uecfg_launcher_%TS%_fail.log"
    echo [launcher] launcher: %~f0>>"%LAUNCH_LOG%"
    echo [launcher] marker: %MARKER%>>"%LAUNCH_LOG%"
    echo [launcher] start_cwd: %START_CWD%>>"%LAUNCH_LOG%"
    if defined REPO_ROOT echo [launcher] repo: %REPO_ROOT%>>"%LAUNCH_LOG%"
    if defined ADMIN_STATE echo [launcher] admin: %ADMIN_STATE%>>"%LAUNCH_LOG%"
)
if not defined LAST_ERROR set "LAST_ERROR=Unknown launcher failure."
if "%EXIT_CODE%"=="" set "EXIT_CODE=1"
if not defined FINAL_CWD set "FINAL_CWD=%CD%"
if defined LAST_ERROR (
    echo [setup] %LAST_ERROR%
    echo [marker] error: %LAST_ERROR%>>"%MARKER%"
    if defined LAUNCH_LOG echo [launcher] error: %LAST_ERROR%>>"%LAUNCH_LOG%"
)
echo [marker] failure_exit: %EXIT_CODE%>>"%MARKER%"
echo [marker] exit: %EXIT_CODE%>>"%MARKER%"
if defined LAUNCH_LOG (
    echo [launcher] final_cwd: %FINAL_CWD%>>"%LAUNCH_LOG%"
    echo [launcher] exit: %EXIT_CODE%>>"%LAUNCH_LOG%"
    echo [setup] Launcher log: %LAUNCH_LOG%
)
echo [setup] FAILED (exit %EXIT_CODE%). Marker: %MARKER%
if "%DEBUG_MODE%"=="1" (
    echo [setup] DEBUG: Keeping window open after failure.
    cmd /k
) else (
    pause
)

:end
if defined PUSHD_OK popd >nul 2>&1
exit /b %EXIT_CODE%
