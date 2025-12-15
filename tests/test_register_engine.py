from __future__ import annotations

from pathlib import Path

from ue_configurator.probe.base import ProbeContext
from ue_configurator.profile import Profile
from ue_configurator.setup.pipeline import SetupOptions, SetupRuntime, SetupState, StepStatus, _apply_register_engine
from ue_configurator.ue.registration import find_selector
from ue_configurator.probe.runner import ScanData


class _Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, message: str) -> None:
        self.lines.append(message)


def _runtime(tmp_path: Path, ue_root: Path) -> SetupRuntime:
    options = SetupOptions(
        phases=[2],
        apply=True,
        resume=False,
        plan_only=False,
        include_horde=False,
        use_winget=False,
        ue_root=str(ue_root),
        dry_run=False,
        verbose=False,
        no_color=True,
        json_path=None,
        log_path=tmp_path / "log.txt",
        profile=Profile.WORKSTATION,
        register_engine=True,
    )
    logger = _Logger()
    ctx = ProbeContext(dry_run=False, ue_root=str(ue_root))
    scan = ScanData(metadata={}, results={}, phase_modes={}, profile=Profile.WORKSTATION)
    return SetupRuntime(options=options, logger=logger, context=ctx, scan=scan, state=SetupState())


def test_register_missing_script_warns(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    (ue_root / "Engine" / "Binaries").mkdir(parents=True)
    runtime = _runtime(tmp_path, ue_root)

    result = _apply_register_engine(runtime, ue_root)

    assert result.status == StepStatus.WARN
    assert "not found" in result.message.lower()


def test_find_selector_prefers_shipping(tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    preferred = ue_root / "Engine" / "Binaries" / "Win64"
    preferred.mkdir(parents=True)
    fallback = preferred / "UnrealVersionSelector-Alt.exe"
    shipping = preferred / "UnrealVersionSelector-Win64-Shipping.exe"
    fallback.write_text("", encoding="utf-8")
    shipping.write_text("", encoding="utf-8")

    result = find_selector(ue_root)
    assert result == shipping
