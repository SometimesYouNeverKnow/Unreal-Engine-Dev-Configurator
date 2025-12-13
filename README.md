# Unreal Engine Dev Configurator
Unreal Engine Dev Configurator
==============================

`uecfg` is a Windows-first audit and guidance tool that verifies whether a machine is ready to build Unreal Engine from source and compile downstream UE projects. It focuses on discoverability, evidence-rich reporting, and repeatable remediation steps that work across many developer workstations.

Key capabilities
----------------
- Detects operating system, hardware, and baseline tooling needed for Epic's source build flow (Phase 0).
- Verifies Visual Studio, Windows SDK, .NET, CMake/Ninja, and other compilation toolchains using discovery commands such as `vswhere`, `where.exe`, and registry queries (Phase 1).
- Audits Unreal Engine source trees (when provided) and reports the exact scripts/commands necessary to complete `Setup.bat`, `GenerateProjectFiles.bat`, and editor builds (Phase 2).
- Provides an optional Horde / Unreal Build Accelerator readiness module that inventories BuildConfiguration.xml files and can generate a safe template when explicitly requested (Phase 3).
- Produces both human-friendly console output with phase progress bars and machine-readable JSON for CI or support ticket attachments.
- Guards every mutation behind `--dry-run` (default) / `--apply` switches and never assumes installation paths.

Installation
------------
The project targets Python 3.10+ and uses the standard library only. Install it in editable mode from the repository root:

```powershell
py -3 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -e .
```

Quick start
-----------
- Double-click `run_uecfg.bat` to run the default scan; the launcher prints a timestamped header, shows the chosen Python interpreter, and pauses at the end so you can read the output before closing.
- When running from an existing terminal (PowerShell/CMD/Git Bash) or CI system, disable the pause by either passing `--no-pause` (batch-only flag) or exporting `UECFG_NO_PAUSE=1`. Use `--pause` to force the pause even if the environment variable is set.
- All additional arguments are forwarded to `uecfg scan`, so you can run smoke checks directly:

```
run_uecfg.bat --phase 0 --no-color
run_uecfg.bat --no-pause --phase 0 --no-color
run_uecfg.bat --phase 0 --json artifacts\ue-scan.json
```

- The first two commands above are quick smoke checks to verify the launcher works with and without the pause behavior enabled.

- For unattended validation, capture JSON and logs in one go. For interactive discovery, simply double-click and follow the prompts.

CLI overview
------------

```
uecfg scan [--phase 0 --phase 1 --phase 2 --phase 3] [--ue-root <path>] [--dry-run] [--json <path>] [--verbose] [--no-color]
uecfg fix  --phase <n> [--apply] [--dry-run]
uecfg verify --ue-root <path> [--json <path>] [--dry-run]
```

- `scan` runs audit probes. By default phases 0‑2 execute; include `--phase 3` to opt into the Horde/UBA checks.
- `fix` surfaces recommended actions for the requested phase and, when `--apply` is present, performs guarded helpers such as generating Horde templates. Without `--apply`, commands are only printed.
- `verify` focuses on a provided Unreal Engine source root and ensures `Setup.bat`, `GenerateProjectFiles.bat`, and redist installers are ready to run.

Every command accepts `--dry-run` (default) to prevent writes, `--json <path>` to emit machine logs, `--verbose` for detailed evidence, and `--no-color` to disable ANSI styling.

How it works
------------
1. **Probe modules** (under `src/ue_configurator/probe/`) each perform single-purpose checks and emit structured `CheckResult` objects that include evidence, remediation guidance, and optional follow-up actions.
2. The **scan runner** orchestrates probes per phase, computes readiness scores, and forwards the results to console / JSON renderers.
3. **Reporting** modules summarize PASS/WARN/FAIL outcomes with descriptions, evidence snippets, and “next action” commands that can be copy/pasted.
4. **Fix helpers** are opt-in and conservative. They primarily create configuration templates or show the exact command necessary to install a missing dependency, never invoking installers automatically unless the user explicitly runs them.

Testing
-------

```
pytest
```

The test suite covers the most complex probe logic (e.g., readiness scoring and action planning) with deterministic inputs so it can run on machines without the full Unreal dependency stack.
