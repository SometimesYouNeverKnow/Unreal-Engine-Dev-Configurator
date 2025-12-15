"""Automated setup pipeline for configuring UE developer machines."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import shlex
import sys
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ue_configurator.manifest import Manifest

from ue_configurator.fix import horde as horde_fix
from ue_configurator.fix import toolchain as toolchain_fix
from ue_configurator.fix import visual_studio as vs_fix
from ue_configurator.profile import DEFAULT_PROFILE, Profile
from ue_configurator.probe import horde as horde_probe
from ue_configurator.probe import system as system_probe
from ue_configurator.probe import toolchain as toolchain_probe
from ue_configurator.probe import unreal as unreal_probe
from ue_configurator.probe.base import CheckResult, CheckStatus, ProbeContext
from ue_configurator.probe.runner import ScanData, run_scan
from ue_configurator.report.console import render_console
from ue_configurator.report.json_report import write_json
from ue_configurator.report.common import ConsoleTheme
from ue_configurator.setup.splash import maybe_show_splash
from ue_configurator.ue.build_targets import (
    build_missing_targets,
    determine_build_plan,
    missing_targets,
    summarize_plan,
)
from ue_configurator.ue.ubt_runner import UBTRunner


STATE_FILE = Path(".uecfg_state.json")


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass
class StepResult:
    status: StepStatus
    message: str = ""


CheckFunc = Callable[["SetupRuntime"], bool]
ApplyFunc = Callable[["SetupRuntime"], StepResult]


@dataclass
class SetupStep:
    id: str
    title: str
    phase: int
    requires_admin: bool
    estimated_time: int
    description: str
    check: CheckFunc
    apply: ApplyFunc


@dataclass
class SetupState:
    completed: Dict[str, str] = field(default_factory=dict)

    def is_done(self, step_id: str) -> bool:
        return step_id in self.completed

    def mark_done(self, step_id: str) -> None:
        self.completed[step_id] = datetime.now(timezone.utc).isoformat()


@dataclass
class SetupOptions:
    phases: List[int]
    apply: bool
    resume: bool
    plan_only: bool
    include_horde: bool
    use_winget: bool
    ue_root: Optional[str]
    dry_run: bool
    verbose: bool
    no_color: bool
    json_path: Optional[str]
    log_path: Path
    state_path: Path = STATE_FILE
    elevated: bool = False
    profile: Profile = DEFAULT_PROFILE
    manifest: Optional["Manifest"] = None
    manifest_source: Optional[str] = None
    ue_version: Optional[str] = None
    manifest_arg: Optional[str] = None
    show_splash: bool = True
    no_splash_flag: bool = False
    vs_passive: bool = True
    run_prereqs: bool = False
    build_engine: bool = False
    build_targets: Optional[List[str]] = None


class SetupLogger:
    """Lightweight console+file logger."""

    def __init__(self, path: Path) -> None:
        self.path = sanitize_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        line = f"[{timestamp}] {message}"
        print(message)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + os.linesep)


@dataclass
class SetupRuntime:
    options: SetupOptions
    logger: SetupLogger
    context: ProbeContext
    scan: ScanData
    state: SetupState
    start_time: float = field(default_factory=time.time)

    def refresh_scan(self) -> None:
        self.logger.log("Re-running readiness scan...")
        self.scan = run_scan(self.options.phases, self.context, self.options.profile)


def load_state(path: Path) -> SetupState:
    if not path.exists():
        return SetupState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        completed = data.get("completed", {})
        if isinstance(completed, dict):
            return SetupState(completed={str(k): str(v) for k, v in completed.items()})
    except json.JSONDecodeError:
        pass
    return SetupState()


def save_state(path: Path, state: SetupState) -> None:
    payload = {"completed": state.completed}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _get_check(scan: ScanData, check_id: str) -> Optional[CheckResult]:
    for checks in scan.results.values():
        for check in checks:
            if check.id == check_id:
                return check
    return None


def _needs_check(scan: ScanData, check_id: str) -> bool:
    check = _get_check(scan, check_id)
    if check is None:
        return False
    return check.status != CheckStatus.PASS


def _is_admin() -> bool:
    try:
        shell32 = getattr(ctypes, "windll", None)
        return bool(shell32 and shell32.shell32.IsUserAnAdmin())
    except Exception:
        return False


def build_steps(runtime: SetupRuntime) -> List[SetupStep]:
    options = runtime.options
    ctx = runtime.context
    steps: List[SetupStep] = []

    def phases_include(phase: int) -> bool:
        return phase in options.phases

    if phases_include(0) and _needs_check(runtime.scan, "os.git"):
        steps.append(
            SetupStep(
                id="install.git",
                title="Install Git",
                phase=0,
                requires_admin=options.use_winget,
                estimated_time=3,
                description="Install Git via winget (Git.Git).",
                check=lambda rt: system_probe.check_git_presence(rt.context).status == CheckStatus.PASS,
                apply=lambda rt: _apply_winget_install(rt, "Git", "Git.Git"),
            )
        )

    if phases_include(1) and _needs_check(runtime.scan, "toolchain.cmake"):
        steps.append(
            SetupStep(
                id="install.cmake_ninja",
                title="Install CMake and Ninja",
                phase=1,
                requires_admin=options.use_winget,
                estimated_time=5,
                description="Install missing CMake/Ninja components with winget.",
                check=lambda rt: toolchain_probe.check_cmake_ninja(rt.context).status == CheckStatus.PASS,
                apply=lambda rt: _apply_toolchain_extras(rt),
            )
        )

    if phases_include(1) and options.manifest:
        vs_plan = vs_fix.plan_vs_modify(ctx, options.manifest)
        if vs_plan.required:
            steps.append(
                SetupStep(
                    id="vs.manifest",
                    title="Ensure Visual Studio components (manifest)",
                    phase=1,
                    requires_admin=True,
                    estimated_time=15,
                    description="Use Visual Studio Installer CLI to add manifest-required workloads/components.",
                    check=lambda rt: not vs_fix.plan_vs_modify(rt.context, rt.options.manifest).required,
                    apply=lambda rt: _apply_vs_manifest(rt),
                )
            )

    if phases_include(1) and _needs_check(runtime.scan, "toolchain.dotnet"):
        steps.append(
            SetupStep(
                id="install.dotnet",
                title=".NET SDK",
                phase=1,
                requires_admin=options.use_winget,
                estimated_time=4,
                description="Install Microsoft .NET SDK via winget.",
                check=lambda rt: toolchain_probe.check_dotnet(rt.context).status == CheckStatus.PASS,
                apply=lambda rt: _apply_winget_install(rt, ".NET SDK", "Microsoft.DotNet.SDK.8"),
            )
        )

    if phases_include(1):
        vs_checks = [
            _get_check(runtime.scan, "toolchain.vs"),
            _get_check(runtime.scan, "toolchain.msvc"),
            _get_check(runtime.scan, "toolchain.sdk"),
        ]
        if options.manifest is None and any(check and check.status != CheckStatus.PASS for check in vs_checks):
            steps.append(
                SetupStep(
                    id="guidance.visualstudio",
                    title="Visual Studio components",
                    phase=1,
                    requires_admin=False,
                    estimated_time=2,
                    description="Review required Visual Studio workloads and install via VS Installer.",
                    check=lambda rt: _vs_ready(rt),
                    apply=lambda rt: _apply_vs_guidance(rt),
                )
            )

    if phases_include(2) and options.ue_root:
        steps.extend(_build_unreal_steps(options.ue_root, runtime))

    if phases_include(3) and options.include_horde:
        steps.append(
            SetupStep(
                id="horde.template",
                title="Generate BuildConfiguration template",
                phase=3,
                requires_admin=False,
                estimated_time=1,
                description="Create BuildConfiguration.xml for Horde/UBA.",
                check=lambda rt: bool(horde_probe._find_build_configs(rt.context)),
                apply=lambda rt: _apply_horde_template(rt),
            )
        )

    return steps


def _apply_winget_install(runtime: SetupRuntime, name: str, package_id: str) -> StepResult:
    if not runtime.options.use_winget:
        runtime.logger.log(f"[setup] winget disabled; skipping auto-install for {name}.")
        return StepResult(StepStatus.BLOCKED, f"winget disabled for {name}.")
    outcome = toolchain_fix.install_package_via_winget(runtime.context, package_id, name)
    for line in outcome.logs:
        runtime.logger.log(line)
    status = StepStatus.DONE if outcome.success else StepStatus.FAILED
    return StepResult(status, outcome.message)


def _apply_toolchain_extras(runtime: SetupRuntime) -> StepResult:
    if not runtime.options.use_winget:
        runtime.logger.log("[setup] winget disabled; skipping CMake/Ninja install.")
        return StepResult(StepStatus.BLOCKED, "winget disabled.")
    outcome = toolchain_fix.ensure_toolchain_extras(runtime.context)
    for line in outcome.logs:
        runtime.logger.log(line)
    status = StepStatus.DONE if outcome.success else StepStatus.BLOCKED
    return StepResult(status, outcome.message)


def _vs_ready(runtime: SetupRuntime) -> bool:
    checks = [
        toolchain_probe.check_visual_studio(runtime.context),
        toolchain_probe.check_msvc_toolchain(runtime.context),
        toolchain_probe.check_windows_sdks(runtime.context),
    ]
    return all(check.status == CheckStatus.PASS for check in checks)


def _apply_vs_guidance(runtime: SetupRuntime) -> StepResult:
    runtime.logger.log("[setup] Visual Studio workloads are incomplete.")
    runtime.logger.log(
        "Install the 'Desktop development with C++' workload and Windows 10/11 SDK via the Visual Studio Installer."
    )
    runtime.logger.log("Recommended command (elevated CMD): vs_installer.exe modify --add Microsoft.VisualStudio.Workload.NativeDesktop")
    return StepResult(StepStatus.BLOCKED, "Awaiting Visual Studio modifications.")


def _apply_vs_manifest(runtime: SetupRuntime) -> StepResult:
    manifest = runtime.options.manifest
    if manifest is None:
        return StepResult(StepStatus.SKIPPED, "No manifest defined.")
    outcome = vs_fix.ensure_vs_manifest_components(
        runtime.context,
        manifest,
        vs_passive=runtime.options.vs_passive,
        dry_run=runtime.options.dry_run,
        logger=runtime.logger,
    )
    status = StepStatus.DONE if outcome.success else StepStatus.BLOCKED if outcome.blocked else StepStatus.FAILED
    return StepResult(status, outcome.message)


def _build_unreal_steps(ue_root: str, runtime: SetupRuntime) -> List[SetupStep]:
    path = Path(ue_root)
    ctx = runtime.context

    def ue_exists() -> bool:
        return path.exists()

    def step_check_scripts(rt: SetupRuntime) -> bool:
        result = unreal_probe.check_setup_scripts(rt.context)
        return result.status == CheckStatus.PASS

    def run_batch(rt: SetupRuntime, script: Path | None, label: str) -> StepResult:
        if script is None:
            return StepResult(
                StepStatus.BLOCKED,
                f"{label} missing (UEPrereqSetup_x64.exe not found under Engine/Extras/Redist).",
            )
        if not script.exists():
            return StepResult(StepStatus.BLOCKED, f"{label} missing.")
        if rt.options.dry_run:
            rt.logger.log(f"[dry-run] Would run {script}")
            return StepResult(StepStatus.DONE, f"{label} dry-run complete.")
        result = rt.context.run_command(f'"{script}"', timeout=3600)
        if result.returncode == 0:
            rt.logger.log(f"[setup] {label} succeeded.")
            return StepResult(StepStatus.DONE, f"{label} completed.")
        rt.logger.log(f"[setup] {label} failed: {result.stderr or result.stdout}")
        return StepResult(StepStatus.FAILED, f"{label} failed.")

    steps: List[SetupStep] = []

    steps.append(
        SetupStep(
            id="ue.root.validate",
            title="Validate UE source tree",
            phase=2,
            requires_admin=False,
            estimated_time=1,
            description="Ensure Setup.bat and GenerateProjectFiles.bat exist.",
            check=lambda rt: ue_exists() and step_check_scripts(rt),
            apply=lambda rt: StepResult(
                StepStatus.BLOCKED,
                "UE root missing required batch files. Re-sync repository and resume.",
            ),
        )
    )

    setup_bat = path / "Setup.bat"
    gpf_bat = path / "GenerateProjectFiles.bat"
    prereq_installer = _find_prereq_installer(path)

    steps.append(
        SetupStep(
            id="ue.setup",
            title="Run UE Setup.bat",
            phase=2,
            requires_admin=False,
            estimated_time=20,
            description="Download UE prerequisites via Setup.bat.",
            check=lambda rt: rt.state.is_done("ue.setup"),
            apply=lambda rt: run_batch(rt, setup_bat, "Setup.bat"),
        )
    )

    steps.append(
        SetupStep(
            id="ue.generate-project-files",
            title="Generate project files",
            phase=2,
            requires_admin=False,
            estimated_time=10,
            description="Run GenerateProjectFiles.bat.",
            check=lambda rt: rt.state.is_done("ue.generate-project-files"),
            apply=lambda rt: run_batch(rt, gpf_bat, "GenerateProjectFiles"),
        )
    )

    steps.append(
        SetupStep(
            id="ue.run-prereq",
            title="Install UE prerequisites",
            phase=2,
            requires_admin=True,
            estimated_time=5,
            description="Locate UEPrereqSetup_x64.exe (or vc_redist.x64.exe fallback); only run when --run-prereqs is set.",
            check=lambda rt: rt.state.is_done("ue.run-prereq"),
            apply=lambda rt: _apply_prereq(rt, prereq_installer),
        )
    )

    steps.append(
        SetupStep(
            id="ue.engine-build",
            title="Engine build completeness",
            phase=2,
            requires_admin=False,
            estimated_time=45,
            description="Detect missing UE editor/helper binaries and build them via Build.bat (-WaitMutex).",
            check=lambda rt: _engine_build_ready(path, rt.options.build_targets),
            apply=lambda rt: _apply_engine_build(rt, path),
        )
    )

    return steps


def _apply_horde_template(runtime: SetupRuntime) -> StepResult:
    target = horde_fix.generate_build_configuration(runtime.context)
    runtime.logger.log(f"[setup] Horde template prepared at {target}")
    return StepResult(StepStatus.DONE, "Horde template generated.")


def _apply_prereq(runtime: SetupRuntime, installer: Path | None) -> StepResult:
    if installer is None:
        return StepResult(
            StepStatus.BLOCKED,
            "UE prerequisites installer missing under Engine/Extras/Redist.",
        )
    if not runtime.options.run_prereqs:
        return StepResult(
            StepStatus.DONE,
            f"Prereq installer located at {installer}. Not run by default; rerun with --run-prereqs to execute silently.",
        )

    if runtime.options.dry_run:
        runtime.logger.log(f"[dry-run] Would run {installer}")
        return StepResult(StepStatus.DONE, "UE prerequisites (dry-run).")

    args: Sequence[str]
    if installer.name.lower().startswith("vc_redist"):
        args = [f'"{installer}"', "/install", "/quiet", "/norestart"]
    else:
        args = [f'"{installer}"']

    result = runtime.context.run_command(" ".join(args), timeout=3600)
    if result.returncode in (0, 3010):  # 3010 = restart required
        runtime.logger.log(f"[setup] Prerequisites installer exited {result.returncode}.")
        return StepResult(StepStatus.DONE, "UE prerequisites installed.")
    if result.returncode == 1638:  # already installed
        runtime.logger.log("[setup] Prerequisites installer reports already installed (1638).")
        return StepResult(StepStatus.DONE, "UE prerequisites already installed.")
    return StepResult(
        StepStatus.FAILED,
        f"Prerequisites installer failed with exit code {result.returncode}.",
    )


def _engine_build_ready(ue_root: Path, targets: Optional[List[str]]) -> bool:
    plan = determine_build_plan(ue_root, targets)
    return not missing_targets(plan)


def _apply_engine_build(runtime: SetupRuntime, ue_root: Path) -> StepResult:
    plan = determine_build_plan(ue_root, runtime.options.build_targets)
    runtime.logger.log(f"[build] UE root: {ue_root}")
    runtime.logger.log(f"[build] Targets: {', '.join(item.target.name for item in plan)}")
    runtime.logger.log(f"[build] Plan: {summarize_plan(plan)}")
    missing = missing_targets(plan)
    if not missing:
        runtime.logger.log("[build] All required binaries already present.")
        runtime.logger.log("[build] Final status: OK (already built)")
        return StepResult(StepStatus.DONE, "Engine binaries already built.")

    if not runtime.options.build_engine:
        runtime.logger.log("[build] Build disabled (--build-engine not set).")
        runtime.logger.log(f"[build] Missing: {', '.join(item.target.name for item in missing)}")
        runtime.logger.log("[build] Final status: SKIPPED (--build-engine not set)")
        return StepResult(
            StepStatus.BLOCKED,
            f"{summarize_plan(plan)} | Missing binaries: {', '.join(item.target.name for item in missing)}. "
            "Re-run with --build-engine to build via Build.bat.",
        )

    if runtime.options.dry_run:
        runtime.logger.log("[build] Dry-run: would invoke Build.bat for missing targets.")
        runtime.logger.log("[build] Final status: DRY-RUN")
        return StepResult(StepStatus.DONE, summarize_plan(plan))

    runner = UBTRunner(ue_root)
    execution = build_missing_targets(
        ue_root,
        plan,
        runner=runner,
        logger=runtime.logger.log,
        dry_run=runtime.options.dry_run,
    )
    runtime.logger.log(f"[build] Summary: {execution.summary}")

    if execution.failed:
        target = execution.failed_target.name if execution.failed_target else "unknown"
        message = f"Build failed for {target}. {execution.summary} See log at {runtime.options.log_path}."
        return StepResult(StepStatus.FAILED, message)

    runtime.logger.log("[build] Final status: OK")
    return StepResult(StepStatus.DONE, f"{execution.summary} | status=OK")


def _find_prereq_installer(ue_root: Path) -> Path | None:
    """Locate prereq installer under Engine/Extras/Redist (any locale)."""
    search_root = ue_root / "Engine" / "Extras" / "Redist"
    if not search_root.exists():
        return None
    # Priority: UEPrereqSetup_x64.exe, then vc_redist.x64.exe, then vc_redist.arm64.exe
    candidates = [
        "UEPrereqSetup_x64.exe",
        "vc_redist.x64.exe",
        "vc_redist.arm64.exe",
    ]
    for name in candidates:
        for exe in search_root.rglob(name):
            return exe
    return None


def run_setup(options: SetupOptions) -> int:
    maybe_show_splash(options)
    options.log_path = sanitize_path(options.log_path)
    ctx = ProbeContext(
        dry_run=options.dry_run,
        verbose=options.verbose,
        ue_root=options.ue_root,
        profile=options.profile.value,
        manifest=options.manifest,
    )
    ctx.cache["engine_build_targets"] = options.build_targets
    logger = SetupLogger(options.log_path)
    logger.log(f"[setup] Log file: {options.log_path}")
    if options.elevated:
        logger.log(f"[setup] Elevated session confirmed (is_admin={_is_admin()}). Continuing setup...")
    if options.manifest:
        source = options.manifest_source or "default"
        logger.log(
            f"[setup] Using manifest {options.manifest.describe()} "
            f"(fingerprint {options.manifest.fingerprint[:12]}) from {source}"
        )
    elif options.ue_version:
        logger.log(f"[setup] Requested UE version {options.ue_version} but no manifest file was resolved.")
    if options.build_engine:
        targets = ", ".join(options.build_targets) if options.build_targets else "UnrealEditor, ShaderCompileWorker, UnrealPak, CrashReportClient"
        logger.log(f"[setup] Engine build enabled; targets: {targets}")
    options.state_path = sanitize_path(options.state_path)
    state = load_state(options.state_path) if options.resume else SetupState()

    logger.log("[setup] Running initial readiness scan...")
    scan = run_scan(options.phases, ctx, options.profile)
    runtime = SetupRuntime(options=options, logger=logger, context=ctx, scan=scan, state=state)
    from ue_configurator.reporting.startup_banner import print_startup_banner_for_runtime
    print_startup_banner_for_runtime(runtime, "setup", plan_steps=None)

    steps = build_steps(runtime)
    if not steps:
        logger.log("[setup] Nothing to do. System already satisfies requested phases.")

    _print_plan(runtime, steps)
    if options.plan_only:
        from ue_configurator.reporting.toolchain_summary import render_toolchain_summary
        summary = render_toolchain_summary(runtime.scan, runtime.options.manifest)
        if summary:
            print(summary)
        return 0

    if not options.apply:
        if not _prompt_yes_no("Proceed with the above steps?", default=True):
            logger.log("[setup] Setup aborted by user.")
            return 1
        options.apply = True

    if _needs_admin(steps, runtime) and not _is_admin() and not options.dry_run and not options.elevated:
        return _relaunch_elevated(options, logger)

    statuses: Dict[str, StepStatus] = {}
    for step in steps:
        if runtime.state.is_done(step.id):
            statuses[step.id] = StepStatus.DONE
            continue
        if step.check(runtime):
            statuses[step.id] = StepStatus.DONE
            runtime.state.mark_done(step.id)
            save_state(options.state_path, runtime.state)
            continue
        if options.plan_only or not options.apply:
            statuses[step.id] = StepStatus.PENDING
            continue
        statuses[step.id] = StepStatus.RUNNING
        _print_progress(runtime, steps, statuses, current=step.id)
        result = step.apply(runtime)
        statuses[step.id] = result.status
        logger.log(f"[setup] Step '{step.title}' -> {result.status.value}: {result.message}")
        if result.status == StepStatus.DONE:
            runtime.state.mark_done(step.id)
        save_state(options.state_path, runtime.state)
        _print_progress(runtime, steps, statuses, current=None)

    runtime.refresh_scan()
    theme = ConsoleTheme(no_color=options.no_color)
    render_console(runtime.scan, theme=theme, verbose=options.verbose)
    if options.json_path:
        output_path = sanitize_path(options.json_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(runtime.scan, str(output_path))
        logger.log(f"[setup] JSON report saved to {output_path}")
    return 0


def _prompt_yes_no(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{prompt} [{default_str}] ").strip().lower()
        if not response:
            return default
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False


def _needs_admin(steps: Iterable[SetupStep], runtime: SetupRuntime) -> bool:
    for step in steps:
        if not runtime.state.is_done(step.id) and step.requires_admin:
            if not step.check(runtime):
                return True
    return False


def _relaunch_elevated(options: SetupOptions, logger: SetupLogger) -> int:
    args = ["-m", "ue_configurator.cli", "setup"]
    args.extend(_reconstruct_cli_args(options, include_elevation_flag=True))
    printable = " ".join(shlex.quote(part) for part in ([sys.executable] + args))
    logger.log("[setup] Administrative rights are required. Launching elevated command:")
    logger.log(f"  {printable}")
    logger.log("[setup] A new elevated window will continue the setup. You can close this window.")
    params = " ".join(shlex.quote(part) for part in args)
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception as exc:  # pragma: no cover
        logger.log(f"[setup] Unable to relaunch with elevation: {exc}")
        return 1
    if ret <= 32:
        logger.log("[setup] Elevation cancelled or failed.")
        return 1
    return 0


def _reconstruct_cli_args(options: SetupOptions, *, include_elevation_flag: bool = False) -> List[str]:
    args: List[str] = []
    for phase in options.phases:
        args.extend(["--phase", str(phase)])
    if options.resume:
        args.append("--resume")
    if options.plan_only:
        args.append("--plan")
    if options.include_horde:
        args.append("--include-horde")
    args.extend(["--profile", options.profile.value])
    if options.manifest_arg:
        args.extend(["--manifest", options.manifest_arg])
    elif options.ue_version:
        args.extend(["--ue-version", options.ue_version])
    if options.use_winget:
        args.append("--use-winget")
    else:
        args.append("--no-winget")
    if options.ue_root:
        args.extend(["--ue-root", options.ue_root])
    if options.dry_run:
        args.append("--dry-run")
    if options.verbose:
        args.append("--verbose")
    if options.no_color:
        args.append("--no-color")
    if options.json_path:
        args.extend(["--json", options.json_path])
    args.extend(["--log", str(options.log_path)])
    if options.apply:
        args.append("--apply")
    if options.no_splash_flag:
        args.append("--no-splash")
    if not options.vs_passive:
        args.append("--vs-interactive")
    if options.build_engine:
        args.append("--build-engine")
    if options.build_targets:
        for target in options.build_targets:
            args.extend(["--build-target", target])
    if include_elevation_flag or options.elevated:
        args.append("--_elevated")
    return args


def _progress_bar(completed: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[" + "-" * width + "]"
    filled = int(width * (completed / total))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {completed}/{total}"


def _print_plan(runtime: SetupRuntime, steps: List[SetupStep]) -> None:
    runtime.logger.log("Setup plan:")
    for idx, step in enumerate(steps, start=1):
        runtime.logger.log(f" {idx}. {step.title} (Phase {step.phase}) — {step.description}")


def _print_progress(
    runtime: SetupRuntime,
    steps: List[SetupStep],
    statuses: Dict[str, StepStatus],
    *,
    current: Optional[str],
) -> None:
    total = len(steps)
    done = sum(1 for status in statuses.values() if status == StepStatus.DONE)
    bar = _progress_bar(done, total)
    runtime.logger.log(f"[progress] {bar}")
    if current:
        runtime.logger.log(f"[progress] Running: {current}")
def sanitize_path(value: Path | str) -> Path:
    text = str(value).strip()
    if not text:
        raise ValueError("Path value cannot be empty.")
    quotes = "\"'"
    while text and text[0] in quotes:
        text = text[1:]
    while text and text and text[-1] in quotes:
        text = text[:-1]
    text = text.strip()
    return Path(text)
