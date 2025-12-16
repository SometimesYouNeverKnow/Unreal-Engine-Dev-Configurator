from __future__ import annotations

from pathlib import Path

from ue_configurator.ue import configure_ddc_shaders
from ue_configurator.ue.build_config import apply_build_configuration_update, plan_build_configuration_update
from ue_configurator.ue.ddc_config import validate_ddc_path
from ue_configurator.ue.configure_ddc_shaders import WorkflowOptions


def test_validate_ddc_path_creates_when_opted_in(tmp_path: Path) -> None:
    shared = tmp_path / "ddc"
    result = validate_ddc_path(shared, allow_create=True, dry_run=False, write_probe=lambda p: 0.1)
    assert result.ok is True
    assert result.created is True
    assert shared.exists()


def test_validate_ddc_path_fails_without_opt_in(tmp_path: Path) -> None:
    shared = tmp_path / "missing_ddc"
    result = validate_ddc_path(shared, allow_create=False, dry_run=False, write_probe=lambda p: 0.1)
    assert result.ok is False
    assert shared.exists() is False


def test_build_configuration_backup(tmp_path: Path) -> None:
    cfg = tmp_path / "BuildConfiguration.xml"
    original = """<Configuration><BuildConfiguration><bAllowXGE>false</bAllowXGE></BuildConfiguration></Configuration>"""
    cfg.write_text(original, encoding="utf-8")

    update = plan_build_configuration_update(cfg, {"bAllowXGE": True}, {"bAllowXGE"})
    apply_build_configuration_update(update, dry_run=False)

    assert update.backup is not None
    assert update.backup.exists()
    assert update.backup.read_text(encoding="utf-8") == original


def test_build_configuration_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "BuildConfiguration.xml"
    content = """<Configuration><BuildConfiguration><bAllowXGE>true</bAllowXGE></BuildConfiguration></Configuration>"""
    cfg.write_text(content, encoding="utf-8")

    update = plan_build_configuration_update(cfg, {"bAllowXGE": True}, {"bAllowXGE"})
    assert update.changed is False


def test_unknown_keys_not_written_when_schema_missing(tmp_path: Path) -> None:
    cfg = tmp_path / "BuildConfiguration.xml"
    update = plan_build_configuration_update(cfg, {"bAllowXGE": True}, set())
    apply_build_configuration_update(update, dry_run=False)
    assert not cfg.exists()
    assert "No supported BuildConfiguration keys" in " ".join(update.warnings)


def test_interactive_overrides_and_apply(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    config_dir = ue_root / "Engine" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / "BaseEngine.ini").write_text("SharedDataCachePath=", encoding="utf-8")

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

    shared = tmp_path / "shared_ddc"
    shared.mkdir()

    # Redirect user-scoped paths into the temp directory to avoid touching the real profile.
    monkeypatch.setattr(
        configure_ddc_shaders, "user_build_configuration_path", lambda: tmp_path / "User" / "BuildConfiguration.xml"
    )
    monkeypatch.setattr(
        configure_ddc_shaders, "user_ddc_config_path", lambda: tmp_path / "User" / "DerivedDataCache.ini"
    )
    monkeypatch.setattr(configure_ddc_shaders, "default_local_ddc_path", lambda: tmp_path / "local_ddc")
    monkeypatch.setattr(configure_ddc_shaders, "default_shared_ddc_suggestion", lambda: str(shared))

    inputs = iter(
        [
            "1",  # scope: user
            "",  # accept default shared path override
            "",  # accept default local fallback
            "skip",  # bAllowXGE
            "false",  # bAllowRemoteBuilds
            "",  # bAllowXGEShaderCompile -> True
            "y",  # bUseHordeAgent -> True
            "y",  # apply
        ]
    )
    options = WorkflowOptions(
        ue_root=ue_root,
        dry_run=False,
        apply=True,
        verbose=False,
        interactive=True,
        input=lambda prompt="": next(inputs),
        output=lambda *args, **kwargs: None,
    )
    outcome = configure_ddc_shaders.configure_ddc_and_shaders(options)

    assert outcome.applied is True
    build_cfg = (tmp_path / "User" / "BuildConfiguration.xml").read_text(encoding="utf-8")
    assert "bAllowRemoteBuilds>false" in build_cfg
    assert "bAllowXGEShaderCompile>true" in build_cfg
    assert "bUseHordeAgent>true" in build_cfg
    ddc_cfg = (tmp_path / "User" / "DerivedDataCache.ini").read_text(encoding="utf-8")
    assert str(shared) in ddc_cfg
