from __future__ import annotations

from pathlib import Path
from ue_configurator.probe.horde import HordeAgentStatus
from ue_configurator.probe.unreal import BuildConfigurationInspection
from ue_configurator.ue import horde_helper
from ue_configurator.ue.horde_agent_config import load_horde_agent_config
from ue_configurator.ue.horde_helper import HordeHelperOptions, run_horde_setup_helper


def _fake_input(sequence):
    it = iter(sequence)

    def _inner(prompt: str = ""):
        return next(it, "")

    return _inner


def test_horde_helper_audit_no_write(monkeypatch, tmp_path: Path) -> None:
    ddc_path = tmp_path / "DerivedDataCache.ini"
    ddc_path.write_text("[DerivedDataCache]\nSharedDataCachePath=C:\\DDC\n", encoding="utf-8")

    monkeypatch.setattr(horde_helper, "user_ddc_config_path", lambda: ddc_path)
    monkeypatch.setattr(horde_helper, "engine_ddc_config_path", lambda _root: tmp_path / "EngineDDC.ini")
    monkeypatch.setattr(
        horde_helper,
        "probe_horde_agent_status",
        lambda _ctx: HordeAgentStatus(installed=False, running=False, service_state="unknown", details="missing"),
    )
    monkeypatch.setattr(
        horde_helper,
        "inspect_build_configuration",
        lambda _root: BuildConfigurationInspection(path=None, flags={}, status="missing", details="missing"),
    )
    monkeypatch.setattr(horde_helper, "discover_agent_config", lambda: None)

    output: list[str] = []
    options = HordeHelperOptions(
        ue_root=None,
        dry_run=False,
        apply=False,
        verbose=False,
        interactive=False,
        output=output.append,
    )
    run_horde_setup_helper(options)

    assert "Audit report:" in "\n".join(output)
    assert ddc_path.read_text(encoding="utf-8") == "[DerivedDataCache]\nSharedDataCachePath=C:\\DDC\n"
    assert not list(tmp_path.rglob("*.bak"))


def test_horde_helper_unc_does_not_probe_exists(monkeypatch, tmp_path: Path) -> None:
    ddc_path = tmp_path / "DerivedDataCache.ini"
    ddc_path.write_text("[DerivedDataCache]\nSharedDataCachePath=\\\\HOST\\Share\n", encoding="utf-8")

    monkeypatch.setattr(horde_helper, "user_ddc_config_path", lambda: ddc_path)
    monkeypatch.setattr(horde_helper, "engine_ddc_config_path", lambda _root: tmp_path / "EngineDDC.ini")
    monkeypatch.setattr(
        horde_helper,
        "probe_horde_agent_status",
        lambda _ctx: HordeAgentStatus(installed=True, running=False, service_state="STOPPED", details="stopped"),
    )
    monkeypatch.setattr(
        horde_helper,
        "inspect_build_configuration",
        lambda _root: BuildConfigurationInspection(path=None, flags={}, status="missing", details="missing"),
    )
    monkeypatch.setattr(horde_helper, "discover_agent_config", lambda: None)

    real_exists = Path.exists

    def fake_exists(self) -> bool:
        if str(self).startswith("\\\\"):
            raise AssertionError("UNC path should not be probed with exists()")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    options = HordeHelperOptions(
        ue_root=None,
        dry_run=False,
        apply=False,
        verbose=False,
        interactive=False,
        output=lambda *_args, **_kwargs: None,
    )
    run_horde_setup_helper(options)


def test_horde_helper_apply_backups_idempotent_and_skip(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    ubt_dir = ue_root / "Engine" / "Source" / "Programs" / "UnrealBuildTool" / "Configuration"
    ubt_dir.mkdir(parents=True)
    ubt_dir.joinpath("Flags.cs").write_text(
        """
[XmlConfig]
public bool bAllowXGE = false;
[XmlConfig]
public bool bAllowRemoteBuilds = false;
[XmlConfig]
public bool bAllowXGEShaderCompile = false;
[XmlConfig]
public bool bUseHordeAgent = false;
""",
        encoding="utf-8",
    )

    engine_config_dir = ue_root / "Engine" / "Config"
    engine_config_dir.mkdir(parents=True)
    engine_config_dir.joinpath("BaseEngine.ini").write_text("SharedDataCachePath=\n", encoding="utf-8")

    user_build_config = tmp_path / "User" / "BuildConfiguration.xml"
    user_build_config.parent.mkdir(parents=True)
    user_build_config.write_text("<Configuration><BuildConfiguration></BuildConfiguration></Configuration>", encoding="utf-8")

    user_ddc_config = tmp_path / "User" / "DerivedDataCache.ini"
    user_ddc_config.write_text("[DerivedDataCache]\nSharedDataCachePath=\n", encoding="utf-8")

    shared_ddc = tmp_path / "SharedDDC"
    shared_ddc.mkdir()

    horde_config = tmp_path / "ProgramData" / "Horde" / "Agent" / "appsettings.json"
    horde_config.parent.mkdir(parents=True)
    horde_config.write_text('{"Horde": {"Server": "https://horde", "Pool": "Default"}}', encoding="utf-8")

    monkeypatch.setattr(horde_helper, "user_build_configuration_path", lambda: user_build_config)
    monkeypatch.setattr(horde_helper, "engine_build_configuration_path", lambda _root: ue_root / "EngineBuild.xml")
    monkeypatch.setattr(horde_helper, "user_ddc_config_path", lambda: user_ddc_config)
    monkeypatch.setattr(horde_helper, "engine_ddc_config_path", lambda _root: ue_root / "EngineDDC.ini")
    monkeypatch.setattr(
        horde_helper,
        "probe_horde_agent_status",
        lambda _ctx: HordeAgentStatus(installed=True, running=True, service_state="RUNNING", details="running"),
    )
    monkeypatch.setattr(horde_helper, "discover_agent_config", lambda: load_horde_agent_config(horde_config))

    inputs = _fake_input(
        [
            str(ue_root),  # ue root
            "n",  # verify horde
            "1",  # scope
            "",  # endpoint (skip)
            "",  # pool (skip)
            str(shared_ddc),  # shared DDC
            "",  # local DDC (skip)
            "3",  # preset
            "y",  # apply
        ]
    )
    options = HordeHelperOptions(
        ue_root=ue_root,
        dry_run=False,
        apply=True,
        verbose=False,
        interactive=True,
        input=inputs,
        output=lambda *_args, **_kwargs: None,
        prompt_for_mode=False,
    )
    run_horde_setup_helper(options)

    backups = list(tmp_path.rglob("*.bak"))
    assert any("BuildConfiguration.xml" in str(path) for path in backups)
    assert any("DerivedDataCache.ini" in str(path) for path in backups)
    assert not any("appsettings.json" in str(path) for path in backups)

    inputs = _fake_input(
        [
            str(ue_root),  # ue root
            "n",  # verify horde
            "n",  # verify ddc
            "1",  # scope
            "",  # endpoint (skip)
            "",  # pool (skip)
            str(shared_ddc),  # shared DDC
            "",  # local DDC (skip)
            "3",  # preset
            "y",  # apply
        ]
    )
    options = HordeHelperOptions(
        ue_root=ue_root,
        dry_run=False,
        apply=True,
        verbose=False,
        interactive=True,
        input=inputs,
        output=lambda *_args, **_kwargs: None,
        prompt_for_mode=False,
    )
    run_horde_setup_helper(options)

    backups_after = list(tmp_path.rglob("*.bak"))
    assert len(backups_after) == len(backups)
