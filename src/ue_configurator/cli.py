"""Command line interface for the Unreal Engine Dev Configurator."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, List, Sequence

from ue_configurator import __version__
from ue_configurator.fix import horde as horde_fix
from ue_configurator.probe.base import ProbeContext
from ue_configurator.probe.runner import DEFAULT_PHASES, PHASE_MAP, run_scan
from ue_configurator.report.common import ConsoleTheme, collect_actions
from ue_configurator.report.console import render_console
from ue_configurator.report.json_report import write_json


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="simulate changes without writing")
    parser.add_argument("--json", metavar="PATH", help="write machine-readable JSON output")
    parser.add_argument("--verbose", action="store_true", help="show verbose probe details")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")


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

    verify_parser = subparsers.add_parser("verify", help="Verify a UE source tree")
    _add_global_flags(verify_parser)
    verify_parser.add_argument("--ue-root", required=True, help="UE clone to verify")

    return parser


def _resolve_phases(phase_flags: Sequence[int] | None) -> List[int]:
    if not phase_flags:
        return list(DEFAULT_PHASES)
    return [phase for phase in phase_flags if phase in PHASE_MAP]


def handle_scan(args: argparse.Namespace) -> int:
    phases = _resolve_phases(args.phase)
    ctx = ProbeContext(dry_run=True, verbose=args.verbose, ue_root=args.ue_root)
    scan = run_scan(phases, ctx)
    theme = ConsoleTheme(no_color=args.no_color)
    render_console(scan, theme=theme, verbose=args.verbose)
    if args.json:
        write_json(scan, args.json)
    return 0


def handle_verify(args: argparse.Namespace) -> int:
    ctx = ProbeContext(dry_run=True, verbose=args.verbose, ue_root=args.ue_root)
    scan = run_scan([2], ctx)
    theme = ConsoleTheme(no_color=args.no_color)
    render_console(scan, theme=theme, verbose=True)
    if args.json:
        write_json(scan, args.json)
    return 0


def handle_fix(args: argparse.Namespace) -> int:
    phases = _resolve_phases([args.phase])
    ctx = ProbeContext(dry_run=True, verbose=args.verbose, ue_root=args.ue_root)
    scan = run_scan(phases, ctx)
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
        apply_ctx = ProbeContext(
            dry_run=args.dry_run or not args.apply, verbose=args.verbose, ue_root=args.ue_root
        )
        if args.phase == 3:
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return handle_scan(args)
    if args.command == "verify":
        return handle_verify(args)
    if args.command == "fix":
        return handle_fix(args)
    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    sys.exit(main())
