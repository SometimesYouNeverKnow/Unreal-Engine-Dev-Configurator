"""Shared probe infrastructure and dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
import subprocess
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING, Union

if TYPE_CHECKING:  # pragma: no cover
    from ue_configurator.manifest import Manifest


class CheckStatus(str, Enum):
    """Possible probe outcomes."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"
    NA = "N/A"


@dataclass
class ActionRecommendation:
    """High-level suggestion returned by probes."""

    id: str
    description: str
    commands: List[str] = field(default_factory=list)


@dataclass
class CheckResult:
    """Structured output for each probe."""

    id: str
    phase: int
    status: CheckStatus
    summary: str
    details: str
    evidence: List[str] = field(default_factory=list)
    actions: List[ActionRecommendation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "status": self.status.value,
            "summary": self.summary,
            "details": self.details,
            "evidence": list(self.evidence),
            "actions": [
                {"id": act.id, "description": act.description, "commands": list(act.commands)}
                for act in self.actions
            ],
        }


@dataclass
class CommandResult:
    """Wrapper around subprocess output used as evidence."""

    command: Union[str, Sequence[str]]
    stdout: str
    stderr: str
    returncode: int


class ProbeContext:
    """Runtime helpers shared by probes."""

    def __init__(
        self,
        *,
        dry_run: bool = True,
        verbose: bool = False,
        ue_root: Optional[str] = None,
        timeout: int = 20,
        workdir: Optional[str] = None,
        profile: str = "workstation",
        phase_modes: Optional[Dict[int, str]] = None,
        manifest: Optional["Manifest"] = None,
    ) -> None:
        self.dry_run = dry_run
        self.verbose = verbose
        self.ue_root = ue_root
        self.timeout = timeout
        self.workdir = workdir or os.getcwd()
        self.cache: dict[str, Any] = {}
        self.profile = profile
        self.phase_modes = phase_modes or {}
        self.manifest = manifest

    def run_command(
        self,
        command: Union[str, Sequence[str]],
        *,
        check: bool = False,
        timeout: Optional[int] = None,
        env: Optional[dict[str, str]] = None,
    ) -> CommandResult:
        """Execute a command with a timeout, capturing output."""

        effective_timeout = timeout or self.timeout

        if isinstance(command, str):
            shell = True
            cmd = command
        else:
            shell = False
            cmd = list(command)

        try:
            proc = subprocess.run(
                cmd,
                shell=shell,
                capture_output=True,
                timeout=effective_timeout,
                text=True,
                check=check,
                env=env,
                cwd=self.workdir,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(command, exc.stdout or "", exc.stderr or "timeout", returncode=-1)
        except FileNotFoundError:
            return CommandResult(command, "", "not found", returncode=-1)
        except subprocess.CalledProcessError as exc:
            return CommandResult(command, exc.stdout, exc.stderr, returncode=exc.returncode)

        return CommandResult(command, proc.stdout, proc.stderr, returncode=proc.returncode)


def score_checks(checks: Iterable[CheckResult]) -> Tuple[float, int]:
    """Return (score, count) for a list of checks."""

    total = 0.0
    count = 0
    for check in checks:
        if check.status == CheckStatus.NA:
            continue
        if check.status == CheckStatus.PASS:
            total += 1.0
        elif check.status == CheckStatus.WARN:
            total += 0.5
        elif check.status == CheckStatus.SKIP:
            total += 0.5
        count += 1
    if count == 0:
        return 0.0, 0
    return (total / count) * 100.0, count


def run_parallel(functions: Sequence[Callable[[], CheckResult]]) -> List[CheckResult]:
    """Execute probe callables in parallel threads to reduce latency."""

    results: List[Optional[CheckResult]] = [None] * len(functions)

    def _runner(idx: int, func: Callable[[], CheckResult]) -> None:
        try:
            results[idx] = func()
        except Exception as exc:  # pragma: no cover - last resort
            results[idx] = CheckResult(
                id=f"probe-{idx}",
                phase=-1,
                status=CheckStatus.FAIL,
                summary="Probe crashed",
                details=str(exc),
                evidence=[],
                actions=[],
            )

    threads = [threading.Thread(target=_runner, args=(idx, func)) for idx, func in enumerate(functions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    return [res for res in results if res is not None]
