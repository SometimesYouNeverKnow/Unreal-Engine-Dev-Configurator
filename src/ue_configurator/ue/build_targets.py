"""Engine build completeness planner and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

from ue_configurator.ue.ubt_runner import UBTRunner, UBTResult, UBTRunnerError


@dataclass(frozen=True)
class BuildTarget:
    name: str
    platform: str
    configuration: str

    def binary_path(self, ue_root: Path) -> Path:
        return Path(ue_root) / "Engine" / "Binaries" / self.platform / f"{self.name}.exe"


DEFAULT_TARGETS: Sequence[BuildTarget] = (
    BuildTarget("UnrealEditor", "Win64", "Development"),
    BuildTarget("ShaderCompileWorker", "Win64", "Development"),
    BuildTarget("UnrealPak", "Win64", "Development"),
    BuildTarget("CrashReportClient", "Win64", "Development"),
)


@dataclass
class TargetBuildPlan:
    target: BuildTarget
    binary: Path
    built: bool
    action: str  # "SKIP" or "BUILD"
    result: UBTResult | None = None
    error: str | None = None

    @property
    def status_label(self) -> str:
        if self.error:
            return "FAIL"
        return self.action


@dataclass
class BuildExecution:
    plan: List[TargetBuildPlan]
    failed: bool
    failed_target: BuildTarget | None = None

    @property
    def summary(self) -> str:
        return "; ".join(format_plan_line(item) for item in self.plan)


def _resolve_targets(override: Sequence[str] | None) -> Sequence[BuildTarget]:
    if override:
        return [BuildTarget(name, "Win64", "Development") for name in override]
    return DEFAULT_TARGETS


def format_plan_line(item: TargetBuildPlan) -> str:
    suffix = f"{item.binary}"
    if item.error:
        suffix += f" ({item.error})"
        if item.result:
            suffix += f" (exit {item.result.returncode})"
    return f"{item.status_label}: {item.target.name} [{suffix}]"


def determine_build_plan(ue_root: Path, targets: Sequence[str] | None = None) -> List[TargetBuildPlan]:
    resolved = _resolve_targets(targets)
    plan: List[TargetBuildPlan] = []
    for target in resolved:
        binary = target.binary_path(ue_root)
        exists = binary.exists()
        plan.append(TargetBuildPlan(target=target, binary=binary, built=exists, action="SKIP" if exists else "BUILD"))
    return plan


def missing_targets(plan: Iterable[TargetBuildPlan]) -> List[TargetBuildPlan]:
    return [item for item in plan if not item.built]


def build_missing_targets(
    ue_root: Path,
    plan: List[TargetBuildPlan],
    *,
    runner: UBTRunner,
    logger: Callable[[str], None],
    dry_run: bool = False,
) -> BuildExecution:
    """Execute the build plan. Only missing targets are built."""
    for item in plan:
        if item.built:
            logger(f"[build] SKIP {item.target.name} (found {item.binary})")
            continue

        logger(
            f"[build] BUILD {item.target.name} ({item.target.platform} {item.target.configuration}) "
            f"-> {item.binary}"
        )
        if dry_run:
            logger("[build] Dry-run enabled; skipping invocation.")
            continue

        try:
            result = runner.run(item.target.name, item.target.platform, item.target.configuration)
        except UBTRunnerError as exc:
            item.error = str(exc)
            logger(f"[build] FAIL {item.target.name}: {exc}")
            return BuildExecution(plan=plan, failed=True, failed_target=item.target)

        item.result = result
        if result.returncode != 0:
            item.error = f"Build.bat failed with exit code {result.returncode}"
            logger(
                f"[build] FAIL {item.target.name} (exit {result.returncode}) "
                f"stdout: {result.stdout.strip() or '<empty>'} stderr: {result.stderr.strip() or '<empty>'}"
            )
            return BuildExecution(plan=plan, failed=True, failed_target=item.target)

        item.built = True
        logger(
            f"[build] SUCCESS {item.target.name} (exit {result.returncode}) in {result.elapsed:.1f}s "
            f"(cmd: {result.command})"
        )

    return BuildExecution(plan=plan, failed=False, failed_target=None)


def summarize_plan(plan: Sequence[TargetBuildPlan]) -> str:
    return "; ".join(format_plan_line(item) for item in plan)
