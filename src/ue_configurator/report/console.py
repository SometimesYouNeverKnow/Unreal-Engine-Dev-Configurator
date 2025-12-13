"""Console renderer for scan results."""

from __future__ import annotations

import shutil
from typing import Dict, List

from ue_configurator.probe.base import CheckResult, CheckStatus, score_checks
from ue_configurator.probe.runner import PHASE_MAP, ScanData

from .common import ConsoleTheme, collect_actions


def _terminal_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except OSError:  # pragma: no cover - fallback
        return 100


def render_console(scan: ScanData, *, theme: ConsoleTheme, verbose: bool = False) -> None:
    metadata = scan.metadata
    width = _terminal_width()
    header = f"{metadata.get('machine', '<machine>')} — {metadata.get('timestamp', '')}"
    print(header)
    print("-" * min(len(header), width))

    for phase in sorted(scan.results):
        phase_name, _ = PHASE_MAP[phase]
        checks = scan.results[phase]
        phase_score, _ = score_checks(checks)
        completed = len([c for c in checks if c.status == CheckStatus.PASS])
        progress = theme.progress_bar(completed, len(checks))
        print(f"{phase_name} ({phase_score:.0f}/100)")
        print(progress)
        for check in checks:
            status = theme.status_label(check.status)
            print(f" - {status} {check.summary}")
            if verbose or check.status != CheckStatus.PASS:
                print(f"   {check.details}")
                if (verbose or check.status != CheckStatus.PASS) and check.evidence:
                    print(f"   Evidence: {check.evidence[0]}")
        print()

    total_score = scan.total_score()
    print(f"Final readiness: {total_score:.0f}/100")
    for phase, checks in scan.results.items():
        phase_score, _ = score_checks(checks)
        print(f"  Phase {phase}: {phase_score:.0f}/100")

    actions = collect_actions(scan.results)
    if actions:
        print("\nNext actions:")
        for idx, action in enumerate(actions, start=1):
            print(f" {idx}. {action.description}")
            for cmd in action.commands:
                print(f"    {cmd}")
