"""JSON renderer for scan results."""

from __future__ import annotations

import json
from pathlib import Path

from ue_configurator.probe.runner import PHASE_MAP, ScanData

from .common import collect_actions


def write_json(scan: ScanData, path: str) -> None:
    actions = collect_actions(scan.results)
    phase_scores = scan.readiness_scores()
    document = {
        "metadata": scan.metadata,
        "readiness": {
            "total": scan.total_score(),
            "perPhase": {str(phase): phase_scores.get(phase, 0.0) for phase in sorted(scan.results)},
        },
        "phases": [
            {
                "id": phase,
                "name": PHASE_MAP[phase][0],
                "checks": [check.to_dict() for check in checks],
            }
            for phase, checks in sorted(scan.results.items())
        ],
        "recommendedActions": [
            {"id": action.id, "description": action.description, "commands": action.commands}
            for action in actions
        ],
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2), encoding="utf-8")
