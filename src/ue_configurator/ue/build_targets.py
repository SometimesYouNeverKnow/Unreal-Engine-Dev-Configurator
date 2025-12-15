"""Engine build completeness planner and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

from ue_configurator.ue.artifact_resolver import ArtifactResolver
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
    canonical: Path
    resolved: Path | None
    built: bool
    found_via_search: bool
    pattern: str
    candidates: list[Path]
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
    suffix = f"{item.resolved or item.canonical}"
    if item.resolved and item.resolved != item.canonical:
        suffix = f"FOUND (non-canonical): {item.resolved} (expected {item.canonical})"
        if len(item.candidates) > 1:
            suffix += f" | Alternatives: {', '.join(str(c) for c in item.candidates[1:5])}"
    if not item.built and not item.error and not item.resolved:
        suffix = f"Missing (expected {item.canonical}) | Searched under Engine for {item.pattern}"
        if item.candidates:
            suffix += f" | Candidates: {', '.join(str(c) for c in item.candidates)}"
    if item.error:
        suffix += f" ({item.error})"
        if item.result:
            suffix += f" (exit {item.result.returncode})"
    return f"{item.status_label}: {item.target.name} [{suffix}]"


def determine_build_plan(
    ue_root: Path,
    targets: Sequence[str] | None = None,
    *,
    resolver: ArtifactResolver | None = None,
) -> List[TargetBuildPlan]:
    resolved = _resolve_targets(targets)
    plan: List[TargetBuildPlan] = []
    artifact_resolver = resolver or ArtifactResolver(ue_root)
    for target in resolved:
        resolution = artifact_resolver.resolve(target)
        exists = resolution.found
        plan.append(
            TargetBuildPlan(
                target=target,
                canonical=resolution.canonical,
                resolved=resolution.resolved,
                built=exists,
                found_via_search=resolution.found_via_search,
                pattern=resolution.pattern,
                candidates=resolution.candidates,
                action="SKIP" if exists else "BUILD",
            )
        )
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
    resolver: ArtifactResolver | None = None,
) -> BuildExecution:
    """Execute the build plan. Only missing targets are built."""
    artifact_resolver = resolver or ArtifactResolver(ue_root)
    for item in plan:
        if item.built:
            logger(f"[build] SKIP {item.target.name} (found {item.resolved or item.canonical})")
            continue

        logger(
            f"[build] BUILD {item.target.name} ({item.target.platform} {item.target.configuration}) "
            f"-> {item.canonical}"
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

        post = artifact_resolver.resolve(item.target)
        item.resolved = post.resolved
        item.built = post.found
        item.found_via_search = post.found_via_search
        item.candidates = post.candidates
        if not item.built:
            item.error = (
                f"Build reported success but {item.target.name} is missing "
                f"(expected {post.canonical}; searched pattern {post.pattern})"
            )
            logger(f"[build] FAIL {item.target.name}: {item.error}")
            return BuildExecution(plan=plan, failed=True, failed_target=item.target)

        logger(
            f"[build] SUCCESS {item.target.name} (exit {result.returncode}) in {result.elapsed:.1f}s "
            f"(cmd: {result.command})"
        )

    return BuildExecution(plan=plan, failed=False, failed_target=None)


def summarize_plan(plan: Sequence[TargetBuildPlan]) -> str:
    return "; ".join(format_plan_line(item) for item in plan)
