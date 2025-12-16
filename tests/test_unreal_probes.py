from __future__ import annotations

import os
from pathlib import Path

from ue_configurator.probe.base import CheckStatus, ProbeContext
from ue_configurator.probe import unreal
from ue_configurator.ue import config_paths


def test_parse_build_configuration_flags_reads_booleans() -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
  <BuildConfiguration>
    <bAllowXGE>true</bAllowXGE>
    <bAllowRemoteBuilds>False</bAllowRemoteBuilds>
    <bUseHordeAgent>1</bUseHordeAgent>
    <bAllowXGEShaderCompile>0</bAllowXGEShaderCompile>
  </BuildConfiguration>
</Configuration>
"""
    flags = unreal._parse_build_configuration_flags(xml)
    assert flags["bAllowXGE"] is True
    assert flags["bAllowRemoteBuilds"] is False
    assert flags["bUseHordeAgent"] is True
    assert flags["bAllowXGEShaderCompile"] is False


def test_ddc_detection_prefers_shared_env(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    (ue_root / "Engine" / "Config").mkdir(parents=True)
    ctx = ProbeContext(ue_root=str(ue_root))
    ctx.cache["ue_root_path"] = ue_root

    # Configure environment for shared + local paths
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv("UE-LocalDataCachePath", str(tmp_path / "LocalAppData" / "UnrealEngine" / "DDC"))
    monkeypatch.setenv("UE-SharedDataCachePath", r"\\nas\ddc\share")

    result = unreal.check_ddc_configuration(ctx)
    assert result.status == CheckStatus.PASS
    assert "shared" in result.summary.lower()
    assert "\\\\nas\\ddc\\share" in "".join(result.evidence)


def test_ddc_detection_warns_when_local_only(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    cfg_dir = ue_root / "Engine" / "Config"
    cfg_dir.mkdir(parents=True)
    config_path = cfg_dir / "DefaultEngine.ini"
    local_ddc = tmp_path / "LocalAppData" / "UnrealEngine" / "Common" / "DerivedDataCache"
    config_path.write_text(f'DerivedDataCachePath="{local_ddc}"\n', encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    ctx = ProbeContext(ue_root=str(ue_root))
    ctx.cache["ue_root_path"] = ue_root

    result = unreal.check_ddc_configuration(ctx)
    assert result.status == CheckStatus.WARN
    assert "local" in result.summary.lower()


def test_ddc_detection_reads_user_config(monkeypatch, tmp_path: Path) -> None:
    ue_root = tmp_path / "UE"
    (ue_root / "Engine" / "Config").mkdir(parents=True)
    user_ddc = tmp_path / "User" / "DerivedDataCache.ini"
    user_ddc.parent.mkdir(parents=True)
    user_ddc.write_text("[DerivedDataCache]\nSharedDataCachePath=\\\\nas\\ddc\n", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setattr(config_paths, "user_ddc_config_path", lambda: user_ddc)

    ctx = ProbeContext(ue_root=str(ue_root))
    ctx.cache["ue_root_path"] = ue_root
    result = unreal.check_ddc_configuration(ctx)
    assert result.status == CheckStatus.PASS
    assert "\\\\nas\\ddc" in result.details
