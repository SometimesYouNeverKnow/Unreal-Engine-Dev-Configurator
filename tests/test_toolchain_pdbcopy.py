from __future__ import annotations

from pathlib import Path

from ue_configurator.probe.base import CommandResult, ProbeContext, CheckStatus
import ue_configurator.probe.toolchain as toolchain


def test_pdbcopy_probe_passes_when_found_on_path(monkeypatch) -> None:
    ctx = ProbeContext(dry_run=True)

    def fake_run(command, **kwargs):
        if command == ["where", "pdbcopy.exe"]:
            return CommandResult(command, "C:\\Tools\\pdbcopy.exe\n", "", 0)
        return CommandResult(command, "", "", 1)

    monkeypatch.setattr(ctx, "run_command", fake_run)
    monkeypatch.setattr(toolchain, "_pdbcopy_candidates", lambda: [])

    result = toolchain.check_pdbcopy(ctx)
    assert result.status == CheckStatus.PASS
    assert result.id == "toolchain.pdbcopy"


def test_pdbcopy_probe_passes_when_found_in_windows_kits(monkeypatch, tmp_path: Path) -> None:
    ctx = ProbeContext(dry_run=True)

    def fake_run(command, **kwargs):
        return CommandResult(command, "", "not found", 1)

    pdbcopy = tmp_path / "pdbcopy.exe"
    pdbcopy.write_text("stub")
    monkeypatch.setattr(ctx, "run_command", fake_run)
    monkeypatch.setattr(toolchain, "_pdbcopy_candidates", lambda: [pdbcopy])

    result = toolchain.check_pdbcopy(ctx)
    assert result.status == CheckStatus.PASS
    assert str(pdbcopy) in result.evidence


def test_pdbcopy_probe_fails_when_missing(monkeypatch) -> None:
    ctx = ProbeContext(dry_run=True)

    def fake_run(command, **kwargs):
        return CommandResult(command, "", "not found", 1)

    monkeypatch.setattr(ctx, "run_command", fake_run)
    monkeypatch.setattr(toolchain, "_pdbcopy_candidates", lambda: [])

    result = toolchain.check_pdbcopy(ctx)
    assert result.status == CheckStatus.FAIL
    assert result.actions
    assert result.actions[0].id == "sdk.debugging-tools"
