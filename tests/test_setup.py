"""Tests for setup plan generation and state handling."""

from __future__ import annotations

from pathlib import Path

from ue_configurator.profile import Profile
from ue_configurator.probe.base import ActionRecommendation, CheckResult, CheckStatus, CommandResult, ProbeContext
from ue_configurator.probe.runner import ScanData
from ue_configurator.setup.pipeline import (
    SetupOptions,
    SetupRuntime,
    SetupState,
    SetupStep,
    StepResult,
    StepStatus,
    build_steps,
    sanitize_path,
    _needs_admin,
    SetupLogger,
)


class DummyLogger:
    def log(self, message: str) -> None:  # pragma: no cover - simple stub
        pass


def _make_runtime(checks: list[CheckResult], phases: list[int] | None = None) -> SetupRuntime:
    phase = checks[0].phase if checks else 0
    scan = ScanData(
        metadata={},
        results={phase: checks},
        phase_modes={phase: "required"},
        profile=Profile.WORKSTATION,
    )
    options = SetupOptions(
        phases=phases or [0, 1, 2],
        apply=True,
        resume=False,
        plan_only=False,
        include_horde=False,
        use_winget=True,
        ue_root=None,
        dry_run=True,
        verbose=False,
        no_color=True,
        json_path=None,
        log_path=Path("logs/test.log"),
    )
    return SetupRuntime(
        options=options,
        logger=DummyLogger(),
        context=ProbeContext(dry_run=True),
        scan=scan,
        state=SetupState(),
    )


def test_build_steps_includes_git_when_missing() -> None:
    checks = [
        CheckResult(
            id="os.git",
            phase=0,
            status=CheckStatus.FAIL,
            summary="Git missing",
            details="",
            evidence=[],
            actions=[ActionRecommendation(id="git.install", description="install", commands=[])],
        )
    ]
    runtime = _make_runtime(checks, phases=[0])
    steps = build_steps(runtime)
    assert any(step.id == "install.git" for step in steps)


def test_needs_admin_respects_completed_steps() -> None:
    dummy_step = SetupStep(
        id="admin.step",
        title="Needs admin",
        phase=1,
        requires_admin=True,
        estimated_time=1,
        description="",
        check=lambda rt: False,
        apply=lambda rt: StepResult(StepStatus.DONE, ""),
    )
    runtime = _make_runtime([], phases=[1])
    assert _needs_admin([dummy_step], runtime)
    runtime.state.mark_done("admin.step")
    assert not _needs_admin([dummy_step], runtime)


def test_install_package_dry_run(monkeypatch) -> None:
    ctx = ProbeContext(dry_run=True)

    def fake_where(self, command, **kwargs):
        if command[1] == "winget":
            return CommandResult(command, "winget", "", 0)
        raise AssertionError("Unexpected command")

    monkeypatch.setattr(ProbeContext, "run_command", fake_where, raising=False)
    from ue_configurator.fix.toolchain import install_package_via_winget

    outcome = install_package_via_winget(ctx, "Example.Package", "Example")
    assert outcome.success
    assert any("dry-run" in line for line in outcome.logs)


def test_sanitize_path_handles_quotes() -> None:
    assert sanitize_path('"C:\\tmp\\logs"') == Path(r"C:\tmp\logs")
    assert sanitize_path("C:\\tmp\\logs\"") == Path(r"C:\tmp\logs")
    assert sanitize_path('"C:\\tmp\\my logs\\file.log"') == Path(r"C:\tmp\my logs\file.log")


def test_setup_logger_sanitizes_path(tmp_path: Path) -> None:
    quoted = f'"{tmp_path / "logs with space" / "setup.log"}"'
    logger = SetupLogger(Path(quoted))
    assert logger.path.exists()
