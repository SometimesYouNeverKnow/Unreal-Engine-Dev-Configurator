from __future__ import annotations

from pathlib import Path

from ue_configurator.ue import config_paths, configure_ddc_shaders, ddc_verify
from ue_configurator.ue.build_config import apply_build_configuration_update, plan_build_configuration_update
from ue_configurator.ue.ddc_config import validate_ddc_path
from ue_configurator.ue.configure_ddc_shaders import WorkflowOptions
from ue_configurator.ue.ddc_verify import verify_shared_ddc_path


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
    monkeypatch.setattr(configure_ddc_shaders, "default_shared_ddc_suggestion", lambda _ue_root=None: str(shared))

    inputs = iter(
        [
            "1",  # scope: user
            "",  # accept default shared path override
            "",  # accept default local fallback
            "skip",  # bAllowXGE
            "false",  # bAllowRemoteBuilds
            "",  # bAllowXGEShaderCompile -> True
            "y",  # bUseHordeAgent -> True
            "",  # skip verification prompt
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


def test_unc_prompt_skips_exists(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    ubt_dir = ue_root / "Engine" / "Source" / "Programs" / "UnrealBuildTool" / "Configuration"
    ubt_dir.mkdir(parents=True)
    ubt_dir.joinpath("Flags.cs").write_text("[XmlConfig]\npublic bool bAllowXGE = false;", encoding="utf-8")

    monkeypatch.setattr(
        configure_ddc_shaders, "user_build_configuration_path", lambda: tmp_path / "User" / "BuildConfiguration.xml"
    )
    monkeypatch.setattr(
        configure_ddc_shaders, "user_ddc_config_path", lambda: tmp_path / "User" / "DerivedDataCache.ini"
    )
    monkeypatch.setattr(configure_ddc_shaders, "default_local_ddc_path", lambda: tmp_path / "local_ddc")
    monkeypatch.setattr(configure_ddc_shaders, "default_shared_ddc_suggestion", lambda _ue_root=None: "")

    real_exists = Path.exists

    def fake_exists(self) -> bool:
        if str(self).startswith("\\\\"):
            raise AssertionError("UNC path should not be probed with exists()")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)

    inputs = iter(
        [
            "1",  # scope: user
            r"\\\\HOST\\Share\\UnrealDDC",  # shared path
            "",  # accept default local fallback
            "",  # accept recommended flag default
            "",  # accept recommended flag default
            "",  # accept recommended flag default
            "",  # accept recommended flag default
            "",  # skip verification prompt
            "",  # do not apply
        ]
    )
    options = WorkflowOptions(
        ue_root=ue_root,
        dry_run=False,
        apply=False,
        verbose=False,
        interactive=True,
        input=lambda prompt="": next(inputs),
        output=lambda *args, **kwargs: None,
    )
    outcome = configure_ddc_shaders.configure_ddc_and_shaders(options)

    assert outcome.applied is False


def test_verify_handles_access_denied(monkeypatch) -> None:
    def _deny(_path):
        err = OSError("denied")
        err.winerror = 5
        err.errno = 5
        raise err

    monkeypatch.setattr(ddc_verify.os, "listdir", _deny)
    ok, detail, hints = verify_shared_ddc_path(r"\\\\HOST\\Share")
    assert ok is False
    assert "Access denied" in detail
    assert hints == []


def test_verify_handles_logon_failure(monkeypatch) -> None:
    def _reject(_path):
        err = OSError("bad creds")
        err.winerror = 1326
        err.errno = 1326
        raise err

    monkeypatch.setattr(ddc_verify.os, "listdir", _reject)
    ok, detail, hints = verify_shared_ddc_path(r"\\\\HOST\\Share")
    assert ok is False
    assert "Credentials rejected" in detail
    assert any("net use" in cmd for cmd in hints)


def test_default_shared_ddc_has_no_fake_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config_paths, "user_ddc_config_path", lambda: tmp_path / "User" / "DerivedDataCache.ini")
    monkeypatch.setattr(config_paths, "engine_ddc_config_path", lambda ue_root: tmp_path / "Engine" / "DerivedDataCache.ini")
    value = config_paths.default_shared_ddc_suggestion(None)
    assert value in ("", None)
    assert value is None or "LULU" not in value


def test_write_test_only_on_opt_in(tmp_path: Path) -> None:
    ok, _, _ = verify_shared_ddc_path(str(tmp_path), write_test=False)
    assert ok is True
    assert not list(tmp_path.glob("uecfg_write_test_*.tmp"))

    ok, detail, _ = verify_shared_ddc_path(str(tmp_path), write_test=True)
    assert ok is True
    assert "Write test succeeded" in detail
    assert not list(tmp_path.glob("uecfg_write_test_*.tmp"))
