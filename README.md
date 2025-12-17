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

Quick Start (Windows)
---------------------
### A. Scan-only (no installs)
1. Double-click `run_uecfg.bat`. The launcher prints a timestamped header, shows the chosen Python interpreter, and pauses at the end so you can read the output before closing.
2. Or run from an existing shell:
   ```powershell
   python -m ue_configurator.cli scan --phase 0 --no-color
   ```
   Expect a Phase 0 readiness score plus "Next actions" suggestions. Provide `--json <path>` if you need an artifact for support tickets.

### B. Recommended workflow (scan -> dry-run fix -> apply fix -> rescan)
```powershell
uecfg scan --phase 0 --no-color
uecfg scan --phase 1 --no-color
uecfg fix --phase 1 --dry-run
# elevated PowerShell (Start-Process powershell -Verb runAs)
uecfg fix --phase 1 --apply
uecfg scan --phase 1 --json reports\phase1-after.json
```
- Start with scans to detect issues.
- Use `--dry-run` to preview winget commands; nothing installs yet.
- Switch to an elevated shell before `--apply` so winget can install CMake/Ninja.
- Re-run the scan (optionally with `--json`) to confirm the fixes and capture evidence.

Double-click Setup
------------------
- Launch `run_setup.bat` to open the guided wizard. It will:
  1. Run a scan across the requested phases.
  2. Present a plan (Git, CMake, Ninja, .NET SDK, UE scripts, Horde template).
  3. Ask for consent, UE root path, and whether to include Horde/UBA checks.
  4. Elevate via UAC if installs are requested.
  5. Execute the plan, stream logs to `logs\uecfg_setup_<timestamp>.log`, resume from `.uecfg_state.json` if rerun, and save a JSON report to `reports\uecfg_report_<timestamp>.json`.
- Setup greets interactive users with a short tongue-in-cheek ASCII skull splash. Skip it with `uecfg setup --no-splash` (or pass `--no-splash` to `run_setup.bat`) or set `UECFG_NO_SPLASH=1` for scripting environments.
- When a UE manifest is selected (`--ue-version 5.7` or `--manifest ...`), setup can modify Visual Studio automatically by generating a `.vsconfig` and running the official installer (`setup.exe modify --config ...`). Consent + elevation are required, and you can force the UI with `--vs-interactive`.
- From any shell you can run the same workflow with more control:

```powershell
uecfg setup --plan --phase 0 --phase 1
uecfg setup --apply --phase 0 --phase 1 --json reports\setup_after.json
uecfg setup --resume --apply --phase 1 --phase 2 --ue-root D:\UnrealEngine
```
- Validation commands (non-interactive friendly):
  ```powershell
  python -m ue_configurator.cli setup --plan --dry-run --no-color
  python -m ue_configurator.cli setup --dry-run --no-color --use-winget --apply
  ```

- Use `run_setup.bat --no-pause ...` or set `UECFG_NO_PAUSE=1` if you do not want the launcher to wait for a key press at the end.

Shared DDC / Distributed Shaders
--------------------------------
- The setup wizard now offers a **Configure Shared DDC / Distributed Shaders** intent alongside configure/build/register.
- You can target user-global (`%APPDATA%\Unreal Engine\UnrealBuildTool\BuildConfiguration.xml` + per-user DerivedDataCache.ini), engine-global (writes under `Engine/` in the provided UE root), or both.
- The workflow prompts for a shared DDC path (prefers existing config values; otherwise shows a placeholder), optional local fallback, shows a diff-style preview, and backs up any touched files with timestamps. UNC paths are written without probing the network unless you request verification.
- Distributed shader settings are derived from the UnrealBuildTool XML schema in your UE source tree so unknown keys are never written; every proposed value can be overridden or skipped before apply.
- Optional verification is available via `--verify-ddc` (read-only) or `--verify-ddc-write-test` (create/delete a tiny file). Skipping verification prints a reminder that Unreal will try the shared cache at next launch.
- Reruns are idempotent—if the requested DDC/share + shader flags are already present, it reports that nothing changed and exits cleanly.

Horde setup helper (post-compile)
---------------------------------
- The setup wizard includes a **Horde setup helper (post-compile)** intent that audits Horde agent status, distributed shader settings, and shared DDC after the engine/toolchain is working.
- Default mode is audit-only and read-only; apply mode previews diffs, backs up any files it touches, and only writes after confirmation.
- Endpoint/pool/DDC path prompts only prefill detected values; leaving a prompt blank skips that write.
- Optional verification flags: `--verify-horde`, `--verify-ddc`, and `--verify-ddc-write-test`.
- After a successful engine build in the setup wizard, it can offer to run the helper (audit first, then apply).

Making a source build runnable (ShaderCompileWorker etc.)
--------------------------------------------------------
- Phase 2 now reports **Engine Build Completeness** with PASS/WARN outcomes for the default Win64 Development targets (UnrealEditor, ShaderCompileWorker, UnrealPak, CrashReportClient).
- Run `uecfg setup --apply --phase 2 --ue-root D:\UnrealEngine --build-engine` to build only the missing binaries via `Engine/Build/BatchFiles/Build.bat <Target> Win64 Development -WaitMutex`. Existing binaries are skipped; failures stop the sequence and point to the log.
- Override the target list with repeated `--build-target <Name>` flags when you need a narrower build (e.g., only ShaderCompileWorker).
- Re-run safely after interruptions; the summary prints SKIP/BUILD per target plus the log path.

Profiles
--------
- Select machine roles with `--profile` (or set `UECFG_PROFILE=agent`):

```powershell
uecfg scan --profile agent --phase 0 --phase 1
uecfg setup --profile agent --apply --include-horde
uecfg scan --profile minimal --phase 0
```

- **workstation** (default): targets UE dev PCs. Phase 0/1/2 count toward readiness.
- **agent**: for Horde/CI builders. Phase 2 is N/A unless you pass `--ue-root`; Phase 3 recommendations highlight Horde readiness.
- **minimal**: baseline sanity checks. Phase 0 required, Phase 1 optional, Phases 2/3 marked N/A so they do not affect scores.

Toolchain manifests
-------------------
- Versioned manifests live under `manifests/` (schema documented in `manifests/schema.json`). Each file pins the Visual Studio major/build, MSVC toolset family, Windows SDKs, and auxiliary tools (Git, CMake, Ninja, .NET) for a given Unreal Engine release line.
- Run audits against a manifest with `--ue-version <major.minor>` or point to a custom file via `--manifest <path>`. Example commands:
  ```powershell
  uecfg scan --profile agent --phase 0 --phase 1 --ue-version 5.7
  uecfg setup --profile agent --ue-version 5.7 --plan
  uecfg setup --profile agent --ue-version 5.7 --apply --include-horde
  ```
- When `--ue-root` is provided, `uecfg` auto-detects the UE version from `Engine/Build/Build.version`. Otherwise the setup wizard prompts for the version (defaulting to the latest manifest) so double-clicking `run_setup.bat` still produces a strict plan.
- Manifest metadata (ID, UE version, fingerprint) is included in console and JSON output. A compliance check runs in Phase 1 and produces PASS/WARN/FAIL verdicts plus actionable instructions (e.g., Visual Studio components to add). Non-applicable phases are marked `N/A` so profiles such as `agent` are not penalized for missing UE source trees.
- **UE 5.7 baseline:** Visual Studio 2022 (major 17, >=17.8 with 17.14 recommended), MSVC 14.44 toolset, and Windows SDK 10.0.22621.0. Required VS Installer IDs are encoded directly in `manifests/ue_5.7.json`.

CLI overview
------------

```
uecfg scan [--phase 0 --phase 1 --phase 2 --phase 3] [--ue-root <path>] [--ue-version <x.y>] [--manifest <file>] [--dry-run] [--json <path>] [--verbose] [--no-color]
uecfg fix  --phase <n> [--apply] [--dry-run]
uecfg verify --ue-root <path> [--ue-version <x.y>] [--json <path>] [--dry-run]
uecfg setup [--phase ...] [--plan] [--apply] [--resume] [--ue-root <path>] [--ue-version <x.y>] [--manifest <file>] [--include-horde] [--build-engine] [--build-target <Name>]
```

- `scan` runs audit probes. By default phases 0-2 execute; include `--phase 3` to opt into the Horde/UBA checks. Add `--ue-version 5.7` (or `--manifest manifests\ue_5.7.json`) to require manifest compliance.
- `fix` surfaces recommended actions for the requested phase and, when `--apply` is present, performs guarded helpers such as generating Horde templates or modifying Visual Studio to match a manifest. Without `--apply`, commands are only printed. Use `--vs-interactive` if you want the Visual Studio Installer UI instead of the passive mode.
- `verify` focuses on a provided Unreal Engine source root and ensures `Setup.bat`, `GenerateProjectFiles.bat`, and redist installers are ready to run.
- `setup` orchestrates scans, installs, confirmations, elevation, and resume-friendly state tracking. Use `--plan` to see the plan, `--apply` to skip prompts, and `--resume` to continue after manual steps. When `--ue-version` is present (or detected), every step references the manifest so reruns stay deterministic. Control Visual Studio Installer mode with `--vs-interactive` / `--vs-passive`. Engine builds stay opt-in; add `--build-engine` (and optional `--build-target`) to build missing editor/helper binaries via Build.bat.

Every command accepts `--dry-run` (default) to prevent writes, `--json <path>` to emit machine logs, `--verbose` for detailed evidence, and `--no-color` to disable ANSI styling.

Auto-fix (Phase 1)
------------------
- **What it fixes automatically:** Missing Git, CMake, Ninja, and Microsoft .NET SDK can be installed via `winget` when you confirm either in `uecfg fix --phase 1 --apply` or during the setup wizard. Everything honours `--dry-run`.
- **Visual Studio via manifest:** `uecfg fix --phase 1 --ue-version 5.7 --apply` (or the setup wizard with a selected manifest) will generate a `.vsconfig`, locate `setup.exe`, and run `setup.exe modify --config ...` automatically. Use `--vs-interactive` if you prefer to watch the installer UI.
- **What stays manual/guided:** Windows SDK-only installs and Unreal Engine source sync remain guided - uecfg prints precise command lines (`Setup.bat`, etc.) and lets you resume once they're done.
- **Dry-run previews:** `uecfg fix --phase 1 --dry-run` (or the setup wizard in dry-run mode) prints `[dry-run] Would run: ...` so you can copy/paste the exact winget command or hand it to IT.
- **winget missing-** The fixer detects that scenario and prints manual instructions rather than failing.
- **Admin expectations:** Installing packages requires an elevated PowerShell window (UAC prompt). If you stay non-elevated, the fixer reminds you to re-run with elevation.
- **Verify after apply:** `uecfg scan --phase 1 --json reports\phase1-after.json` captures evidence that CMake/Ninja are present.

Troubleshooting
---------------
- **The batch file opens and closes immediately**  
  Both launchers pause by default so you can read the log. Disable the pause with `run_uecfg.bat --no-pause ...`, `run_setup.bat --no-pause ...`, or set `UECFG_NO_PAUSE=1` in environments where a pause is undesirable. Use `--pause` to force the prompt even when the environment variable is set.
- **winget not found**  
  Install/repair "App Installer" from the Microsoft Store, then run `winget source update`. Until winget works, `uecfg fix` falls back to printing the `winget install --id ...` commands so you can run them later.
- **Multiple Visual Studio installs detected**  
  The scan lists every instance discovered by `vswhere`. Pick the install path you want to use inside the Visual Studio Installer UI; `uecfg` simply surfaces evidence and leaves configuration to you.
- **Resuming after interruption**  
  Every setup run writes `.uecfg_state.json`. Re-run `uecfg setup --resume --apply` (or double-click `run_setup.bat` again and answer "Yes" when prompted) to skip completed steps. Logs stay under `logs\` with timestamps so you can review previous attempts.

What gets installed vs guided
-----------------------------
- **Automated via winget (with consent):** Git (`Git.Git`), CMake (`Kitware.CMake`), Ninja (`Ninja-build.Ninja`), Microsoft .NET SDK (`Microsoft.DotNet.SDK.8`), Unreal prerequisites installer (`UEPrereqSetup_x64.exe`), and the Horde `BuildConfiguration.xml` template.
- **Automated via Visual Studio Installer:** When a manifest is selected, `setup`/`fix` generate a `.vsconfig` and run `setup.exe modify --installPath <...> --config <...>` to add missing workloads/components (defaults to `--passive`, opt into UI with `--vs-interactive`).
- **Guided/manual:** Windows SDK-only additions, UE `Setup.bat` / `GenerateProjectFiles.bat` syncs (uecfg can execute them for you but still shows the commands), and Horde/UBA services. When automation isn't possible, the setup wizard marks the step as BLOCKED, prints exact commands, and lets you resume once the manual work is finished.

How it works
------------
1. **Probe modules** (under `src/ue_configurator/probe/`) each perform single-purpose checks and emit structured `CheckResult` objects that include evidence, remediation guidance, and optional follow-up actions.
2. The **scan runner** orchestrates probes per phase, computes readiness scores, and forwards the results to console / JSON renderers.
3. **Reporting** modules summarize PASS/WARN/FAIL outcomes with descriptions, evidence snippets, and "next action" commands that can be copy/pasted.
4. **Fix helpers** are opt-in and conservative. They primarily create configuration templates or show the exact command necessary to install a missing dependency, never invoking installers automatically unless the user explicitly runs them.

Testing
-------

```
pytest
```

The test suite covers the most complex probe logic (e.g., readiness scoring and action planning) with deterministic inputs so it can run on machines without the full Unreal dependency stack.
