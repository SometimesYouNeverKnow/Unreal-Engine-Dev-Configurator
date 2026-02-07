from __future__ import annotations

import json
from pathlib import Path
import shutil

from ue_configurator.ue import installed_build_sync as sync


def _make_sample_installed_build(root: Path) -> None:
    editor = root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    editor.parent.mkdir(parents=True, exist_ok=True)
    editor.write_bytes(b"sample-editor")


def _fake_robocopy(source: Path, destination: Path, *, dry_run: bool, thread_count: int):
    if dry_run:
        return 1, "dry-run"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return 1, "copied"


def test_publish_writes_info_and_settings(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    publish_root = tmp_path / "publish"
    _make_sample_installed_build(source)
    monkeypatch.setattr(sync, "_run_robocopy", _fake_robocopy)

    result = sync.publish_installed_build(
        source_installed_build_path=source,
        publish_root_path=publish_root,
        build_id="UE_5.7.2",
        unreal_source_path=None,
        shared_ddc_path=r"\\DDC-SERVER\UnrealDDC",
        engine_association_guid="{GUID}",
        thread_count=8,
        dry_run=False,
    )

    assert result.success
    info = json.loads((publish_root / "UE_5.7.2" / "BUILD_INFO.json").read_text(encoding="utf-8"))
    settings = json.loads((publish_root / "UE_5.7.2" / "BUILD_SETTINGS.json").read_text(encoding="utf-8"))
    assert info["build_id"] == "UE_5.7.2"
    assert settings["shared_ddc_path"] == r"\\DDC-SERVER\UnrealDDC"
    assert settings["engine_association_guid"] == "{GUID}"


def test_pull_applies_settings_and_hash_verifies(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    publish_root = tmp_path / "publish"
    destination = tmp_path / "dest"
    _make_sample_installed_build(source)
    monkeypatch.setattr(sync, "_run_robocopy", _fake_robocopy)

    published = sync.publish_installed_build(
        source_installed_build_path=source,
        publish_root_path=publish_root,
        build_id="UE_5.7.2",
        unreal_source_path=None,
        shared_ddc_path=r"\\DDC-SERVER\UnrealDDC",
        engine_association_guid="{GUID}",
        thread_count=8,
        dry_run=False,
    )
    assert published.success

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        sync,
        "_set_user_env_var",
        lambda name, value, dry_run: calls.append((name, value)) or None,
    )
    monkeypatch.setattr(sync, "_set_engine_association", lambda guid, path, dry_run: None)
    user_build_config = tmp_path / "BuildConfiguration.xml"
    monkeypatch.setattr(sync, "user_build_configuration_path", lambda: user_build_config)

    pulled = sync.pull_installed_build(
        publish_root_path=publish_root,
        build_id="UE_5.7.2",
        destination_installed_build_path=destination,
        thread_count=8,
        dry_run=False,
        install_settings=True,
        apply_engine_association=True,
    )

    assert pulled.success
    assert ("UE-SharedDataCachePath", r"\\DDC-SERVER\UnrealDDC") in calls
    text = user_build_config.read_text(encoding="utf-8")
    assert "bAllowXGEShaderCompile" in text
    assert "bUseHordeAgent" in text
