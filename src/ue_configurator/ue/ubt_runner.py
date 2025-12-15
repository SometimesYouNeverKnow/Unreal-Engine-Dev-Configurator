"""Thin wrapper around Epic's Build.bat (UBT) invocation."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class UBTResult:
    command: str
    cwd: Path
    returncode: int
    stdout: str
    stderr: str
    elapsed: float


class UBTRunnerError(RuntimeError):
    """Raised when the UBT invocation cannot be executed."""


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


class UBTRunner:
    """Responsible for invoking Build.bat in the UE source tree."""

    def __init__(self, ue_root: Path) -> None:
        self.ue_root = Path(ue_root)

    def _build_script(self) -> Path:
        return self.ue_root / "Engine" / "Build" / "BatchFiles" / "Build.bat"

    def run(
        self,
        target: str,
        platform: str,
        configuration: str,
        extra_args: Sequence[str] | None = None,
    ) -> UBTResult:
        build_bat = self._build_script()
        if not build_bat.exists():
            raise UBTRunnerError(f"Build script not found at {build_bat}")

        args = [str(build_bat), target, platform, configuration, "-WaitMutex"]
        if extra_args:
            args.extend(extra_args)
        command_str = " ".join(_quote(arg) for arg in args)

        start = time.time()
        try:
            proc = subprocess.run(
                args,
                cwd=self.ue_root,
                capture_output=True,
                text=True,
            )
        except OSError as exc:  # pragma: no cover - surface failure
            raise UBTRunnerError(str(exc)) from exc
        elapsed = time.time() - start

        return UBTResult(
            command=command_str,
            cwd=self.ue_root,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed=elapsed,
        )
