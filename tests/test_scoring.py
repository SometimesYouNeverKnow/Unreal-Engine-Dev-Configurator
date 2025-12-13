"""Unit tests for scoring and fix helpers."""

from __future__ import annotations

from pathlib import Path

from ue_configurator.fix.horde import generate_build_configuration
from ue_configurator.probe.base import ActionRecommendation, CheckResult, CheckStatus, ProbeContext, score_checks
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
