"""Unit tests for scoring and fix helpers."""

from __future__ import annotations

from pathlib import Path

from ue_configurator.fix.horde import generate_build_configuration
from ue_configurator.fix.toolchain import ensure_toolchain_extras
from ue_configurator.profile import Profile
from ue_configurator.probe import system
from ue_configurator.probe.base import (
    ActionRecommendation,
    CheckResult,
    CheckStatus,
    CommandResult,
    ProbeContext,
    score_checks,
)
from ue_configurator.probe.runner import ScanData
from ue_configurator.report.common import collect_actions


def _check(status: CheckStatus) -> CheckResult:
    return CheckResult(
        id=f"id.{status.value}",
        phase=0,
        status=status,
        summary="summary",
        details="details",
        evidence=[],
        actions=[
            ActionRecommendation(
                id=f"action.{status.value}",
                description="desc",
                commands=["cmd"],
            )
        ],
    )


def test_score_checks_weights_statuses() -> None:
    checks = [_check(CheckStatus.PASS), _check(CheckStatus.WARN), _check(CheckStatus.FAIL)]
    score, count = score_checks(checks)
    assert count == 3
    assert score == (1.5 / 3) * 100


def test_score_checks_ignores_na() -> None:
    checks = [_check(CheckStatus.PASS), _check(CheckStatus.NA)]
    score, count = score_checks(checks)
    assert count == 1
    assert score == 100.0


def test_collect_actions_deduplicates() -> None:
    checks = {
        0: [_check(CheckStatus.FAIL)],
        1: [_check(CheckStatus.WARN)],
    }
    actions = collect_actions(checks)
    ids = {action.id for action in actions}
    assert ids == {"action.FAIL", "action.WARN"}


def test_generate_build_configuration_respects_dry_run(tmp_path: Path) -> None:
    ctx = ProbeContext(dry_run=True, workdir=str(tmp_path))
    target = generate_build_configuration(ctx, destination=str(tmp_path / "BuildConfiguration.xml"))
    assert not target.exists()

    ctx_real = ProbeContext(dry_run=False, workdir=str(tmp_path))
    target_real = generate_build_configuration(ctx_real, destination=str(tmp_path / "BuildConfiguration.xml"))
    assert target_real.exists()
    assert "<BuildConfiguration>" in target_real.read_text(encoding="utf-8")


def test_profile_agent_treats_phase2_na() -> None:
    phase0 = [
        CheckResult(
            id="os.version",
            phase=0,
            status=CheckStatus.PASS,
            summary="ok",
            details="",
            evidence=[],
            actions=[],
        )
    ]
    phase2_agent = [
        CheckResult(
            id="phase.2.na",
            phase=2,
            status=CheckStatus.NA,
            summary="N/A",
            details="",
            evidence=[],
            actions=[],
        )
    ]
    agent_scan = ScanData(
        metadata={},
        results={0: phase0, 2: phase2_agent},
        phase_modes={0: "required", 2: "na"},
        profile=Profile.AGENT,
    )
    workstation_scan = ScanData(
        metadata={},
        results={0: phase0, 2: [_check(CheckStatus.WARN)]},
        phase_modes={0: "required", 2: "required"},
        profile=Profile.WORKSTATION,
    )
    assert agent_scan.total_score() > workstation_scan.total_score()


def test_hardware_probe_accepts_31gb(monkeypatch) -> None:
    monkeypatch.setattr(system, "_get_total_ram_bytes", lambda: int(31.0 * 1024**3))
    monkeypatch.setattr(system, "_get_installed_ram_bytes", lambda: int(32.0 * 1024**3))
    monkeypatch.setattr(system.os, "cpu_count", lambda: 16)
    result = system.check_hardware_profile(ProbeContext())
    assert result.status == CheckStatus.PASS
    assert any("installed" in entry for entry in result.details.split(";"))


def test_hardware_probe_flags_low_ram(monkeypatch) -> None:
    monkeypatch.setattr(system, "_get_total_ram_bytes", lambda: int(23.0 * 1024**3))
    monkeypatch.setattr(system, "_get_installed_ram_bytes", lambda: int(23.0 * 1024**3))
    monkeypatch.setattr(system.os, "cpu_count", lambda: 16)
    result = system.check_hardware_profile(ProbeContext())
    assert result.status == CheckStatus.FAIL


def test_toolchain_fix_respects_dry_run(monkeypatch) -> None:
    ctx = ProbeContext(dry_run=True)
    monkeypatch.setattr("ue_configurator.fix.toolchain._is_admin", lambda: True)

    def fake_run(self, command, **kwargs):
        cmd = list(command)
        if cmd[0] == "where":
            target = cmd[1].lower()
            if target in ("cmake.exe", "ninja.exe"):
                return CommandResult(command, "", "", 1)
            if target == "winget":
                return CommandResult(command, "C:\\\\Windows\\\\System32\\\\winget.exe", "", 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(ProbeContext, "run_command", fake_run, raising=False)
    outcome = ensure_toolchain_extras(ctx)
    assert outcome.success
    assert any("dry-run" in line for line in outcome.logs)


def test_toolchain_fix_apply_success(monkeypatch) -> None:
    ctx = ProbeContext(dry_run=False)
    monkeypatch.setattr("ue_configurator.fix.toolchain._is_admin", lambda: True)

    def fake_run(self, command, **kwargs):
        cmd = list(command)
        if cmd[0] == "where":
            target = cmd[1].lower()
            if target in ("cmake.exe", "ninja.exe"):
                return CommandResult(command, "", "", 1)
            if target == "winget":
                return CommandResult(command, "winget.exe", "", 0)
        if cmd[0] == "winget":
            return CommandResult(command, "Installed", "", 0)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(ProbeContext, "run_command", fake_run, raising=False)
    outcome = ensure_toolchain_extras(ctx)
    assert outcome.success
    assert any("installed successfully" in line for line in outcome.logs)


def test_toolchain_fix_handles_missing_winget(monkeypatch) -> None:
    ctx = ProbeContext(dry_run=True)

    def fake_run(self, command, **kwargs):
        cmd = list(command)
        if cmd[0] == "where":
            target = cmd[1].lower()
            if target in ("cmake.exe", "ninja.exe"):
                return CommandResult(command, "", "", 1)
            if target == "winget":
                return CommandResult(command, "", "", 1)
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(ProbeContext, "run_command", fake_run, raising=False)
    outcome = ensure_toolchain_extras(ctx)
    assert not outcome.success
    assert any("winget command not found" in line for line in outcome.logs)
