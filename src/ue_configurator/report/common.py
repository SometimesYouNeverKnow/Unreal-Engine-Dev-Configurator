"""Rendering helpers shared by console and JSON outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from ue_configurator.probe.base import ActionRecommendation, CheckResult, CheckStatus
from ue_configurator.probe.runner import PHASE_MAP


class ConsoleTheme:
    """ANSI-aware styling helper."""

    STATUS_COLORS = {
        CheckStatus.PASS: "32",
        CheckStatus.WARN: "33",
        CheckStatus.FAIL: "31",
        CheckStatus.SKIP: "36",
        CheckStatus.NA: "90",
    }

    def __init__(self, *, no_color: bool = False):
        self.no_color = no_color

    def colorize(self, text: str, color_code: str) -> str:
        if self.no_color:
            return text
        return f"\x1b[{color_code}m{text}\x1b[0m"

    def status_label(self, status: CheckStatus) -> str:
        code = self.STATUS_COLORS.get(status, "37")
        return self.colorize(status.value, code)

    def progress_bar(self, completed: int, total: int, width: int = 28) -> str:
        if total == 0:
            return "[" + "-" * width + "]"
        completed_blocks = int(width * (completed / total))
        bar = "#" * completed_blocks + "-" * (width - completed_blocks)
        return f"[{bar}] {completed}/{total}"


def collect_actions(results: Dict[int, List[CheckResult]]) -> List[ActionRecommendation]:
    unique: Dict[str, ActionRecommendation] = {}
    for checks in results.values():
        for check in checks:
            if check.status in (CheckStatus.PASS, CheckStatus.NA):
                continue
            for action in check.actions:
                if action.id not in unique:
                    unique[action.id] = action
    return list(unique.values())
