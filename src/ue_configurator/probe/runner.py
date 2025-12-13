"""Entry points that orchestrate probes across phases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import platform
from typing import Dict, Iterable, List, Sequence

from .base import CheckResult, ProbeContext, score_checks
from . import system, toolchain, unreal, horde


PHASE_MAP = {
    0: ("Phase 0 — OS & baseline", system.PHASE0_PROBES),
    1: ("Phase 1 — Visual Studio & toolchain", toolchain.PHASE1_PROBES),
    2: ("Phase 2 — Unreal prerequisites", unreal.PHASE2_PROBES),
    3: ("Phase 3 — Horde / UBA (optional)", horde.PHASE3_PROBES),
}

DEFAULT_PHASES = [0, 1, 2]


@dataclass
class ScanData:
    metadata: Dict[str, str]
    results: Dict[int, List[CheckResult]]

    def readiness_scores(self) -> Dict[int, float]:
        return {phase: score_checks(checks)[0] for phase, checks in self.results.items()}

    def total_score(self) -> float:
        checks = [check for bucket in self.results.values() for check in bucket]
        score, count = score_checks(checks)
        return score if count else 0.0


def _phase_probes(phase: int):
    name, probes = PHASE_MAP.get(phase, ("Unknown", []))
    return name, probes


def run_scan(phases: Sequence[int], ctx: ProbeContext) -> ScanData:
    unique_phases = [phase for phase in sorted(set(phases)) if phase in PHASE_MAP]
    results: Dict[int, List[CheckResult]] = {}
    for phase in unique_phases:
        _, probes = _phase_probes(phase)
        bucket: List[CheckResult] = []
        for probe in probes:
            bucket.append(probe(ctx))
        results[phase] = bucket

    metadata = {
        "machine": platform.node(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
    }
    return ScanData(metadata=metadata, results=results)
