"""Command line interface for the Unreal Engine Dev Configurator."""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime
import os
from pathlib import Path
import shlex
import sys
from typing import Iterable, List, Sequence

from ue_configurator import __version__
from ue_configurator.fix import horde as horde_fix
from ue_configurator.fix import toolchain as toolchain_fix
from ue_configurator.fix import visual_studio as vs_fix
from ue_configurator.manifest import available_manifests, resolve_manifest
from ue_configurator.profile import DEFAULT_PHASES, Profile, resolve_profile
from ue_configurator.runtime.single_instance import (
    SingleInstanceError,
    acquire_single_instance_lock,
)
from ue_configurator.setup.pipeline import SetupOptions, run_setup
from ue_configurator.probe.base import ProbeContext
from ue_configurator.probe.runner import PHASE_MAP, run_scan
from ue_configurator.report.common import ConsoleTheme, collect_actions
from ue_configurator.report.console import render_console
from ue_configurator.report.json_report import write_json
from ue_configurator.reporting.toolchain_summary import render_toolchain_summary
from ue_configurator.reporting.startup_banner import format_startup_banner, format_minimal_banner


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="simulate changes without writing")
    parser.add_argument("--json", metavar="PATH", help="write machine-readable JSON output")
    parser.add_argument("--verbose", action="store_true", help="show verbose probe details")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument("--ue-version", help="Target Unreal Engine version for manifest compliance (e.g., 5.7)")
    parser.add_argument(
        "--manifest",
        help="Manifest identifier or JSON path describing required toolchain components",
    )
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in Profile],
        help="Machine profile (workstation, agent, minimal). Defaults to workstation or UECFG_PROFILE env.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uecfg", description="Unreal Engine Dev Configurator")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Run the readiness audit")
    _add_global_flags(scan_parser)
    scan_parser.add_argument(
        "--phase",
        type=int,
        action="append",
        choices=list(PHASE_MAP.keys()),
        help="Restrict scan to selected phases (0-3). Repeat for multiple phases.",
    )
    scan_parser.add_argument("--ue-root", help="Path to an Unreal Engine source tree")

    fix_parser = subparsers.add_parser("fix", help="Review or apply guarded fixes")
    _add_global_flags(fix_parser)
    fix_parser.add_argument("--phase", type=int, choices=list(PHASE_MAP.keys()), required=True)
    fix_parser.add_argument("--apply", action="store_true", help="Apply safe fixes (still honors --dry-run)")
    fix_parser.add_argument("--ue-root", help="Path to an Unreal Engine source tree")
    fix_parser.add_argument(
        "--destination",
        help="Custom destination for generated config files (phase 3 helpers)",
    )
    fix_parser.add_argument(
        "--vs-passive",
        dest="vs_passive",
        action="store_true",
        help="Run Visual Studio Installer in passive mode (default).",
    )
    fix_parser.add_argument(
        "--vs-interactive",
        dest="vs_passive",
        action="store_false",
        help="Force the Visual Studio Installer UI when modifying components.",
    )
    fix_parser.set_defaults(vs_passive=True)

    verify_parser = subparsers.add_parser("verify", help="Verify a UE source tree")
    _add_global_flags(verify_parser)
    verify_parser.add_argument("--ue-root", required=True, help="UE clone to verify")

    setup_parser = subparsers.add_parser("setup", help="Automated setup wizard")
    _add_global_flags(setup_parser)
    setup_parser.add_argument(
        "--phase",
        type=int,
        action="append",
        choices=list(PHASE_MAP.keys()),
        help="Restrict setup to selected phases.",
    )
    setup_parser.add_argument("--ue-root", help="Path to an Unreal Engine source tree")
    setup_parser.add_argument("--include-horde", action="store_true", help="Include optional Horde/UBA steps")
    setup_parser.add_argument("--apply", action="store_true", help="Apply steps without confirmation prompts")
    setup_parser.add_argument("--plan", action="store_true", help="Print the setup plan then exit")
    setup_parser.add_argument("--resume", action="store_true", help="Resume from previous setup state")
    setup_parser.add_argument("--log", help=argparse.SUPPRESS)
    setup_parser.add_argument("--use-winget", dest="use_winget", action="store_true", help=argparse.SUPPRESS)
    setup_parser.add_argument("--no-winget", dest="use_winget", action="store_false", help=argparse.SUPPRESS)
    setup_parser.add_argument("--no-splash", action="store_true", help="Skip the punk skull splash screen.")
    setup_parser.add_argument(
        "--vs-passive",
        dest="vs_passive",
        action="store_true",
        help="Run Visual Studio Installer in passive mode (default).",
    )
    setup_parser.add_argument(
        "--vs-interactive",
        dest="vs_passive",
        action="store_false",
        help="Force the Visual Studio Installer UI during VS component installs.",
    )
    setup_parser.add_argument(
        "--run-prereqs",
        action="store_true",
        help="Run UEPrereqSetup/VC++ redistributable installers (silent). Default is detect-only.",
    )
    setup_parser.add_argument(
        "--build-engine",
        action="store_true",
        help="Build missing Unreal editor/helper binaries via Build.bat after checks pass.",
    )
    setup_parser.add_argument(
        "--build-target",
        action="append",
        dest="build_targets",
        help="Override the default engine targets to build (repeatable).",
    )
    setup_parser.add_argument("--_elevated", action="store_true", help=argparse.SUPPRESS)
    setup_parser.set_defaults(use_winget=None)

    return parser


def _resolve_phases(phase_flags: Sequence[int] | None, profile: Profile) -> List[int]:
    if not phase_flags:
        return list(DEFAULT_PHASES[profile])
    return [phase for phase in phase_flags if phase in PHASE_MAP]


def handle_scan(args: argparse.Namespace) -> int:
    profile = resolve_profile(args.profile)
    phases = _resolve_phases(args.phase, profile)
    manifest_res = resolve_manifest(manifest=args.manifest, ue_version=args.ue_version, ue_root=args.ue_root)
    if manifest_res.manifest is None and (args.manifest or args.ue_version):
        target = args.manifest or args.ue_version
        print(f"[manifest] Unable to load manifest '{target}'. Continuing without manifest.")
    ctx = ProbeContext(
        dry_run=True,
        verbose=args.verbose,
        ue_root=args.ue_root,
        profile=profile.value,
        manifest=manifest_res.manifest,
    )
    banner = format_startup_banner(
        ctx,
        command="scan",
        phases=phases,
        apply=False,
        json_path=args.json,
        log_path=None,
        manifest=manifest_res.manifest,
        manifest_source=manifest_res.source,
        ue_root=args.ue_root,
        profile=profile,
    )
    print(banner, flush=True)
    scan = run_scan(phases, ctx, profile)
    theme = ConsoleTheme(no_color=args.no_color)
    render_console(scan, theme=theme, verbose=args.verbose)
    summary = render_toolchain_summary(scan, manifest_res.manifest)
    if summary:
        print(summary)
    if args.json:
        write_json(scan, args.json)
    return 0


def handle_verify(args: argparse.Namespace) -> int:
    profile = resolve_profile(args.profile)
    manifest_res = resolve_manifest(manifest=args.manifest, ue_version=args.ue_version, ue_root=args.ue_root)
    if manifest_res.manifest is None and (args.manifest or args.ue_version):
        target = args.manifest or args.ue_version
        print(f"[manifest] Unable to load manifest '{target}'. Continuing without manifest.")
    ctx = ProbeContext(
        dry_run=True,
        verbose=args.verbose,
        ue_root=args.ue_root,
        profile=profile.value,
        manifest=manifest_res.manifest,
    )
    scan = run_scan([2], ctx, profile)
    theme = ConsoleTheme(no_color=args.no_color)
    render_console(scan, theme=theme, verbose=True)
    if args.json:
        write_json(scan, args.json)
    return 0


def _prompt_bool_cli(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{prompt} [{default_str}] ").strip().lower()
        if not response:
            return default
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False


def _prompt_profile_choice(current: Profile) -> Profile:
    choices = "/".join(profile.value for profile in Profile)
    prompt = f"Select profile ({choices}) [{current.value}] "
    while True:
        response = input(prompt).strip().lower()
        if not response:
            return current
        for profile in Profile:
            if profile.value == response:
                return profile


def _prompt_intent() -> str:
    print("What do you want to do?")
    print("  1) Configure dev environment (safe / recommended)")
    print("  2) Build engine/tools (slow; runs Build.bat; opt-in)")
    print("  3) Configure + build (configure first, then build)")
    while True:
        choice = input("Select an option [1]: ").strip()
        if not choice or choice == "1":
            return "configure"
        if choice == "2":
            return "build"
        if choice == "3":
            return "both"
        print("Please enter 1, 2, or 3.")


def _prompt_admin_fallback() -> str:
    print("[setup] Apply/build requested but this session is not elevated.")
    print("        a) Continue in check/plan-only mode (no installs/builds)")
    print("        b) Exit and re-run as admin")
    while True:
        resp = input("Choose [a]: ").strip().lower()
        if not resp or resp == "a":
            return "plan-only"
        if resp == "b":
            return "exit"
        print("Please choose a or b.")


def handle_setup(args: argparse.Namespace) -> int:
    interactive = sys.stdin.isatty()
    intent = "configure"
    build_after_config = False
    build_only = False
    build_engine_flag = bool(args.build_engine)
    interactive_prompt_needed = (
        interactive
        and not args.plan
        and not args.apply
        and args.profile is None
        and not args.build_engine
        and not args.build_targets
    )
    if interactive_prompt_needed:
        intent = _prompt_intent()
        if intent == "build":
            build_engine_flag = True
            build_only = True
        elif intent == "both":
            build_after_config = True

    profile = resolve_profile(args.profile)
    skip_profile_prompt = build_only
    if args.profile is None and interactive and not skip_profile_prompt and "UECFG_PROFILE" not in os.environ:
        profile = _prompt_profile_choice(profile)
    phases = _resolve_phases(args.phase, profile)
    if build_only and not args.phase:
        phases = [2]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre_log = getattr(args, "_pre_log_path", None)
    log_path = pre_log if pre_log is not None else (Path(args.log) if args.log else Path("logs") / f"uecfg_setup_{timestamp}.log")
    json_path = args.json or str(Path("reports") / f"uecfg_report_{timestamp}.json")

    ctx_preview = ProbeContext(dry_run=True, verbose=args.verbose, ue_root=args.ue_root)
    winget_available = toolchain_fix.winget_available(ctx_preview)
    use_winget = winget_available if args.use_winget is None else args.use_winget
    include_horde = False if build_only else args.include_horde
    ue_root = args.ue_root
    selected_manifest = args.manifest
    selected_ue_version = args.ue_version
    build_targets = args.build_targets or None
    if build_targets:
        normalized_targets = []
        for entry in build_targets:
            parts = [part.strip() for part in entry.split(",") if part.strip()]
            normalized_targets.extend(parts)
        build_targets = normalized_targets or None

    apply_flag = args.apply or build_only
    plan_only_flag = args.plan

    if build_only and ue_root is None and interactive:
        response = input("Enter UE root path (required for build): ").strip().strip('"')
        if not response:
            print("[setup] UE root is required for build. Exiting.")
            return 1
        root_path = Path(response)
        if not root_path.exists():
            print(f"[setup] UE root {root_path} does not exist. Exiting.")
            return 1
        ue_root = response

    if not args.apply and interactive and not args.plan and not build_only:
        if winget_available and args.use_winget is None:
            use_winget = _prompt_bool_cli("winget detected. Use it for installs?", True)
        elif not winget_available:
            print("[setup] winget not detected; installs will be manual.")
        if ue_root is None and profile == Profile.WORKSTATION:
            response = input("Provide Unreal Engine root path (leave blank to skip): ").strip().strip('"')
            if response:
                ue_root = response
        if selected_manifest is None and not selected_ue_version:
            manifests = sorted(available_manifests().keys())
            if manifests:
                default_manifest = manifests[-1]
                default_version = default_manifest.split("_", 1)[-1]
                response = input(
                    f"Target UE version ({', '.join(m.split('_',1)[-1] for m in manifests)}) [{default_version}]: "
                ).strip()
                if response:
                    selected_ue_version = response
                else:
                    selected_ue_version = default_version
        if not include_horde:
            include_horde = _prompt_bool_cli("Include optional Horde/UBA steps?", profile == Profile.AGENT)
        if not args.plan:
            consent = _prompt_bool_cli(
                "Setup may install Git, CMake, Ninja, and .NET SDK via winget. Proceed?", True
            )
            if not consent:
                print("[setup] Setup cancelled.")
                return 1
            apply_flag = True
        else:
            apply_flag = False
    elif not args.apply and not interactive and not args.plan and not build_only:
        if not args.plan:
            print("[setup] Non-interactive session detected. Re-run with --apply to execute steps.")
        apply_flag = False

    if interactive and (apply_flag or build_engine_flag) and not getattr(args, "_elevated", False) and not _is_admin():
        choice = _prompt_admin_fallback()
        if choice == "exit":
            print("[setup] Exiting so you can rerun as admin.")
            return 1
        apply_flag = False
        build_engine_flag = False
        build_after_config = False
        plan_only_flag = True

    manifest_res = resolve_manifest(manifest=selected_manifest, ue_version=selected_ue_version, ue_root=ue_root)
    if manifest_res.manifest is None and (selected_manifest or selected_ue_version):
        target = selected_manifest or selected_ue_version
        print(f"[manifest] Unable to load manifest '{target}'. Continuing without manifest.")
    no_splash_flag = bool(getattr(args, "no_splash", False))
    no_splash_env = os.environ.get("UECFG_NO_SPLASH") == "1"
    show_splash = bool(interactive and not no_splash_flag and not no_splash_env)
    elevated_flag = bool(getattr(args, "_elevated", False))
    vs_passive = getattr(args, "vs_passive", True)

    if interactive and build_after_config:
        build_engine_flag = _prompt_bool_cli("Build missing engine/tools now?", True)

    options = SetupOptions(
        phases=phases,
        apply=apply_flag and not plan_only_flag,
        resume=args.resume,
        plan_only=plan_only_flag,
        include_horde=include_horde,
        use_winget=use_winget,
        ue_root=ue_root,
        dry_run=args.dry_run,
        verbose=args.verbose,
        no_color=args.no_color,
        json_path=json_path,
        log_path=log_path,
        manifest=manifest_res.manifest,
        manifest_source=manifest_res.source,
        ue_version=selected_ue_version
        or manifest_res.detected_version
        or (manifest_res.manifest.ue_version if manifest_res.manifest else None),
        manifest_arg=selected_manifest,
        vs_passive=vs_passive,
        show_splash=show_splash,
        no_splash_flag=no_splash_flag or no_splash_env,
        profile=profile,
        elevated=elevated_flag,
        run_prereqs=getattr(args, "run_prereqs", False),
        build_engine=build_engine_flag,
        build_targets=build_targets,
    )
    return run_setup(options)


def handle_fix(args: argparse.Namespace) -> int:
    profile = resolve_profile(args.profile)
    phases = _resolve_phases([args.phase], profile)
    manifest_res = resolve_manifest(manifest=args.manifest, ue_version=args.ue_version, ue_root=args.ue_root)
    if manifest_res.manifest is None and (args.manifest or args.ue_version):
        target = args.manifest or args.ue_version
        print(f"[manifest] Unable to load manifest '{target}'. Continuing without manifest.")
    ctx = ProbeContext(
        dry_run=True,
        verbose=args.verbose,
        ue_root=args.ue_root,
        profile=profile.value,
        manifest=manifest_res.manifest,
    )
    vs_plan = vs_fix.plan_vs_modify(ctx, manifest_res.manifest)
    scan = run_scan(phases, ctx, profile)
    actions = collect_actions(scan.results)
    if not actions:
        print("No actionable recommendations for this phase.")
    else:
        print("Recommended actions:")
        for idx, action in enumerate(actions, start=1):
            print(f" {idx}. {action.description}")
            for cmd in action.commands:
                print(f"    {cmd}")

    if args.apply:
        if args.phase == 1 and vs_plan.required and not args.dry_run and not _is_admin():
            if _relaunch_fix_elevated(args):
                return 0
        apply_ctx = ProbeContext(
            dry_run=args.dry_run or not args.apply,
            verbose=args.verbose,
            ue_root=args.ue_root,
            profile=profile.value,
            manifest=manifest_res.manifest,
        )
        if args.phase == 1:
            outcome = toolchain_fix.ensure_toolchain_extras(apply_ctx)
            for line in outcome.logs:
                print(line)
            vs_plan = vs_fix.plan_vs_modify(apply_ctx, manifest_res.manifest)
            if vs_plan.required:
                vs_outcome = vs_fix.ensure_vs_manifest_components(
                    apply_ctx,
                    manifest_res.manifest,
                    vs_passive=getattr(args, "vs_passive", True),
                    dry_run=args.dry_run,
                )
                for line in vs_outcome.logs:
                    print(line)
                print(vs_outcome.message)
        elif args.phase == 3:
            target = horde_fix.generate_build_configuration(apply_ctx, destination=args.destination)
            if apply_ctx.dry_run:
                print(f"[dry-run] Would create BuildConfiguration.xml at {target}")
            else:
                print(f"BuildConfiguration template written to {target}")
        else:
            print("No automated fix routines for this phase yet.")
    else:
        print("Run again with --apply to execute guarded fixes.")

    if args.json:
        write_json(scan, args.json)
    return 0


def _reconstruct_fix_args(args: argparse.Namespace) -> List[str]:
    rebuilt: List[str] = ["-m", "ue_configurator.cli", "fix", "--phase", str(args.phase)]
    if args.apply:
        rebuilt.append("--apply")
    if args.ue_root:
        rebuilt.extend(["--ue-root", args.ue_root])
    if getattr(args, "destination", None):
        rebuilt.extend(["--destination", args.destination])
    if args.dry_run:
        rebuilt.append("--dry-run")
    if args.verbose:
        rebuilt.append("--verbose")
    if getattr(args, "no_color", False):
        rebuilt.append("--no-color")
    if args.json:
        rebuilt.extend(["--json", args.json])
    if args.profile:
        rebuilt.extend(["--profile", args.profile])
    if args.manifest:
        rebuilt.extend(["--manifest", args.manifest])
    if args.ue_version:
        rebuilt.extend(["--ue-version", args.ue_version])
    if not getattr(args, "vs_passive", True):
        rebuilt.append("--vs-interactive")
    return rebuilt


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_fix_elevated(args: argparse.Namespace) -> bool:
    cmd = _reconstruct_fix_args(args)
    params = " ".join(shlex.quote(part) for part in cmd)
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception as exc:
        print(f"[fix] Unable to request elevation: {exc}")
        return False
    if ret <= 32:
        print("[fix] Elevation cancelled.")
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "scan"
    pre_log_path = None
    if command == "setup":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_log_path = Path(args.log) if args.log else Path("logs") / f"uecfg_setup_{timestamp}.log"
        args._pre_log_path = pre_log_path  # type: ignore[attr-defined]

    log_for_lock = pre_log_path if command == "setup" else None

    try:
        with acquire_single_instance_lock("uecfg", log_for_lock):
            print(
                format_minimal_banner(
                    command=command,
                    json_path=getattr(args, "json", None),
                    log_path=str(pre_log_path) if pre_log_path else None,
                    ue_root=getattr(args, "ue_root", None),
                ),
                flush=True,
            )
            if args.command == "scan":
                return handle_scan(args)
            if args.command == "verify":
                return handle_verify(args)
            if args.command == "fix":
                return handle_fix(args)
            if args.command == "setup":
                return handle_setup(args)
            parser.error("Unknown command")
            return 1
    except SingleInstanceError as err:
        print(err.user_message)
        return 2


if __name__ == "__main__":
    sys.exit(main())
